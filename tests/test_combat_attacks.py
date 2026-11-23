import itertools
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import data.db as db_module
from combat import commands as combat_commands
from combat.attacks import (
    Attack,
    AttackContext,
    DamagePart,
    attack_advantage,
    damage_types_in,
    monster_attacks,
    resolve_attack,
    weapon_attack,
)
from combat.encounter import (
    MONSTER,
    PLAYER,
    Combatant,
    Encounter,
    load_encounter,
    save_encounter,
)
from combat.hp import damage_combatant, heal_combatant, roll_death_save, set_temp_hp
from sheets.data import CharacterSheet
from sheets.equipment import ITEM_KIND_WEAPON, InventoryItem
from sheets.storage import get_sheet, save_sheet

GUILD = 1
CHANNEL = 10
MJ = 100
PIP = 200

LONGSWORD = {
    "name": "Longsword",
    "type": "M|XPHB",
    "dmg1": "1d8",
    "dmg2": "1d10",
    "dmgType": "S",
    "property": ["V|XPHB"],
}
RAPIER = {
    "name": "Rapier",
    "type": "M|XPHB",
    "dmg1": "1d8",
    "dmgType": "P",
    "property": ["F|XPHB"],
}
LONGBOW = {
    "name": "Longbow",
    "type": "R|XPHB",
    "dmg1": "1d8",
    "dmgType": "P",
    "property": ["A|XPHB"],
}
GOBLIN_ACTIONS = {
    "action": [
        {
            "name": "Scimitar",
            "entries": [
                "{@atkr m} {@hit 4}, reach 5 ft. {@h}5 ({@damage 1d6 + 2}) Slashing damage, "
                "plus 2 ({@damage 1d4}) Slashing damage if the attack roll had "
                "{@variantrule Advantage|XPHB}."
            ],
        },
        {
            "name": "Shortbow",
            "entries": [
                "{@atkr r} {@hit 4}, range 80/320 ft. {@h}5 ({@damage 1d6 + 2}) Piercing damage."
            ],
        },
        {
            "name": "Fire Breath {@recharge 5}",
            "entries": ["{@actSave dex} {@dc 13} … {@damage 6d6} Fire damage."],
        },
    ]
}


def _sheet(**kwargs) -> CharacterSheet:
    abilities = {"str": 16, "dex": 14, "con": 10, "int": 10, "wis": 10, "cha": 10}
    return CharacterSheet(name="Pip", level=5, abilities=abilities, **kwargs)


def _faces(*values: int):
    return patch("sheets.dice.random.randint", side_effect=list(values))


class TestParsing(unittest.TestCase):
    def test_monster_attacks(self) -> None:
        attacks = monster_attacks(GOBLIN_ACTIONS)
        self.assertEqual([a.name for a in attacks], ["Scimitar", "Shortbow"])
        scimitar, bow = attacks
        self.assertEqual(scimitar.hit, 4)
        self.assertFalse(scimitar.ranged)
        self.assertTrue(bow.ranged)
        self.assertEqual(
            [(p.dice, p.type, p.needs_advantage) for p in scimitar.damage],
            [("1d6+2", "slashing", False), ("1d4", "slashing", True)],
        )
        restored = Attack.from_dict(scimitar.to_dict())
        self.assertEqual(restored, scimitar)

    def test_damage_types_in(self) -> None:
        self.assertEqual(damage_types_in("🔥 Fire, ☠️ Poison"), ["fire", "poison"])
        self.assertEqual(damage_types_in("—"), [])

    def test_weapon_attack(self) -> None:
        sheet = _sheet()  # STR +3, DEX +2, proficiency +3
        sword = weapon_attack(sheet, name="Longsword", raw=LONGSWORD)
        self.assertEqual(
            (sword.hit, sword.damage[0].dice, sword.damage[0].type),
            (6, "1d8+3", "slashing"),
        )
        versatile = weapon_attack(
            sheet, name="Longsword", raw=LONGSWORD, two_handed=True
        )
        self.assertEqual(versatile.damage[0].dice, "1d10+3")
        bow = weapon_attack(sheet, name="Longbow", raw=LONGBOW)
        self.assertEqual((bow.hit, bow.ranged, bow.damage[0].dice), (5, True, "1d8+2"))
        nimble = _sheet()
        nimble.abilities["dex"] = 18
        rapier = weapon_attack(nimble, name="Rapier", raw=RAPIER)
        self.assertEqual(rapier.hit, 7)
        magic = weapon_attack(sheet, name="Longsword +1", raw=LONGSWORD)
        self.assertEqual((magic.hit, magic.damage[0].dice), (7, "1d8+4"))
        self.assertIsNone(weapon_attack(sheet, name="Bâton maison", raw=None))


