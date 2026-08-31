import difflib
import re

from discord.ext.commands.bot import Bot

from config import PREFIX

_INVOKED_NAME = re.compile(r'Command "(.+)" is not found')


def collect_command_names(bot: Bot) -> list[str]:
    names: list[str] = []
    for command in bot.walk_commands():
        if command.hidden:
            continue
        if command.parent is None and command.name == "help":
            continue
        names.append(command.qualified_name)
        parent = command.full_parent_name
        for alias in command.aliases:
            names.append(f"{parent} {alias}" if parent else alias)
    return names


def invoked_command_name(error: BaseException, invoked_with: str | None) -> str:
    if invoked_with:
        return str(invoked_with).strip()
    match = _INVOKED_NAME.search(str(error))
    return match.group(1).strip() if match else ""


def suggest_commands(
    query: str,
    names: list[str],
    *,
    limit: int = 3,
    cutoff: float = 0.72,
) -> list[str]:
    cleaned = query.strip().casefold()
    if len(cleaned) < 2:
        return []
    catalog = sorted({name.strip() for name in names if name.strip()})
    folded = [name.casefold() for name in catalog]
    matches = difflib.get_close_matches(cleaned, folded, n=limit, cutoff=cutoff)
    by_fold = {name.casefold(): name for name in catalog}
    return [by_fold[match] for match in matches if match in by_fold]


def format_command_suggestions(names: list[str]) -> str:
    if not names:
        return ""
    options = " · ".join(f"`{PREFIX}{name}`" for name in names)
    if len(names) == 1:
        return f"Commande inconnue. Tu voulais dire {options} ?"
    return f"Commande inconnue. Tu voulais dire : {options} ?"
