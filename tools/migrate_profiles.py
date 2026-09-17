#!/usr/bin/env python3
"""Split config.json into table.json + profiles/shared/library.json.

    python tools/migrate_profiles.py /var/lib/warlocktable/config.json
    python tools/migrate_profiles.py --check /var/lib/warlocktable/config.json

Plan doc 4.8, step 1. install.sh runs this once, as the service user, when
it finds a config.json with no profiles/ beside it. Safe to run by hand.

WHAT IT DOES, AND DOES NOT

- Reads config.json, checks it loads, splits it, writes the two new files
  beside it, and copies the original into backups/ as
  config-pre-profiles-<stamp>.json.
- Does NOT modify or remove config.json. The previous build boots from it
  unchanged; that is what makes rolling back a plain redeploy.
- Refuses to run twice (profiles/ exists), and refuses a config that does
  not load or does not round-trip -- nothing is written in either case.

--check reports what would happen and exits 0 if already migrated, 1 if
not, without touching anything.
"""

from __future__ import annotations

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from warlock.config import ConfigError, load_config   # noqa: E402
from warlock.profiles import ProfileStore, migrate     # noqa: E402


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    check = "--check" in sys.argv
    if len(args) != 1:
        print(__doc__.split("\n")[0])
        print("usage: migrate_profiles.py [--check] /path/to/config.json", file=sys.stderr)
        return 2
    config_path = os.path.abspath(args[0])
    data_dir = os.path.dirname(config_path)
    existing = ProfileStore.beside(config_path)

    if check:
        if existing is not None:
            print("already split: %s" % existing.describe())
            return 0
        try:
            cfg = load_config(config_path)
        except Exception as exc:   # noqa: BLE001
            print("NOT split, and config.json does not load: %s" % exc)
            return 1
        print("not split yet; config.json loads (%d cards, %d scenes, %d "
              "interruptions). Run without --check to split it."
              % (len(cfg.cards), len(cfg.scenes), len(cfg.interruptions)))
        return 1

    try:
        store = migrate(config_path, backup_dir=os.path.join(data_dir, "backups"))
    except ConfigError as exc:
        print("refused: %s" % exc, file=sys.stderr)
        return 1
    # Prove it, the same way the tests do.
    if store.load() != load_config(config_path):
        print("MISMATCH: the split files do not load to the same config -- "
              "leaving them in place for inspection, but the service will "
              "see a different table. Report this.", file=sys.stderr)
        return 1
    print("split: %s" % store.describe())
    print("config.json left untouched; copy in backups/config-pre-profiles-*.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
