import unittest

from srd.fivetools.images import (
    FIVETOOLS_IMG,
    first_image_url,
    image_href_url,
    media_url,
    monster_token_url,
)
from srd.fivetools.loader import FiveToolsIndex


class TestMonsterImageUrls(unittest.TestCase):
    def test_media_url_encodes_spaces(self) -> None:
        self.assertEqual(
            media_url("bestiary/XMM/Adult Black Dragon.webp"),
            f"{FIVETOOLS_IMG}/bestiary/XMM/Adult%20Black%20Dragon.webp",
        )

    def test_internal_and_external_hrefs(self) -> None:
        self.assertEqual(
            image_href_url(
                {"href": {"type": "internal", "path": "bestiary/XMM/Goblins.webp"}}
            ),
            f"{FIVETOOLS_IMG}/bestiary/XMM/Goblins.webp",
        )
        self.assertEqual(
            image_href_url(
                {"href": {"type": "external", "url": "https://cdn.example.com/owlbear.png"}}
            ),
            "https://cdn.example.com/owlbear.png",
        )
        self.assertIsNone(first_image_url([]))

    def test_token_url_from_has_token(self) -> None:
        url = monster_token_url(
            {"name": "Goblin Warrior", "source": "XMM", "hasToken": True}
        )
        self.assertEqual(
            url, f"{FIVETOOLS_IMG}/bestiary/tokens/XMM/Goblin%20Warrior.webp"
        )
        self.assertIsNone(monster_token_url({"name": "Nameless", "source": "HB"}))

    def test_fluff_copy_inherits_parent_image(self) -> None:
        index = FiveToolsIndex()
        index._ingest_monster_fluff(
            {
                "name": "Goblins",
                "source": "XMM",
                "images": [
                    {
                        "type": "image",
                        "href": {"type": "internal", "path": "bestiary/XMM/Goblins.webp"},
                    }
                ],
            }
        )
        index._ingest_monster_fluff(
            {
                "name": "Goblin Warrior",
                "source": "XMM",
                "_copy": {"name": "Goblins", "source": "XMM"},
            }
        )
        self.assertEqual(
            index.monster_image_url("Goblin Warrior", "XMM"),
            f"{FIVETOOLS_IMG}/bestiary/XMM/Goblins.webp",
        )
        self.assertIsNone(index.monster_image_url("Missing", "XMM"))
