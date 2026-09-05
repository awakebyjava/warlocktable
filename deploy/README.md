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

### 2. Image support, for map import

Map import needs Pillow and a HEIC decoder. **Both come from apt, not pip** —
`install.sh` builds the venv with `--system-site-packages` precisely so that
packages which are slow or painful to build on ARM can come from the system.
Pillow is one of those; adding it to `requirements.txt` would risk a repeat of
the mini-racer episode below.

```bash
sudo apt install -y python3-pil libheif-examples
```

`python3-pil` is Pillow; `libheif-examples` provides the `heif-convert` binary
that iPhone HEIC uploads are piped through. Verify:

```bash
python3 -c "from PIL import Image; print(Image.__version__)"    # 8.1.2
command -v heif-convert
```

Do **not** check with `heif-convert --help`: Debian's libheif 1.11 has no such
option and replies `invalid option`, which looks like a failure when the
binary is working. Confirmed installed on the table 2026-09-05.

Neither is required for the table to run. Without them the panel loads
normally and the Maps section says what to install.

**Bullseye's libheif is 1.11.0 and cannot read a current iPhone photo.**
Tested 2026-09-05: iOS 18 HDR photos carry a `tmap` gain map and a tiled
`grid` item, and libheif only learned `tmap` in 1.18. It fails with
"Metadata not correctly assigned to image".

Do not try to fix this with pip — `pillow-heif` has no armv7l wheel and this
Pi is **armhf**, so it would build libheif from source: the mini-racer trap
again. Upload JPEG or PNG instead; uploading from an iPad through the panel
generally converts to JPEG on the way. Older HEICs still decode fine.

**Write map import code against Pillow 8.1 / Python 3.9**, which is what
Bullseye ships — a laptop has Pillow 12 and will silently accept things the Pi
rejects. See `map-import-specification.md` §5.

### 3. The mini-racer stub

`pixelblaze-client` imports `MiniRacer` at module scope, so the import fails
without *something* named `py_mini_racer` on the path — even though it is only
used for pattern compilation, which happens on the laptop.

```bash
cp deploy/py_mini_racer.py "$(python3 -c 'import site; print(site.USER_SITE)')/"
```

Read the docstring in that file for the full reasoning, including why pinning
the older `pixelblaze-client` 0.9.6 is *not* an acceptable alternative (it
lacks `setActivePatternByName` and `EnumerateAddresses`).

### 4. Verify

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

## Everyday workflow

There are now **two copies of the code**, and keeping them straight is the whole
trick:

| | Where | What it is |
|---|---|---|
| **Source** | `~/Documents/warlocktable` | The git repo. Where you develop and test. |
| **Running** | `/opt/warlocktable` | What systemd actually runs. Replaced by `install.sh`. |
| **Data** | `/var/lib/warlocktable` | Config, audio, backups. **Never** touched by install. |

### To change something on the table

```bash
./deploy/update.sh
```

Fetches, shows the incoming commits, asks for confirmation, then pulls,
installs and restarts. `--check` shows what is pending without deploying;
`--yes` skips the prompt.

The review step is deliberate: `install.sh` never pulls on its own (plan doc
5.5), so nothing reaches the table that you have not seen.

**Run it WITHOUT `sudo`.** It elevates itself for the install step, and as
of 2026-08-24 it refuses to start as root rather than letting this happen
quietly:

> Git compares a repository's owner against `SUDO_UID`, not against root.
> Running the whole script under sudo means the nested `sudo install.sh`
> sees `SUDO_UID=0`, which no longer matches the pi-owned repo, so git
> rejects it as *dubious ownership*. install.sh's "is this a checkout?"
> test then fails and it stamps `VERSION` as `not-a-git-checkout` — and
> the table can no longer say which build it is running.

This cost a day of the table reporting a useless version string, and it
survived that long because the failure printed nothing at all. Both
scripts are louder about it now.

### To develop and test without touching the service

The repo still runs directly — this is the fast loop, no install needed:

```bash
sudo systemctl stop warlocktable      # only if using --nfc; see below
python3 run_table.py --config /var/lib/warlocktable/config.json         --real-lights --real-audio --nfc
```

Point `--config` at the live file to test against real data, or leave it off
to use the repo's `data/config.example.json` as a scratch copy.

When it works, `./deploy/update.sh` makes it the table's behaviour.

### The two gotchas

**Only one program can own the NFC reader.** The service and an interactive
CLI cannot both hold the PN532's SPI bus and GPIO reset pin. The loser reports
`Failed to detect the PN532`, which looks like dead hardware rather than a
second copy of the program. Stop the service first. (The CLI warns about this
now, but the warning is easy to scroll past.)

**Config does not come from git any more.** `/var/lib/warlocktable/config.json`
was seeded once at install and is now Pi-owned — that is what lets the panel
edit it without desyncing the repo (plan doc 4.4). Editing
`data/config.example.json` in the repo will **not** reach the table.

To see how they have diverged:

```bash
diff /var/lib/warlocktable/config.json data/config.example.json
```

To adopt the repo version wholesale (this **discards** live edits):

```bash
sudo cp /var/lib/warlocktable/config.json /var/lib/warlocktable/backups/config-$(date +%F).json
sudo cp data/config.example.json /var/lib/warlocktable/config.json
sudo systemctl restart warlocktable
```

### Rolling back

`install.sh` deploys whatever is checked out, so rollback is a checkout:

```bash
git checkout <tag-or-sha>
sudo ./deploy/install.sh
```

`/opt/warlocktable/VERSION` records what is actually deployed.

---

## Useful commands

```bash
systemctl status warlocktable          # is it up?
journalctl -u warlocktable -f          # live logs
journalctl -u warlocktable -n 50       # recent logs
sudo systemctl restart warlocktable
sudo systemctl stop warlocktable        # before interactive --nfc work
cat /opt/warlocktable/VERSION           # what build is deployed
cat /etc/default/warlocktable           # the flags it runs with
```

Flags live in `/etc/default/warlocktable` and survive reinstalls; the unit
file itself is overwritten on every install, so do not edit it.
