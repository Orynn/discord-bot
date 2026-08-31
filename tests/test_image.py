import base64
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from bot.speech import format_npc_speech
from image.commands import gather_scene_lines, scene_place
from image.generate import (
    ImageGenerationError,
    ImagePromptError,
    STYLE_PREFIX,
    build_prompt,
    extract_scene_line,
    filename_for_content_type,
    generate_image,
    parse_rp_line,
    pollinations_url,
    public_caption,
    summarize_scene,
    unwrap_scene_text,
    usable_scene_line,
)


class _FakeResponse:
    def __init__(
        self, *, status: int, body: bytes, content_type: str = "image/jpeg"
    ) -> None:
        self.status = status
        self._body = body
        self.headers = {"Content-Type": content_type}

    async def read(self) -> bytes:
        return self._body

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *_args) -> bool:
        return False


class _FakeSession:
    def __init__(self, response: _FakeResponse | list[_FakeResponse]) -> None:
        self.responses = response if isinstance(response, list) else [response]
        self.calls = 0
        self.last_url: str | None = None
        self.last_json: dict | None = None
        self.urls: list[str] = []

    def get(self, url: str, **_kwargs) -> _FakeResponse:
        self.last_url = url
        self.urls.append(url)
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]

    def post(self, url: str, **kwargs) -> _FakeResponse:
        self.last_url = url
        self.last_json = kwargs.get("json")
        self.urls.append(url)
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


class _FakeHistory:
    def __init__(self, messages: list) -> None:
        self._messages = messages

    def __call__(self, *args, **kwargs):
        limit = kwargs.get("limit", args[0] if args else None)

        async def _gen():
            items = self._messages if limit is None else self._messages[:limit]
            for message in items:
                yield message

        return _gen()


def _message(
    *, mid: int, content: str, bot: bool = False, attachments: bool = False
) -> MagicMock:
    message = MagicMock()
    message.id = mid
    message.clean_content = content
    message.author.bot = bot
    message.author.display_name = "Bot" if bot else "Theo"
    message.attachments = [MagicMock()] if attachments else []
    return message


class TestPromptBuilding(unittest.TestCase):
    def test_includes_style_and_user_text(self) -> None:
        prompt = build_prompt(user_prompt="a rainy dock at night")
        self.assertTrue(prompt.startswith(STYLE_PREFIX))
        self.assertIn("Focus: a rainy dock at night", prompt)
        self.assertIn("SFW", prompt)

    def test_adds_thread_place(self) -> None:
        prompt = build_prompt(user_prompt="the tavern", place="Padhiver")
        self.assertIn("Place: Padhiver", prompt)

    def test_uses_scene_when_prompt_omitted(self) -> None:
        prompt = build_prompt(
            scene_lines=["The gates creak open.", "A guard shouts."],
            character="FOX",
        )
        self.assertIn("In frame: FOX", prompt)
        self.assertIn("The gates creak open.", prompt)
        self.assertIn("A guard shouts.", prompt)

    def test_keeps_channel_scene_with_user_focus(self) -> None:
        prompt = build_prompt(
            user_prompt="the swinging lantern",
            place="Padhiver",
            scene_lines=[
                "Rain hammers the docks.",
                format_npc_speech("FOX", "Stay low."),
            ],
        )
        self.assertIn("Focus: the swinging lantern", prompt)
        self.assertIn("Padhiver", prompt)
        self.assertIn("FOX", prompt)
        self.assertIn("Rain hammers the docks.", prompt)

    def test_requires_prompt_or_scene(self) -> None:
        with self.assertRaises(ImagePromptError):
            build_prompt()

    def test_caption_prefers_user_prompt(self) -> None:
        self.assertEqual(
            public_caption(user_prompt="the docks", place="Padhiver", from_scene=False),
            "Padhiver — the docks",
        )
        self.assertEqual(
            public_caption(user_prompt="", place="Padhiver", from_scene=True),
            "Padhiver — from the scene",
        )


