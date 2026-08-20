#!/usr/bin/env python3
"""Online-safe snapshot of data/arkann.db (keeps the last 14 copies)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.backup import backup_database
from data.db import DB_FILE


def main() -> int:
    if not DB_FILE.exists():
        print(f"No database yet at {DB_FILE}", file=sys.stderr)
        return 0
    path = backup_database()
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
