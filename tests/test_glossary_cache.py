import unittest

from srd.glossary import GlossaryEntry
from srd.glossary_cache import load_glossary, save_glossary


class TestGlossaryCache(unittest.TestCase):
    def test_fingerprint_mismatch_invalidates_cache(self) -> None:
        entry = GlossaryEntry(
            name="Kindred",
            kind="class",
            slug="kindred",
            url="https://5e.tools/classes.html#kindred_boundbyblood",
        )
        save_glossary([entry], fingerprint="old")
        self.assertIsNone(load_glossary(fingerprint="new"))
        cached = load_glossary(fingerprint="old")
        assert cached is not None
        self.assertEqual(cached[0]["name"], "Kindred")


if __name__ == "__main__":
    unittest.main()