class TestSceneSummary(unittest.TestCase):
    def test_parse_pc_speech_and_action(self) -> None:
        speaker, action, text = parse_rp_line(
            format_npc_speech("FOX", "Stay back.", action="draws a sword")
        )
        self.assertEqual(speaker, "FOX")
        self.assertEqual(action, "draws a sword")
        self.assertEqual(text, "Stay back.")

    def test_keeps_early_setting_and_recent_action(self) -> None:
        lines = [
            "Padhiver sleeps under a cold rain.",
            format_npc_speech("FOX", "We should hide.", action="pulls her cloak"),
            "A lantern swings above the pier.",
            format_npc_speech("Garde", "Qui va là ?"),
        ]
        summary = summarize_scene(lines, place="Les docks", character="FOX")
        self.assertNotIn("Focus:", summary)
        self.assertIn("Padhiver sleeps under a cold rain.", summary)
        self.assertIn("A lantern swings above the pier.", summary)
        self.assertIn("Garde", summary)
        self.assertIn("Qui va là ?", summary)
        self.assertIn("Les docks", summary)
        self.assertIn("In frame: FOX, Garde", summary)

    def test_now_prefers_the_latest_beats(self) -> None:
        lines = [f"Old beat {index}." for index in range(20)]
        lines.append("The dragon lands on the roof.")
        summary = summarize_scene(lines)
        self.assertIn("The dragon lands on the roof.", summary)
        self.assertNotIn("Old beat 5.", summary)


class TestSceneLines(unittest.TestCase):
    def test_unwraps_desc_italics(self) -> None:
        self.assertEqual(unwrap_scene_text("*The rain falls.*"), "The rain falls.")

    def test_skips_prefix_commands(self) -> None:
        self.assertIsNone(usable_scene_line(";image a dragon", prefix=";"))
        self.assertIsNone(usable_scene_line("  ;desc rain  ", prefix=";"))
        self.assertEqual(
            usable_scene_line("*The rain falls.*", prefix=";"), "The rain falls."
        )

    def test_extracts_bot_rp_and_skips_other_bot_posts(self) -> None:
        desc = extract_scene_line(
            content="*The gates creak open.*", prefix=";", is_bot=True
        )
        self.assertEqual(desc, "The gates creak open.")
        speech = extract_scene_line(
            content=format_npc_speech("FOX", "I wait."),
            prefix=";",
            is_bot=True,
        )
        self.assertIsNotNone(speech)
        self.assertIn("FOX", speech or "")
        self.assertIsNone(
            extract_scene_line(
                content="**Round 3** — FOX vs goblin", prefix=";", is_bot=True
            )
        )
        self.assertIsNone(
            extract_scene_line(
                content="*Padhiver — from the scene*",
                prefix=";",
                is_bot=True,
                has_attachments=True,
            )
        )

    def test_thread_name_is_place(self) -> None:
        thread = MagicMock(spec=discord.Thread)
        thread.name = "Les docks de Padhiver"
        self.assertEqual(scene_place(thread), "Les docks de Padhiver")
        channel = MagicMock(spec=discord.TextChannel)
        channel.name = "🎲roleplay"
        channel.topic = None
        self.assertIsNone(scene_place(channel))


class TestGatherSceneLines(unittest.IsolatedAsyncioTestCase):
    async def test_collects_the_whole_channel_rp(self) -> None:
        messages = [_message(mid=99, content=";image")]
        for index in range(12, 0, -1):
            messages.append(
                _message(mid=index, content=f"*Narration {index}.*", bot=True)
            )
        messages.append(_message(mid=0, content=";pc I wait."))

        ctx = MagicMock()
        ctx.message.id = 99
        ctx.channel.history = _FakeHistory(messages)

        lines = await gather_scene_lines(ctx, limit=1000)
        self.assertEqual(len(lines), 12)
        self.assertEqual(lines[0], "Narration 1.")
        self.assertEqual(lines[-1], "Narration 12.")


class TestPollinationsUrl(unittest.TestCase):
    def test_encodes_prompt_and_privacy_flags(self) -> None:
        url = pollinations_url(
            "a dragon over Padhiver",
            width=1024,
            height=1024,
            model="flux",
            seed=42,
        )
        self.assertTrue(
            url.startswith(
                "https://gen.pollinations.ai/image/a%20dragon%20over%20Padhiver?"
            )
        )
        self.assertIn("private=true", url)
        self.assertIn("nologo=true", url)
        self.assertIn("seed=42", url)
        self.assertIn("model=flux", url)

    def test_filename_from_content_type(self) -> None:
        self.assertEqual(filename_for_content_type("image/png"), "scene.png")
        self.assertEqual(
            filename_for_content_type("image/jpeg; charset=binary"), "scene.jpg"
        )


