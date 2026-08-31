import discord
from discord.ext.commands import Group
from discord.ext.commands.context import Context

from bot.checks import is_admin
from bot.command_helpers import command_reply, delete_command
from bot.help_text import HELP_MAGIC_COLOR, command_help
from bot.messaging import send_message
from config import PREFIX
from sheets.context import get_sheet_for_owner, save_owner_sheet, target_label
from sheets.spell_slots import level_label, parse_slot_level, slots_table_for_class


def _slots_help_embed(*, label: str, slots_text: str, admin_hint: str) -> discord.Embed:
    embed = discord.Embed(
        title="🔮 Spell slots",
        description=(
            f"{label}: {slots_text}\n\n"
            f"_Cast tracking — different from `{PREFIX}sheet spells` (known spells)._"
        ),
        color=HELP_MAGIC_COLOR,
    )
    embed.add_field(
        name="⌨️ Commands",
        value=(
            f"`{PREFIX}sheet slots show{admin_hint}` — remaining / max\n"
            f"`{PREFIX}sheet slots use{admin_hint} <level> [count]` — "
            f"ex: `{PREFIX}sheet slots use 1`\n"
            f"`{PREFIX}sheet slots recover{admin_hint}` — restore all\n"
            f"`{PREFIX}sheet slots set{admin_hint} <level> <max> [current]`\n"
            f"`{PREFIX}sheet slots auto{admin_hint}` — from class & level (PHB)\n"
            f"`{PREFIX}sheet slots clear{admin_hint}` — remove tracking"
        ),
        inline=False,
    )
    embed.set_footer(text="Long rest restores slots · Warlock also on short rest")
    return embed


def register_slot_commands(sheet_group: Group) -> None:
    @sheet_group.group(
        name="slots",
        aliases=["slot"],
        invoke_without_command=True,
        help=command_help(
            "Suivi des emplacements de sorts (pas les sorts connus).",
            f"`{PREFIX}sheet slots`",
        ),
    )
    async def sheet_slots_group(
        ctx: Context, member: discord.Member | None = None
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        _, sheet = result

        label = target_label(member, sheet)
        admin_hint = " [@player]" if is_admin(ctx) else ""
        await send_message(
            ctx,
            embed=_slots_help_embed(
                label=label,
                slots_text=sheet.spell_slots.format(),
                admin_hint=admin_hint,
            ),
            definition_menu=False,
        )
        await delete_command(ctx)

    @sheet_slots_group.command(
        name="show",
        help=command_help(
            "Affiche les emplacements restants.",
            f"`{PREFIX}sheet slots show [@joueur]`",
        ),
    )
    async def sheet_slots_show(
        ctx: Context, member: discord.Member | None = None
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        _, sheet = result
        label = target_label(member, sheet)
        await command_reply(ctx, f"{label} spell slots: {sheet.spell_slots.format()}.")
        await delete_command(ctx)

    @sheet_slots_group.command(
        name="use",
        aliases=["spend", "cast"],
        help=command_help(
            "Dépense des emplacements de sorts.",
            f"`{PREFIX}sheet slots use [@joueur] <niveau> [nombre]`",
        ),
    )
    async def sheet_slots_use(
        ctx: Context,
        member: discord.Member | None = None,
        level: str = "",
        count: int = 1,
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result

        if not level:
            await command_reply(
                ctx,
                f"Usage: `{PREFIX}sheet slots use [@player] <level> [count]`",
            )
            return

        try:
            slot_level = parse_slot_level(level)
            sheet.spell_slots.use(slot_level, count)
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            return

        save_owner_sheet(ctx, owner_id, sheet)
        label = target_label(member, sheet)
        await command_reply(
            ctx,
            f"{label} used **{count}** {level_label(slot_level)}-level slot(s). "
            f"Now: {sheet.spell_slots.format()}.",
        )
        await delete_command(ctx)

    @sheet_slots_group.command(
        name="recover",
        aliases=["restore", "fill"],
        help=command_help(
            "Récupère des emplacements de sorts.",
            f"`{PREFIX}sheet slots recover [@joueur] [niveau] [nombre]`",
        ),
    )
    async def sheet_slots_recover(
        ctx: Context,
        member: discord.Member | None = None,
        level: str = "",
        count: int | None = None,
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result

        try:
            if not level:
                sheet.spell_slots.restore_all()
            else:
                slot_level = parse_slot_level(level)
                sheet.spell_slots.recover(slot_level, count)
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            return

        save_owner_sheet(ctx, owner_id, sheet)
        label = target_label(member, sheet)
        await command_reply(
            ctx,
            f"{label} recovered spell slots. Now: {sheet.spell_slots.format()}.",
        )
        await delete_command(ctx)

    @sheet_slots_group.command(
        name="set",
        help=command_help(
            "Fixe les emplacements d’un niveau.",
            f"`{PREFIX}sheet slots set [@joueur] <niveau> <max> [actuel]`",
        ),
    )
    async def sheet_slots_set(
        ctx: Context,
        member: discord.Member | None = None,
        level: str = "",
        maximum: int | None = None,
        current: int | None = None,
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result

        if not level or maximum is None:
            await command_reply(
                ctx,
                f"Usage: `{PREFIX}sheet slots set [@player] <level> <max> [current]`",
            )
            return

        try:
            slot_level = parse_slot_level(level)
            sheet.spell_slots.set_level(slot_level, maximum, current)
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            return

        save_owner_sheet(ctx, owner_id, sheet)
        label = target_label(member, sheet)
        await command_reply(
            ctx,
            f"{label} spell slots updated: {sheet.spell_slots.format()}.",
        )
        await delete_command(ctx)

    @sheet_slots_group.command(
        name="auto",
        help=command_help(
            "Remplit le max d’emplacements selon classe et niveau (PHB).",
            f"`{PREFIX}sheet slots auto [@joueur]`",
        ),
    )
    async def sheet_slots_auto(
        ctx: Context, member: discord.Member | None = None
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result

        try:
            table = slots_table_for_class(
                sheet.char_class,
                sheet.level,
                subclass=sheet.subclass,
            )
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            return

        if table is None:
            await command_reply(
                ctx,
                f"No spell slot table for **{sheet.char_class or 'unknown class'}** "
                f"(subclass: {sheet.subclass or '—'}). "
                f"Set class/level first, or use `{PREFIX}sheet slots set`.",
            )
            return

        sheet.spell_slots.apply_table(table, fill=True)
        save_owner_sheet(ctx, owner_id, sheet)
        label = target_label(member, sheet)
        await command_reply(
            ctx,
            f"{label} spell slots set from **{sheet.char_class}** "
            f"level **{sheet.level}**: {sheet.spell_slots.format()}.",
        )
        await delete_command(ctx)

    @sheet_slots_group.command(
        name="clear",
        help=command_help(
            "Efface tout le suivi d’emplacements.",
            f"`{PREFIX}sheet slots clear [@joueur]`",
        ),
    )
    async def sheet_slots_clear(
        ctx: Context, member: discord.Member | None = None
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result
        sheet.spell_slots.clear()
        save_owner_sheet(ctx, owner_id, sheet)
        label = target_label(member, sheet)
        await command_reply(ctx, f"{label}: spell slots cleared.")
        await delete_command(ctx)
