import itertools
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import data.db as db_module
from combat import commands as combat_commands
from combat.encounter import (
    MONSTER,
    PLAYER,
    Combatant,
    Encounter,
    condition_key,
    load_encounter,
    monster_state,
)
from combat.monsters import MonsterStats, roll_hp, stats_from_monster
from combat.render import tracker_embed
from sheets.data import CharacterSheet
from sheets.storage import get_sheet, save_sheet

GUILD = 1
CHANNEL = 10
MJ = 100
PIP = 200


def _monster(name: str, initiative: int, hp: int = 10, **kwargs) -> Combatant:
    return Combatant(
        id="",
        name=name,
        kind=MONSTER,
        initiative=initiative,
        hp=hp,
        hp_max=hp,
        **kwargs,
    )


def _player(name: str, initiative: int, user_id: int) -> Combatant:
    return Combatant(
        id="", name=name, kind=PLAYER, initiative=initiative, user_id=user_id
    )


class TestEncounter(unittest.TestCase):
    def setUp(self) -> None:
        self.encounter = Encounter(guild_id=GUILD, channel_id=CHANNEL)

    def test_order_and_ties(self) -> None:
        enc = self.encounter
        slow = enc.add(_monster("Ogre", 8))
        fast = enc.add(_player("Pip", 15, PIP))
        tie_high = enc.add(_monster("Loup", 12, init_bonus=3))
        tie_low = enc.add(_monster("Rat", 12, init_bonus=0))
        self.assertEqual(enc.order(), [fast, tie_high, tie_low, slow])

    def test_monster_names_number_and_rename(self) -> None:
        enc = self.encounter
        self.assertEqual(enc.monster_names("Gobelin", 1), ["Gobelin"])
        enc.add(_monster("Gobelin", 10))
        self.assertEqual(enc.monster_names("Gobelin", 2), ["Gobelin 2", "Gobelin 3"])
        self.assertEqual(enc.combatants[0].name, "Gobelin 1")
        self.assertEqual(enc.monster_names("Ogre", 2), ["Ogre 1", "Ogre 2"])

    def test_advance_skips_out_monsters_and_counts_rounds(self) -> None:
        enc = self.encounter
        pip = enc.add(_player("Pip", 15, PIP))
        dead = enc.add(_monster("Gobelin 1", 12, hp=0))
        gob = enc.add(_monster("Gobelin 2", 10))
        first = enc.advance()
        self.assertEqual((first.current, enc.round, first.new_round), (pip, 1, True))
        second = enc.advance()
        self.assertEqual(second.current, gob)
        self.assertNotEqual(second.current, dead)
        third = enc.advance()
        self.assertEqual((third.current, enc.round, third.new_round), (pip, 2, True))

    def test_timed_condition_expires_after_its_owner_turns(self) -> None:
        enc = self.encounter
        pip = enc.add(_player("Pip", 15, PIP))
        gob = enc.add(_monster("Gobelin", 10))
        gob.conditions["prone"] = 1
        gob.conditions["poisoned"] = None
        enc.advance()  # Pip
        self.assertEqual(enc.advance().expired, [])  # Pip ends, Gobelin starts
        change = enc.advance()  # Gobelin ends
        self.assertEqual(change.expired, [(gob, "prone")])
        self.assertEqual(change.current, pip)
        self.assertEqual(gob.conditions, {"poisoned": None})

    def test_condition_set_on_own_turn_waits_for_next_turn(self) -> None:
        enc = self.encounter
        pip = enc.add(_player("Pip", 15, PIP))
        enc.add(_monster("Gobelin", 10))
        enc.advance()  # Pip's turn
        enc.set_condition(pip, "prone", 1)
        self.assertEqual(enc.advance().expired, [])  # end of this turn: kept
        enc.advance()  # Gobelin ends, Pip again
        self.assertEqual(enc.advance().expired, [(pip, "prone")])

    def test_everyone_out(self) -> None:
        self.encounter.add(_monster("Gobelin", 10, hp=0))
        with self.assertRaisesRegex(ValueError, "Plus personne"):
            self.encounter.advance()

    def test_remove_current_moves_turn(self) -> None:
        enc = self.encounter
        pip = enc.add(_player("Pip", 15, PIP))
        gob = enc.add(_monster("Gobelin", 10))
        enc.advance()
        enc.remove(pip)
        self.assertEqual(enc.current(), gob)

    def test_find(self) -> None:
        enc = self.encounter
        one = enc.add(_monster("Gobelin 1", 10))
        enc.add(_monster("Gobelin 2", 10))
        pip = enc.add(_player("Pip", 15, PIP))
        self.assertIs(enc.find("gobelin 1"), one)
        self.assertIs(enc.find("Gobelin1"), one)
        self.assertIs(enc.find("pi"), pip)
        with self.assertRaisesRegex(ValueError, "plusieurs"):
            enc.find("gob")
        with self.assertRaisesRegex(ValueError, "Pas de"):
            enc.find("ogre")
        target, rest = enc.find_prefix(["gobelin", "1", "à", "terre"])
        self.assertIs(target, one)
        self.assertEqual(rest, ["à", "terre"])

    def test_round_trip(self) -> None:
        enc = self.encounter
        gob = enc.add(_monster("Gobelin", 10, ac=15))
        gob.conditions["prone"] = 2
        enc.advance()
        restored = Encounter.from_dict(enc.to_dict())
        self.assertEqual(restored, enc)

    def test_monster_state(self) -> None:
        self.assertEqual(monster_state(_monster("A", 1, hp=10)), "indemne")
        hurt = _monster("A", 1, hp=10)
        hurt.hp = 6
        self.assertEqual(monster_state(hurt), "🩹 blessé")
        hurt.hp = 5
        self.assertEqual(monster_state(hurt), "🩸 en sang")
        hurt.hp = 0
        self.assertEqual(monster_state(hurt), "💀 hors combat")

    def test_condition_key(self) -> None:
        self.assertEqual(condition_key("À terre"), "prone")
        self.assertEqual(condition_key("béni"), "blessed")
        self.assertEqual(condition_key("Marque du chasseur"), "marque du chasseur")


