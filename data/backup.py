from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from data import DATA_DIR
from data.db import DB_FILE

BACKUP_DIR = DATA_DIR / "backups"
KEEP_BACKUPS = 14


def backup_database(
    *,
    source: Path | None = None,
    dest_dir: Path | None = None,
    keep: int = KEEP_BACKUPS,
) -> Path:
    src = Path(source or DB_FILE)
    if not src.exists():
        raise FileNotFoundError(f"Database not found: {src}")

    dest_dir = Path(dest_dir or BACKUP_DIR)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"arkann-{stamp}.db"

    source_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        dest_conn = sqlite3.connect(dest)
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        source_conn.close()

    prune_backups(dest_dir, keep=keep)
    return dest


def prune_backups(dest_dir: Path, *, keep: int = KEEP_BACKUPS) -> None:
    if keep < 0:
        return
    files = sorted(dest_dir.glob("arkann-*.db"), key=lambda path: path.name)
    for stale in files[:-keep] if keep else files:
        stale.unlink(missing_ok=True)