class TestGenerateImage(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        provider = patch("image.generate.IMAGE_PROVIDER", "pollinations")
        provider.start()
        self.addCleanup(provider.stop)

    async def test_pollinations_returns_jpeg_bytes(self) -> None:
        jpeg = b"\xff\xd8" + b"\x00" * 64
        session = _FakeSession(
            _FakeResponse(status=200, body=jpeg, content_type="image/jpeg")
        )
        image = await generate_image("a torchlit hall", seed=7, session=session)
        self.assertEqual(image.data, jpeg)
        self.assertEqual(image.filename, "scene.jpg")
        self.assertIn("seed=7", session.last_url or "")
        self.assertIn("gen.pollinations.ai/image/", session.last_url or "")

    async def test_pollinations_rejects_html_errors(self) -> None:
        session = _FakeSession(
            _FakeResponse(
                status=200, body=b"<html>rate limit</html>", content_type="text/html"
            )
        )
        with patch("image.generate.asyncio.sleep", new_callable=AsyncMock):
            with self.assertRaises(ImageGenerationError):
                await generate_image("a dragon", seed=1, session=session)
        self.assertEqual(session.calls, 3)

    async def test_pollinations_retries_html_then_uses_legacy_host(self) -> None:
        jpeg = b"\xff\xd8" + b"\x00" * 64
        session = _FakeSession(
            [
                _FakeResponse(
                    status=200, body=b"<html>wait</html>", content_type="text/html"
                ),
                _FakeResponse(status=200, body=jpeg, content_type="image/jpeg"),
            ]
        )
        with patch("image.generate.asyncio.sleep", new_callable=AsyncMock):
            image = await generate_image("a dragon", seed=1, session=session)
        self.assertEqual(image.data, jpeg)
        self.assertEqual(session.calls, 2)
        self.assertIn("gen.pollinations.ai/image/", session.urls[0])
        self.assertIn("image.pollinations.ai/prompt/", session.urls[1])

    async def test_local_decodes_base64_png(self) -> None:
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 48
        payload = json.dumps(
            {"images": [base64.b64encode(png).decode("ascii")]}
        ).encode("utf-8")
        session = _FakeSession(
            _FakeResponse(status=200, body=payload, content_type="application/json")
        )
        with patch("image.generate.IMAGE_PROVIDER", "local"):
            image = await generate_image("a torchlit hall", session=session)
        self.assertEqual(image.data, png)
        self.assertEqual(image.filename, "scene.png")
        self.assertIn("/sdapi/v1/txt2img", session.last_url or "")
        self.assertIn("a torchlit hall", session.last_json["prompt"])
        self.assertIn("nsfw", session.last_json["negative_prompt"])

    async def test_auto_falls_back_to_pollinations_when_local_is_down(self) -> None:
        jpeg = b"\xff\xd8" + b"\x00" * 64
        session = _FakeSession(
            [
                _FakeResponse(
                    status=503,
                    body=b'{"error":"loading"}',
                    content_type="application/json",
                ),
                _FakeResponse(status=200, body=jpeg, content_type="image/jpeg"),
            ]
        )
        with patch("image.generate.IMAGE_PROVIDER", "auto"):
            with patch("image.generate.asyncio.sleep", new_callable=AsyncMock):
                image = await generate_image("a torchlit hall", seed=3, session=session)
        self.assertEqual(image.data, jpeg)
        self.assertIn("/sdapi/v1/txt2img", session.urls[0])
        self.assertIn("gen.pollinations.ai/image/", session.urls[1])


class TestLocalServerHelpers(unittest.TestCase):
    def test_round_edge_clamps_for_cpu(self) -> None:
        from image.server import round_edge

        self.assertEqual(round_edge(1024), 768)
        self.assertEqual(round_edge(511), 504)
        self.assertEqual(round_edge(0), 512)


if __name__ == "__main__":
    unittest.main()
