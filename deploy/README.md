# Deploying to the Raspberry Pi

The Pi is **consume-only**: code arrives via `git pull`, never the other way
round (`pull.ff only` is set globally there). Media arrives via `rsync`, not
git. See plan doc §4.2 and §5.3.

Verified working on: Raspberry Pi 4, Raspberry Pi OS Bullseye, Python 3.9.2.

---

## One-time setup

### 1. Python dependencies

**Do not** run `pip install -r requirements.txt` on the Pi. `pixelblaze-client`
depends on `mini-racer`, which embeds V8, has no ARM wheel, and will try to
build V8 from source — that fails on a Pi 4 after a long wait.

Install the dependencies without it:

```bash
python3 -m pip install --upgrade \
    requests websocket-client pytz json5 lzstring click colorama future
python3 -m pip install --upgrade --no-deps pixelblaze-client
```

### 2. The mini-racer stub

`pixelblaze-client` imports `MiniRacer` at module scope, so the import fails
without *something* named `py_mini_racer` on the path — even though it is only
used for pattern compilation, which happens on the laptop.

```bash
cp deploy/py_mini_racer.py "$(python3 -c 'import site; print(site.USER_SITE)')/"
```

Read the docstring in that file for the full reasoning, including why pinning
the older `pixelblaze-client` 0.9.6 is *not* an acceptable alternative (it
lacks `setActivePatternByName` and `EnumerateAddresses`).

### 3. Verify

```bash
python3 -c "import pixelblaze; print(hasattr(pixelblaze.Pixelblaze, 'setActivePatternByName'))"
```

Should print `True`.

---

## Running

```bash
cd ~/Documents/warlocktable
git pull
python3 run_table.py --real-lights
```

The Pixelblaze is found by UDP discovery, so no address argument is needed.
Add `--pixelblaze-ip <addr>` only to skip discovery with a known-good hint.

---

## Gotchas found the hard way

| Symptom | Cause |
|---|---|
| `pip install` hangs for ages then fails on `mini-racer` | No ARM wheel; it is building V8. Use the `--no-deps` route above. |
| `AttributeError: setActivePatternByName` | Old `pixelblaze-client` (0.9.6). Upgrade to 1.1.8. |
| `ModuleNotFoundError: py_mini_racer` | The stub is missing from user site-packages. |
| Table looks dead but logs say success | Brightness. Run `status` in the CLI — see the power budget in `warlock-table-led-reference.md` §3b. |

---

## Current status: development mode, not a real install

Everything above runs the controller **out of the git working tree**, which is
fine for development and wrong for the finished table. See plan doc §5.5 for
the target layout: code installed to `/opt/warlocktable`, mutable state in
`/var/lib/warlocktable`, and a systemd unit — with the repo as *source* rather
than runtime.

Still to build, in this order (§5.5 explains why the order matters):

1. **Headless mode.** `run_table.py` is an interactive REPL reading stdin; a
   service needs a mode that runs the controller and waits on events with no
   console attached.
2. **`deploy/install.sh`.** Builds the venv (with the ARM workaround above),
   copies code to `/opt/warlocktable`, *seeds* `/var/lib/warlocktable/config.json`
   only if absent, records `VERSION`, installs the unit, restarts the service.
3. **The systemd unit itself.** `Restart=always`, `After=network-online.target`,
   starting with zero hardware present (§5.1/§5.2).

Until then the Pi must be started by hand and will not survive a reboot.
