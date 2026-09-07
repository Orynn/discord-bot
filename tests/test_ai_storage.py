import tempfile
import unittest
from pathlib import Path

import data.db as db_module
from ai.storage import (
    CONTEXT_LIMIT,
    clear_ai_context,
    get_ai_context,
    save_ai_context,
)


class TestAiContextStorage(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        db_module.init_db()

    def tearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    def test_round_trip_and_clear(self) -> None:
        self.assertEqual(get_ai_context(guild_id=1, channel_id=10), "")
        saved = save_ai_context(
            guild_id=1, channel_id=10, text="  Ils ont volé le sceau.  "
        )
        self.assertEqual(saved, "Ils ont volé le sceau.")
        self.assertEqual(
            get_ai_context(guild_id=1, channel_id=10), "Ils ont volé le sceau."
        )
        self.assertEqual(get_ai_context(guild_id=1, channel_id=11), "")
        clear_ai_context(guild_id=1, channel_id=10)
        self.assertEqual(get_ai_context(guild_id=1, channel_id=10), "")

    def test_truncates_long_context(self) -> None:
        saved = save_ai_context(guild_id=1, channel_id=10, text="x" * 3000)
        self.assertEqual(len(saved), CONTEXT_LIMIT)
        self.assertTrue(saved.endswith("…"))
