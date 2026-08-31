import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

import data.db as db_module
from combat.board import board_snapshot
from combat.discord_sync import bind_pusher, flush_discord_sync
from combat.editor_server import (
    combat_board_url,
    create_app,
    editor_is_running,
    editor_public_url,
    start_editor_server,
    stop_editor_server,
)
from combat.storage import CombatState, CombatantState, save_combat
from combat.web_commands import parse_web_command
from config import PREFIX
from data.db import init_db


class TestEditorApp(unittest.IsolatedAsyncioTestCase):
    async def test_serves_editor_and_health(self) -> None:
        async with TestClient(TestServer(create_app())) as client:
            home = await client.get("/")
            self.assertEqual(home.status, 200)
            body = await home.text()
            self.assertIn("Éditeur de cartes", body)
            self.assertIn("formatMap", body)
            alias = await client.get("/editor")
            self.assertEqual(alias.status, 200)
            health = await client.get("/health")
            self.assertEqual(health.status, 200)
            payload = await health.json()
            self.assertTrue(payload["ok"])
            missing = await client.get("/secret")
            self.assertEqual(missing.status, 404)
            board = await client.get("/combat/1/2")
            self.assertEqual(board.status, 200)
            board_html = await board.text()
            self.assertIn("Plateau", board_html)
            self.assertIn('id="cmd"', board_html)
            empty = await client.get("/combat/1/2/state")
            self.assertEqual(empty.status, 404)