class TestMonsterStats(unittest.TestCase):
    def test_from_5etools(self) -> None:
        stats = stats_from_monster(
            {
                "name": "Adult Red Dragon",
                "hp": "256 (19d12 + 133)",
                "ac": "19",
                "dex": 10,
                "cr": "17",
                "initiative": {"proficiency": 2},
                "source": "XMM",
            }
        )
        self.assertEqual(stats.hp_average, 256)
        self.assertEqual(stats.hp_formula, "19d12+133")
        self.assertEqual(stats.ac, 19)
        self.assertEqual(stats.init_bonus, 12)

    def test_plain_dex_and_fraction_cr(self) -> None:
        stats = stats_from_monster(
            {
                "name": "Goblin",
                "hp": "7 (2d6)",
                "ac": "15 (armor)",
                "dex": 14,
                "cr": "1/4",
            }
        )
        self.assertEqual((stats.ac, stats.init_bonus), (15, 2))

    def test_roll_hp(self) -> None:
        stats = MonsterStats(
            name="Goblin", hp_average=7, hp_formula="2d6", ac=15, init_bonus=2
        )
        self.assertEqual(roll_hp(stats, average=True), 7)
        with patch("sheets.dice.random.randint", side_effect=[1, 1]):
            self.assertEqual(roll_hp(stats), 2)
        custom = MonsterStats(
            name="Bandit", hp_average=11, hp_formula=None, ac=12, init_bonus=1
        )
        self.assertEqual(roll_hp(custom), 11)


