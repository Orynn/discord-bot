import discord
from discord import app_commands
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.checks import guild_only, is_staff, is_staff_user_id
from bot.command_helpers import command_reply, delete_command
from bot.help_text import HELP_COLOR, command_help
from bot.messaging import send_message
from bot.privacy import DENIED_OTHER_PLAYER
from campaign.clock import MINUTES_PER_DAY
from campaign.clock_storage import get_clock, save_clock
from config import PREFIX
from players.storage import list_player_user_ids
from sheets.context import (
    get_sheet_for_owner,
    parse_mention_and_text,
    save_owner_sheet,
    target_plain,
)
from sheets.data import CharacterSheet
from sheets.hunger import (
    apply_clock_hunger,
    consume_ration,
    eat_full,
    eat_half,
    format_hunger_line,
    hunger_embed_color,
    hunger_state,
    meal_clock,
    parse_hunger_days,
    set_hunger_days,
    sync_hunger_to_clock,
    tick_hunger_for_clock,
)
from sheets.storage import get_sheet, list_sheet_user_ids


def _party_user_ids(guild_id: int, *, fallback_id: int) -> list[int]:
    ids = [
        user_id
        for user_id in list_player_user_ids(guild_id=guild_id)
        if not is_staff_user_id(user_id)
    ]
    if ids:
        return ids
    ids = [
        user_id
        for user_id in list_sheet_user_ids(guild_id=guild_id)
        if not is_staff_user_id(user_id)
    ]
    return ids or [fallback_id]


def _hunger_embed(
    sheet: CharacterSheet,
    *,
    who: str | None = None,
    notice: str | None = None,
    clock=None,
) -> discord.Embed:
    title = "🍖 Hunger"
    if who:
        title = f"{title} — {who}"
    embed = discord.Embed(
        title=title,
        description=f"**{sheet.name}** · {format_hunger_line(sheet)}",
        color=hunger_embed_color(sheet),
    )
    state = hunger_state(sheet)
    embed.add_field(name="State", value=state.title(), inline=True)
    if clock is not None:
        embed.add_field(name="📅 Date", value=clock.format_date(), inline=True)
        last_meal = meal_clock(sheet)
        if last_meal is not None:
            kind = "half rations" if sheet.hunger_meal_kind == "half" else "full meal"
            embed.add_field(
                name="Last meal",
                value=f"{last_meal.format_date()} ({kind})",
                inline=False,
            )
    if notice:
        embed.add_field(name="Change", value=notice, inline=False)
    embed.set_footer(
        text=f"Follows this player's ;time clock · eat with {PREFIX}hunger eat"
    )
    return embed


def _party_embed(lines: list[str], *, notice: str | None = None) -> discord.Embed:
    embed = discord.Embed(
        title="🍖 Hunger",
        description="\n".join(lines) or "No character sheets yet.",
        color=HELP_COLOR,
    )
    if notice:
        embed.add_field(name="Change", value=notice, inline=False)
    embed.set_footer(
        text=f"One tracker per player · DM: {PREFIX}hunger @player · {PREFIX}hunger all"
    )
    return embed


def _sheet_line(guild_id: int, user_id: int, sheet: CharacterSheet) -> str:
    marker = "⚠️" if hunger_state(sheet) == "starving" else "🍖"
    return f"{marker} **{sheet.name}** — {format_hunger_line(sheet)}"


async def _show_hunger(ctx: Context, member: discord.Member | None) -> None:
    result = await get_sheet_for_owner(ctx, member)
    if result is None:
        await delete_command(ctx)
        return
    _owner_id, sheet = result
    clock = get_clock(ctx.guild.id, _owner_id) if ctx.guild is not None else None
    notices: list[str] = []
    if clock is not None:
        notices, dirty = apply_clock_hunger(sheet, clock)
        if dirty:
            save_owner_sheet(ctx, _owner_id, sheet)
    label = target_plain(member, sheet)
    notice = "\n".join(notices) if notices else None
    await send_message(
        ctx,
        embed=_hunger_embed(sheet, who=label, notice=notice, clock=clock),
        definition_menu=False,
    )
    await delete_command(ctx)


async def _show_all(ctx: Context) -> None:
    assert ctx.guild is not None
    if not is_staff(ctx):
        await command_reply(ctx, DENIED_OTHER_PLAYER)
        await delete_command(ctx)
        return
    lines: list[str] = []
    extra: list[str] = []
    for user_id in _party_user_ids(ctx.guild.id, fallback_id=ctx.author.id):
        sheet = get_sheet(user_id=user_id, guild_id=ctx.guild.id)
        if sheet is None:
            continue
        clock = get_clock(ctx.guild.id, user_id)
        notices, dirty = apply_clock_hunger(sheet, clock)
        if dirty:
            save_owner_sheet(ctx, user_id, sheet)
        lines.append(_sheet_line(ctx.guild.id, user_id, sheet))
        extra.extend(f"**{sheet.name}**: {notice}" for notice in notices)
    notice = "\n".join(extra) if extra else None
    await send_message(
        ctx, embed=_party_embed(lines, notice=notice), definition_menu=False
    )
    await delete_command(ctx)


