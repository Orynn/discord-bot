import discord
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.checks import admin_only, guild_only, is_staff
from bot.command_helpers import command_reply, delete_command
from bot.messaging import send_message
from combat.cards import WEAPON_CARD_ID, DODGE_CARD_ID, CardSnapshot
from combat.display import build_combat_embed, build_hand_embed
from combat.engine import add_combatant, can_control_combatant, end_turn, play_card, start_combat
from combat.scope import PLAYER_COMBAT_ONLY, scope_id_for_channel
from combat.storage import clear_combat, get_combat, lock_for
from combat.view import build_combat_view
from config import PREFIX
from sheets.context import parse_mention_and_text


def _scope_id(ctx: Context) -> int | None:
    assert ctx.guild is not None
    return scope_id_for_channel(guild=ctx.guild, channel=ctx.channel)


async def _require_player_scope(ctx: Context) -> int | None:
    scope_id = _scope_id(ctx)
    if scope_id is None:
        await command_reply(ctx, PLAYER_COMBAT_ONLY)
        await delete_command(ctx)
        return None
    return scope_id


def setup_combat(bot: Bot) -> None:
    @bot.hybrid_group(
        name="combat",
        invoke_without_command=True,
        fallback="menu",
        help="Card combat board, hand, and play commands.",
    )
    @guild_only
    async def combat_group(ctx: Context) -> None:
        scope_id = await _require_player_scope(ctx)
        if scope_id is None:
            return
        state = get_combat(guild_id=ctx.guild.id, scope_id=scope_id)
        if state is None:
            await command_reply(
                ctx,
                (
                    f"**Card combat** — this player's section only. Guide: `{PREFIX}help combat`\n\n"
                    f"1. `{PREFIX}init add @player` — initiative\n"
                    f"2. `{PREFIX}combat start` — deal decks *(admin)*\n"
                    f"3. `{PREFIX}combat board` — play your cards"
                ),
            )
        else:
            await send_message(
                ctx,
                embed=build_combat_embed(state),
                view=build_combat_view(state),
                definition_menu=False,
            )
        await delete_command(ctx)

    @combat_group.command(name="start", help=f"Start card combat from initiative. `{PREFIX}combat start`")
    @guild_only
    @admin_only
    async def combat_start(ctx: Context) -> None:
        scope_id = await _require_player_scope(ctx)
        if scope_id is None:
            return
        try:
            async with lock_for(guild_id=ctx.guild.id, scope_id=scope_id):
                state = await start_combat(
                    guild_id=ctx.guild.id,
                    channel_id=ctx.channel.id,
                    scope_id=scope_id,
                )
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            await delete_command(ctx)
            return

        await send_message(
            ctx,
            embed=build_combat_embed(state),
            view=build_combat_view(state),
            definition_menu=False,
        )
        await delete_command(ctx)

    @combat_group.command(
        name="board",
        help=f"Show the combat board and card menu. `{PREFIX}combat board`",
    )
    @guild_only
    async def combat_board(ctx: Context) -> None:
        scope_id = await _require_player_scope(ctx)
        if scope_id is None:
            return
        state = get_combat(guild_id=ctx.guild.id, scope_id=scope_id)
        if state is None:
            await command_reply(ctx, "No card combat in progress. Use `;combat start` first.")
            await delete_command(ctx)
            return

        await send_message(
            ctx,
            embed=build_combat_embed(state),
            view=build_combat_view(state),
            definition_menu=False,
        )
        await delete_command(ctx)

    @combat_group.command(
        name="hand",
        help=f"Show your hand (private). `{PREFIX}combat hand`",
    )
    @guild_only
    async def combat_hand(ctx: Context) -> None:
        scope_id = await _require_player_scope(ctx)
        if scope_id is None:
            return
        state = get_combat(guild_id=ctx.guild.id, scope_id=scope_id)
        if state is None:
            await command_reply(ctx, "No card combat in progress.")
            await delete_command(ctx)
            return

        combatant = next(
            (entry for entry in state.combatants.values() if entry.user_id == ctx.author.id),
            None,
        )
        if combatant is None:
            await command_reply(ctx, "You are not in this combat.")
            await delete_command(ctx)
            return

        await send_message(
            ctx,
            embed=build_hand_embed(
                combatant_name=combatant.name,
                hand=combatant.hand,
                catalog=combatant.card_catalog,
            ),
            definition_menu=False,
        )
        await delete_command(ctx)

    @combat_group.command(
        name="play",
        help=f"Play a card. `{PREFIX}combat play strike Goblin`",
    )
    @guild_only
    async def combat_play(ctx: Context, card: str, *, target: str = "") -> None:
        scope_id = await _require_player_scope(ctx)
        if scope_id is None:
            return
        try:
            async with lock_for(guild_id=ctx.guild.id, scope_id=scope_id):
                state = get_combat(guild_id=ctx.guild.id, scope_id=scope_id)
                if state is None:
                    await command_reply(ctx, "No card combat in progress.")
                    await delete_command(ctx)
                    return

                active = state.active_combatant()
                if active is None:
                    await command_reply(ctx, "No active combatant.")
                    await delete_command(ctx)
                    return

                if not can_control_combatant(
                    combatant=active,
                    user_id=ctx.author.id,
                    is_admin=is_staff(ctx),
                    scope_id=scope_id,
                ):
                    if active.user_id is None:
                        await command_reply(ctx, f"Only the DM or this player can play for **{active.name}**.")
                    else:
                        await command_reply(ctx, f"It is **{active.name}**'s turn.")
                    await delete_command(ctx)
                    return

                card_id = _resolve_card_id(card, active.card_catalog)
                if card_id is None:
                    labels = ", ".join(sorted(card.label for card in active.card_catalog.values()))
                    await command_reply(ctx, f"Unknown card. Your hand uses: {labels}")
                    await delete_command(ctx)
                    return

                result = play_card(
                    state,
                    actor_name=active.name,
                    card_id=card_id,
                    target_name=target.strip() or None,
                )
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            await delete_command(ctx)
            return

        await send_message(
            ctx,
            content=result.message,
            embed=build_combat_embed(state),
            view=build_combat_view(state),
            definition_menu=False,
        )
        await delete_command(ctx)

    @combat_group.command(name="end", help=f"End card combat. `{PREFIX}combat end`")
    @guild_only
    @admin_only
    async def combat_end(ctx: Context) -> None:
        scope_id = await _require_player_scope(ctx)
        if scope_id is None:
            return
        clear_combat(guild_id=ctx.guild.id, scope_id=scope_id)
        await command_reply(ctx, "Card combat ended.")
        await delete_command(ctx)

    @combat_group.command(
        name="add",
        help=f"Add a combatant mid-fight. `{PREFIX}combat add Goblin` or `{PREFIX}combat add Name 30`",
    )
    @guild_only
    @admin_only
    async def combat_add(
        ctx: Context,
        member: discord.Member | None = None,
        *,
        args: str = "",
    ) -> None:
        scope_id = await _require_player_scope(ctx)
        if scope_id is None:
            return
        state = get_combat(guild_id=ctx.guild.id, scope_id=scope_id)
        if state is None:
            await command_reply(ctx, "No card combat in progress.")
            await delete_command(ctx)
            return

        if member is None:
            member, args = parse_mention_and_text(ctx, args)
        else:
            _, args = parse_mention_and_text(ctx, args)
        if member is not None:
            parts = args.replace(f"<@{member.id}>", "").replace(f"<@!{member.id}>", "").strip().rsplit(maxsplit=1)
            hp = int(parts[-1]) if parts and parts[-1].isdigit() else None
            try:
                combatant = await add_combatant(
                    state,
                    name=member.display_name,
                    hp=hp,
                    user_id=member.id,
                )
            except ValueError as exc:
                await command_reply(ctx, str(exc))
                await delete_command(ctx)
                return
        else:
            cleaned = args.strip()
            if not cleaned:
                await command_reply(ctx, f"Usage: `{PREFIX}combat add <name> [hp]`")
                await delete_command(ctx)
                return
            parts = cleaned.rsplit(maxsplit=1)
            if len(parts) == 2 and parts[1].isdigit():
                monster_name, hp = parts[0], int(parts[1])
            else:
                monster_name, hp = cleaned, None
            try:
                combatant = await add_combatant(state, name=monster_name, hp=hp)
            except ValueError as exc:
                await command_reply(ctx, str(exc))
                await delete_command(ctx)
                return

        if combatant.user_id is None:
            traits = f" · {', '.join(combatant.traits)}" if combatant.traits else ""
            reply = f"Added **{combatant.name}**{traits} with {len(combatant.hand)} cards."
        else:
            reply = f"Added **{combatant.name}** ({combatant.hp} HP) with {len(combatant.hand)} cards."
        await command_reply(ctx, reply)
        await delete_command(ctx)

    @combat_group.command(name="pass", help=f"End your turn without playing. `{PREFIX}combat pass`")
    @guild_only
    async def combat_pass(ctx: Context) -> None:
        scope_id = await _require_player_scope(ctx)
        if scope_id is None:
            return
        try:
            async with lock_for(guild_id=ctx.guild.id, scope_id=scope_id):
                state = get_combat(guild_id=ctx.guild.id, scope_id=scope_id)
                if state is None:
                    await command_reply(ctx, "No card combat in progress.")
                    await delete_command(ctx)
                    return

                active = state.active_combatant()
                if active is None:
                    await command_reply(ctx, "No active combatant.")
                    await delete_command(ctx)
                    return

                if not can_control_combatant(
                    combatant=active,
                    user_id=ctx.author.id,
                    is_admin=is_staff(ctx),
                    scope_id=scope_id,
                ):
                    if active.user_id is None:
                        await command_reply(ctx, f"Only the DM or this player can play for **{active.name}**.")
                    else:
                        await command_reply(ctx, f"It is **{active.name}**'s turn.")
                    await delete_command(ctx)
                    return

                result = end_turn(state, actor_name=active.name)
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            await delete_command(ctx)
            return

        await send_message(
            ctx,
            content=result.message,
            embed=build_combat_embed(state),
            view=build_combat_view(state),
            definition_menu=False,
        )
        await delete_command(ctx)


def _resolve_card_id(query: str, catalog: dict[str, CardSnapshot]) -> str | None:
    normalized = query.strip().lower().replace(" ", "-")
    aliases = {
        "weapon": WEAPON_CARD_ID,
        "attack": WEAPON_CARD_ID,
        "strike": WEAPON_CARD_ID,
        "dodge": DODGE_CARD_ID,
    }
    if normalized in aliases and aliases[normalized] in catalog:
        return aliases[normalized]
    if normalized in catalog:
        return normalized
    for card_id, card in catalog.items():
        label_key = card.label.lower().replace(" ", "-")
        if normalized == label_key or normalized in label_key:
            return card_id
        if card.spell_slug and normalized in card.spell_slug:
            return card_id
    return None
