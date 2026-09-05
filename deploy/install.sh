#!/usr/bin/env bash
#
# Install the Warlock Table controller as a system service.
#
#   sudo deploy/install.sh [--user pi] [--no-restart]
#
# Deploys whatever is CURRENTLY CHECKED OUT. It does not pull - that is
# deliberate (plan doc 5.5): you choose the version, the installer deploys
# it. A script that pulls for you is convenient right up until it deploys
# something you had not reviewed.
#
#   git checkout v0.3.0 && sudo deploy/install.sh     # deploy a tag
#   git checkout main   && sudo deploy/install.sh     # roll forward
#
# THE RULE THAT MATTERS: this never overwrites /var/lib/warlocktable.
# Code is replaced wholesale; data is seeded once and then belongs to the
# Pi. That is what lets the panel edit config without the Pi drifting out
# of sync with GitHub (plan doc 4.4).

set -euo pipefail

CODE_DIR=/opt/warlocktable
DATA_DIR=/var/lib/warlocktable
UNIT=/etc/systemd/system/warlocktable.service
DEFAULTS=/etc/default/warlocktable
SERVICE_USER=pi
DO_RESTART=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        --user)       SERVICE_USER="$2"; shift 2 ;;
        --no-restart) DO_RESTART=0; shift ;;
        -h|--help)    sed -n '2,22p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { printf '\n=== %s ===\n' "$*"; }

# --- checks -----------------------------------------------------------

[[ $EUID -eq 0 ]] || { echo "must run as root (use sudo)" >&2; exit 1; }
id "$SERVICE_USER" >/dev/null 2>&1 || { echo "no such user: $SERVICE_USER" >&2; exit 1; }
[[ -f "$SRC/run_service.py" ]] || { echo "can't find run_service.py in $SRC" >&2; exit 1; }

say "Installing from $SRC"
echo "  code -> $CODE_DIR"
echo "  data -> $DATA_DIR   (never overwritten)"
echo "  user -> $SERVICE_USER"

# --- data directory ---------------------------------------------------
# First, because config seeding must happen before the service starts.

say "Data directory"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 755 "$DATA_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 755 "$DATA_DIR/audio"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 755 "$DATA_DIR/backups"
# Session recordings (plan doc 3.10). Owned by the service user like the
# rest of $DATA_DIR, and never touched again by install.
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 755 "$DATA_DIR/recordings"
# Map import (map-import-specification.md). backgrounds/custom holds the
# finished renders and MUST be listed in config background_paths -- the
# display's scanner does not recurse, so being a subdirectory is not enough.
# maps/ holds the sources and recipes, deliberately outside backgrounds so
# the scanner never sees a source image or a half-finished upload.
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 755 "$DATA_DIR/backgrounds"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 755 "$DATA_DIR/backgrounds/custom"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 755 "$DATA_DIR/maps"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 755 "$DATA_DIR/maps/originals"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 755 "$DATA_DIR/maps/recipes"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 755 "$DATA_DIR/maps/work"

if [[ -f "$DATA_DIR/config.json" ]]; then
    echo "  config.json exists - LEFT ALONE (this is your live data)"
else
    install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 644 \
        "$SRC/data/config.example.json" "$DATA_DIR/config.json"
    echo "  config.json seeded from data/config.example.json"
    echo "  (from here on it is Pi-owned; repo edits will NOT propagate)"
fi

# --- code -------------------------------------------------------------
# Replaced wholesale rather than merged, so no file from an older version
# can survive and confuse things.

say "Code"
install -d -m 755 "$CODE_DIR"
rm -rf "$CODE_DIR/warlock" "$CODE_DIR/patterns" "$CODE_DIR/branding"
cp -r "$SRC/warlock"        "$CODE_DIR/"
cp -r "$SRC/patterns"       "$CODE_DIR/" 2>/dev/null || true
# branding/ is small and versioned with the code (unlike backgrounds/,
# which is media and syncs separately) - the status screen needs it.
cp -r "$SRC/branding"       "$CODE_DIR/" 2>/dev/null || true
# Derived data the code reads at runtime. NOT $DATA_DIR: that is
# operator-owned and never overwritten, whereas this is generated output
# that must travel with the code it was generated from.
install -d -m 755 "$CODE_DIR/data"
cp    "$SRC/data/scene-colours.json" "$CODE_DIR/data/" 2>/dev/null || true
cp    "$SRC/run_service.py" "$CODE_DIR/"
cp    "$SRC/run_table.py"   "$CODE_DIR/"
find "$CODE_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
echo "  copied"

# Record exactly what got deployed, so "which build is on the table?" has
# an answer (plan doc 5.5).
if git -C "$SRC" rev-parse --git-dir >/dev/null 2>&1; then
    {
        git -C "$SRC" describe --tags --always --dirty 2>/dev/null || echo "unknown"
        git -C "$SRC" rev-parse HEAD 2>/dev/null || true
        date -Is
    } > "$CODE_DIR/VERSION"
    echo "  VERSION: $(head -1 "$CODE_DIR/VERSION")"
