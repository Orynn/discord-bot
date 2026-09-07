import unittest

import bot.command_parser  # noqa: F401
from discord.ext.commands.view import StringView

from ai.prompt import parse_ai_request


class TestRelaxCommandQuotes(unittest.TestCase):
    def test_french_apostrophe_is_not_a_quote(self) -> None:
        view = StringView("Qu’est ce qu’il peut trouver")
        self.assertEqual(view.get_quoted_word(), "Qu’est")

    def test_no_context_line_stays_intact(self) -> None:
        text = (
            "Qu’est ce qu’il peut trouver pour faire du feu "
            "sur une montagne ? --no-context"
        )
        instruction, extra, no_context = parse_ai_request(text)
        self.assertTrue(no_context)
        self.assertEqual(extra, "")
        self.assertIn("feu", instruction)
        self.assertNotIn("--no-context", instruction)
