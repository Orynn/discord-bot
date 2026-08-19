import unittest

from srd.fivetools.loader import get_index, reload_index
from srd.fivetools.paths import has_official_source, is_available, is_official_mirror_entry


class TestFiveToolsPaths(unittest.TestCase):
    def test_official_source_available(self) -> None:
        self.assertTrue(has_official_source())
        self.assertTrue(is_available())

    def test_official_mirror_entry_detection(self) -> None:
        entry = {
            "head": {
                "filename": "5etools-src-official.json",
                "url": "https://github.com/5etools-mirror-3/5etools-src.git",
            }
        }
        self.assertTrue(is_official_mirror_entry(entry))
        self.assertFalse(is_official_mirror_entry({"head": {"filename": "My Homebrew.json"}}))


class TestFiveToolsOfficialData(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reload_index()

    def test_acolyte_uses_xphb(self) -> None:
        index = get_index()
        acolyte = index.backgrounds_by_name["acolyte"]
        self.assertEqual(acolyte["source"], "XPHB")

    def test_no_phb_spells_from_official_source(self) -> None:
        index = get_index()
        phb_spells = [s["name"] for s in index.spells_by_name.values() if s.get("source") == "PHB"]
        self.assertEqual(phb_spells, [])

    def test_wizard_uses_xphb(self) -> None:
        index = get_index()
        wizard = index.classes_by_name["wizard"]
        self.assertEqual(wizard["source"], "XPHB")
        self.assertEqual(wizard.get("edition"), "one")

    def test_fireball_indexed_from_official_source(self) -> None:
        index = get_index()
        self.assertIn("fireball", index.spells_by_name)
        self.assertEqual(index.spells_by_name["fireball"]["source"], "XPHB")

    def test_homebrew_spell_still_indexed(self) -> None:
        index = get_index()
        self.assertIn("blood bolt", index.spells_by_name)
        self.assertEqual(index.spells_by_name["blood bolt"]["source"], "CrookedMoon24")

    def test_xmm_goblin_warrior_indexed(self) -> None:
        index = get_index()
        goblin = index.monsters_by_name.get("goblin warrior")
        self.assertIsNotNone(goblin)
        self.assertEqual(goblin["source"], "XMM")


if __name__ == "__main__":
    unittest.main()
