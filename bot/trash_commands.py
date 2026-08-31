from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.checks import admin_only, guild_only
from bot.command_helpers import command_reply, delete_command
from bot.help_text import command_help
from combat.storage import get_combat
from config import PREFIX
from players.discover import (
    is_sandbox_channel,
    sandbox_player_id,
    sandbox_scope_id,
)
from sheets.sandbox import MOCK_NAME, ensure_sandbox_sheet, reset_sandbox


def setup_trash(bot: Bot) -> None:
    @bot.hybrid_group(
        name="trash",
        invoke_without_command=True,
        fallback="status",
        help=command_help(
            "Sandbox mock dans #🚯trash.",
            f"`{PREFIX}trash`",
            f"`{PREFIX}trash reset` — recréer Mock et vider combat/init",
        ),
    )
    @guild_only
    @admin_only
    async def trash_group(ctx: Context) -> None:
        if not is_sandbox_channel(ctx.channel):
            await command_reply(
                ctx, "Mock data only works in #🚯trash."
            )
            await delete_command(ctx)
            return
        assert ctx.guild is not None
        owner_id = sandbox_player_id(ctx.channel)
        assert owner_id is not None
        sheet = ensure_sandbox_sheet(guild_id=ctx.guild.id, user_id=owner_id)
        scope_id = sandbox_scope_id(ctx.channel)
        combat = (
            get_combat(guild_id=ctx.guild.id, scope_id=scope_id)
            if scope_id is not None
            else None
        )
        fight = "combat in progress" if combat is not None else "no combat"
        await command_reply(
            ctx,
            (
                f"**Sandbox** — `{MOCK_NAME}` (not a real player sheet)\n"
                f"HP **{sheet.hp_current}/{sheet.hp_max}** · "
                f"AC **{sheet.ac}** · {sheet.char_class} {sheet.level}\n"
                f"{fight}. `{PREFIX}sheet show` · `{PREFIX}combat start Gobelin`\n"
                f"`{PREFIX}trash reset` — restore mock + clear this channel's fight."
            ),
        )
        await delete_command(ctx)

    @trash_group.command(
        name="reset",
        help=command_help(
            "Recrée la fiche Mock et vide combat / initiative du trash.",
            f"`{PREFIX}trash reset`",
        ),
    )
    @guild_only
    @admin_only
    async def trash_reset(ctx: Context) -> None:
        if not is_sandbox_channel(ctx.channel):
            await command_reply(ctx, "Mock data only works in #🚯trash.")
            await delete_command(ctx)
            return
        assert ctx.guild is not None
        sheet = reset_sandbox(guild_id=ctx.guild.id, channel=ctx.channel)
        await command_reply(
            ctx,
            (
                f"Sandbox reset. **{sheet.name}** is "
                f"**{sheet.hp_current}/{sheet.hp_max} HP**, "
                f"{sheet.char_class} {sheet.level}. "
                f"Real player sheets were not touched."
            ),
        )
        await delete_command(ctx)
