import discord
from discord.ext.commands import Group
from discord.ext.commands.context import Context

from bot.checks import is_admin
from bot.command_helpers import command_reply, delete_command
from bot.help_text import HELP_COLOR, HELP_SHEET_COLOR
from bot.messaging import send_message
from config import PREFIX
from sheets.context import get_sheet_for_owner, parse_mention_and_text, target_label
from sheets.equipment import (
    ITEM_KIND_CUSTOM,
    custom_slug,
    format_item_line,
    is_custom_slug,
    parse_name_and_quantity,
)
from sheets.storage import save_sheet
from srd import fivetools
from srd.embeds import equipment_embed


def _equipment_embed_for_item(item) -> discord.Embed | None:
    if is_custom_slug(item.slug):
        embed = discord.Embed(
            title=f"🎒 {item.name}",
            description="Custom item (not in your 5etools export).",
            color=HELP_COLOR,
        )
        if item.notes:
            embed.add_field(name="📝 Notes", value=item.notes[:1024], inline=False)
        return embed
    return None


async def _lookup_sheet_item(item) -> discord.Embed:
    custom = _equipment_embed_for_item(item)
    if custom is not None:
        return custom

    try:
        entry = await fivetools.get_equipment(slug=item.slug, kind=item.kind)
    except fivetools.Open5eError:
        embed = discord.Embed(
            title=f"🎒 {item.name}",
            description="Saved on sheet (not found in your 5etools export).",
            color=HELP_COLOR,
        )
        return embed
    return equipment_embed(entry)


async def _gear_reply(ctx: Context, message: str) -> None:
    await command_reply(ctx, message)
    await delete_command(ctx)


