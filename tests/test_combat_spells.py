import itertools
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import data.db as db_module
from combat import commands as combat_commands
from combat.attacks import DamagePart
from combat.effects import (
    concentration_check,
    link_to_concentration,
    roll_save,
    start_concentration,
)
from combat.encounter import (
    MONSTER,
    PLAYER,
    Combatant,
    Encounter,
    load_encounter,
    save_encounter,
)
from combat.hp import damage_combatant
from combat.spells import (
    SpellInfo,
    damage_for_cast,
    heal_for_cast,
    monster_save_actions,
    monster_spellcasting,
    projectile_count,
    spell_from_5etools,
)
from combat.views import ComponentContext, TrackerView
from sheets.data import CharacterSheet
from sheets.spell_slots import SpellSlots
from sheets.storage import get_sheet, save_sheet

GUILD = 1
CHANNEL = 10
MJ = 100
PIP = 200

FIREBALL_RAW = {
    "name": "Fireball",
    "level": 3,
    "savingThrow": ["dexterity"],
    "damageInflict": ["fire"],
    "duration": [{"type": "instant"}],
    "entries": [
        "Each creature in a 20-foot-radius Sphere … makes a Dexterity saving throw, taking "
        "{@damage 8d6} Fire damage on a failed save or half as much damage on a successful one."
    ],
    "entriesHigherLevel": [
        {"type": "entries", "entries": ["{@scaledamage 8d6|3-9|1d6}"]}
    ],
}
FIRE_BOLT_RAW = {
    "name": "Fire Bolt",
    "level": 0,
    "spellAttack": ["R"],
    "damageInflict": ["fire"],
    "entries": ["Make a ranged spell attack … {@damage 1d10} Fire damage."],
    "scalingLevelDice": {
        "label": "Fire damage",
        "scaling": {"1": "1d10", "5": "2d10", "11": "3d10", "17": "4d10"},
    },
}
CURE_RAW = {
    "name": "Cure Wounds",
    "level": 1,
    "miscTags": ["HL"],
    "entries": [
        "A creature you touch regains a number of Hit Points equal to {@dice 2d8} plus your spellcasting ability modifier."
    ],
    "entriesHigherLevel": [{"entries": ["{@scaledice 2d8|1-9|2d8}"]}],
}
HOLD_RAW = {
    "name": "Hold Person",
    "level": 2,
    "savingThrow": ["wisdom"],
    "conditionInflict": ["paralyzed"],
    "duration": [
        {
            "type": "timed",
            "duration": {"type": "minute", "amount": 1},
            "concentration": True,
        }
    ],
    "entries": [
        "Choose a Humanoid … or have the {@condition Paralyzed|XPHB} condition."
    ],
}
BLESS_RAW = {
    "name": "Bless",
    "level": 1,
    "duration": [
        {
            "type": "timed",
            "duration": {"type": "minute", "amount": 1},
            "concentration": True,
        }
    ],
    "entries": ["… add {@dice 1d4} to the attack roll or saving throw."],
}
MISSILE_RAW = {
    "name": "Magic Missile",
    "level": 1,
    "damageInflict": ["force"],
    "entries": ["Each dart … deals {@damage 1d4 + 1} Force damage to its target."],
}
DRAGON = {
    "action": [
        {
            "name": "Fire Breath {@recharge 5}",
            "entries": [
                "{@actSave dex} {@dc 21}, each creature in a 60-foot Cone. {@actSaveFail} 59 "
                "({@damage 17d6}) Fire damage. {@actSaveSuccess} Half damage."
            ],
        },
        {
            "name": "Frightful Presence",
            "entries": [
                "{@actSave wis} {@dc 19} {@actSaveFail} The target has the {@condition Frightened|XPHB} condition."
            ],
        },
    ]
}


def _faces(*values: int):
    return patch("sheets.dice.random.randint", side_effect=list(values))


