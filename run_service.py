#!/usr/bin/env python3
"""Run the table headless, with no console — what systemd starts.

    python3 run_service.py --real-lights --real-audio --nfc

Use run_table.py instead for the interactive prompt. See plan doc 5.5.
"""
import sys

from warlock.service import main

if __name__ == "__main__":
    sys.exit(main())
