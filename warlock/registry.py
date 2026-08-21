"""The self-describing action registry (plan doc section 4.5).

Section 4.5 requires that "the action registry must describe itself" — so
a future management UI can ask the controller "what actions exist, what
parameters do they take, what are the valid values" and build an editing
form from the answer, rather than that list being hardcoded twice (once
in the backend, once in the frontend) and drifting apart.

This is a small piece of infrastructure to prove that idea works, not the
final form of it. The @action decorator tags a Controller method with
metadata; describe_actions() reads that metadata back, including asking
the live devices for their current pattern/track lists where relevant —
so, per 4.5, "you can never assign a pattern that doesn't exist."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

_REGISTRY: Dict[str, "ActionSpec"] = {}


@dataclass
class ParamSpec:
    name: str
    kind: str                                   # "str" / "float" / "target"
    choices: Optional[Callable[[Any], List[str]]] = None  # live, given the controller


@dataclass
class ActionSpec:
    name: str
    doc: str
    params: List[ParamSpec] = field(default_factory=list)
    fn: Optional[Callable] = None


def action(*params: ParamSpec):
    """Decorator: @action(ParamSpec("scene_name", "str", choices=lambda c: list(c.config.scenes)))"""
    def wrap(fn: Callable) -> Callable:
        _REGISTRY[fn.__name__] = ActionSpec(
            name=fn.__name__,
            doc=(fn.__doc__ or "").strip(),
            params=list(params),
            fn=fn,
        )
        return fn
    return wrap


def describe_actions(controller: Any) -> List[Dict[str, Any]]:
    """What a management UI would call to build its editing forms. Choices
    are resolved live against the given controller/devices, per 4.5."""
    out = []
    for spec in _REGISTRY.values():
        out.append({
            "name": spec.name,
            "doc": spec.doc,
            "params": [
                {
                    "name": p.name,
                    "kind": p.kind,
                    "choices": p.choices(controller) if p.choices else None,
                }
                for p in spec.params
            ],
        })
    return out


def validate_params(controller: Any, name: str, params: Dict[str, Any]) -> Optional[str]:
    """Check params against the action's declared choices.

    Returns an error string, or None if the call looks valid.

    This exists because the controller's fault isolation deliberately
    SWALLOWS a bad asset — a card pointing at a missing sound must not take
    the audio subsystem down (plan doc 5.2). Correct for the table, wrong
    for an API: the caller got "ok" while nothing happened.

    Validating here, against the same live choice-lists the UI builds its
    forms from, means a bad request is refused honestly and the isolation
    still protects the table from bad *config*.
    """
    spec = _REGISTRY.get(name)
    if spec is None:
        return "no such action: %s" % name

    declared = {p.name for p in spec.params}
    unexpected = set(params) - declared
    if unexpected:
        return "unexpected parameter(s): %s" % ", ".join(sorted(unexpected))

    for p in spec.params:
        if p.name not in params:
            return "missing parameter: %s" % p.name
        if not p.choices:
            continue
        try:
            allowed = p.choices(controller)
        except Exception:
            continue          # cannot resolve right now - let the call proceed
        value = params[p.name]
        if allowed and value not in allowed:
            shown = ", ".join(str(a) for a in list(allowed)[:8])
            return "%s: no such %s (have: %s%s)" % (
                value, p.name, shown, "..." if len(allowed) > 8 else "")
    return None
