from collections.abc import Callable

import discord
from discord import app_commands
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.checks import admin_only, guild_only, is_admin, is_staff_user_id
from bot.command_helpers import command_reply, delete_command
from bot.help_text import HELP_COLOR, command_help
from bot.messaging import send_message
from bot.privacy import DENIED_OTHER_PLAYER
from campaign.clock import (
    CampaignTime,
    format_duration,
    parse_clock_set,
    parse_duration,
    parse_skip_period,
)
from campaign.clock_storage import get_clock, save_clock
from config import PREFIX
from sheets.context import infer_player_id, parse_mention_and_text, resolve_owner
from sheets.hunger import (
    format_hunger_line,
    sync_hunger_to_clock,
    tick_hunger_for_clock,
)
from players.storage import list_player_user_ids
from sheets.storage import (
    get_character_name,
    get_sheet,
    list_sheet_user_ids,
    save_sheet,
)

CLOCK_COLOR = 0x5DADE2


def _clock_label(
    guild_id: int, user_id: int, member: discord.Member | None = None
) -> str:
    name = get_character_name(user_id=user_id, guild_id=guild_id)
    if name:
        return name
    if member is not None:
        return member.display_name
    return f"<@{user_id}>"


def _clock_embed(
    clock: CampaignTime,
    *,
    who: str | None = None,
    notice: str | None = None,
    hunger_line: str | None = None,
) -> discord.Embed:
    day = clock.calendar_day()
    title = "🎉 Festival" if day.festival else "⏳ Campaign time"
    if who:
        title = f"{title} — {who}"
    embed = discord.Embed(
        title=title,
        description=f"**{clock.format_date()}**",
        color=CLOCK_COLOR if not day.festival else HELP_COLOR,
    )
    if notice:
        embed.add_field(name="⏭️ Change", value=notice, inline=False)
    embed.add_field(
        name="🕰️ Clock", value=f"{clock.format_clock()} · {clock.period()}", inline=True
    )
    embed.add_field(name="📅 Tenday", value=clock.tenday(), inline=True)
    until_dusk = clock.minutes_until_hour(18)
    until_dawn = clock.minutes_until_hour(6)
    if clock.period() in {"dusk", "night"}:
        next_label = f"dawn in {format_duration(until_dawn)}"
    else:
        next_label = f"dusk in {format_duration(until_dusk)}"
    embed.add_field(name="🌅 Next", value=next_label, inline=False)
    if hunger_line:
        embed.add_field(name="🍖 Hunger", value=hunger_line, inline=False)
    embed.set_footer(text=f"Personal Harptos clock · {PREFIX}time")
    return embed


def _party_embed(lines: list[str], *, notice: str | None = None) -> discord.Embed:
    embed = discord.Embed(
        title="⏳ Campaign time",
        description="\n".join(lines) or "No character sheets yet.",
        color=CLOCK_COLOR,
    )
    if notice:
        embed.add_field(name="⏭️ Change", value=notice, inline=False)
    embed.set_footer(
        text=f"One clock per player · DM: {PREFIX}time @player · {PREFIX}time all"
    )
    return embed


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


async def _mutation_targets(
    ctx: Context, member: discord.Member | None
) -> list[int] | None:
    assert ctx.guild is not None
    if not is_admin(ctx):
        await command_reply(
            ctx, "Only the DM can change a campaign clock. Use `;time` to see yours."
        )
        await delete_command(ctx)
        return None
    if member is not None and member.id != ctx.author.id:
        return [member.id]
    inferred = infer_player_id(ctx)
    if inferred is not None:
        return [inferred]
    return _party_user_ids(ctx.guild.id, fallback_id=ctx.author.id)


def _clock_line(guild_id: int, user_id: int, clock: CampaignTime) -> str:
    return f"**{_clock_label(guild_id, user_id)}** — {clock.format_date()} · {clock.format_clock()}"