class TestSpellData(unittest.TestCase):
    def test_fireball(self) -> None:
        info = spell_from_5etools({"name": "Fireball"}, FIREBALL_RAW)
        self.assertEqual((info.level, info.save, info.half_on_save), (3, "dex", True))
        self.assertEqual([(p.dice, p.type) for p in info.damage], [("8d6", "fire")])
        self.assertEqual(info.upcast_step, "1d6")
        self.assertEqual(
            damage_for_cast(info, cast_level=5, character_level=9)[0].dice, "10d6"
        )
        restored = SpellInfo.from_dict(info.to_dict())
        self.assertEqual(restored, info)

    def test_cantrip_scaling(self) -> None:
        info = spell_from_5etools({"name": "Fire Bolt"}, FIRE_BOLT_RAW)
        self.assertEqual(info.attack, "R")
        self.assertEqual(
            damage_for_cast(info, cast_level=0, character_level=11)[0].dice, "3d10"
        )
        self.assertEqual(
            damage_for_cast(info, cast_level=0, character_level=4)[0].dice, "1d10"
        )

    def test_healing(self) -> None:
        info = spell_from_5etools({"name": "Cure Wounds"}, CURE_RAW)
        self.assertEqual((info.heal_dice, info.heal_adds_modifier), ("2d8", True))
        self.assertEqual(heal_for_cast(info, cast_level=3), "6d8")

    def test_conditions_and_concentration(self) -> None:
        hold = spell_from_5etools({"name": "Hold Person"}, HOLD_RAW)
        self.assertEqual(
            (hold.conditions, hold.concentration, hold.duration_rounds),
            (["paralyzed"], True, 10),
        )
        bless = spell_from_5etools({"name": "Bless"}, BLESS_RAW)
        self.assertEqual(bless.conditions, ["blessed"])
        self.assertEqual(bless.damage, [])

    def test_projectiles(self) -> None:
        missile = spell_from_5etools({"name": "Magic Missile"}, MISSILE_RAW)
        self.assertEqual(projectile_count(missile, cast_level=3, character_level=5), 5)
        blast = SpellInfo(
            name="Eldritch Blast", attack="R", damage=[DamagePart("1d10", "force")]
        )
        self.assertEqual(projectile_count(blast, cast_level=0, character_level=11), 3)

    def test_monster_save_actions(self) -> None:
        breath, fear = monster_save_actions(DRAGON)
        self.assertEqual(breath.name, "Fire Breath (recharge 5)")
        self.assertEqual(
            (breath.save, breath.dc, breath.half_on_save), ("dex", 21, True)
        )
        self.assertEqual([(p.dice, p.type) for p in breath.damage], [("17d6", "fire")])
        self.assertEqual((fear.save, fear.conditions), ("wis", ["frightened"]))

    def test_monster_spellcasting(self) -> None:
        self.assertEqual(
            monster_spellcasting(
                {"spellcasting": "uses Intelligence (spell save DC 14, +6 to hit)"}
            ),
            (14, 6),
        )
        self.assertEqual(monster_spellcasting({}), (None, None))


class _SpellCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        db_module.init_db()
        slots = SpellSlots()
        slots.set_level(1, 4)
        slots.set_level(3, 2)
        sheet = CharacterSheet(
            name="Pip",
            char_class="Wizard",
            level=5,
            hp_max=20,
            hp_current=20,
            ac=12,
            abilities={"str": 8, "dex": 14, "con": 14, "int": 18, "wis": 10, "cha": 10},
            save_proficiencies=["int", "wis"],
            spell_slots=slots,
        )
        save_sheet(user_id=PIP, guild_id=GUILD, sheet=sheet)
        self.encounter = Encounter(guild_id=GUILD, channel_id=CHANNEL)
        self.pip = self.encounter.add(
            Combatant(id="", name="Pip", kind=PLAYER, initiative=15, user_id=PIP)
        )
        self.gob = self.encounter.add(
            Combatant(
                id="",
                name="Gobelin",
                kind=MONSTER,
                initiative=12,
                hp=30,
                hp_max=30,
                ac=13,
                saves={"dex": 2, "wis": -1, "con": 0},
            )
        )
        self.salamander = self.encounter.add(
            Combatant(
                id="",
                name="Salamandre",
                kind=MONSTER,
                initiative=8,
                hp=40,
                hp_max=40,
                ac=15,
                saves={"dex": 0},
                resist=["fire"],
            )
        )

    def tearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    def _sheet(self) -> CharacterSheet:
        sheet = get_sheet(user_id=PIP, guild_id=GUILD)
        assert sheet is not None
        return sheet

    def _ctx(self, author_id: int) -> MagicMock:
        ctx = MagicMock()
        ctx.guild.id = GUILD
        ctx.author.id = author_id
        ctx.interaction = None
        return ctx

    def _cast(self, info: SpellInfo, args: str, author: int = PIP) -> list[str]:
        with patch.object(
            combat_commands, "is_staff", side_effect=lambda ctx: ctx.author.id == MJ
        ):
            request = combat_commands.parse_cast(
                self._ctx(author), self.encounter, args
            )
            sheet = self._sheet() if request.caster.is_player else None
            return combat_commands.cast_spell(self.encounter, request, info, sheet)


