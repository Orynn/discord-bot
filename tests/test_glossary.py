import unittest

from srd import glossary


class TestGlossary(unittest.TestCase):
    def setUp(self) -> None:
        glossary.reset_store()

    def test_register_prefers_longer_name(self) -> None:
        glossary.register_item(name="Fire", kind="spell", slug="fire")
        glossary.register_item(name="Fireball", kind="spell", slug="fireball")
        glossary._store.loaded = True
        glossary._store.rebuild_index()

        mentions = glossary.find_mentions("A Fireball explodes")
        self.assertEqual(len(mentions), 1)
        self.assertEqual(mentions[0].name, "Fireball")

    def test_find_mentions_does_not_link_shorter_overlap(self) -> None:
        glossary.register_item(name="Fire", kind="spell", slug="fire")
        glossary.register_item(name="Fireball", kind="spell", slug="fireball")
        glossary._store.loaded = True
        glossary._store.rebuild_index()

        mentions = glossary.find_mentions("Fire and Fireball")
        names = {entry.name for entry in mentions}
        self.assertEqual(names, {"Fire", "Fireball"})

    def test_find_mentions_case_insensitive(self) -> None:
        glossary.register_item(name="Poisoned", kind="condition", slug="poisoned")
        glossary._store.loaded = True
        glossary._store.rebuild_index()

        mentions = glossary.find_mentions("You are poisoned.")
        self.assertEqual(len(mentions), 1)
        self.assertEqual(mentions[0].kind, "condition")

    def test_register_item_uses_source_in_url(self) -> None:
        glossary.register_item(
            name="Kindred",
            kind="class",
            slug="kindred",
            source="BoundByBlood",
        )
        glossary._store.loaded = True
        entry = glossary.lookup("Kindred")
        assert entry is not None
        self.assertIn("boundbyblood", entry.url.lower())

    def test_register_item_default_source(self) -> None:
        glossary.register_item(name="Fireball", kind="spell", slug="fireball")
        glossary._store.loaded = True
        entry = glossary.lookup("Fireball")
        assert entry is not None
        self.assertIn("xphb", entry.url.lower())
        self.assertNotIn("_phb", entry.url.lower().replace("_xphb", ""))

    def test_register_item_maps_phb_source_to_xphb_url(self) -> None:
        glossary.register_item(
            name="Fireball",
            kind="spell",
            slug="fireball",
            source="PHB",
        )
        glossary._store.loaded = True
        entry = glossary.lookup("Fireball")
        assert entry is not None
        self.assertIn("_xphb", entry.url.lower())


if __name__ == "__main__":
    unittest.main()
