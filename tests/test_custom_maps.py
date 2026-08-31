import tempfile
import unittest
from pathlib import Path

from PIL import Image

import data.db as db_module
from combat.custom_maps import (
    clamp_map_size,
    custom_map_from_state,
    delete_custom_map,
    extract_map_source,
    format_map_text,
    get_custom_map,
    list_custom_maps,
    parse_map_text,
    parse_size_token,
    save_custom_map,
    validate_map_id,
)
from combat.map import apply_template, parse_cell, toggle_walls
from combat.render import (
    LEGEND_WIDTH,
    MARGIN_BOTTOM,
    MARGIN_LEFT,
    MARGIN_TOP,
    cell_px,
    render_combat_map,
)
from combat.setup import parse_start_args
from combat.storage import CombatState, CombatantState
from combat.templates import lookup_template
from data.db import init_db


GRID = """
# id: crypt
# label: Crypte
# theme: dungeon
# pc: B
# npc: G
........
.##..##.
.#....#.
........
........
........
........
........
"""


class TestCustomMaps(unittest.TestCase):
    def test_parse_ascii_grid(self) -> None:
        data = parse_map_text(GRID)
        self.assertEqual(data.map_id, "crypt")
        self.assertEqual(data.label, "Crypte")
        self.assertEqual(data.theme, "dungeon")
        self.assertEqual(data.pc_column, 1)
        self.assertEqual(data.npc_column, 6)
        self.assertIn((1, 1), data.blocked)
        self.assertIn((1, 2), data.blocked)
        self.assertNotIn((0, 0), data.blocked)

    def test_parse_json_grid(self) -> None:
        data = parse_map_text(
            '{"id":"cave","label":"Grotte","theme":"camp","grid":[".##.....","........"]}'
        )
        self.assertEqual(data.map_id, "cave")
        self.assertEqual(data.theme, "camp")
        self.assertEqual(data.blocked, ((1, 0), (2, 0)))

    def test_roundtrip_text(self) -> None:
        data = parse_map_text(GRID)
        again = parse_map_text(format_map_text(data))
        self.assertEqual(again.blocked, data.blocked)
        self.assertEqual(again.theme, data.theme)

    def test_extract_codeblock(self) -> None:
        source = extract_map_source("voici\n```\n# id: crypt\n........\n```")
        assert source is not None
        self.assertIn("# id: crypt", source)

    def test_reject_reserved_and_bad_ids(self) -> None:
        with self.assertRaises(ValueError):
            validate_map_id("import")
        with self.assertRaises(ValueError):
            validate_map_id("editor")
        with self.assertRaises(ValueError):
            validate_map_id("1crypt")
        with self.assertRaises(ValueError):
            parse_map_text("........\n........")

    def test_save_list_lookup_delete(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        original = db_module.DB_FILE
        db_module.DB_FILE = Path(tmpdir.name) / "test.db"
        try:
            init_db()
            data = parse_map_text(GRID)
            save_custom_map(guild_id=7, data=data)
            self.assertEqual(len(list_custom_maps(guild_id=7)), 1)
            loaded = get_custom_map(guild_id=7, map_id="crypt")
            assert loaded is not None
            self.assertEqual(loaded.label, "Crypte")
            template = lookup_template("crypt", guild_id=7)
            self.assertEqual(template.label, "Crypte")
            self.assertEqual(
                parse_start_args("Gobelin crypt", guild_id=7),
                ("Gobelin", None, "crypt"),
            )
            self.assertTrue(delete_custom_map(guild_id=7, map_id="crypt"))
            with self.assertRaises(ValueError):
                lookup_template("crypt", guild_id=7)
        finally:
            db_module.DB_FILE = original
            tmpdir.cleanup()

    def test_apply_custom_and_toggle_walls(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        original = db_module.DB_FILE
        db_module.DB_FILE = Path(tmpdir.name) / "test.db"
        try:
            init_db()
            save_custom_map(guild_id=1, data=parse_map_text(GRID))
            state = CombatState(
                guild_id=1,
                channel_id=2,
                turn_order=["Hero"],
                active_index=0,
                combatants={
                    "hero": CombatantState(
                        name="Hero",
                        user_id=1,
                        hp=10,
                        max_hp=10,
                        hand=[],
                        deck=[],
                        x=1,
                        y=3,
                    )
                },
            )
            apply_template(state, "crypt")
            self.assertEqual(state.map_id, "crypt")
            self.assertIn([1, 1], state.blocked)
            note = toggle_walls(state, [(0, 0)])
            self.assertIn("A1", note)
            self.assertIn((0, 0), state.blocked_set)
            saved = custom_map_from_state(state, map_id="crypt-2", label="Bis")
            self.assertIn((0, 0), saved.blocked)
        finally:
            db_module.DB_FILE = original
            tmpdir.cleanup()

    def test_parse_wide_grid_and_labels(self) -> None:
        rows = ["." * 12] * 10
        rows[0] = "#" * 12
        rows[9] = "#" * 12
        text = "# id: hall\n# size: 12x10\n# theme: dungeon\n" + "\n".join(rows)
        data = parse_map_text(text)
        self.assertEqual((data.width, data.height), (12, 10))
        self.assertEqual(data.npc_column, 10)
        self.assertIn((0, 0), data.blocked)
        self.assertIn((11, 9), data.blocked)
        again = parse_map_text(format_map_text(data))
        self.assertEqual((again.width, again.height), (12, 10))
        self.assertIn("# size: 12x10", format_map_text(data))

    def test_infer_size_from_grid_without_header(self) -> None:
        grid = "\n".join(["." * 12] * 10)
        data = parse_map_text("# id: hall\n" + grid)
        self.assertEqual((data.width, data.height), (12, 10))

    def test_reject_oversize_and_tiny(self) -> None:
        with self.assertRaises(ValueError):
            clamp_map_size(20, 16)
        with self.assertRaises(ValueError):
            clamp_map_size(3, 8)
        self.assertEqual(parse_size_token("12x12"), (12, 12))
        with self.assertRaises(ValueError):
            parse_size_token("20x20")

    def test_apply_wide_map_and_parse_cell(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        original = db_module.DB_FILE
        db_module.DB_FILE = Path(tmpdir.name) / "test.db"
        try:
            init_db()
            grid = "\n".join(["." * 12] * 10)
            save_custom_map(
                guild_id=1,
                data=parse_map_text("# id: hall\n# theme: dungeon\n" + grid),
            )
            loaded = get_custom_map(guild_id=1, map_id="hall")
            assert loaded is not None
            self.assertEqual((loaded.width, loaded.height), (12, 10))
            state = CombatState(
                guild_id=1,
                channel_id=2,
                turn_order=["Hero"],
                active_index=0,
                combatants={
                    "hero": CombatantState(
                        name="Hero",
                        user_id=1,
                        hp=10,
                        max_hp=10,
                        hand=[],
                        deck=[],
                        x=1,
                        y=3,
                    )
                },
            )
            apply_template(state, "hall")
            self.assertEqual((state.map_width, state.map_height), (12, 10))
            self.assertEqual(parse_cell("L10", state), (11, 9))
            self.assertIsNone(parse_cell("M1", state))
            self.assertEqual(parse_cell("L10"), (11, 9))
            image = render_combat_map(state)
            image.seek(0)
            rendered = Image.open(image)
            cell = cell_px(state)
            self.assertEqual(cell, 96)
            self.assertEqual(
                rendered.size,
                (
                    MARGIN_LEFT + 12 * cell + LEGEND_WIDTH,
                    MARGIN_TOP + 10 * cell + MARGIN_BOTTOM,
                ),
            )
        finally:
            db_module.DB_FILE = original
            tmpdir.cleanup()

    def test_editor_html_and_export_parse(self) -> None:
        editor = Path(__file__).resolve().parent.parent / "tools" / "map-editor.html"
        self.assertTrue(editor.is_file())
        html = editor.read_text(encoding="utf-8")
        for marker in ("map-id", "tool-wall", "btn-download", "formatMap"):
            self.assertIn(marker, html)
        exported = (
            "# id: hall\n"
            "# label: Grande salle\n"
            "# theme: dungeon\n"
            "# size: 12x10\n"
            "# pc: B\n"
            "# npc: K\n"
            + ("." * 12 + "\n") * 9
            + "#" * 12
            + "\n"
        )
        data = parse_map_text(exported)
        self.assertEqual((data.width, data.height), (12, 10))
        self.assertEqual(data.npc_column, 10)
        self.assertIn((0, 9), data.blocked)