class TestCasting(_SpellCase):
    def test_parse_cast(self) -> None:
        with patch.object(combat_commands, "is_staff", return_value=False):
            request = combat_commands.parse_cast(
                self._ctx(PIP),
                self.encounter,
                "boule de feu niv 4 dc 15 adv sur gob, moi",
            )
        self.assertEqual(request.query, "boule de feu")
        self.assertEqual((request.level, request.dc, request.advantage), (4, 15, True))
        self.assertEqual(request.targets, [self.gob, self.pip])

    def test_fireball_saves_halves_and_resistance(self) -> None:
        info = spell_from_5etools({"name": "Fireball"}, FIREBALL_RAW)
        # Damage rolled once (8 × 3 = 24); goblin fails (5+2), salamander saves (20).
        with _faces(*([3] * 8), 5, 20):
            lines = self._cast(info, "fireball sur gob, salamandre")
        text = "\n".join(lines)
        self.assertIn("emplacement niv. 3 : 1/2", text)
        self.assertIn(
            "**Gobelin** — sauvegarde DEX : ❌ 5 → 7 vs DD 15 → 24 dégâts", text
        )
        self.assertIn(
            "**Salamandre** — sauvegarde DEX : ✅ 20 vs DD 15 → 6 dégâts", text
        )
        self.assertEqual((self.gob.hp, self.salamander.hp), (6, 34))
        self.assertEqual(self._sheet().spell_slots.get_current(3), 1)

    def test_out_of_slots(self) -> None:
        info = spell_from_5etools({"name": "Fireball"}, FIREBALL_RAW)
        sheet = self._sheet()
        sheet.spell_slots.use(3, 2)
        save_sheet(user_id=PIP, guild_id=GUILD, sheet=sheet)
        with self.assertRaisesRegex(ValueError, "Plus d’emplacement"):
            self._cast(info, "fireball sur gob")
        self.assertEqual(self.gob.hp, 30)

    def test_fire_bolt_attack(self) -> None:
        info = spell_from_5etools({"name": "Fire Bolt"}, FIRE_BOLT_RAW)
        with _faces(10, 7, 3):
            lines = self._cast(info, "trait de feu sur gob")
        text = "\n".join(lines)
        self.assertIn("10 + 7 = **17** contre CA 13 → ✅ Touché", text)
        self.assertIn("`2d10` → 10 feu", text)
        self.assertEqual(self.gob.hp, 20)

    def test_cure_wounds_on_self(self) -> None:
        sheet = self._sheet()
        sheet.hp_current = 5
        save_sheet(user_id=PIP, guild_id=GUILD, sheet=sheet)
        info = spell_from_5etools({"name": "Cure Wounds"}, CURE_RAW)
        with _faces(3, 4):
            lines = self._cast(info, "soins")
        self.assertIn("= **11** PV", lines[1])
        self.assertEqual(self._sheet().hp_current, 16)

    def test_hold_person_links_to_concentration(self) -> None:
        info = spell_from_5etools({"name": "Hold Person"}, HOLD_RAW)
        with self.assertRaisesRegex(ValueError, "Lance-le plus haut : `niv 3`"):
            self._cast(info, "hold person sur gob")
        with _faces(2):
            lines = self._cast(info, "hold person niv 3 sur gob")
        self.assertIn("paralysé", "\n".join(lines))
        self.assertIn("paralyzed", self.gob.conditions)
        self.assertEqual(self.pip.concentration["links"], [[self.gob.id, "paralyzed"]])
        # Pip takes 22 damage: CON save DC 11 with +2; a 3 fails and frees the goblin.
        with _faces(3):
            lines = damage_combatant(self.encounter, self.pip, 12)
        self.assertIn("perd sa concentration sur Hold Person", "\n".join(lines))
        self.assertNotIn("paralyzed", self.gob.conditions)
        self.assertIsNone(self.pip.concentration)

    def test_bless_puts_condition_on_sheet(self) -> None:
        info = spell_from_5etools({"name": "Bless"}, BLESS_RAW)
        self._cast(info, "bless sur moi")
        self.assertIn("blessed", self._sheet().conditions)
        self.assertEqual(self.pip.concentration["spell"], "Bless")

    def test_magic_missile_spreads_darts(self) -> None:
        info = spell_from_5etools({"name": "Magic Missile"}, MISSILE_RAW)
        with _faces(1, 1, 1):
            lines = self._cast(info, "projectile magique sur gob, salamandre")
        text = "\n".join(lines)
        self.assertIn("3 projectiles", text)
        self.assertIn("**Gobelin** : 4 dégâts", text)
        self.assertIn("**Salamandre** : 2 dégâts", text)

    def test_monster_breath(self) -> None:
        self.gob.save_actions = [
            action.to_dict() for action in monster_save_actions(DRAGON)
        ]
        self.encounter.current_id = self.gob.id
        info = SpellInfo.from_dict(self.gob.save_actions[0])
        with _faces(*([1] * 17), 10):
            lines = self._cast(info, "fire breath sur pip", author=MJ)
        text = "\n".join(lines)
        self.assertIn("**Gobelin** lance **Fire Breath (recharge 5)**", text)
        self.assertIn("vs DD 21", text)
        self.assertIn("→ 17 dégâts", text)

    def test_monster_spell_needs_dc(self) -> None:
        info = spell_from_5etools({"name": "Fireball"}, FIREBALL_RAW)
        self.encounter.current_id = self.gob.id
        with self.assertRaisesRegex(ValueError, "ajoute `dc 15`"):
            self._cast(info, "fireball sur pip", author=MJ)