class TestEditorLifecycle(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        await stop_editor_server()

    async def test_start_binds_and_reports_url(self) -> None:
        with (
            patch("combat.editor_server.EDITOR_HOST", "127.0.0.1"),
            patch("combat.editor_server.EDITOR_PORT", 0),
            patch("combat.editor_server.EDITOR_PUBLIC_URL", ""),
        ):
            url = await start_editor_server()
            self.assertTrue(editor_is_running())
            self.assertIsNotNone(url)
            assert url is not None
            self.assertTrue(url.startswith("http://127.0.0.1:"))
            again = await start_editor_server()
            self.assertEqual(again, url)
        await stop_editor_server()
        self.assertFalse(editor_is_running())
        self.assertIsNone(editor_public_url())

    def test_public_url_override(self) -> None:
        with patch(
            "combat.editor_server.EDITOR_PUBLIC_URL", "https://maps.example/"
        ):
            self.assertEqual(editor_public_url(), "https://maps.example")

    def test_combat_board_url_requires_server(self) -> None:
        self.assertIsNone(combat_board_url(1, 2))

    def test_combat_board_url_strips_extra_slash(self) -> None:
        with (
            patch("combat.editor_server.editor_is_running", return_value=True),
            patch(
                "combat.editor_server.editor_public_url",
                return_value="http://172.16.7.89:8765/",
            ),
        ):
            self.assertEqual(
                combat_board_url(1, 2),
                "http://172.16.7.89:8765/combat/1/2",
            )


class TestBoardSnapshot(unittest.TestCase):
    def test_hides_monster_hp_and_marks_reach(self) -> None:
        state = CombatState(
            guild_id=1,
            channel_id=2,
            scope_id=9,
            turn_order=["Hero", "Goblin"],
            active_index=0,
            combatants={
                "hero": CombatantState(
                    name="Hero",
                    user_id=1,
                    hp=12,
                    max_hp=20,
                    hand=[],
                    deck=[],
                    x=1,
                    y=3,
                ),
                "goblin": CombatantState(
                    name="Goblin",
                    user_id=None,
                    hp=7,
                    max_hp=7,
                    hand=[],
                    deck=[],
                    x=3,
                    y=3,
                ),
            },
        )
        payload = board_snapshot(state)
        by_name = {entry["name"]: entry for entry in payload["combatants"]}
        self.assertEqual(by_name["Hero"]["hp"], 12)
        self.assertIsNone(by_name["Goblin"]["hp"])
        self.assertEqual(payload["map"]["width"], 8)
        self.assertIn([2, 3], payload["moves"])

    def test_threats_include_allies_in_weapon_range(self) -> None:
        state = CombatState(
            guild_id=1,
            channel_id=2,
            scope_id=9,
            turn_order=["Hero", "Ally", "Goblin"],
            active_index=0,
            combatants={
                "hero": CombatantState(
                    name="Hero",
                    user_id=1,
                    hp=12,
                    max_hp=20,
                    hand=[],
                    deck=[],
                    x=1,
                    y=3,
                ),
                "ally": CombatantState(
                    name="Ally",
                    user_id=2,
                    hp=18,
                    max_hp=20,
                    hand=[],
                    deck=[],
                    x=2,
                    y=3,
                ),
                "goblin": CombatantState(
                    name="Goblin",
                    user_id=None,
                    hp=7,
                    max_hp=7,
                    hand=[],
                    deck=[],
                    x=2,
                    y=4,
                ),
            },
        )
        payload = board_snapshot(state)
        self.assertIn([2, 3], payload["allies"])
        self.assertIn([2, 4], payload["threats"])
        self.assertNotIn([2, 3], payload["threats"])
        self.assertNotIn([2, 4], payload["allies"])
        self.assertNotIn([1, 3], payload["threats"])
        self.assertNotIn([1, 3], payload["allies"])


class TestCombatStateHttp(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        init_db()

    async def asyncTearDown(self) -> None:
        await flush_discord_sync()
        bind_pusher(None)
        db_module.DB_FILE = self._original
        self._tmpdir.cleanup()

    async def test_state_endpoint_returns_snapshot(self) -> None:
        save_combat(
            CombatState(
                guild_id=3,
                channel_id=4,
                scope_id=5,
                turn_order=["Hero"],
                active_index=0,
                combatants={
                    "hero": CombatantState(
                        name="Hero",
                        user_id=1,
                        hp=8,
                        max_hp=8,
                        hand=[],
                        deck=[],
                        x=1,
                        y=1,
                    )
                },
            )
        )
        async with TestClient(TestServer(create_app())) as client:
            response = await client.get("/combat/3/5/state")
            self.assertEqual(response.status, 200)
            payload = await response.json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["active"], "Hero")
            self.assertEqual(payload["combatants"][0]["cell"], "B2")

    async def test_web_move_action(self) -> None:
        save_combat(
            CombatState(
                guild_id=3,
                channel_id=4,
                scope_id=6,
                turn_order=["Hero"],
                active_index=0,
                combatants={
                    "hero": CombatantState(
                        name="Hero",
                        user_id=1,
                        hp=8,
                        max_hp=8,
                        hand=[],
                        deck=[],
                        x=1,
                        y=1,
                        speed=30,
                    )
                },
            )
        )
        async with TestClient(TestServer(create_app())) as client:
            response = await client.post(
                "/combat/3/6/action",
                json={"type": "move", "dest": [2, 1]},
            )
            self.assertEqual(response.status, 200)
            payload = await response.json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["snapshot"]["combatants"][0]["cell"], "C2")

    async def test_web_discord_command_move(self) -> None:
        save_combat(
            CombatState(
                guild_id=3,
                channel_id=4,
                scope_id=7,
                turn_order=["Hero"],
                active_index=0,
                combatants={
                    "hero": CombatantState(
                        name="Hero",
                        user_id=1,
                        hp=8,
                        max_hp=8,
                        hand=[],
                        deck=[],
                        x=1,
                        y=1,
                        speed=30,
                    )
                },
            )
        )
        async with TestClient(TestServer(create_app())) as client:
            response = await client.post(
                "/combat/3/7/action",
                json={"type": "command", "text": f"{PREFIX}combat move C2"},
            )
            self.assertEqual(response.status, 200)
            payload = await response.json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["snapshot"]["combatants"][0]["cell"], "C2")
            self.assertEqual(payload["snapshot"]["prefix"], PREFIX)

    async def test_web_command_help_without_combat(self) -> None:
        async with TestClient(TestServer(create_app())) as client:
            response = await client.post(
                "/combat/3/8/action",
                json={"type": "command", "text": "help combat"},
            )
            self.assertEqual(response.status, 200)
            payload = await response.json()
            self.assertTrue(payload["ok"])
            self.assertIn("combat move", payload["message"].lower())
            self.assertIsNone(payload["snapshot"])

    async def test_web_move_syncs_discord_message(self) -> None:
        save_combat(
            CombatState(
                guild_id=3,
                channel_id=4,
                scope_id=9,
                board_message_id=99,
                turn_order=["Hero"],
                active_index=0,
                combatants={
                    "hero": CombatantState(
                        name="Hero",
                        user_id=1,
                        hp=8,
                        max_hp=8,
                        hand=[],
                        deck=[],
                        x=1,
                        y=1,
                        speed=30,
                    )
                },
            )
        )
        called: list[tuple[int | None, str | None, bool, int | None]] = []

        async def fake_push(state, *, content, ended):
            hero = state.combatants["hero"]
            called.append((hero.x, content, ended, state.board_message_id))
            return True

        bind_pusher(fake_push)
        async with TestClient(TestServer(create_app())) as client:
            response = await client.post(
                "/combat/3/9/action",
                json={"type": "move", "dest": [2, 1]},
            )
        await flush_discord_sync()
        self.assertEqual(response.status, 200)
        self.assertEqual(len(called), 1)
        self.assertEqual(called[0][0], 2)
        self.assertFalse(called[0][2])
        self.assertEqual(called[0][3], 99)

    async def test_web_command_move_syncs_discord(self) -> None:
        save_combat(
            CombatState(
                guild_id=3,
                channel_id=4,
                scope_id=12,
                board_message_id=88,
                turn_order=["Hero"],
                active_index=0,
                combatants={
                    "hero": CombatantState(
                        name="Hero",
                        user_id=1,
                        hp=8,
                        max_hp=8,
                        hand=[],
                        deck=[],
                        x=1,
                        y=1,
                        speed=30,
                    )
                },
            )
        )
        called: list[tuple[int | None, bool]] = []

        async def fake_push(state, *, content, ended):
            called.append((state.combatants["hero"].x, ended))
            return True

        bind_pusher(fake_push)
        async with TestClient(TestServer(create_app())) as client:
            response = await client.post(
                "/combat/3/12/action",
                json={"type": "command", "text": f"{PREFIX}combat move C2"},
            )
            self.assertEqual(response.status, 200)
        await flush_discord_sync()
        self.assertEqual(called, [(2, False)])

    async def test_web_help_does_not_sync_discord(self) -> None:
        save_combat(
            CombatState(
                guild_id=3,
                channel_id=4,
                scope_id=10,
                board_message_id=99,
                turn_order=["Hero"],
                active_index=0,
                combatants={
                    "hero": CombatantState(
                        name="Hero",
                        user_id=1,
                        hp=8,
                        max_hp=8,
                        hand=[],
                        deck=[],
                        x=1,
                        y=1,
                    )
                },
            )
        )
        called: list[bool] = []

        async def fake_push(state, *, content, ended):
            called.append(True)
            return True

        bind_pusher(fake_push)
        async with TestClient(TestServer(create_app())) as client:
            response = await client.post(
                "/combat/3/10/action",
                json={"type": "command", "text": "help combat"},
            )
        await flush_discord_sync()
        self.assertEqual(response.status, 200)
        self.assertEqual(called, [])

    async def test_web_end_syncs_discord_as_ended(self) -> None:
        save_combat(
            CombatState(
                guild_id=3,
                channel_id=4,
                scope_id=11,
                board_message_id=77,
                turn_order=["Hero"],
                active_index=0,
                combatants={
                    "hero": CombatantState(
                        name="Hero",
                        user_id=1,
                        hp=8,
                        max_hp=8,
                        hand=[],
                        deck=[],
                        x=1,
                        y=1,
                    )
                },
            )
        )
        called: list[tuple[bool, int | None]] = []

        async def fake_push(state, *, content, ended):
            called.append((ended, state.board_message_id))
            return True

        bind_pusher(fake_push)
        async with TestClient(TestServer(create_app())) as client:
            response = await client.post(
                "/combat/3/11/action",
                json={"type": "command", "text": f"{PREFIX}combat end"},
            )
            self.assertEqual(response.status, 200)
            payload = await response.json()
        await flush_discord_sync()
        self.assertTrue(payload["combat_over"])
        self.assertEqual(called, [(True, 77)])


class TestParseWebCommand(unittest.TestCase):
    def test_prefix_and_bare_verbs(self) -> None:
        self.assertEqual(parse_web_command(f"{PREFIX}combat move C4"), ("combat", "move", ["C4"]))
        self.assertEqual(parse_web_command("attack Goblin"), ("combat", "attack", ["Goblin"]))
        self.assertEqual(parse_web_command(f"{PREFIX}r 1d20 str"), ("roll", "roll", ["1d20", "str"]))
        self.assertEqual(parse_web_command("/init show"), ("init", "show", []))
        self.assertEqual(
            parse_web_command(f"{PREFIX}combat play fire-bolt Goblin"),
            ("combat", "play", ["fire-bolt", "Goblin"]),
        )

    def test_rejects_unknown(self) -> None:
        with self.assertRaises(ValueError):
            parse_web_command(f"{PREFIX}wiki search goblin")
