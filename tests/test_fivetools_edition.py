import unittest

from srd.fivetools.edition import edition_rank, should_replace, url_target
from srd.fivetools.lookup import entry_url_for_item


class TestEditionRank(unittest.TestCase):
    def test_include_official_item_drops_phb(self) -> None:
        from srd.fivetools.edition import include_official_item

        self.assertFalse(include_official_item({"source": "PHB", "name": "Fireball"}))
        self.assertTrue(include_official_item({"source": "XPHB", "name": "Fireball"}))

    def test_xphb_beats_phb(self) -> None:
        xphb = {"name": "Fireball", "source": "XPHB", "basicRules2024": True}
        phb = {"name": "Fireball", "source": "PHB"}
        self.assertGreater(edition_rank(xphb), edition_rank(phb))

    def test_edition_one_beats_xphb(self) -> None:
        one = {"name": "Wizard", "source": "XPHB", "edition": "one"}
        classic = {"name": "Wizard", "source": "XPHB"}
        self.assertGreater(edition_rank(one), edition_rank(classic))

    def test_should_replace_phb_with_xphb(self) -> None:
        phb = {"name": "Fireball", "source": "PHB"}
        xphb = {"name": "Fireball", "source": "XPHB", "basicRules2024": True}
        self.assertTrue(should_replace(phb, xphb))
        self.assertFalse(should_replace(xphb, phb))

    def test_url_target_maps_phb_to_xphb(self) -> None:
        name, source = url_target({"name": "Fireball", "source": "PHB"})
        self.assertEqual(name, "Fireball")
        self.assertEqual(source, "XPHB")

    def test_url_target_follows_reprinted_as(self) -> None:
        item = {
            "name": "Shining Smite",
            "source": "PHB",
            "reprintedAs": ["Shining Smite|XPHB"],
        }
        name, source = url_target(item)
        self.assertEqual(name, "Shining Smite")
        self.assertEqual(source, "XPHB")
        url = entry_url_for_item("spell", item)
        self.assertIn("shining%20smite_xphb", url.lower())

    def test_url_source_maps_mm_to_xmm(self) -> None:
        name, source = url_target({"name": "Goblin Warrior", "source": "MM"})
        self.assertEqual(name, "Goblin Warrior")
        self.assertEqual(source, "XMM")


if __name__ == "__main__":
    unittest.main()
