import tempfile
import unittest
from pathlib import Path

import data.db as db_module
from data.backup import backup_database, prune_backups
from data.db import init_db


class TestDatabaseBackup(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        self.root = Path(self._tmpdir.name)
        db_module.DB_FILE = self.root / "arkann.db"
        init_db()

    def tearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    def test_backup_copies_sqlite_file(self) -> None:
        dest_dir = self.root / "backups"
        path = backup_database(source=db_module.DB_FILE, dest_dir=dest_dir, keep=5)
        self.assertTrue(path.exists())
        self.assertGreater(path.stat().st_size, 0)
        self.assertTrue(path.name.startswith("arkann-"))
        self.assertTrue(path.name.endswith(".db"))

    def test_prune_keeps_newest_files(self) -> None:
        dest_dir = self.root / "backups"
        dest_dir.mkdir()
        for index in range(16):
            (dest_dir / f"arkann-20260101-{index:06d}.db").write_bytes(b"x")
        prune_backups(dest_dir, keep=14)
        remaining = sorted(path.name for path in dest_dir.glob("arkann-*.db"))
        self.assertEqual(len(remaining), 14)
        self.assertEqual(remaining[0], "arkann-20260101-000002.db")
        self.assertEqual(remaining[-1], "arkann-20260101-000015.db")


if __name__ == "__main__":
    unittest.main()