async def _show_clock(ctx: Context, member: discord.Member | None = None) -> None:
    assert ctx.guild is not None
    owner_id = await resolve_owner(ctx, member)
    if owner_id is None:
        await delete_command(ctx)
        return
    if member is None and owner_id != ctx.author.id:
        found = ctx.guild.get_member(owner_id)
        if isinstance(found, discord.Member):
            member = found
    clock = get_clock(ctx.guild.id, owner_id)
    sheet = get_sheet(user_id=owner_id, guild_id=ctx.guild.id)
    hunger_line = None
    if sheet is not None:
        sync_hunger_to_clock(sheet, clock)
        save_sheet(user_id=owner_id, guild_id=ctx.guild.id, sheet=sheet)
        hunger_line = format_hunger_line(sheet)
    await send_message(
        ctx,
        embed=_clock_embed(
            clock,
            who=_clock_label(ctx.guild.id, owner_id, member),
            hunger_line=hunger_line,
        ),
        definition_menu=False,
    )
    await delete_command(ctx)


async def _show_all_clocks(ctx: Context) -> None:
    assert ctx.guild is not None
    if not is_admin(ctx):
        await command_reply(ctx, DENIED_OTHER_PLAYER)
        await delete_command(ctx)
        return
    user_ids = _party_user_ids(ctx.guild.id, fallback_id=ctx.author.id)
    lines = [
        _clock_line(ctx.guild.id, user_id, get_clock(ctx.guild.id, user_id))
        for user_id in user_ids
    ]
    await send_message(ctx, embed=_party_embed(lines), definition_menu=False)
    await delete_command(ctx)


def _day_notice(previous: CampaignTime, clock: CampaignTime) -> list[str]:
    extra: list[str] = []
    if clock.day_index != previous.day_index or clock.year != previous.year:
        extra.append(f"A new day begins — {clock.format_date()}.")
    day = clock.calendar_day()
    if day.festival:
        extra.append(f"Today is **{day.name}**.")
    return extra


async def _apply_each(
    ctx: Context,
    user_ids: list[int],
    transform: Callable[[CampaignTime], CampaignTime],
    *,
    notice: str,
    update_default: bool = False,
    member: discord.Member | None = None,
) -> None:
    assert ctx.guild is not None
    unique_ids = list(dict.fromkeys(user_ids))
    results: list[tuple[int, CampaignTime, list[str]]] = []
    hunger_notices: list[str] = []
    for user_id in unique_ids:
        previous = get_clock(ctx.guild.id, user_id)
        clock = transform(previous)
        save_clock(ctx.guild.id, user_id, clock, update_default=update_default)
        hunger_notices.extend(
            tick_hunger_for_clock(
                guild_id=ctx.guild.id,
                user_id=user_id,
                previous=previous,
                current=clock,
            )
        )
        results.append((user_id, clock, _day_notice(previous, clock)))

    if len(results) == 1:
        user_id, clock, extra = results[0]
        sheet = get_sheet(user_id=user_id, guild_id=ctx.guild.id)
        hunger_line = format_hunger_line(sheet) if sheet is not None else None
        bits = [notice, *extra, *hunger_notices]
        await send_message(
            ctx,
            embed=_clock_embed(
                clock,
                who=_clock_label(ctx.guild.id, user_id, member),
                notice="\n".join(bits),
                hunger_line=hunger_line,
            ),
            definition_menu=False,
        )
        await delete_command(ctx)
        return

    lines = [_clock_line(ctx.guild.id, user_id, clock) for user_id, clock, _ in results]
    new_days = sum(1 for _, _, extra in results if extra)
    bits = [f"{notice} · {len(results)} clocks"]
    if new_days:
        bits.append(f"{new_days} new day(s).")
    bits.extend(hunger_notices)
    await send_message(
        ctx,
        embed=_party_embed(lines, notice=" ".join(bits)),
        definition_menu=False,
    )
    await delete_command(ctx)