class TestParsing(unittest.IsolatedAsyncioTestCase):
    async def test_custom_monster_spec(self) -> None:
        spec = await combat_commands.parse_monster_spec(
            "bandit x2 pv 11 ca 12 init 1 # Chef"
        )
        self.assertEqual(spec.count, 2)
        self.assertEqual(spec.name, "Chef")
        self.assertEqual(
            (spec.stats.hp_average, spec.stats.ac, spec.stats.init_bonus), (11, 12, 1)
        )

    async def test_lookup_monster_spec(self) -> None:
        stats = MonsterStats(
            name="Goblin Warrior", hp_average=10, hp_formula="3d6", ac=15, init_bonus=2
        )
        with patch.object(
            combat_commands, "lookup_monster", AsyncMock(return_value=stats)
        ) as lookup:
            spec = await combat_commands.parse_monster_spec(
                "goblin warrior 3x moy ca 16"
            )
        lookup.assert_awaited_once_with("goblin warrior")
        self.assertEqual((spec.count, spec.average, spec.stats.ac), (3, True, 16))

    async def test_bad_specs(self) -> None:
        with self.assertRaisesRegex(ValueError, "nombre après"):
            await combat_commands.parse_monster_spec("bandit pv")
        with self.assertRaisesRegex(ValueError, "Entre 1 et"):
            await combat_commands.parse_monster_spec("bandit x50 pv 4")

    def test_hp_args_and_amount(self) -> None:
        parsed = combat_commands.parse_hp_args("gob 1, gob 2 8d6 feu moitié")
        self.assertEqual(parsed, (["gob 1", "gob 2"], "8d6", True, "fire"))
        self.assertEqual(combat_commands.roll_amount("8"), (8, None))
        with patch("sheets.dice.random.randint", side_effect=[3, 4]):
            total, line = combat_commands.roll_amount("2d6+3")
        self.assertEqual(total, 10)
        self.assertIn("2d6+3", line)
        with self.assertRaises(ValueError):
            combat_commands.roll_amount("beaucoup")


class TestRender(unittest.TestCase):
    def test_players_see_states_mj_sees_hp(self) -> None:
        enc = Encounter(guild_id=GUILD, channel_id=CHANNEL)
        gob = enc.add(_monster("Gobelin", 10, hp=10, ac=15))
        gob.hp = 4
        gob.conditions["prone"] = 1
        enc.add(_player("Pip", 15, PIP))
        enc.advance()
        sheets = {
            PIP: CharacterSheet(
                name="Pip", hp_max=24, hp_current=18, conditions=["blessed"]
            )
        }
        public = tracker_embed(enc, sheets)
        self.assertIn("Round 1", public.title)
        lines = public.description.splitlines()
        self.assertTrue(lines[0].startswith("▶"))
        self.assertIn("PV 18/24", lines[0])
        self.assertIn("🙏 béni", lines[0])
        self.assertIn("🩸 en sang", lines[1])
        self.assertIn("🛌 à terre (1)", lines[1])
        self.assertNotIn("4/10", public.description)
        mj = tracker_embed(enc, sheets, mj=True)
        self.assertIn("PV 4/10 · CA 15", mj.description)


