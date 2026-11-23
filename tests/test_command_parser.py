import unittest

import bot.command_parser  # noqa: F401
from discord.ext.commands.view import StringView


class TestRelaxCommandQuotes(unittest.TestCase):
    def test_french_apostrophe_is_not_a_quote(self) -> None:
        view = StringView("Qu’est ce qu’il peut trouver")
        self.assertEqual(view.get_quoted_word(), "Qu’est")
