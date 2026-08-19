import re
from typing import FrozenSet

from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.command_helpers import delete_command
from bot.messaging import send_message
from bot.names import get_known_character_names
from config import PREFIX

_ENDING_PUNCTUATION: FrozenSet[str] = frozenset(".!?,;:")


def _is_already_bold(text: str, start: int, end: int) -> bool:
    return (
        start >= 2
        and text[start - 2 : start] == "**"
        and text[end : end + 2] == "**"
    )


def _format_known_names(text: str) -> str:
    known_names = get_known_character_names()
    if not known_names:
        return text

    candidates: list[tuple[int, int, str]] = []
    for name in known_names:
        pattern = re.compile(rf"(?<![\w*]){re.escape(name)}(?![\w*])", re.IGNORECASE)
        for match in pattern.finditer(text):
            start, end = match.start(), match.end()
            if _is_already_bold(text=text, start=start, end=end):
                continue
            candidates.append((start, end, match.group(0)))

    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    selected: list[tuple[int, int, str]] = []
    occupied: list[tuple[int, int]] = []
    for start, end, original in candidates:
        if any(not (end <= occ_start or start >= occ_end) for occ_start, occ_end in occupied):
            continue
        selected.append((start, end, original))
        occupied.append((start, end))

    result = text
    for start, end, original in sorted(selected, key=lambda item: item[0], reverse=True):
        result = f"{result[:start]}**{original}**{result[end:]}"
    return result


def _format_description(text: str) -> str:
    text = _format_known_names(text=text.rstrip())
    if not text or text[-1] not in _ENDING_PUNCTUATION:
        text = f"{text}."
    return f"*{text}*"


def setup_desc(bot: Bot) -> None:
    @bot.hybrid_command(name="desc", help="Post a scene description in italics.")
    async def desc_command(ctx: Context, *, text: str) -> None:
        await send_message(ctx, content=_format_description(text=text))
        await delete_command(ctx)
