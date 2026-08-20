import unittest

from combat.monsters import lookup_monster_profile, profile_from_monster
from srd.fivetools.loader import reload_index


def setUpModule() -> None:
    reload_index()


class TestMonsterProfiles(unittest.IsolatedAsyncioTestCase):
    async def test_goblin_warrior_scimitar_and_nimble_escape(self) -> None:
        profile = await lookup_monster_profile("Goblin Warrior")
        assert profile is not None
        self.assertEqual(profile.attack_name, "Scimitar")
        self.assertEqual(profile.dice_count, 1)
        self.assertEqual(profile.dice_sides, 6)
        self.assertEqual(profile.flat_modifier, 2)
        self.assertEqual(profile.hp, 10)
        self.assertEqual(profile.ac, 15)
        self.assertEqual(profile.attack_bonus, 4)
        self.assertTrue(any("nimble escape" in trait.lower() for trait in profile.traits))

    async def test_wolf_has_pack_tactics_and_bite(self) -> None:
        profile = await lookup_monster_profile("Wolf")
        assert profile is not None
        self.assertEqual(profile.attack_name, "Bite")
        self.assertIn("Pack Tactics", profile.traits)

    def test_profile_from_legacy_damage_tag(self) -> None:
        profile = profile_from_monster(
            {
                "name": "Goblin",
                "hp": {"average": 7, "formula": "2d6"},
                "trait": [{"name": "Nimble Escape", "entries": ["Disengage or Hide."]}],
                "action": [
                    {
                        "name": "Scimitar",
                        "entries": [
                            "{@atk mw} {@hit 4} to hit. {@h}5 ({@damage 1d6 + 2}) slashing damage."
                        ],
                    }
                ],
            }
        )
        self.assertEqual(profile.hp, 7)
        self.assertEqual(profile.ac, 10)
        self.assertEqual(profile.attack_bonus, 4)
        self.assertEqual(profile.attack_name, "Scimitar")
        self.assertEqual((profile.dice_count, profile.dice_sides, profile.flat_modifier), (1, 6, 2))
        self.assertEqual(profile.traits, ("Nimble Escape",))
