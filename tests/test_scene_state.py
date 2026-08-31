import tempfile
import unittest
from pathlib import Path

import data.db as db_module
from pc.identity import resolve_whisper_target
from scene.state import (
    SceneState,
    build_scene_embed,
    get_scene,
    mark_absent,
    mark_present,
    parse_scene_set,
    present_names,
    save_scene,
)
from sheets.data import CharacterSheet
from sheets.storage import save_sheet


class TestParseSceneSet(unittest.TestCase):
    def test_title_only_keeps_mood(self) -> None:
        self.assertEqual(parse_scene_set("La taverne"), ("La taverne", None))

    def test_splits_on_dash_separator(self) -> None:
        self.assertEqual(
            parse_scene_set("La taverne -- feu de cheminée"),
            ("La taverne", "feu de cheminée"),
        )
        self.assertEqual(
            parse_scene_set("La crique — vent salé"),
            ("La crique", "vent salé"),
        )

    def test_empty_mood_after_separator(self) -> None:
        self.assertEqual(parse_scene_set("La taverne -- "), ("La taverne", ""))


class TestSceneStorage(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        db_module.init_db()

    def tearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    def test_round_trip_and_presence(self) -> None:
        scene = SceneState(title="La taverne", mood="feu de cheminée")
        save_scene(guild_id=1, channel_id=10, scene=scene)
        loaded = get_scene(guild_id=1, channel_id=10)
        self.assertEqual(loaded.title, "La taverne")
        self.assertEqual(loaded.mood, "feu de cheminée")

        mark_present(guild_id=1, channel_id=10, user_id=7, name="Aelric")
        mark_present(guild_id=1, channel_id=10, user_id=8, name="Mira")
        present = get_scene(guild_id=1, channel_id=10)
        self.assertEqual(present_names(present), ["Aelric", "Mira"])

        mark_absent(guild_id=1, channel_id=10, user_id=7)
        after = get_scene(guild_id=1, channel_id=10)
        self.assertEqual(present_names(after), ["Mira"])

    def test_channels_are_isolated(self) -> None:
        mark_present(guild_id=1, channel_id=10, user_id=1, name="Aelric")
        other = get_scene(guild_id=1, channel_id=11)
        self.assertEqual(other.present, {})

    def test_from_dict_ignores_junk(self) -> None:
        scene = SceneState.from_dict(
            {"title": " Dock ", "present": {1: "  ", "2": "Mira"}}
        )
        self.assertEqual(scene.title, "Dock")
        self.assertEqual(scene.present, {"2": "Mira"})
        self.assertEqual(SceneState.from_dict(None).title, "")


class TestSceneEmbed(unittest.TestCase):
    def test_empty_scene_explains_how_to_set(self) -> None:
        embed = build_scene_embed(SceneState(), prefix=";")
        self.assertEqual(embed.title, "🎭 Scène")
        self.assertIn(";scene set", embed.description or "")
        self.assertIn("Personne n’a annoncé", embed.fields[0].value)

    def test_lists_present_and_clock(self) -> None:
        scene = SceneState(title="Docks", mood="brume", present={"1": "Aelric"})
        embed = build_scene_embed(
            scene, clock_line="the 1st of Hammer · 08:00 · morning"
        )
        self.assertEqual(embed.title, "🎭 Docks")
        self.assertEqual(embed.description, "brume")
        self.assertIn("**Aelric**", embed.fields[0].value)
        self.assertEqual(embed.fields[-1].name, "⏳ Temps")


class TestWhisperTarget(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        db_module.init_db()
        save_sheet(user_id=11, guild_id=1, sheet=CharacterSheet(name="Aelric Fox"))
        save_sheet(user_id=12, guild_id=1, sheet=CharacterSheet(name="Mira"))

    def tearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    def test_prefers_mention(self) -> None:
        target = resolve_whisper_target(
            guild_id=1,
            text="suis-moi",
            mentioned_id=12,
            mentioned_name="Player",
        )
        self.assertEqual(target, (12, "Mira", "suis-moi"))

    def test_matches_longest_character_name(self) -> None:
        target = resolve_whisper_target(guild_id=1, text="Aelric Fox suis-moi")
        self.assertEqual(target, (11, "Aelric Fox", "suis-moi"))

    def test_rejects_name_without_message(self) -> None:
        self.assertIsNone(resolve_whisper_target(guild_id=1, text="Mira"))
        self.assertIsNone(
            resolve_whisper_target(
                guild_id=1, text="", mentioned_id=12, mentioned_name="Mira"
            )
        )
        self.assertIsNone(resolve_whisper_target(guild_id=1, text="Inconnu bonjour"))
