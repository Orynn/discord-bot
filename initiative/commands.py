import random

import discord
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.checks import admin_only, guild_only, is_staff
from bot.command_helpers import command_reply, delete_command
from bot.messaging import send_message
from bot.privacy import reject_other_player
from combat.scope import PLAYER_INIT_ONLY, scope_id_for_channel
from config import PREFIX
from initiative.display import advance_turn, build_initiative_embed
from initiative.storage import (
    InitiativeState,
    add_initiative_entry,
    clear_initiative,
    get_initiative,
    save_initiative,
)
from sheets.context import infer_player_id, parse_mention_and_text
from sheets.data import ability_modifier
from sheets.storage import get_sheet


async def _require_player_scope(ctx: Context) -> int | None:
    assert ctx.guild is not None
    scope_id = scope_id_for_channel(guild=ctx.guild, channel=ctx.channel)
    if scope_id is None:
        await command_reply(ctx, PLAYER_INIT_ONLY)
        await delete_command(ctx)
        return None
    return scope_id


def setup_initiative(bot: Bot) -> None:
    @bot.hybrid_group(
        name="init",
        invoke_without_command=True,
        fallback="menu",
        help="Initiative tracker: add, next, show, clear.",
    )
    @guild_only
    async def init_group(ctx: Context) -> None:
        scope_id = await _require_player_scope(ctx)
        if scope_id is None:
            return
        state = get_initiative(guild_id=ctx.guild.id, scope_id=scope_id)
        if state is None:
            await command_reply(
                ctx,
                (
                    f"**⚡ Initiative**\n"
                    f"`{PREFIX}init add @player` · `{PREFIX}init add NPC 2`\n"
                    f"`{PREFIX}init next` · `{PREFIX}init show` · `{PREFIX}init clear`"
                ),
            )
        else:
            await send_message(
                ctx, embed=build_initiative_embed(state), definition_menu=False
            )
        await delete_command(ctx)

    @init_group.command(
        name="add",
        help=f"Add to initiative. `{PREFIX}init add @player` or `{PREFIX}init add Name 2`",
    )
    @guild_only
    async def init_add(
        ctx: Context,
        member: discord.Member | None = None,
        *,
        args: str = "",
    ) -> None:
        scope_id = await _require_player_scope(ctx)
        if scope_id is None:
            return
        if member is None:
            member, args = parse_mention_and_text(ctx, args)
        else:
            _, args = parse_mention_and_text(ctx, args)
        if is_staff(ctx) and member is not None and member.id == ctx.author.id:
            member = None
        if member is None and not args.strip() and is_staff(ctx):
            inferred = infer_player_id(ctx)
            if inferred is not None and ctx.guild is not None:
                found = ctx.guild.get_member(inferred)
                if isinstance(found, discord.Member):
                    member = found
        if not await reject_other_player(ctx, member, delete=True):
            return
        modifier = 0
        if member is not None:
            sheet = get_sheet(user_id=member.id, guild_id=ctx.guild.id)
            entry_name = sheet.name if sheet else member.display_name
            if sheet:
                modifier = ability_modifier(sheet.abilities["dex"])
            user_id = member.id
        else:
            user_id = None
            parts = args.strip().rsplit(maxsplit=1)
            if len(parts) == 2 and parts[1].lstrip("+-").isdigit():
                modifier = int(parts[1])
                entry_name = parts[0]
            else:
                entry_name = args.strip() or "Combatant"

        state = get_initiative(guild_id=ctx.guild.id, scope_id=scope_id)
        if state is None:
            state = InitiativeState(channel_id=ctx.channel.id, active_index=0, order=[])

        roll = random.randint(1, 20)
        total = roll + modifier
        add_initiative_entry(state, name=entry_name, total=total, user_id=user_id)
        save_initiative(guild_id=ctx.guild.id, scope_id=scope_id, state=state)
        mod_label = f"+{modifier}" if modifier >= 0 else str(modifier)
        await send_message(
            ctx,
            embed=build_initiative_embed(
                state,
                notice=f"**{entry_name}** rolled **{total}** (d20: {roll} {mod_label}).",
            ),
            definition_menu=False,
        )
        await delete_command(ctx)

    @init_group.command(name="next", help=f"Next turn. `{PREFIX}init next`")
    @guild_only
    async def init_next(ctx: Context) -> None:
        scope_id = await _require_player_scope(ctx)
        if scope_id is None:
            return
        result = advance_turn(guild_id=ctx.guild.id, scope_id=scope_id)
        if result is None:
            await command_reply(ctx, "No initiative tracked.")
            return
        state, current = result
        await send_message(
            ctx,
            embed=build_initiative_embed(state, notice=f"Turn: **{current.name}**"),
            definition_menu=False,
        )
        await delete_command(ctx)

    @init_group.command(name="show", help=f"Show initiative. `{PREFIX}init show`")
    @guild_only
    async def init_show(ctx: Context) -> None:
        scope_id = await _require_player_scope(ctx)
        if scope_id is None:
            return
        state = get_initiative(guild_id=ctx.guild.id, scope_id=scope_id)
        if not state or not state.order:
            await command_reply(ctx, "No initiative tracked.")
            return
        await send_message(
            ctx, embed=build_initiative_embed(state), definition_menu=False
        )
        await delete_command(ctx)

    @init_group.command(name="clear", help=f"Clear initiative. `{PREFIX}init clear`")
    @guild_only
    @admin_only
    async def init_clear(ctx: Context) -> None:
        scope_id = await _require_player_scope(ctx)
        if scope_id is None:
            return
        clear_initiative(guild_id=ctx.guild.id, scope_id=scope_id)
        await command_reply(ctx, "Initiative cleared.")
        await delete_command(ctx)

    @init_group.command(
        name="remove", help=f"Remove combatant. `{PREFIX}init remove <name>`"
    )
    @guild_only
    @admin_only
    async def init_remove(ctx: Context, *, name: str) -> None:
        scope_id = await _require_player_scope(ctx)
        if scope_id is None:
            return
        state = get_initiative(guild_id=ctx.guild.id, scope_id=scope_id)
        if not state:
            await command_reply(ctx, "No initiative tracked.")
            return
        query = name.lower()
        active_entry = None
        if state.order and 0 <= state.active_index < len(state.order):
            active_entry = state.order[state.active_index]

        state.order = [
            entry for entry in state.order if query not in entry.name.lower()
        ]
        if not state.order:
            clear_initiative(guild_id=ctx.guild.id, scope_id=scope_id)
        else:
            if active_entry is not None:
                for index, entry in enumerate(state.order):
                    if (
                        entry.name == active_entry.name
                        and entry.user_id == active_entry.user_id
                    ):
                        state.active_index = index
                        break
                else:
                    state.active_index = min(state.active_index, len(state.order) - 1)
            else:
                state.active_index = min(state.active_index, len(state.order) - 1)
            save_initiative(guild_id=ctx.guild.id, scope_id=scope_id, state=state)
        await command_reply(ctx, f"Removed **{name}** from initiative.")
        await delete_command(ctx)