async def _eat(
    ctx: Context,
    member: discord.Member | None,
    *,
    half: bool,
    require_ration: bool,
) -> None:
    result = await get_sheet_for_owner(ctx, member)
    if result is None:
        await delete_command(ctx)
        return
    owner_id, sheet = result
    clock = get_clock(ctx.guild.id, owner_id) if ctx.guild is not None else None
    ration = None
    if not half:
        ration = consume_ration(sheet)
        if ration is None and require_ration and not is_staff(ctx):
            await command_reply(
                ctx,
                f"**{sheet.name}** has no rations. Add some with `{PREFIX}sheet gear add rations`.",
            )
            await delete_command(ctx)
            return
    if half:
        eat_half(sheet, clock)
        notice = "Half rations today."
    else:
        eat_full(sheet, clock)
        if ration is not None:
            left = sheet.equipment.find_item(ration.name)
            remaining = left.quantity if left is not None else 0
            notice = f"Ate **{ration.name}**. {remaining} left."
        else:
            notice = "Ate a full meal (no ration consumed)."
    save_owner_sheet(ctx, owner_id, sheet)
    await send_message(
        ctx,
        embed=_hunger_embed(
            sheet, who=target_plain(member, sheet), notice=notice, clock=clock
        ),
        definition_menu=False,
    )
    await delete_command(ctx)


async def _skip(ctx: Context, member: discord.Member | None) -> None:
    if not is_staff(ctx):
        await command_reply(
            ctx,
            "Only the DM can skip a meal day. Use `;time advance 1d` to move the clock.",
        )
        await delete_command(ctx)
        return
    result = await get_sheet_for_owner(ctx, member)
    if result is None:
        await delete_command(ctx)
        return
    assert ctx.guild is not None
    owner_id, sheet = result
    clock = get_clock(ctx.guild.id, owner_id)
    nxt = clock.advance(MINUTES_PER_DAY)
    save_clock(ctx.guild.id, owner_id, nxt)
    notices = tick_hunger_for_clock(
        guild_id=ctx.guild.id,
        user_id=owner_id,
        previous=clock,
        current=nxt,
    )
    sheet = get_sheet(user_id=owner_id, guild_id=ctx.guild.id) or sheet
    notice = f"Clock +1 day — {nxt.format_date()}."
    extra = [line for line in notices if "exhaustion" in line or "starvation" in line]
    if extra:
        notice = f"{notice}\n" + "\n".join(extra)
    await send_message(
        ctx,
        embed=_hunger_embed(
            sheet,
            who=target_plain(member, sheet),
            notice=notice,
            clock=nxt,
        ),
        definition_menu=False,
    )
    await delete_command(ctx)


async def _set(ctx: Context, member: discord.Member | None, amount: str) -> None:
    if not is_staff(ctx):
        await command_reply(ctx, "Only the DM can set hunger.")
        await delete_command(ctx)
        return
    try:
        days = parse_hunger_days(amount)
    except ValueError as exc:
        await command_reply(ctx, str(exc))
        await delete_command(ctx)
        return
    result = await get_sheet_for_owner(ctx, member)
    if result is None:
        await delete_command(ctx)
        return
    owner_id, sheet = result
    clock = get_clock(ctx.guild.id, owner_id) if ctx.guild is not None else None
    set_hunger_days(sheet, days, clock)
    if clock is not None:
        sync_hunger_to_clock(sheet, clock)
    save_owner_sheet(ctx, owner_id, sheet)
    await send_message(
        ctx,
        embed=_hunger_embed(
            sheet,
            who=target_plain(member, sheet),
            notice=f"Set to {days:g} day(s) without food.",
            clock=clock,
        ),
        definition_menu=False,
    )
    await delete_command(ctx)


async def _eat_all(ctx: Context, *, half: bool) -> None:
    assert ctx.guild is not None
    if not is_staff(ctx):
        await command_reply(ctx, "Only the DM can feed the whole party.")
        await delete_command(ctx)
        return
    lines: list[str] = []
    fed = 0
    for user_id in _party_user_ids(ctx.guild.id, fallback_id=ctx.author.id):
        sheet = get_sheet(user_id=user_id, guild_id=ctx.guild.id)
        if sheet is None:
            continue
        if half:
            eat_half(sheet, get_clock(ctx.guild.id, user_id))
        else:
            consume_ration(sheet)
            eat_full(sheet, get_clock(ctx.guild.id, user_id))
        save_owner_sheet(ctx, user_id, sheet)
        lines.append(_sheet_line(ctx.guild.id, user_id, sheet))
        fed += 1
    notice = (
        f"Half rations for {fed} character(s)." if half else f"Fed {fed} character(s)."
    )
    await send_message(
        ctx, embed=_party_embed(lines, notice=notice), definition_menu=False
    )
    await delete_command(ctx)


