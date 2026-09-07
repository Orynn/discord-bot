import discord.ext.commands.view as command_view

# Discord and French keyboards often send ’ (U+2019) instead of ASCII '.
# discord.py treats those marks as string quotes, so `;ai Qu’est-ce…` dies
# with UnexpectedQuoteError and never reaches the callback.
_FRENCH_APOSTROPHES = frozenset({"‘", "’", "‚", "‛"})


def relax_command_quotes() -> None:
    for mark in _FRENCH_APOSTROPHES:
        command_view._quotes.pop(mark, None)
    command_view._all_quotes = set(command_view._quotes) | set(
        command_view._quotes.values()
    )


relax_command_quotes()