class TestAdvantage(unittest.TestCase):
    melee = Attack(name="Sword", hit=5, damage=[DamagePart("1d8")])
    ranged = Attack(name="Bow", hit=5, damage=[DamagePart("1d8")], ranged=True)

    def test_prone_target(self) -> None:
        context = AttackContext(attacker_conditions=set(), target_conditions={"prone"})
        self.assertTrue(attack_advantage(self.melee, context)[0])
        self.assertFalse(attack_advantage(self.ranged, context)[0])

    def test_cancel_out(self) -> None:
        context = AttackContext(
            attacker_conditions={"poisoned"}, target_conditions={"restrained"}
        )
        advantage, notes = attack_advantage(self.melee, context)
        self.assertIsNone(advantage)
        self.assertEqual(len(notes), 2)


class TestResolve(unittest.TestCase):
    attack = Attack(
        name="Scimitar",
        hit=4,
        damage=[
            DamagePart("1d6+2", "slashing"),
            DamagePart("1d4", "slashing", needs_advantage=True),
        ],
    )

    def _resolve(
        self, *faces: int, ac=15, target=frozenset(), requested=None, **kwargs
    ):
        context = AttackContext(set(), set(target), requested=requested)
        with _faces(*faces):
            return resolve_attack(
                self.attack,
                attacker_sheet=None,
                context=context,
                target_ac=ac,
                **kwargs,
            )

    def test_hit_and_miss(self) -> None:
        hit = self._resolve(11, 3)
        self.assertTrue(hit.hit)
        self.assertEqual(hit.total_damage, 5)
        self.assertEqual(len(hit.skipped), 1)
        miss = self._resolve(10)
        self.assertFalse(miss.hit)
        self.assertEqual(miss.damage, [])

    def test_natural_rolls(self) -> None:
        crit = self._resolve(20, 3, 4, ac=30)
        self.assertTrue(crit.hit and crit.critical)
        self.assertEqual(crit.total_damage, 3 + 4 + 2)
        self.assertEqual(crit.damage[0].notation, "2d6+2")
        fumble = self._resolve(1, ac=0)
        self.assertFalse(fumble.hit)
        self.assertTrue(fumble.fumble)

    def test_advantage_adds_bonus_part(self) -> None:
        outcome = self._resolve(3, 15, 2, 4, requested=True)
        self.assertEqual(outcome.total_damage, 2 + 2 + 4)
        self.assertEqual(outcome.skipped, [])

    def test_auto_crit_on_paralyzed(self) -> None:
        outcome = self._resolve(4, 15, 3, 3, 1, 1, target={"paralyzed"})
        self.assertTrue(outcome.critical)
        self.assertTrue(
            any("critique automatique" in note for note in outcome.advantage_notes)
        )

    def test_unknown_ac_and_defenses(self) -> None:
        unknown = self._resolve(12, ac=None)
        self.assertIsNone(unknown.hit)
        resisted = self._resolve(15, 6, resist=["slashing"])
        self.assertEqual(resisted.total_damage, 4)
        immune = self._resolve(15, 6, immune=["slashing"])
        self.assertEqual(immune.total_damage, 0)
        vulnerable = self._resolve(15, 6, vulnerable=["slashing"])
        self.assertEqual(vulnerable.total_damage, 16)