def setup_time(bot: Bot) -> None:
    @bot.hybrid_group(
        name="time",
        aliases=["clock", "calendar", "date", "temps"],
        invoke_without_command=True,
        fallback="now",
        help=command_help(
            "Horloge Harptos de ce joueur. Un nouveau jour de calendrier fait avancer la faim.",
            f"`{PREFIX}time`",
            f"`{PREFIX}time advance 2h` — staff",
        ),
    )
    @guild_only
    async def time_group(ctx: Context, *, spec: str = "") -> None:
        member, cleaned = parse_mention_and_text(ctx, spec)
        if not cleaned or cleaned.lower() in {"now", "show"}:
            await _show_clock(ctx, member)
            return
        if cleaned.lower() in {"all", "party"}:
            if not is_admin(ctx):
                await command_reply(ctx, DENIED_OTHER_PLAYER)
                await delete_command(ctx)
                return
            await _show_all_clocks(ctx)
            return
        if not is_admin(ctx):
            await command_reply(
                ctx,
                "Only the DM can change a campaign clock. Use `;time` to see yours.",
            )
            await delete_command(ctx)
            return
        targets = await _mutation_targets(ctx, member)
        if targets is None:
            return
        sync_all = member is None
        try:
            skip_hour = parse_skip_period(cleaned)
            if skip_hour is not None:
                await _apply_each(
                    ctx,
                    targets,
                    lambda clock, hour=skip_hour: clock.skip_to_hour(hour),
                    notice=f"Skipped to {skip_hour:02d}:00.",
                    member=member,
                )
                return
            if cleaned.lower().startswith("set "):
                clock = parse_clock_set(cleaned[4:])
                await _apply_each(
                    ctx,
                    targets,
                    lambda _previous, value=clock: value,
                    notice="Clock set.",
                    update_default=sync_all,
                    member=member,
                )
                return
            minutes = parse_duration(cleaned)
            await _apply_each(
                ctx,
                targets,
                lambda clock, amount=minutes: clock.advance(amount),
                notice=f"+{format_duration(minutes)}",
                member=member,
            )
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            await delete_command(ctx)

    @time_group.command(
        name="all",
        aliases=["party"],
        help=command_help(
            "Affiche l’horloge de chaque joueur.",
            f"`{PREFIX}time all`",
        ),
    )
    @guild_only
    @admin_only
    async def time_all(ctx: Context) -> None:
        await _show_all_clocks(ctx)

    @time_group.command(
        name="advance",
        aliases=["add", "skip"],
        help=command_help(
            "Avance l’horloge (staff).",
            f"`{PREFIX}time advance [@joueur] <durée>`",
            "`2h` · `3d` · `1h 30m`",
        ),
    )
    @app_commands.describe(amount="Duration to skip, e.g. 2h, 3d, 1h 30m")
    @guild_only
    @admin_only
    async def time_advance(
        ctx: Context, member: discord.Member | None = None, *, amount: str
    ) -> None:
        if member is None:
            member, amount = parse_mention_and_text(ctx, amount)
        try:
            minutes = parse_duration(amount)
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            await delete_command(ctx)
            return
        targets = await _mutation_targets(ctx, member)
        if targets is None:
            return
        await _apply_each(
            ctx,
            targets,
            lambda clock, value=minutes: clock.advance(value),
            notice=f"+{format_duration(minutes)}",
            member=member,
        )

    @time_group.command(
        name="set",
        help=command_help(
            "Fixe la date Harptos (staff).",
            f"`{PREFIX}time set [@joueur] <date>`",
            "`12 Hammer 1492 14:00`",
        ),
    )
    @app_commands.describe(when="Harptos date and time, e.g. 12 Hammer 1492 14:00")
    @guild_only
    @admin_only
    async def time_set(
        ctx: Context, member: discord.Member | None = None, *, when: str
    ) -> None:
        if member is None:
            member, when = parse_mention_and_text(ctx, when)
        try:
            clock = parse_clock_set(when)
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            await delete_command(ctx)
            return
        targets = await _mutation_targets(ctx, member)
        if targets is None:
            return
        await _apply_each(
            ctx,
            targets,
            lambda _previous, value=clock: value,
            notice="Clock set.",
            update_default=member is None,
            member=member,
        )

    async def _skip_to(
        ctx: Context, hour: int, *, label: str, member: discord.Member | None
    ) -> None:
        targets = await _mutation_targets(ctx, member)
        if targets is None:
            return
        await _apply_each(
            ctx,
            targets,
            lambda clock, value=hour: clock.skip_to_hour(value),
            notice=f"Skipped to {label}.",
            member=member,
        )

    @time_group.command(
        name="dawn",
        help=command_help(
            "Passe à l’aube suivante (06:00).",
            f"`{PREFIX}time dawn [@joueur]`",
        ),
    )
    @guild_only
    @admin_only
    async def time_dawn(ctx: Context, member: discord.Member | None = None) -> None:
        await _skip_to(ctx, 6, label="dawn (06:00)", member=member)

    @time_group.command(
        name="noon",
        help=command_help(
            "Passe à midi (12:00).",
            f"`{PREFIX}time noon [@joueur]`",
        ),
    )
    @guild_only
    @admin_only
    async def time_noon(ctx: Context, member: discord.Member | None = None) -> None:
        await _skip_to(ctx, 12, label="noon (12:00)", member=member)

    @time_group.command(
        name="dusk",
        help=command_help(
            "Passe au crépuscule (18:00).",
            f"`{PREFIX}time dusk [@joueur]`",
        ),
    )
    @guild_only
    @admin_only
    async def time_dusk(ctx: Context, member: discord.Member | None = None) -> None:
        await _skip_to(ctx, 18, label="dusk (18:00)", member=member)

    @time_group.command(
        name="midnight",
        help=command_help(
            "Passe à minuit (00:00).",
            f"`{PREFIX}time midnight [@joueur]`",
        ),
    )
    @guild_only
    @admin_only
    async def time_midnight(ctx: Context, member: discord.Member | None = None) -> None:
        await _skip_to(ctx, 0, label="midnight (00:00)", member=member)

    @time_group.group(
        name="rest",
        invoke_without_command=True,
        fallback="help",
        help=command_help(
            "Avance l’horloge d’un repos court (1 h) ou long (8 h).",
            f"`{PREFIX}time rest short|long [@joueur]`",
        ),
    )
    @guild_only
    @admin_only
    async def time_rest_group(ctx: Context) -> None:
        await command_reply(
            ctx,
            f"`{PREFIX}time rest short [@player]` — +1 hour\n"
            f"`{PREFIX}time rest long [@player]` — +8 hours\n"
            f"No @player advances every character sheet. "
            f"This only moves the clock. Characters still use `{PREFIX}sheet rest`.",
        )
        await delete_command(ctx)

    @time_rest_group.command(
        name="short",
        help=command_help(
            "Avance 1 heure (repos court).",
            f"`{PREFIX}time rest short [@joueur]`",
        ),
    )
    @guild_only
    @admin_only
    async def time_rest_short(
        ctx: Context, member: discord.Member | None = None
    ) -> None:
        minutes = parse_duration("short")
        targets = await _mutation_targets(ctx, member)
        if targets is None:
            return
        await _apply_each(
            ctx,
            targets,
            lambda clock, value=minutes: clock.advance(value),
            notice=f"Short rest · +{format_duration(minutes)}",
            member=member,
        )

    @time_rest_group.command(
        name="long",
        help=command_help(
            "Avance 8 heures (repos long).",
            f"`{PREFIX}time rest long [@joueur]`",
        ),
    )
    @guild_only
    @admin_only
    async def time_rest_long(
        ctx: Context, member: discord.Member | None = None
    ) -> None:
        minutes = parse_duration("long")
        targets = await _mutation_targets(ctx, member)
        if targets is None:
            return
        await _apply_each(
            ctx,
            targets,
            lambda clock, value=minutes: clock.advance(value),
            notice=f"Long rest · +{format_duration(minutes)}",
            member=member,
        )
