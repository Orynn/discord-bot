import unittest

from bot.speech import (
    format_emote,
    format_ooc,
    format_thought,
    format_whisper_private,
    format_whisper_public,
)
from image.generate import parse_rp_line


class TestRoleplaySpeech(unittest.TestCase):
    def test_thought_uses_spoiler_and_pense_action(self) -> None:
        line = format_thought("Aelric", "je ne lui fais pas confiance")
        self.assertIn("||Je ne lui fais pas confiance.||", line)
        speaker, action, text = parse_rp_line(line)
        self.assertEqual(speaker, "Aelric")
        self.assertEqual(action, "pense")
        self.assertIn("Je ne lui fais pas confiance.", text)

    def test_emote_keeps_french_lowercase_and_adds_period(self) -> None:
        self.assertEqual(format_emote("Aelric", "se lève"), "*Aelric se lève.*")
        self.assertEqual(format_emote("Aelric", "s’en va."), "*Aelric s’en va.*")
        self.assertEqual(format_emote("Aelric", "  "), "")

    def test_ooc_is_marked(self) -> None:
        self.assertEqual(format_ooc("on pause 5 min"), "**OOC** — on pause 5 min")

    def test_whisper_public_and_private(self) -> None:
        self.assertEqual(
            format_whisper_public("Aelric", "Mira"),
            "*Aelric se penche vers Mira et chuchote.*",
        )
        private = format_whisper_private("Aelric", "Mira", "suis-moi")
        self.assertIn("**Aelric** chuchote à **Mira**", private)
        self.assertIn("Suis-moi.", private)
