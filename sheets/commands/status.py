import random

import discord
from discord.ext.commands import Group
from discord.ext.commands.context import Context

from bot.command_helpers import command_reply, delete_command
from config import PREFIX
from sheets.context import get_sheet_for_owner, target_label
from sheets.data import ability_modifier
from sheets.storage import save_sheet


def register_status_commands(sheet_group: Group) -> None:
    @sheet_group.command(
        name="condition",
        help=f"Toggle a condition. `{PREFIX}sheet condition [@player] poisoned`",
    )
    async def sheet_condition(
        ctx: Context,
        member: discord.Member | None = None,
        *,
        condition: str = "",
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result
        if not condition:
            await command_reply(ctx, f"Usage: `{PREFIX}sheet condition [@player] <condition>`")
            return
        added = sheet.toggle_condition(condition)
        save_sheet(user_id=owner_id, sheet=sheet)
        status = "added" if added else "removed"
        await command_reply(ctx, f"**{sheet.name}**: condition **{condition.lower()}** {status}.")
        await delete_command(ctx)

    @sheet_group.command(
        name="inspire",
        help=f"Toggle heroic inspiration. `{PREFIX}sheet inspire [@player]`",
    )
    async def sheet_inspire(ctx: Context, member: discord.Member | None = None) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result
        sheet.inspired = not sheet.inspired
        save_sheet(user_id=owner_id, sheet=sheet)
        state = "has" if sheet.inspired else "no longer has"
        await command_reply(ctx, f"**{sheet.name}** {state} **Heroic Inspiration**.")
        await delete_command(ctx)

    @sheet_group.command(
        name="deathsave",
        help=f"Record a death save. `{PREFIX}sheet deathsave [@player] success|failure`",
    )
    async def sheet_deathsave(
        ctx: Context,
        member: discord.Member | None = None,
        outcome: str = "",
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result
        key = outcome.lower()
        if key not in {"success", "failure", "fail"}:
            await command_reply(ctx, f"Usage: `{PREFIX}sheet deathsave [@player] success|failure`")
            return
        if key.startswith("success"):
            sheet.death_save_successes += 1
        else:
            sheet.death_save_failures += 1
        save_sheet(user_id=owner_id, sheet=sheet)
        await command_reply(
            ctx,
            f"**{sheet.name}** death saves: "
            f"**{sheet.death_save_successes}** successes / "
            f"**{sheet.death_save_failures}** failures.",
        )
        await delete_command(ctx)

    @sheet_group.group(
        name="rest",
        invoke_without_command=True,
        fallback="help",
        help="Take a short or long rest.",
    )
    async def sheet_rest_group(ctx: Context) -> None:
        await command_reply(
            ctx,
            f"`{PREFIX}sheet rest short [@player] [hit dice]` — short rest\n"
            f"`{PREFIX}sheet rest long [@player]` — long rest",
        )
        await delete_command(ctx)

    @sheet_rest_group.command(
        name="long",
        help=f"Long rest. `{PREFIX}sheet rest long [@player]`",
    )
    async def sheet_rest_long(ctx: Context, member: discord.Member | None = None) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result
        sheet.long_rest()
        save_sheet(user_id=owner_id, sheet=sheet)
        slots_note = ""
        if sheet.spell_slots.has_slots():
            slots_note = f", spell slots {sheet.spell_slots.format()}"
        await command_reply(
            ctx,
            f"**{sheet.name}** finished a long rest — "
            f"HP **{sheet.hp_current}/{sheet.hp_max}**, "
            f"hit dice **{sheet.hit_dice_remaining}**"
            f"{slots_note}.",
        )
        await delete_command(ctx)

    @sheet_rest_group.command(
        name="short",
        help=f"Short rest. `{PREFIX}sheet rest short [@player] [dice]`",
    )
    async def sheet_rest_short(
        ctx: Context,
        member: discord.Member | None = None,
        dice_spent: int = 1,
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result
        if dice_spent < 1:
            await command_reply(ctx, "Must spend at least 1 hit die.")
            return
        if sheet.hit_dice_remaining < dice_spent:
            await command_reply(ctx, f"Not enough hit dice ({sheet.hit_dice_remaining} remaining).")
            return
        con_mod = ability_modifier(sheet.abilities["con"])
        die_sides = sheet.get_hit_die_sides()
        healing = sum(random.randint(1, die_sides) + con_mod for _ in range(dice_spent))
        healing = max(0, healing)
        sheet.short_rest(dice_spent=dice_spent, healing=healing)
        save_sheet(user_id=owner_id, sheet=sheet)
        slots_note = ""
        if sheet.char_class.lower().startswith("warlock") and sheet.spell_slots.has_slots():
            slots_note = f", pact slots {sheet.spell_slots.format()}"
        await command_reply(
            ctx,
            f"**{sheet.name}** short rest — recovered **{healing}** HP "
            f"({sheet.hp_current}/{sheet.hp_max}), "
            f"hit dice **{sheet.hit_dice_remaining}** left"
            f"{slots_note}.",
        )
        await delete_command(ctx)
