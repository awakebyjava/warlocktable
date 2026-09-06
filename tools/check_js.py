#!/usr/bin/env python3
"""Catch a re-declared const/let before it takes the whole panel down.

    tools/check_js.py            # every .js under warlock/web/static
    tools/check_js.py app.js     # just one

WHY THIS EXISTS

A duplicate `const row` inside one function stopped app.js PARSING. That
does not break one control -- it takes out every script that depends on the
file. window.goto and window.api were undefined and the GM panel was a dead
page. It got deployed that way, because every check that ran was against the
Python API, and the Python API was completely fine. That is the trap worth
tooling against: the server can be in perfect health while the panel is
blank.

WHAT THIS IS NOT

Not a JavaScript parser. A real one would be better, and there isn't a
usable one here: esprima is pure Python and needs no wheel, but it is
ES2017-era and rejects the optional chaining app.js legitimately uses. A
checker that cries "do not deploy" over correct code is worse than no
checker, because it teaches you to ignore it.

So this does ONE thing and does it without false alarms: it finds a `const`
or `let` declared twice in the same block. That is a hard SyntaxError in
every browser, it is the specific mistake that caused the outage, and it is
the easy one to make while editing a long function someone else's variable
already lives in.

Everything else -- an unbalanced brace, a bad call -- still needs the
browser. Load the page and read the console before deploying static changes.
"""

from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(os.path.dirname(HERE), "warlock", "web", "static")

DECL = re.compile(r"\b(const|let)\s+([A-Za-z_$][\w$]*)")


def strip_noise(src: str) -> str:
    """Blank out comments, strings and template literals.

    Replaced with spaces rather than removed so every byte keeps its offset
    and reported line numbers stay true.
    """
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""

        if c == "/" and nxt == "/":
            while i < n and src[i] != "\n":
                out[i] = " "
                i += 1
            continue
        if c == "/" and nxt == "*":
            while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                if src[i] != "\n":
                    out[i] = " "
                i += 1
            for _ in range(2):
                if i < n:
                    out[i] = " "
                    i += 1
            continue
        if c in "\"'`":
            quote = c
            out[i] = " "
            i += 1
            while i < n:
                if src[i] == "\\":
                    out[i] = " "
                    if i + 1 < n and src[i + 1] != "\n":
                        out[i + 1] = " "
                    i += 2
                    continue
                if src[i] == quote:
                    out[i] = " "
                    i += 1
                    break
                if src[i] != "\n":
                    out[i] = " "
                i += 1
            continue
        i += 1
    return "".join(out)


def duplicates(path: str):
    """-> [(name, first line, second line)] for anything declared twice in
    the same block."""
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    src = strip_noise(raw)

    # A stack of scopes, each mapping name -> the line it was declared on.
    # Every `{` opens one and every `}` closes it. That treats an object
    # literal as a scope too, which is harmless: nothing declares a const
    # inside one, so it can only ever be an empty frame.
    stack = [{}]
    found = []
    line = 1
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c == "{":
            stack.append({})
            i += 1
            continue
        if c == "}":
            if len(stack) > 1:
                stack.pop()
            i += 1
            continue

        m = DECL.match(src, i)
        if m:
            name = m.group(2)
            scope = stack[-1]
            if name in scope:
                found.append((name, scope[name], line))
            else:
                scope[name] = line
            i = m.end()
            continue
        i += 1
    return found, raw.splitlines()


def main():
    names = sys.argv[1:]
    if names:
        paths = [n if os.path.isfile(n) else os.path.join(STATIC, n)
                 for n in names]
    else:
        paths = sorted(os.path.join(STATIC, f) for f in os.listdir(STATIC)
                       if f.endswith(".js"))

    bad = 0
    for path in paths:
        if not os.path.isfile(path):
            print("  %-22s NOT FOUND" % os.path.basename(path))
            bad += 1
            continue
        dupes, lines = duplicates(path)
        if not dupes:
            print("  %-22s ok" % os.path.basename(path))
            continue
        bad += 1
        for name, first, second in dupes:
            print("  %-22s %r declared twice in one block, lines %d and %d"
                  % (os.path.basename(path), name, first, second))
            for ln in (first, second):
                if 0 < ln <= len(lines):
                    print("       %5d| %s" % (ln, lines[ln - 1].strip()[:90]))

    print()
    if bad:
        print("%d file(s) would fail to parse in the browser. Do not deploy."
              % bad)
        return 1
    print("all %d clear" % len(paths))
    return 0


if __name__ == "__main__":
    sys.exit(main())