class TestCommandFlow(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        db_module.init_db()
        save_sheet(
            user_id=PIP,
            guild_id=GUILD,
            sheet=CharacterSheet(
                name="Pip",
                hp_max=20,
                hp_current=20,
                abilities={
                    "str": 10,
                    "dex": 14,
                    "con": 10,
                    "int": 10,
                    "wis": 10,
                    "cha": 10,
                },
            ),
        )
        self.replies: list[str] = []
        self.posted: list[str] = []
        message_ids = itertools.count(1000)

        async def channel_send(content=None, embed=None, **_kwargs):
            self.posted.append(content or "")
            return MagicMock(id=next(message_ids))

        self.channel = MagicMock()
        self.channel.id = CHANNEL
        self.channel.send = AsyncMock(side_effect=channel_send)
        partial = MagicMock()
        partial.edit = AsyncMock()
        partial.delete = AsyncMock()
        self.channel.get_partial_message = MagicMock(return_value=partial)

        async def reply(_ctx, message, **_kwargs):
            self.replies.append(message)

        self.patches = [
            patch.object(
                combat_commands, "command_reply", AsyncMock(side_effect=reply)
            ),
            patch.object(combat_commands, "delete_command", AsyncMock()),
            patch.object(
                combat_commands, "is_staff", side_effect=lambda ctx: ctx.author.id == MJ
            ),
            patch.object(
                combat_commands,
                "resolve_owner",
                AsyncMock(side_effect=lambda ctx, member: ctx.author.id),
            ),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in self.patches:
            item.stop()
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    def _ctx(self, author_id: int) -> MagicMock:
        ctx = MagicMock()
        ctx.guild.id = GUILD
        ctx.channel = self.channel
        ctx.author.id = author_id
        ctx.interaction = None
        return ctx

    def _encounter(self) -> Encounter:
        encounter = load_encounter(guild_id=GUILD, channel_id=CHANNEL)
        assert encounter is not None
        return encounter

    async def test_full_fight(self) -> None:
        stats = MonsterStats(
            name="Goblin", hp_average=7, hp_formula=None, ac=15, init_bonus=2
        )
        mj, pip = self._ctx(MJ), self._ctx(PIP)
        with patch.object(
            combat_commands, "lookup_monster", AsyncMock(return_value=stats)
        ):
            with patch("combat.encounter.random.randint", return_value=5):
                await combat_commands.handle_start(mj, "goblin x2")
        self.assertIn("Le combat commence", self.posted[-1])
        enc = self._encounter()
        self.assertEqual([c.name for c in enc.order()], ["Goblin 1", "Goblin 2"])
        self.assertEqual(enc.tracker_message_id, 1000)

        # Players cannot add monsters, but can join.
        await combat_commands.handle_add(pip, "ogre")
        self.assertIn("Seul le MJ", self.replies[-1])
        await combat_commands.handle_join(pip, "18")
        self.assertIn("Pip", self.replies[-1])

        # Round 1: Pip first; only MJ may start the fight.
        await combat_commands.handle_next(pip)
        self.assertIn("Seul le MJ", self.replies[-1])
        await combat_commands.handle_next(mj)
        self.assertIn(f"<@{PIP}>", self.posted[-1])
        self.assertIn("Round 1", self.posted[-1])

        # Pip hits both goblins; Goblin 1 drops.
        await combat_commands._change_hp(pip, "goblin 1, goblin 2 4", healing=False)
        self.assertIn("Tu ne peux changer", self.replies[-1])
        await combat_commands._change_hp(mj, "goblin 1, goblin 2 4", healing=False)
        self.assertIn("**Goblin 2** : −4 → 🩸 en sang", self.replies[-1])
        await combat_commands._change_hp(mj, "goblin 1 3", healing=False)
        self.assertIn("💀 **Goblin 1** est hors combat.", self.replies[-1])

        # Goblin 2 hits Pip and knocks him prone for 1 round.
        await combat_commands._change_hp(mj, f"<@{PIP}> 6", healing=False)
        self.assertIn("PV 20 → 14/20", self.replies[-1])
        self.assertEqual(get_sheet(user_id=PIP, guild_id=GUILD).hp_current, 14)
        await combat_commands.handle_condition(mj, "pip à terre 1")
        self.assertIn("prone", get_sheet(user_id=PIP, guild_id=GUILD).conditions)

        # Set during Pip's turn, `à terre 1` lasts until the end of his next turn.
        # Pip may end his own turn; Goblin 1 (0 HP) is skipped.
        await combat_commands.handle_next(pip)
        self.assertIn("**Goblin 2**", self.posted[-1])
        await combat_commands.handle_next(mj)
        self.assertIn("Round 2", self.posted[-1])
        await combat_commands.handle_next(pip)
        self.assertIn("fin de 🛌 à terre", self.posted[-1])
        self.assertNotIn("prone", get_sheet(user_id=PIP, guild_id=GUILD).conditions)

        # Healing a player, then ending the fight.
        await combat_commands._change_hp(pip, "pip 3", healing=True)
        self.assertIn("PV 14 → 17/20", self.replies[-1])
        await combat_commands.handle_end(mj)
        self.assertIn("Combat terminé après 2 round(s)", self.replies[-1])
        self.assertIsNone(load_encounter(guild_id=GUILD, channel_id=CHANNEL))

    async def test_commands_without_fight(self) -> None:
        await combat_commands.handle_next(self._ctx(MJ))
        self.assertIn("Pas de combat", self.replies[-1])

    async def test_start_twice(self) -> None:
        await combat_commands.handle_start(self._ctx(MJ), "")
        await combat_commands.handle_start(self._ctx(MJ), "")
        self.assertIn("déjà en cours", self.replies[-1])

    async def test_untimed_condition_toggles(self) -> None:
        mj = self._ctx(MJ)
        await combat_commands.handle_start(mj, "bandit pv 11")
        await combat_commands.handle_condition(mj, "bandit empoisonné")
        self.assertEqual(self._encounter().combatants[0].conditions, {"poisoned": None})
        await combat_commands.handle_condition(mj, "bandit empoisonné")
        self.assertEqual(self._encounter().combatants[0].conditions, {})
        self.assertIn("n’est plus", self.replies[-1])


if __name__ == "__main__":
    unittest.main()
