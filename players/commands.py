import discord
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.checks import admin_only, guild_only
from bot.command_helpers import command_reply, delete_command
from config import PREFIX
from players.setup import PlayerSetupError, create_player_section, remove_player_section
from players.storage import get_player_section, list_player_sections
from sheets.storage import get_character_name


def setup_player(bot: Bot) -> None:
    @bot.hybrid_group(
        name="player",
        invoke_without_command=True,
        fallback="menu",
        help="Set up private player channels.",
    )
    @guild_only
    @admin_only
    async def player_group(ctx: Context) -> None:
        await command_reply(
            ctx,
            "**Player sections (admin):**\n"
            f"`{PREFIX}player setup @member [name]` — category + channels + sheet\n"
            f"`{PREFIX}player list` — registered player sections\n"
            f"`{PREFIX}player remove @member` — delete section (keeps sheet)\n\n"
            f"• Category: `🐉-----------NAME-----------🐉`\n"
            f"• Channels: `📢blabla` · `🎲roleplay` + welcome message\n"
            f"If `name` is omitted, uses their sheet name or Discord display name.",
        )
        await delete_command(ctx)

    @player_group.command(
        name="setup",
        aliases=["add", "create"],
        help=f"Create a player section. Usage: `{PREFIX}player setup @member [name]`",
    )
    @guild_only
    @admin_only
    async def player_setup(
        ctx: Context,
        member: discord.Member,
        *,
        name: str | None = None,
    ) -> None:
        assert ctx.guild is not None

        if get_player_section(guild_id=ctx.guild.id, user_id=member.id):
            await command_reply(
                ctx,
                f"{member.mention} already has a player section. "
                f"Use `{PREFIX}player remove @member` first.",
            )
            await delete_command(ctx)
            return

        display_name = (name or get_character_name(user_id=member.id) or member.display_name).strip()
        if not display_name:
            await command_reply(ctx, "Provide a name or set the player's character name with `;pcname`.")
            await delete_command(ctx)
            return

        try:
            record = await create_player_section(
                guild=ctx.guild,
                member=member,
                display_name=display_name,
            )
        except PlayerSetupError as exc:
            await command_reply(ctx, str(exc))
            await delete_command(ctx)
            return
        except discord.Forbidden:
            await command_reply(ctx, "Missing permissions to create channels or categories.")
            await delete_command(ctx)
            return
        except discord.HTTPException as exc:
            await command_reply(ctx, f"Discord error while creating channels: {exc}")
            await delete_command(ctx)
            return

        ooc = ctx.guild.get_channel(record["ooc_channel_id"])
        rp = ctx.guild.get_channel(record["roleplay_channel_id"])
        ooc_mention = ooc.mention if isinstance(ooc, discord.TextChannel) else f"<#{record['ooc_channel_id']}>"
        rp_mention = rp.mention if isinstance(rp, discord.TextChannel) else f"<#{record['roleplay_channel_id']}>"

        sheet_note = (
            "Character sheet created."
            if record.get("sheet_created")
            else "Character sheet updated."
        )
        await command_reply(
            ctx,
            f"Created player section for {member.mention} (**{record['name']}**).\n"
            f"{sheet_note}\n"
            f"{ooc_mention} · {rp_mention}",
        )
        await delete_command(ctx)

    @player_group.command(
        name="list",
        help=f"List registered player sections. Usage: `{PREFIX}player list`",
    )
    @guild_only
    @admin_only
    async def player_list(ctx: Context) -> None:
        assert ctx.guild is not None

        entries = list_player_sections(guild_id=ctx.guild.id)
        if not entries:
            await command_reply(ctx, "No player sections registered yet.")
            await delete_command(ctx)
            return

        lines: list[str] = []
        for user_id, record in entries:
            member = ctx.guild.get_member(user_id)
            label = member.mention if member else f"`{user_id}`"
            ooc_id = record.get("ooc_channel_id")
            rp_id = record.get("roleplay_channel_id")
            channels = ""
            if ooc_id and rp_id:
                channels = f" — <#{ooc_id}> · <#{rp_id}>"
            lines.append(f"• {label} · **{record.get('name', '?')}**{channels}")

        body = "\n".join(lines)
        if len(body) > 1900:
            body = f"{body[:1897]}..."
        await command_reply(ctx, f"**Player sections ({len(entries)}):**\n{body}")
        await delete_command(ctx)

    @player_group.command(
        name="remove",
        aliases=["delete"],
        help=f"Remove a player's section. Usage: `{PREFIX}player remove @member`",
    )
    @guild_only
    @admin_only
    async def player_remove(ctx: Context, member: discord.Member) -> None:
        assert ctx.guild is not None

        try:
            record = await remove_player_section(guild=ctx.guild, user_id=member.id)
        except PlayerSetupError as exc:
            await command_reply(ctx, str(exc))
            await delete_command(ctx)
            return
        except discord.Forbidden:
            await command_reply(ctx, "Missing permissions to delete channels or categories.")
            await delete_command(ctx)
            return
        except discord.HTTPException as exc:
            await command_reply(ctx, f"Discord error while removing channels: {exc}")
            await delete_command(ctx)
            return

        await command_reply(
            ctx,
            f"Removed player section for {member.mention} (**{record.get('name', '?')}**). "
            f"Their character sheet was kept.",
        )
        await delete_command(ctx)
