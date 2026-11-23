import logging

import discord

logger = logging.getLogger(__name__)

_ENTRY_POINT_COMMAND_TYPE = 4


async def purge_stale_global_app_commands(bot: discord.Client) -> int:
    """Remove legacy global slash commands (guild-only bot keeps Entry Point commands)."""
    app_id = bot.application_id
    if app_id is None:
        return 0

    removed = 0
    commands = await bot.http.get_global_commands(app_id)
    for command in commands:
        if command.get("type") == _ENTRY_POINT_COMMAND_TYPE:
            continue
        name = command.get("name", "?")
        command_id = command["id"]
        await bot.http.delete_global_command(app_id, command_id)
        removed += 1
        logger.info("Removed stale global slash command /%s", name)
    return removed