class _DbCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        db_module.init_db()
        save_sheet(
            user_id=PIP, guild_id=GUILD, sheet=_sheet(hp_max=20, hp_current=20, ac=16)
        )
        self.encounter = Encounter(guild_id=GUILD, channel_id=CHANNEL)
        self.pip = self.encounter.add(
            Combatant(id="", name="Pip", kind=PLAYER, initiative=15, user_id=PIP)
        )
        self.gob = self.encounter.add(
            Combatant(
                id="",
                name="Gobelin",
                kind=MONSTER,
                initiative=10,
                hp=10,
                hp_max=10,
                ac=15,
                attacks=[a.to_dict() for a in monster_attacks(GOBLIN_ACTIONS)],
                resist=["fire"],
            )
        )

    def tearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    def _pip_sheet(self) -> CharacterSheet:
        sheet = get_sheet(user_id=PIP, guild_id=GUILD)
        assert sheet is not None
        return sheet


class TestHp(_DbCase):
    def test_temp_hp_soaks_first(self) -> None:
        self.assertIn("5 PV temporaires", set_temp_hp(self.gob, 5))
        self.assertIn("ne se cumulent pas", set_temp_hp(self.gob, 3))
        lines = damage_combatant(self.encounter, self.gob, 7)
        self.assertIn("5 absorbé", lines[0])
        self.assertEqual((self.gob.temp_hp, self.gob.hp), (0, 8))

    def test_player_down_then_hit(self) -> None:
        lines = damage_combatant(self.encounter, self.pip, 25)
        self.assertIn("PV 20 → 0/20", lines[0])
        self.assertIn("tombe à 0 PV", lines[1])
        self.assertFalse(self.pip.dead)
        damage_combatant(self.encounter, self.pip, 3)
        self.assertEqual(self._pip_sheet().death_save_failures, 1)
        lines = damage_combatant(self.encounter, self.pip, 3, critical=True)
        self.assertEqual(self._pip_sheet().death_save_failures, 3)
        self.assertTrue(self.pip.dead)
        self.assertIn("meurt", lines[-1])
        self.assertTrue(self.pip.is_out)

    def test_massive_damage(self) -> None:
        lines = damage_combatant(self.encounter, self.pip, 40)
        self.assertTrue(self.pip.dead)
        self.assertIn("dégâts massifs", lines[-1])

    def test_heal_from_zero(self) -> None:
        damage_combatant(self.encounter, self.pip, 20)
        damage_combatant(self.encounter, self.pip, 1)
        lines = heal_combatant(self.encounter, self.pip, 4)
        self.assertIn("se relève", lines[0])
        sheet = self._pip_sheet()
        self.assertEqual((sheet.hp_current, sheet.death_save_failures), (4, 0))

    def test_death_saves(self) -> None:
        damage_combatant(self.encounter, self.pip, 20)
        with _faces(12):
            self.assertIn(
                "Réussite. ✅ 1/3", roll_death_save(self.encounter, self.pip)[1]
            )
        with _faces(1):
            self.assertIn("deux échecs", roll_death_save(self.encounter, self.pip)[1])
        with _faces(5):
            lines = roll_death_save(self.encounter, self.pip)
        self.assertIn("meurt", lines[-1])
        self.assertTrue(self.pip.dead)

    def test_death_save_twenty_and_stable(self) -> None:
        damage_combatant(self.encounter, self.pip, 20)
        with _faces(20):
            self.assertIn("reprend 1 PV", roll_death_save(self.encounter, self.pip)[1])
        self.assertEqual(self._pip_sheet().hp_current, 1)
        with self.assertRaisesRegex(ValueError, "n’est pas à 0 PV"):
            roll_death_save(self.encounter, self.pip)
        damage_combatant(self.encounter, self.pip, 1)
        with _faces(10, 11, 12):
            for _ in range(3):
                lines = roll_death_save(self.encounter, self.pip)
        self.assertIn("stabilisé", lines[-1])
        with self.assertRaisesRegex(ValueError, "déjà stabilisé"):
            roll_death_save(self.encounter, self.pip)