def setup_hunger(bot: Bot) -> None:
    @bot.hybrid_group(
        name="hunger",
        aliases=["faim", "food"],
        invoke_without_command=True,
        fallback="now",
        help=command_help(
            "La faim suit l’horloge `;time` de ce joueur (inanition PHB).",
            f"`{PREFIX}hunger`",
            f"Guide : `{PREFIX}help hunger`",
        ),
    )
    @guild_only
    async def hunger_group(ctx: Context, *, spec: str = "") -> None:
        member, cleaned = parse_mention_and_text(ctx, spec)
        key = cleaned.lower().strip()
        if not key or key in {"now", "show", "status"}:
            await _show_hunger(ctx, member)
            return
        if key in {"all", "party"}:
            await _show_all(ctx)
            return
        if key in {"eat all", "feed all", "manger tout", "eatall"}:
            await _eat_all(ctx, half=False)
            return
        if key in {"eat", "manger", "feed", "full"}:
            await _eat(ctx, member, half=False, require_ration=True)
            return
        if key in {"half", "demi"}:
            await _eat(ctx, member, half=True, require_ration=False)
            return
        if key in {"skip", "starve", "jeune", "jeûne"}:
            await _skip(ctx, member)
            return
        if key.startswith("set "):
            await _set(ctx, member, key[4:])
            return
        await command_reply(
            ctx,
            f"Hunger follows this player's `{PREFIX}time` clock. A meal covers that day.\n"
            f"`{PREFIX}hunger` · `{PREFIX}faim` — status\n"
            f"`{PREFIX}hunger eat` · `manger` — eat a ration (resets hunger)\n"
            f"`{PREFIX}hunger half` · `demi` — half rations (0.5 day)\n"
            f"`{PREFIX}hunger skip` — clock +1 day, no meal *(DM)*\n"
            f"`{PREFIX}time advance 1d` — ticks hunger at midnight · `{PREFIX}hunger all` *(DM)*",
        )
        await delete_command(ctx)

    @hunger_group.command(
        name="eat",
        aliases=["manger", "feed"],
        help=command_help(
            "Mange une ration : repas complet sur l’horloge de ce joueur.",
            f"`{PREFIX}hunger eat [@joueur]`",
        ),
    )
    @guild_only
    async def hunger_eat(ctx: Context, member: discord.Member | None = None) -> None:
        await _eat(ctx, member, half=False, require_ration=True)

    @hunger_group.command(
        name="half",
        aliases=["demi"],
        help=command_help(
            "Demi-rations (0,5 jour manqué).",
            f"`{PREFIX}hunger half [@joueur]`",
        ),
    )
    @guild_only
    async def hunger_half(ctx: Context, member: discord.Member | None = None) -> None:
        await _eat(ctx, member, half=True, require_ration=False)

    @hunger_group.command(
        name="skip",
        aliases=["starve", "jeune"],
        help=command_help(
            "Avance l’horloge d’un jour sans repas (MJ).",
            f"`{PREFIX}hunger skip [@joueur]`",
        ),
    )
    @guild_only
    async def hunger_skip(ctx: Context, member: discord.Member | None = None) -> None:
        await _skip(ctx, member)

    @hunger_group.command(
        name="set",
        help=command_help(
            "Fixe les jours sans manger (MJ).",
            f"`{PREFIX}hunger set [@joueur] <jours>`",
            "Exemples : `2` · `0` · `2.5`",
        ),
    )
    @app_commands.describe(days="Days without food, e.g. 0, 2, 2.5")
    @guild_only
    async def hunger_set(
        ctx: Context, member: discord.Member | None = None, *, days: str
    ) -> None:
        if member is None:
            member, days = parse_mention_and_text(ctx, days)
        await _set(ctx, member, days)

    @hunger_group.command(
        name="all",
        aliases=["party"],
        help=command_help(
            "Affiche la faim de tout le groupe.",
            f"`{PREFIX}hunger all`",
        ),
    )
    @guild_only
    async def hunger_all(ctx: Context) -> None:
        await _show_all(ctx)

    @hunger_group.command(
        name="eatall",
        help=command_help(
            "Fait manger une ration à chaque personnage.",
            f"`{PREFIX}hunger eatall`",
        ),
    )
    @guild_only
    async def hunger_eat_all(ctx: Context) -> None:
        await _eat_all(ctx, half=False)