def register_equipment_commands(sheet_group: Group) -> None:
    @sheet_group.group(
        name="gear",
        aliases=["equipment", "inv", "inventory"],
        invoke_without_command=True,
        fallback="list",
        help="Manage character equipment from your 5etools export.",
    )
    async def sheet_gear_group(ctx: Context, member: discord.Member | None = None) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        _, sheet = result

        label = target_label(member, sheet)
        admin_hint = " [@player]" if is_admin(ctx) else ""

        if not sheet.equipment.items:
            embed = discord.Embed(
                title="🎒 Equipment",
                description=f"{label} carries nothing yet.",
                color=HELP_SHEET_COLOR,
            )
        else:
            equipped = sheet.equipment.equipped_items()
            equipped_text = (
                "\n".join(format_item_line(item) for item in equipped)
                or "—"
            )
            inventory_text = sheet.equipment.format_summary(limit=20, exclude_equipped=True) or "—"
            embed = discord.Embed(
                title=f"🎒 {sheet.name} — Equipment ({len(sheet.equipment.items)})",
                color=HELP_SHEET_COLOR,
            )
            embed.add_field(name="⚔️ Equipped", value=equipped_text, inline=False)
            embed.add_field(name="🎒 Inventory", value=inventory_text, inline=False)

        embed.add_field(
            name="⌨️ Commands",
            value=(
                f"`{PREFIX}sheet gear add{admin_hint} <name> [qty]` — add from export or custom item\n"
                f"`{PREFIX}sheet gear remove{admin_hint} <name> [qty]` — remove item\n"
                f"`{PREFIX}sheet gear equip{admin_hint} <name>` — equip weapon/armor\n"
                f"`{PREFIX}sheet gear unequip{admin_hint} <name>` — unequip\n"
                f"`{PREFIX}sheet gear show{admin_hint} <name>` — item details\n\n"
                f"Qty: `{PREFIX}sheet gear add rope x50` or `{PREFIX}sheet gear add dagger 2`\n"
                f"Look up gear: `{PREFIX}srd weapon|armor|item <name>`"
            ),
            inline=False,
        )
        await send_message(ctx, embed=embed, definition_menu=False)
        await delete_command(ctx)

    @sheet_gear_group.command(
        name="add",
        help=f"Add equipment. Usage: `{PREFIX}sheet gear add [@player] <name> [quantity]`",
    )
    async def sheet_gear_add(ctx: Context, member: discord.Member | None = None, *, name: str = "") -> None:
        if member is None:
            member, name = parse_mention_and_text(ctx, name)
        if not name:
            await _gear_reply(
                ctx,
                f"Missing item name. Usage: `{PREFIX}sheet gear add [@player] <name> [qty]`",
            )
            return

        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result

        cleaned, parsed_qty = parse_name_and_quantity(name)
        quantity = parsed_qty or 1
        if not cleaned:
            await _gear_reply(ctx, "Item name cannot be empty.")
            return

        try:
            entry = await fivetools.search_equipment(query=cleaned)
            sheet.equipment.add_item(
                slug=entry["slug"],
                name=entry["name"],
                kind=entry["kind"],
                quantity=quantity,
            )
            fivetools.register_glossary_item(
                item=entry,
                endpoint={"weapon": "weapons", "armor": "armor", "item": "items"}[entry["kind"]],
            )
            save_sheet(user_id=owner_id, sheet=sheet)
            label = target_label(member, sheet)
            qty_text = f" ×{quantity}" if quantity > 1 else ""
            await _gear_reply(
                ctx,
                f"{label}: added **{entry['name']}**{qty_text} ({entry['kind']}).",
            )
        except fivetools.Open5eNotFoundError:
            slug = custom_slug(cleaned)
            sheet.equipment.add_item(
                slug=slug,
                name=cleaned,
                kind=ITEM_KIND_CUSTOM,
                quantity=quantity,
            )
            save_sheet(user_id=owner_id, sheet=sheet)
            label = target_label(member, sheet)
            qty_text = f" ×{quantity}" if quantity > 1 else ""
            await _gear_reply(
                ctx,
                f"{label}: added custom item **{cleaned}**{qty_text} (not in your 5etools export).",
            )
        except fivetools.Open5eError as exc:
            await _gear_reply(ctx, str(exc))

    @sheet_gear_group.command(
        name="remove",
        aliases=["drop"],
        help=f"Remove equipment. Usage: `{PREFIX}sheet gear remove [@player] <name> [quantity]`",
    )
    async def sheet_gear_remove(ctx: Context, member: discord.Member | None = None, *, name: str = "") -> None:
        if member is None:
            member, name = parse_mention_and_text(ctx, name)
        if not name:
            await _gear_reply(
                ctx,
                f"Missing item name. Usage: `{PREFIX}sheet gear remove [@player] <name> [qty]`",
            )
            return

        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result

        cleaned, quantity = parse_name_and_quantity(name)

        try:
            removed = sheet.equipment.remove_item(cleaned, quantity=quantity)
        except ValueError as exc:
            await _gear_reply(ctx, str(exc))
            return

        if removed is None:
            await _gear_reply(ctx, f"**{cleaned}** is not on this sheet.")
            return

        save_sheet(user_id=owner_id, sheet=sheet)
        label = target_label(member, sheet)
        qty_text = f" ×{removed.quantity}" if removed.quantity > 1 else ""
        await _gear_reply(ctx, f"{label}: removed **{removed.name}**{qty_text}.")

    @sheet_gear_group.command(
        name="equip",
        help=f"Equip an item. Usage: `{PREFIX}sheet gear equip [@player] <name>`",
    )
    async def sheet_gear_equip(ctx: Context, member: discord.Member | None = None, *, name: str = "") -> None:
        if member is None:
            member, name = parse_mention_and_text(ctx, name)
        if not name:
            await _gear_reply(
                ctx,
                f"Missing item name. Usage: `{PREFIX}sheet gear equip [@player] <name>`",
            )
            return

        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result

        try:
            item = sheet.equipment.equip(name.strip())
        except ValueError as exc:
            await _gear_reply(ctx, str(exc))
            return

        save_sheet(user_id=owner_id, sheet=sheet)
        label = target_label(member, sheet)
        kind_label = {"weapon": "weapon", "armor": "armor"}.get(item.kind, "item")
        await _gear_reply(ctx, f"{label}: equipped **{item.name}** ({kind_label}).")

    @sheet_gear_group.command(
        name="unequip",
        help=f"Unequip an item. Usage: `{PREFIX}sheet gear unequip [@player] <name>`",
    )
    async def sheet_gear_unequip(ctx: Context, member: discord.Member | None = None, *, name: str = "") -> None:
        if member is None:
            member, name = parse_mention_and_text(ctx, name)
        if not name:
            await _gear_reply(
                ctx,
                f"Missing item name. Usage: `{PREFIX}sheet gear unequip [@player] <name>`",
            )
            return

        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result

        try:
            item = sheet.equipment.unequip(name.strip())
        except ValueError as exc:
            await _gear_reply(ctx, str(exc))
            return

        save_sheet(user_id=owner_id, sheet=sheet)
        label = target_label(member, sheet)
        await _gear_reply(ctx, f"{label}: unequipped **{item.name}**.")

    @sheet_gear_group.command(
        name="show",
        help=f"Show gear details from your 5etools export. Usage: `{PREFIX}sheet gear show [@player] <name>`",
    )
    async def sheet_gear_show(ctx: Context, member: discord.Member | None = None, *, name: str = "") -> None:
        if member is None:
            member, name = parse_mention_and_text(ctx, name)
        if not name:
            await _gear_reply(
                ctx,
                f"Missing item name. Usage: `{PREFIX}sheet gear show [@player] <name>`",
            )
            return

        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        _, sheet = result

        item = sheet.equipment.find_item(name.strip())
        if item is None:
            try:
                entry = await fivetools.search_equipment(query=name.strip())
            except fivetools.Open5eError as exc:
                await _gear_reply(ctx, str(exc))
                return
            await send_message(ctx, embed=equipment_embed(entry))
            await delete_command(ctx)
            return

        embed = await _lookup_sheet_item(item)
        await send_message(ctx, embed=embed)
        await delete_command(ctx)
