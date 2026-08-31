import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from sheets.data import CharacterSheet
from PIL import Image

from sheets.portrait import (
    PORTRAIT_DIR,
    clear_portrait_file,
    load_portrait_image,
    parse_image_url,
    portrait_path,
)


class TestPortraitHelpers(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original = PORTRAIT_DIR
        import sheets.portrait as portrait

        portrait.PORTRAIT_DIR = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        import sheets.portrait as portrait

        portrait.PORTRAIT_DIR = self._original
        self._tmpdir.cleanup()

    def test_parse_image_url_requires_http(self) -> None:
        self.assertEqual(
            parse_image_url("https://cdn.example.com/hero.png"),
            "https://cdn.example.com/hero.png",
        )
        with self.assertRaises(ValueError):
            parse_image_url("not-a-url")
        with self.assertRaises(ValueError):
            parse_image_url("ftp://files.example.com/hero.png")

    def test_roundtrip_sheet_image_url(self) -> None:
        sheet = CharacterSheet(name="Hero", image_url="https://example.com/a.png")
        restored = CharacterSheet.from_dict(sheet.to_dict())
        self.assertEqual(restored.image_url, "https://example.com/a.png")

    def test_clear_removes_stored_file(self) -> None:
        import sheets.portrait as portrait

        path = portrait.PORTRAIT_DIR / "7_42.png"
        path.write_bytes(b"png")
        self.assertEqual(portrait_path(guild_id=7, user_id=42), path)
        clear_portrait_file(guild_id=7, user_id=42)
        self.assertIsNone(portrait_path(guild_id=7, user_id=42))

    def test_load_portrait_image_reads_local_file(self) -> None:
        path = Path(self._tmpdir.name) / "3_9.png"
        Image.new("RGB", (12, 12), (10, 20, 30)).save(path)
        loaded = load_portrait_image(guild_id=3, user_id=9)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.getpixel((0, 0))[:3], (10, 20, 30))
        self.assertIsNone(load_portrait_image(guild_id=3, user_id=99))

    def test_is_image_attachment(self) -> None:
        from sheets.portrait import is_image_attachment

        png = MagicMock()
        png.content_type = "image/png"
        png.filename = "face.png"
        self.assertTrue(is_image_attachment(png))
        pdf = MagicMock()
        pdf.content_type = "application/pdf"
        pdf.filename = "sheet.pdf"
        self.assertFalse(is_image_attachment(pdf))