else
    # SAY WHY. This branch used to fail silently, and the table spent a
    # day reporting "not-a-git-checkout" while $SRC was, in fact, a
    # perfectly good checkout.
    #
    # The cause was invoking `sudo ./deploy/update.sh` rather than
    # `./deploy/update.sh` -- update.sh calls sudo itself. Git compares a
    # repository's owner against SUDO_UID rather than against root, so the
    # nested sudo made SUDO_UID=0, which no longer matched the pi-owned
    # repo, and git refused it as dubious ownership. Running the whole
    # thing as root is what breaks it; running it as the owning user does
    # not.
    #
    # A version string exists to answer "what is on the table?". Losing it
    # to something this recoverable, without a word, is worse than the
    # missing string itself.
    echo "not-a-git-checkout $(date -Is)" > "$CODE_DIR/VERSION"
    echo "  WARNING: could not read git metadata from $SRC"
    echo "           git says: $(git -C "$SRC" rev-parse --git-dir 2>&1 | head -1)"
    echo "           VERSION is a timestamp only, so the table cannot report"
    echo "           which build it is running."
    if [[ -n "${SUDO_USER:-}" && "${SUDO_UID:-}" == "0" ]]; then
        echo "           LIKELY CAUSE: this was run with sudo. Use"
        echo "           ./deploy/update.sh (no sudo) -- it elevates itself."
    fi
fi

# --- python environment ----------------------------------------------
# --system-site-packages on purpose: pygame, RPi.GPIO and spidev are
# already installed system-wide and are slow or painful to build from
# source on ARM. The venv exists to give systemd a stable interpreter path
# and to hold anything pip-installed, not to hide the system packages.

say "Python environment"
if [[ ! -x "$CODE_DIR/venv/bin/python" ]]; then
    python3 -m venv --system-site-packages "$CODE_DIR/venv"
    echo "  venv created (inheriting system packages)"
else
    echo "  venv exists"
fi
VENV_PY="$CODE_DIR/venv/bin/python"

# pixelblaze-client pulls in mini-racer, which embeds V8, has no ARM wheel,
# and fails building from source on a Pi 4. It is imported at module scope
# but only USED for pattern compilation, which we do on the laptop. So:
# install without deps and satisfy the import with a stub that fails loudly
# if anything ever does try to compile a pattern here.
if ! "$VENV_PY" -c 'import pixelblaze' >/dev/null 2>&1; then
    echo "  installing pixelblaze-client (no deps - see deploy/README.md)"
    "$VENV_PY" -m pip install --quiet --upgrade \
        requests websocket-client pytz json5 lzstring click colorama future
    "$VENV_PY" -m pip install --quiet --upgrade --no-deps pixelblaze-client
fi
if ! "$VENV_PY" -c 'import py_mini_racer' >/dev/null 2>&1; then
    SITE="$("$VENV_PY" -c 'import site; print(site.getsitepackages()[0])')"
    cp "$SRC/deploy/py_mini_racer.py" "$SITE/"
    echo "  mini-racer stub installed"
fi

echo "  verifying imports:"
for m in pixelblaze pygame RPi.GPIO spidev; do
    if "$VENV_PY" -c "import $m" >/dev/null 2>&1; then
        echo "     $m ok"
    else
        echo "     $m MISSING - $m-dependent features will be degraded"
    fi
done

chown -R "$SERVICE_USER":"$SERVICE_USER" "$CODE_DIR"

# --- service ----------------------------------------------------------

say "Service"

if [[ ! -f "$DEFAULTS" ]]; then
    cat > "$DEFAULTS" <<EOF
# Arguments for the Warlock Table controller.
# Edit here rather than the unit file - install.sh overwrites the unit,
# but leaves this alone.
WARLOCK_ARGS=--config $DATA_DIR/config.json --real-lights --real-audio --nfc --status-interval 300
EOF
    echo "  wrote $DEFAULTS"
else
    echo "  $DEFAULTS exists - LEFT ALONE (your flags)"
fi

sed "s|__USER__|$SERVICE_USER|g" "$SRC/deploy/warlocktable.service" > "$UNIT"
chmod 644 "$UNIT"
systemctl daemon-reload
systemctl enable warlocktable.service >/dev/null 2>&1
echo "  unit installed and enabled (starts on boot)"

if [[ $DO_RESTART -eq 1 ]]; then
    systemctl restart warlocktable.service
    sleep 3
    if systemctl is-active --quiet warlocktable.service; then
        echo "  service is RUNNING"
    else
        echo "  service FAILED to start - see: journalctl -u warlocktable -n 40"
    fi
else
    echo "  not restarted (--no-restart)"
fi

say "Done"
cat <<EOF
  status:   systemctl status warlocktable
  logs:     journalctl -u warlocktable -f
  restart:  sudo systemctl restart warlocktable
  stop:     sudo systemctl stop warlocktable
  flags:    $DEFAULTS
  config:   $DATA_DIR/config.json   (Pi-owned - repo edits do NOT reach it)
  version:  $(head -1 "$CODE_DIR/VERSION" 2>/dev/null)
EOF
