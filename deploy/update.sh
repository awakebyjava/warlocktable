#!/usr/bin/env bash
#
# Update the table: fetch, show what is coming, confirm, install, restart.
#
#   ./deploy/update.sh            # review, then deploy
#   ./deploy/update.sh --yes      # skip the confirmation
#   ./deploy/update.sh --check    # show what is pending and stop
#
# RUN THIS AS THE USER WHO OWNS THE REPO, NOT WITH SUDO. It elevates
# itself for the install step. Running the whole thing as root makes git
# compare the repo's owner against SUDO_UID=0, which no longer matches,
# so it refuses the checkout as dubious ownership -- and the deploy then
# stamps VERSION as "not-a-git-checkout" and the table can no longer say
# which build it is running.
#
# This exists because "git pull && sudo ./deploy/install.sh" is two commands
# and easy to half-do. It keeps the review step that install.sh deliberately
# does not have: you see the incoming commits before anything is deployed.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR=/var/lib/warlocktable
ASSUME_YES=0
CHECK_ONLY=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes|-y) ASSUME_YES=1; shift ;;
        --check)  CHECK_ONLY=1; shift ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

cd "$REPO"

# Fail fast rather than deploying something that cannot identify itself.
if [[ "${SUDO_UID:-}" == "0" || ( -z "${SUDO_USER:-}" && "$(id -u)" -eq 0 ) ]]; then
    echo "Run this WITHOUT sudo - it elevates itself for the install step." >&2
    echo "As root, git refuses the repo as dubious ownership and the" >&2
    echo "deployed VERSION becomes useless. See the header of this file." >&2
    exit 2
fi

# --- what is pending? -------------------------------------------------

echo "=== Fetching ==="
# --prune-tags as well as --tags: a tag that was MOVED or deleted upstream
# otherwise lingers here forever, and install.sh stamps VERSION from
# `git describe`. The Pi spent a day reporting v0.3.0-12-g... against a tag
# that no longer existed anywhere else, which makes a version string
# useless for the one thing it is for -- saying exactly what is running.
git fetch --quiet --tags --prune --prune-tags origin
BEHIND=$(git rev-list --count HEAD..origin/main)

if [[ "$BEHIND" -eq 0 ]]; then
    echo "  already up to date with origin/main"
    INSTALLED_SHA=$(sed -n '2p' /opt/warlocktable/VERSION 2>/dev/null || echo "")
    LOCAL_SHA=$(git rev-parse HEAD)
    if [[ "$INSTALLED_SHA" == "$LOCAL_SHA" ]]; then
        echo "  and /opt matches the checkout - nothing to do"
        exit 0
    fi
    echo "  but /opt is running a different build - reinstall is worthwhile"
else
    echo
    echo "=== $BEHIND commit(s) incoming ==="
    git --no-pager log --oneline --no-decorate HEAD..origin/main | sed 's/^/  /'
fi

# The live config is Pi-owned and is NOT updated by a pull (plan doc 4.4).
# If the example changed, new scenes or cards will not appear on the table
# unless they are added to the live file - worth saying out loud, because
# the alternative is wondering why a new card does nothing.
if [[ "$BEHIND" -gt 0 ]] && \
   git --no-pager diff --name-only HEAD..origin/main | grep -q '^data/config.example.json$'; then
    echo
    echo "  NOTE: data/config.example.json changed in these commits."
    echo "        Your live config at $DATA_DIR/config.json is independent"
    echo "        and will NOT be updated. To see what differs afterwards:"
    echo "          diff $DATA_DIR/config.json data/config.example.json"
fi

if [[ $CHECK_ONLY -eq 1 ]]; then
    echo
    echo "(--check: stopping here, nothing deployed)"
    exit 0
fi

# --- confirm ----------------------------------------------------------

if [[ $ASSUME_YES -eq 0 ]]; then
    echo
    read -r -p "Pull and deploy this to the table? [y/N] " reply
    case "$reply" in
        [yY]|[yY][eE][sS]) ;;
        *) echo "aborted - nothing changed"; exit 0 ;;
    esac
fi

# --- deploy -----------------------------------------------------------

if [[ "$BEHIND" -gt 0 ]]; then
    echo
    echo "=== Pulling ==="
    git pull --quiet --ff-only origin main
    git fetch --quiet --tags --prune --prune-tags origin
    echo "  now at $(git log --oneline -1)"
fi

echo
echo "=== Installing ==="
sudo "$REPO/deploy/install.sh"

echo
echo "=== Service ==="
systemctl is-active --quiet warlocktable \
    && echo "  running: $(systemctl show -p ActiveEnterTimestamp --value warlocktable)" \
    || echo "  NOT RUNNING - see: journalctl -u warlocktable -n 40"
echo
echo "  logs: journalctl -u warlocktable -f"
