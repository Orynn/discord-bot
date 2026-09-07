import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord.ext import commands

from ai.commands import _brief_for_prompt, _brief_from_ctx, _brief_with_prompt, setup_ai
from ai.gemini import (
    MISSING_KEY,
    GeminiEmptyReply,
    GeminiError,
    build_generate_body,
    candidate_models,
    clamp_discord_text,
    extract_gemini_text,
    generate_text,
    generate_url,
    require_gemini_key,
)
from ai.prompt import (
    SYSTEM_NARRATE,
    SceneBrief,
    build_narrate_prompt,
    build_npc_prompt,
    format_scene_brief,
    looks_formatted,
    merge_ai_context,
    parse_ai_prompt,
    parse_ai_request,
    parse_npc_reply,
    strip_roll_asks,
)


class TestGeminiParse(unittest.TestCase):
    def test_requires_key(self) -> None:
        with self.assertRaises(GeminiError) as raised:
            require_gemini_key("")
        self.assertEqual(str(raised.exception), MISSING_KEY)

    def test_builds_url_without_leaking_in_path(self) -> None:
        url = generate_url(model="gemini-2.0-flash")
        self.assertIn("models/gemini-2.0-flash:generateContent", url)
        self.assertNotIn("key=", url)
        stripped = generate_url(model="models/gemini-flash-latest")
        self.assertIn("models/gemini-flash-latest:generateContent", stripped)

    def test_candidate_models_prefers_then_fallbacks(self) -> None:
        names = candidate_models("gemini-3.5-flash")
        self.assertEqual(names[0], "gemini-3.5-flash")
        self.assertIn("gemini-flash-lite-latest", names)
        self.assertEqual(len(names), len(set(names)))
        self.assertNotIn("gemini-flash-latest", candidate_models("gemini-flash-latest"))

    def test_extracts_text_from_candidates(self) -> None:
        text = extract_gemini_text(
            {"candidates": [{"content": {"parts": [{"text": "  La porte grince.  "}]}}]}
        )
        self.assertEqual(text, "La porte grince.")

    def test_skips_thought_parts(self) -> None:
        text = extract_gemini_text(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"thought": True, "text": "raisonnement interne"},
                                {"text": "La porte grince."},
                            ]
                        }
                    }
                ]
            }
        )
        self.assertEqual(text, "La porte grince.")

    def test_empty_reply_is_retryable(self) -> None:
        with self.assertRaises(GeminiEmptyReply):
            extract_gemini_text(
                {
                    "candidates": [
                        {
                            "finishReason": "MAX_TOKENS",
                            "content": {
                                "parts": [{"thoughtSignature": "abc", "thought": True}]
                            },
                        }
                    ]
                }
            )

    def test_safety_block(self) -> None:
        with self.assertRaises(GeminiError):
            extract_gemini_text(
                {"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]}
            )
        with self.assertRaises(GeminiError):
            extract_gemini_text({"promptFeedback": {"blockReason": "SAFETY"}})

    def test_api_error_payload(self) -> None:
        with self.assertRaises(GeminiError) as raised:
            extract_gemini_text({"error": {"message": "API key expired"}})
        self.assertIn("API key expired", str(raised.exception))

    def test_clamp(self) -> None:
        self.assertEqual(clamp_discord_text("ok"), "ok")
        self.assertTrue(clamp_discord_text("x" * 50, limit=10).endswith("…"))

    def test_body_has_system_and_safety(self) -> None:
        body = build_generate_body(system="sys", user="go", max_tokens=200)
        self.assertEqual(body["systemInstruction"]["parts"][0]["text"], "sys")
        self.assertEqual(body["contents"][0]["parts"][0]["text"], "go")
        self.assertEqual(body["generationConfig"]["maxOutputTokens"], 200)
        self.assertEqual(
            body["generationConfig"]["thinkingConfig"],
            {"thinkingLevel": "minimal"},
        )
        self.assertTrue(body["safetySettings"])


class TestGeminiPrompt(unittest.TestCase):
    def test_formats_scene_and_instruction(self) -> None:
        brief = SceneBrief(
            title="La taverne",
            mood="feu",
            present=("Aelric",),
            clock="the 1st of Hammer",
            lines=(">>> ***Aelric*** :\nBonsoir.",),
        )
        block = format_scene_brief(brief)
        self.assertIn("Lieu : La taverne", block)
        self.assertIn("Aelric", block)
        prompt = build_narrate_prompt(brief, "un orage")
        self.assertIn("un orage", prompt)
        self.assertIn("La taverne", prompt)
        empty = build_narrate_prompt(brief, "")
        self.assertIn("Continue la scène", empty)

    def test_includes_mj_context(self) -> None:
        brief = SceneBrief(title="Docks", context="Ils ont volé le sceau.")
        block = format_scene_brief(brief)
        self.assertIn("Contexte MJ :", block)
        self.assertIn("Ils ont volé le sceau.", block)

    def test_includes_campaign_lore(self) -> None:
        brief = SceneBrief(
            title="Phandalin",
            lore="lieux — Phandalin\nPetite ville minière.",
        )
        block = format_scene_brief(brief)
        self.assertIn("Canon CAMPAIGN :", block)
        self.assertIn("Petite ville minière.", block)
        self.assertIn("CAMPAIGN", SYSTEM_NARRATE)

    def test_parses_one_shot_context(self) -> None:
        self.assertEqual(parse_ai_prompt("un orage"), ("un orage", ""))
        self.assertEqual(
            parse_ai_prompt("un orage -- Ils ont volé le sceau"),
            ("un orage", "Ils ont volé le sceau"),
        )
        self.assertEqual(
            parse_ai_prompt(" -- juste le contexte"), ("", "juste le contexte")
        )
        self.assertEqual(
            merge_ai_context("déjà là", "cette fois"),
            "déjà là\n\ncette fois",
        )
        self.assertEqual(merge_ai_context("seul", ""), "seul")

    def test_merges_one_shot_into_brief(self) -> None:
        brief = SceneBrief(context="déjà là")
        updated, instruction, no_context = _brief_with_prompt(
            brief, "un orage -- cette fois"
        )
        self.assertEqual(instruction, "un orage")
        self.assertEqual(updated.context, "déjà là\n\ncette fois")
        self.assertFalse(no_context)

    def test_parses_no_context_flag(self) -> None:
        self.assertEqual(
            parse_ai_request("--no-context allumer un feu"),
            ("allumer un feu", "", True),
        )
        self.assertEqual(
            parse_ai_request("allumer un feu --no-context"),
            ("allumer un feu", "", True),
        )
        self.assertEqual(
            parse_ai_request("--no-context un orage -- Ils ont volé le sceau"),
            ("un orage", "", True),
        )

    def test_no_context_brief_is_description_only(self) -> None:
        brief = SceneBrief(place="La taverne est presque vide.")
        block = format_scene_brief(brief)
        self.assertIn("Description du salon", block)
        self.assertIn("La taverne est presque vide.", block)
        self.assertNotIn("Derniers messages", block)
        prompt = build_narrate_prompt(brief, "Que peut-il trouver pour allumer un feu")
        self.assertIn("Que peut-il trouver pour allumer un feu", prompt)
        self.assertNotIn("Derniers messages", prompt)


class TestNoContextBrief(unittest.IsolatedAsyncioTestCase):
    async def test_uses_channel_topic(self) -> None:
        ctx = MagicMock()
        ctx.channel.topic = "La taverne est presque vide."
        ctx.channel.name = "roleplay"
        brief = await _brief_from_ctx(ctx, no_context=True)
        self.assertEqual(brief.place, "La taverne est presque vide.")
        self.assertEqual(brief.lines, ())
        self.assertEqual(brief.context, "")
        self.assertEqual(brief.title, "")

    async def test_attaches_campaign_lore(self) -> None:
        ctx = MagicMock()
        ctx.guild = MagicMock()
        with (
            patch(
                "ai.commands._brief_from_ctx",
                new=AsyncMock(return_value=SceneBrief(title="Phandalin")),
            ),
            patch(
                "ai.commands.gather_campaign_lore",
                new=AsyncMock(return_value="lieux — Phandalin\nPetite ville."),
            ) as lore,
        ):
            brief, cleaned = await _brief_for_prompt(ctx, "un orage à Phandalin")
        self.assertEqual(cleaned, "un orage à Phandalin")
        self.assertEqual(brief.lore, "lieux — Phandalin\nPetite ville.")
        lore.assert_awaited()


class TestGeminiPromptMore(unittest.TestCase):
    def test_npc_prompt_and_parse(self) -> None:
        brief = SceneBrief(title="Docks")
        prompt = build_npc_prompt(brief, name="Garret", instruction="méfiant")
        self.assertIn("Garret", prompt)
        self.assertIn("méfiant", prompt)
        self.assertEqual(
            parse_npc_reply("(croise les bras) Pas ce soir."),
            ("croise les bras", "Pas ce soir."),
        )
        self.assertEqual(parse_npc_reply("Pas ce soir."), (None, "Pas ce soir."))

    def test_looks_formatted(self) -> None:
        self.assertTrue(looks_formatted(">>> ***Aelric*** :\nHi"))
        self.assertTrue(looks_formatted("*La pluie tombe.*"))
        self.assertFalse(looks_formatted("La pluie tombe."))

    def test_system_forbids_asking_for_rolls(self) -> None:
        self.assertIn("demander un jet", SYSTEM_NARRATE)
        self.assertNotIn("dis au joueur d’utiliser la commande de jet", SYSTEM_NARRATE)

    def test_strips_roll_asks(self) -> None:
        text = (
            "Des branches mortes sèchent au pied des pins.\n\n"
            "Fais un jet de **Sagesse (Survie)** pour allumer le feu."
        )
        cleaned = strip_roll_asks(text)
        self.assertIn("branches mortes", cleaned)
        self.assertNotIn("jet", cleaned)
        self.assertEqual(
            strip_roll_asks("Le vent souffle. Lance un d20 de Survie pour tenir."),
            "Le vent souffle.",
        )


class TestGenerateText(unittest.IsolatedAsyncioTestCase):
    async def test_posts_and_reads_text(self) -> None:
        payload = {
            "candidates": [{"content": {"parts": [{"text": "La brume monte."}]}}]
        }
        response = MagicMock()
        response.status = 200
        response.json = AsyncMock(return_value=payload)
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.post = MagicMock(return_value=response)
        text = await generate_text(
            system="sys",
            user="go",
            key="k",
            model="gemini-2.0-flash",
            session=session,
        )
        self.assertEqual(text, "La brume monte.")
        session.post.assert_called_once()

    async def test_falls_back_after_timeout(self) -> None:
        ok = MagicMock()
        ok.status = 200
        ok.json = AsyncMock(
            return_value={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
        )
        ok.__aenter__ = AsyncMock(return_value=ok)
        ok.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.post = MagicMock(side_effect=[TimeoutError(), ok])
        text = await generate_text(
            system="s", user="u", key="k", model="hanging-model", session=session
        )
        self.assertEqual(text, "ok")
        self.assertEqual(session.post.call_count, 2)

    async def test_falls_back_after_404(self) -> None:
        missing = MagicMock()
        missing.status = 404
        missing.json = AsyncMock(return_value={"error": {"message": "gone"}})
        missing.__aenter__ = AsyncMock(return_value=missing)
        missing.__aexit__ = AsyncMock(return_value=None)
        ok = MagicMock()
        ok.status = 200
        ok.json = AsyncMock(
            return_value={"candidates": [{"content": {"parts": [{"text": "suite"}]}}]}
        )
        ok.__aenter__ = AsyncMock(return_value=ok)
        ok.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.post = MagicMock(side_effect=[missing, ok])
        text = await generate_text(
            system="s", user="u", key="k", model="dead-model", session=session
        )
        self.assertEqual(text, "suite")
        self.assertEqual(session.post.call_count, 2)

    async def test_falls_back_after_503(self) -> None:
        busy = MagicMock()
        busy.status = 503
        busy.json = AsyncMock(return_value={"error": {"message": "high demand"}})
        busy.__aenter__ = AsyncMock(return_value=busy)
        busy.__aexit__ = AsyncMock(return_value=None)
        ok = MagicMock()
        ok.status = 200
        ok.json = AsyncMock(
            return_value={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
        )
        ok.__aenter__ = AsyncMock(return_value=ok)
        ok.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.post = MagicMock(side_effect=[busy, ok])
        with patch("ai.gemini.asyncio.sleep", new_callable=AsyncMock) as slept:
            text = await generate_text(
                system="s", user="u", key="k", model="busy-model", session=session
            )
        self.assertEqual(text, "ok")
        slept.assert_awaited()

    async def test_busy_message_when_all_503(self) -> None:
        busy = MagicMock()
        busy.status = 503
        busy.json = AsyncMock(return_value={})
        busy.__aenter__ = AsyncMock(return_value=busy)
        busy.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.post = MagicMock(return_value=busy)
        with patch("ai.gemini.asyncio.sleep", new_callable=AsyncMock):
            with self.assertRaises(GeminiError) as raised:
                await generate_text(system="s", user="u", key="k", session=session)
        self.assertIn("saturé", str(raised.exception))

    async def test_falls_back_after_empty_text(self) -> None:
        empty = MagicMock()
        empty.status = 200
        empty.json = AsyncMock(
            return_value={
                "candidates": [
                    {
                        "finishReason": "MAX_TOKENS",
                        "content": {"parts": [{"thoughtSignature": "x"}]},
                    }
                ],
                "usageMetadata": {"thoughtsTokenCount": 700, "candidatesTokenCount": 0},
            }
        )
        empty.__aenter__ = AsyncMock(return_value=empty)
        empty.__aexit__ = AsyncMock(return_value=None)
        ok = MagicMock()
        ok.status = 200
        ok.json = AsyncMock(
            return_value={"candidates": [{"content": {"parts": [{"text": "feu"}]}}]}
        )
        ok.__aenter__ = AsyncMock(return_value=ok)
        ok.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.post = MagicMock(side_effect=[empty, ok])
        text = await generate_text(
            system="s", user="u", key="k", model="thinky-model", session=session
        )
        self.assertEqual(text, "feu")
        self.assertEqual(session.post.call_count, 2)

    async def test_maps_http_429(self) -> None:
        response = MagicMock()
        response.status = 429
        response.json = AsyncMock(return_value={})
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=None)
        session = MagicMock()
        session.post = MagicMock(return_value=response)
        with self.assertRaises(GeminiError) as raised:
            await generate_text(system="s", user="u", key="k", session=session)
        self.assertIn("Quota", str(raised.exception))


class TestAiAdminOnly(unittest.IsolatedAsyncioTestCase):
    def _ctx(self, *, admin: bool) -> MagicMock:
        ctx = MagicMock()
        ctx.guild = MagicMock()
        ctx.guild.owner_id = 999
        ctx.author = MagicMock(spec=discord.Member)
        ctx.author.id = 1
        ctx.author.guild_permissions.administrator = admin
        ctx.author.guild_permissions.manage_guild = False
        return ctx

    async def test_admin_check_on_every_ai_command(self) -> None:
        bot = commands.Bot(command_prefix=";", intents=discord.Intents.none())
        setup_ai(bot)
        denied = self._ctx(admin=False)
        allowed = self._ctx(admin=True)
        for name in ("ai", "ai continue", "ai context", "ai npc"):
            command = bot.get_command(name)
            assert command is not None
            self.assertTrue(command.checks)
            results_denied = [await check(denied) for check in command.checks]
            results_allowed = [await check(allowed) for check in command.checks]
            self.assertIn(False, results_denied)
            self.assertNotIn(False, results_allowed)