class TestAttackCommand(_DbCase, unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        super().setUp()
        sheet = self._pip_sheet()
        sheet.equipment.items.append(
            InventoryItem(
                slug="longsword", name="Longsword", kind=ITEM_KIND_WEAPON, equipped=True
            )
        )
        save_sheet(user_id=PIP, guild_id=GUILD, sheet=sheet)
        save_encounter(self.encounter)
        self.replies: list[str] = []
        ids = itertools.count(1000)
        self.channel = MagicMock()
        self.channel.id = CHANNEL
        self.channel.send = AsyncMock(side_effect=lambda **_: MagicMock(id=next(ids)))
        partial = MagicMock(edit=AsyncMock(), delete=AsyncMock())
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
                "_indexed_equipment",
                side_effect=lambda slug: (
                    ("weapon", LONGSWORD) if slug == "longsword" else None
                ),
            ),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in self.patches:
            item.stop()
        super().tearDown()

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

    async def test_player_attacks_with_sheet_weapon(self) -> None:
        with _faces(12, 5):
            await combat_commands.handle_attack(self._ctx(PIP), "gobelin")
        reply = self.replies[-1]
        self.assertIn("**Pip** → **Gobelin** · Longsword", reply)
        self.assertIn("12 + 6 = **18** contre CA 15 → ✅ Touché", reply)
        self.assertIn("`1d8+3` → 8 tranchant", reply)
        self.assertEqual(self._encounter().get(self.gob.id).hp, 2)

    async def test_french_weapon_name_and_two_hands(self) -> None:
        with _faces(12, 9):
            await combat_commands.handle_attack(
                self._ctx(PIP), "gobelin épée longue 2m"
            )
        self.assertIn("`1d10+3` → 12", self.replies[-1])

    async def test_unknown_weapon(self) -> None:
        await combat_commands.handle_attack(self._ctx(PIP), "gobelin arbalète lourde")
        self.assertIn("Pas d’arme `arbalète lourde`", self.replies[-1])

    async def test_players_cannot_attack_as_monsters(self) -> None:
        await combat_commands.handle_attack(self._ctx(PIP), "gobelin -> Pip")
        self.assertIn("qu’avec ton personnage", self.replies[-1])

    async def test_mj_attacks_with_current_monster(self) -> None:
        encounter = self._encounter()
        encounter.current_id = self.gob.id
        encounter.round = 1
        save_encounter(encounter)
        with _faces(19, 4):
            await combat_commands.handle_attack(self._ctx(MJ), "pip")
        reply = self.replies[-1]
        self.assertIn("**Gobelin** → **Pip** · Scimitar", reply)
        self.assertIn("contre CA 16", reply)
        self.assertIn("1d4 en plus seulement avec avantage", reply)
        self.assertEqual(self._pip_sheet().hp_current, 14)

    async def test_mj_names_attacker_and_repeats(self) -> None:
        with _faces(2, 3):
            await combat_commands.handle_attack(
                self._ctx(MJ), "gobelin -> pip shortbow x2"
            )
        reply = self.replies[-1]
        self.assertIn("__Attaque 2__", reply)
        self.assertEqual(reply.count("❌ Raté"), 2)

    async def test_manual_damage_and_resistance(self) -> None:
        with _faces(15, 6):
            await combat_commands.handle_attack(
                self._ctx(PIP), "gobelin torche +2 1d6 feu"
            )
        reply = self.replies[-1]
        self.assertIn("· torche", reply)
        self.assertIn("(résistance : 3)", reply)
        self.assertEqual(self._encounter().get(self.gob.id).hp, 7)

    async def test_dmg_command_with_type(self) -> None:
        await combat_commands._change_hp(self._ctx(MJ), "gobelin 8 feu", healing=False)
        self.assertIn("(résistance) : 4", self.replies[-1])
        self.assertEqual(self._encounter().get(self.gob.id).hp, 6)

    async def test_death_save_and_temp_commands(self) -> None:
        await combat_commands._change_hp(self._ctx(MJ), "pip 20", healing=False)
        with _faces(14):
            await combat_commands.handle_death_save(self._ctx(PIP), "")
        self.assertIn("Réussite", self.replies[-1])
        await combat_commands.handle_temp_hp(self._ctx(MJ), "gobelin 4")
        self.assertEqual(self._encounter().get(self.gob.id).temp_hp, 4)


if __name__ == "__main__":
    unittest.main()