class TestSavesAndConcentration(_SpellCase):
    def test_auto_fail_and_restrained(self) -> None:
        self.gob.conditions["paralyzed"] = None
        self.assertTrue(roll_save(self.encounter, self.gob, "dex", 10).auto_fail)
        self.gob.conditions = {"restrained": None}
        with patch("combat.effects.random.randint", side_effect=[18, 4]):
            result = roll_save(self.encounter, self.gob, "dex", 10)
        self.assertFalse(result.success)

    def test_player_save_uses_sheet(self) -> None:
        with _faces(10):
            result = roll_save(self.encounter, self.pip, "int", 15)
        self.assertEqual(result.total, 10 + 4 + 3)

    def test_concentration_kept(self) -> None:
        start_concentration(self.encounter, self.gob, "Web")
        link_to_concentration(self.gob, self.pip, "restrained")
        with patch("combat.effects.random.randint", return_value=15):
            lines = concentration_check(self.encounter, self.gob, 30)
        self.assertIn("garde sa concentration", lines[0])
        self.assertIn("DD 15", lines[0])

    def test_reaction_once_per_round(self) -> None:
        self.assertEqual(combat_commands.use_reaction(self.gob, False), "")
        self.assertIn("Réaction", combat_commands.use_reaction(self.gob, True))
        with self.assertRaisesRegex(ValueError, "déjà utilisé"):
            combat_commands.use_reaction(self.gob, True)
        self.encounter.advance()  # Pip
        self.encounter.advance()  # Gobelin's turn: reaction back
        self.assertFalse(self.gob.reaction_used)


class TestCastCommandAndViews(_SpellCase):
    def setUp(self) -> None:
        super().setUp()
        save_encounter(self.encounter)
        self.replies: list[str] = []
        ids = itertools.count(1000)
        self.channel = MagicMock()
        self.channel.id = CHANNEL
        self.channel.send = AsyncMock(side_effect=lambda **_: MagicMock(id=next(ids)))
        self.channel.get_partial_message = MagicMock(
            return_value=MagicMock(edit=AsyncMock(), delete=AsyncMock())
        )

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
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in self.patches:
            item.stop()
        super().tearDown()

    async def test_cast_command(self) -> None:
        ctx = self._ctx(PIP)
        ctx.channel = self.channel
        info = spell_from_5etools({"name": "Fireball"}, FIREBALL_RAW)
        with patch.object(
            combat_commands, "lookup_spell", AsyncMock(return_value=info)
        ):
            with _faces(*([6] * 8), 1, 1):
                await combat_commands.handle_cast(
                    ctx, "boule de feu sur gob, salamandre"
                )
        self.assertIn("lance **Fireball**", self.replies[-1])
        encounter = load_encounter(guild_id=GUILD, channel_id=CHANNEL)
        self.assertEqual(encounter.get(self.gob.id).hp, 0)
        view = self.channel.send.await_args.kwargs["view"]
        self.assertIsInstance(view, TrackerView)

    async def test_tracker_view_lists_targets(self) -> None:
        self.gob.hp = 0
        view = TrackerView(self.encounter)
        select = next(
            item
            for item in view.children
            if getattr(item, "custom_id", "") == "arkann:combat:attack"
        )
        self.assertEqual(
            [option.label for option in select.options], ["Pip", "Salamandre"]
        )
        empty = TrackerView(None)
        self.assertEqual(len(empty.children), 5)

    async def test_component_context_sends_ephemeral_errors(self) -> None:
        interaction = MagicMock()
        interaction.guild.id = GUILD
        interaction.channel = self.channel
        interaction.user.id = PIP
        interaction.response.is_done = MagicMock(return_value=False)
        interaction.response.send_message = AsyncMock()
        interaction.original_response = AsyncMock()
        ctx = ComponentContext(interaction)
        await combat_commands.handle_attack(ctx, "personne")
        interaction.response.send_message.assert_awaited_once()
        self.assertTrue(
            interaction.response.send_message.await_args.kwargs["ephemeral"]
        )


if __name__ == "__main__":
    unittest.main()
