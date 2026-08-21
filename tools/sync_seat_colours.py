#!/usr/bin/env python3
"""Bring a config's seat palette in line with the defaults in warlock/zones.py.

    python3 tools/sync_seat_colours.py --dry-run
    python3 tools/sync_seat_colours.py

RUN IT AS THE SERVICE USER, NOT WITH sudo. The config belongs to the
service user and is writable by it, so root is not needed -- and using it
once left a root-owned config the service could not read, which crash-looped
the table. save_config now preserves ownership across its atomic replace, so
sudo is survivable, but it is still the wrong tool for this job.

WHY THIS EXISTS

`deploy/install.sh` seeds /var/lib/warlocktable/config.json once and then
never touches it again -- correct, because it is live data the panel edits.
The side effect is that a config seeded long ago keeps whatever seat palette
was current then, and no amount of deploying new code changes it, because
the controller lets config win over the code defaults.

That bit for real: orange and yellow were indistinguishable on the table,
the palette was fixed in code, and the fix would have had no effect on the
Pi at all.

Not run automatically by install.sh. Overwriting seat colours on every
deploy would throw away a genuine customisation, and the whole point of
seeding-once is that the operator's data is theirs.

Writes through warlock.config.save_config, so the write is atomic and
validated and a backup is taken first.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from warlock import zones as zonemap                      # noqa: E402
from warlock.config import Zone, load_config, save_config  # noqa: E402

DEFAULT_CONFIG = "/var/lib/warlocktable/config.json"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=DEFAULT_CONFIG,
                    help="config to update (default: %s)" % DEFAULT_CONFIG)
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would change and write nothing")
    args = ap.parse_args()

    if not os.path.exists(args.config):
        print("error: no config at %s" % args.config)
        return 2

    config = load_config(args.config)
    wanted = [Zone(id=i, colour=zonemap.seat_colour(i))
              for i in range(1, zonemap.MAX_PLAYERS + 1)]

    current = {z.id: z.colour for z in config.zones}
    changes = []
    for z in wanted:
        was = current.get(z.id)
        if was != z.colour:
            changes.append((z.id, was, z.colour))

    dropped = sorted(i for i in current if i > zonemap.MAX_PLAYERS)

    print("config: %s" % args.config)
    print("current: %s" % ", ".join("%d=%s" % (i, current[i])
                                    for i in sorted(current)) or "(none)")
    print("wanted : %s" % ", ".join("%d=%s" % (z.id, z.colour) for z in wanted))
    print()

    if not changes and not dropped:
        print("already in sync - nothing to do")
        return 0

    for zone_id, was, now in changes:
        print("  seat %d: %s -> %s" % (zone_id, was or "(missing)", now))
    for zone_id in dropped:
        print("  seat %d: %s -> removed (beyond %d seats)"
              % (zone_id, current[zone_id], zonemap.MAX_PLAYERS))

    # Anyone sitting in a seat keeps their seat: this changes what colour a
    # seat IS, not who is in it. Worth stating because a player who claimed
    # "orange" is now in a seat that no longer answers to that name.
    renamed = {i for i, was, now in changes if was}
    affected = [p.name for p in config.players
                if p.zone_id in renamed]
    if affected:
        print()
        print("note: %s claimed a seat whose colour changes - they keep the"
              % ", ".join(affected))
        print("      seat, but should be told its new colour.")

    if args.dry_run:
        print()
        print("--dry-run: nothing written")
        return 0

    config.zones = wanted
    backup_dir = os.path.join(os.path.dirname(args.config), "backups")
    save_config(config, args.config,
                backup_dir if os.path.isdir(backup_dir) else None)
    print()
    print("written. restart the service for it to take effect:")
    print("    sudo systemctl restart warlocktable")
    _warn_if_service_cannot_read(args.config)
    return 0


def _warn_if_service_cannot_read(path: str) -> None:
    """Say so loudly if the file we just wrote is not the service user's.

    Belt and braces: save_config preserves ownership now, but a config the
    service cannot read is a crash loop rather than a degraded mode, and it
    is worth being told at the moment of the write instead of finding out
    from journalctl.
    """
    try:
        import pwd
        st = os.stat(path)
        owner = pwd.getpwuid(st.st_uid).pw_name
    except Exception:
        return
    if os.geteuid() == 0 and st.st_uid == 0:
        print()
        print("WARNING: %s is now owned by root." % path)
        print("         The service runs as a normal user and will not be")
        print("         able to read it. Put it back with:")
        print("             sudo chown %s:%s %s" % (owner, owner, path))
    elif st.st_mode & 0o044 == 0 and st.st_uid != os.geteuid():
        print()
        print("WARNING: %s is not readable by other users." % path)


if __name__ == "__main__":
    raise SystemExit(main())
