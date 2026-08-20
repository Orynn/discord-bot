import discord
from discord.ext.commands import Group
from discord.ext.commands.context import Context

from bot.checks import is_admin
from bot.command_helpers import command_reply, delete_command
from bot.help_text import HELP_COLOR, HELP_SHEET_COLOR
from bot.messaging import send_message
from config import PREFIX
from sheets.armor import apply_armor_ac, has_ac_gear
from sheets.context import (
    get_sheet_for_owner,
    parse_mention_and_text,
    resolve_guild_id,
    save_owner_sheet,
    target_label,
)
from sheets.containers import (
    DEFAULT_BAG_CAPACITY_LB,
    STORED_BELT,
    STORED_HANDS,
    STORED_LOOSE,
    STORED_WORN,
    parse_put_args,
)
from sheets.ddb_pdf import add_catalog_equipment
from sheets.equipment import (
    ITEM_KIND_CUSTOM,
    custom_slug,
    format_pounds,
    is_custom_slug,
    parse_item_and_weight,
    parse_name_quantity_and_weight,
)
from sheets.stashes import (
    get_stash,
    list_stashes,
    parse_let_args,
    resolve_place_name,
    save_stash,
)
from srd import fivetools
from srd.embeds import equipment_embed, truncate

DISCORD_FIELD_LIMIT = 1024
DISCORD_FIELD_NAME_LIMIT = 256
MAX_EMBED_FIELDS = 25


def _chunk_field_value(text: str, *, limit: int = DISCORD_FIELD_LIMIT) -> list[str]:
    cleaned = (text or "").strip() or "—"
    if len(cleaned) <= limit:
        return [cleaned]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in cleaned.split("\n"):
        line = truncate(line, limit)
        extra = len(line) + (1 if current else 0)
        if current and current_len + extra > limit:
            chunks.append("\n".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += extra
    if current:
        chunks.append("\n".join(current))
    return chunks or ["—"]


def _add_embed_fields(
    embed: discord.Embed,
    fields: list[tuple[str, str]],
    *,
    reserve: int = 0,
) -> None:
    remaining = max(0, MAX_EMBED_FIELDS - len(embed.fields) - reserve)
    added = 0
    for name, value in fields:
        chunks = _chunk_field_value(value)
        for index, chunk in enumerate(chunks):
            if added >= remaining:
                return
            label = name if index == 0 else f"{name} (cont.)"
            embed.add_field(
                name=truncate(label, DISCORD_FIELD_NAME_LIMIT),
                value=chunk,
                inline=False,
            )
            added += 1


def _equipment_embed_for_item(item) -> discord.Embed | None:
    if is_custom_slug(item.slug):
        embed = discord.Embed(
            title=f"🎒 {item.name}",
            description="Custom item (not in your 5etools export).",
            color=HELP_COLOR,
        )
        if item.notes:
            embed.add_field(name="📝 Notes", value=item.notes[:1024], inline=False)
        if item.weight_lb is not None:
            embed.add_field(name="⚖️ Weight", value=format_pounds(item.weight_lb), inline=True)
        if item.capacity_lb is not None and item.capacity_lb > 0:
            embed.add_field(name="🎒 Capacity", value=format_pounds(item.capacity_lb), inline=True)
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


def _persist_gear(ctx: Context, owner_id: int, sheet, *, ac_gear_before: bool) -> None:
    apply_armor_ac(sheet, force=ac_gear_before and not has_ac_gear(sheet))
    save_owner_sheet(ctx, owner_id, sheet)


def _ac_note(sheet) -> str:
    return f" AC **{sheet.ac}**."


async def _reply_stash_list(
    ctx: Context,
    *,
    guild_id: int,
    place: str | None,
    list_all: bool,
) -> None:
    if list_all or not place:
        stashes = list_stashes(guild_id=guild_id)
        if not stashes:
            await _gear_reply(ctx, "No gear has been left anywhere yet.")
            return
        embed = discord.Embed(title="📍 Left gear", color=HELP_SHEET_COLOR)
        lines = [
            f"**{stash.place_name}** — {stash.item_count()} item{'s' if stash.item_count() != 1 else ''}"
            for stash in stashes
        ]
        embed.description = "\n".join(lines)
        embed.set_footer(text=f"{PREFIX}sheet gear let at <place> · {PREFIX}sheet gear take <item> at <place>")
        await send_message(ctx, embed=embed, definition_menu=False)
        await delete_command(ctx)
        return

    stash = get_stash(guild_id=guild_id, place=place)
    embed = discord.Embed(
        title=f"📍 Left at {stash.place_name}",
        color=HELP_SHEET_COLOR,
        description="\n".join(stash.format_lines()),
    )
    embed.set_footer(text=f"{PREFIX}sheet gear take <item> at {stash.place_name}")
    await send_message(ctx, embed=embed, definition_menu=False)
    await delete_command(ctx)


def _load_note(sheet) -> str:
    line = sheet.format_load().split("\n", 1)[0]
    if sheet.is_overloaded():
        return f" {line}"
    return f" · {line}"


def _location_note(sheet, name: str, *, item=None) -> str:
    item = item or sheet.equipment.find_item(name)
    if item is None or not item.stored_in:
        return ""
    location = item.stored_in
    if location == STORED_HANDS:
        return " in hand"
    if location == STORED_BELT:
        return " on belt"
    if location == STORED_WORN:
        return " worn"
    if location == STORED_LOOSE:
        return " — ⚠️ not in a bag, hand, or belt"
    container = sheet.equipment.find_item(location)
    if container is not None:
        return f" in **{container.name}**"
    return f" in **{location}**"


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
        owner_id, sheet = result

        label = target_label(member, sheet)
        admin_hint = " [@player]" if is_admin(ctx) else ""

        ac_before = has_ac_gear(sheet)
        sheet.equipment.stow_unassigned()
        _persist_gear(ctx, owner_id, sheet, ac_gear_before=ac_before)
        if not sheet.equipment.items:
            embed = discord.Embed(
                title="🎒 Equipment",
                description=f"{label} carries nothing yet.",
                color=HELP_SHEET_COLOR,
            )
        else:
            embed = discord.Embed(
                title=f"🎒 {sheet.name} — Equipment ({len(sheet.equipment.items)})",
                color=HELP_SHEET_COLOR,
            )
            _add_embed_fields(
                embed,
                sheet.equipment.format_storage_fields(
                    coin_lb=sheet.currency.weight_lb(),
                    coin_text=sheet.currency.format(),
                ),
                reserve=2,
            )

        _add_embed_fields(
            embed,
            [
                ("⚖️ Load", sheet.format_load()),
                (
                    "⌨️ Commands",
                    (
                        f"`{PREFIX}sheet gear add|remove|put|hold|belt|stow{admin_hint}`\n"
                        f"`{PREFIX}sheet gear let|take|equip|unequip|show|weight|bag{admin_hint}`\n"
                        f"Store gear in a bag, on a belt, or in a hand · "
                        f"`{PREFIX}sheet gear put all backpack`"
                    ),
                ),
            ],
        )
        await send_message(ctx, embed=embed, definition_menu=False)
        await delete_command(ctx)

    @sheet_gear_group.command(
        name="add",
        help=f"Add equipment. Usage: `{PREFIX}sheet gear add [@player] <name> [qty] [2kg]`",
    )
    async def sheet_gear_add(ctx: Context, member: discord.Member | None = None, *, name: str = "") -> None:
        if member is None:
            member, name = parse_mention_and_text(ctx, name)
        if not name:
            await _gear_reply(
                ctx,
                f"Missing item name. Usage: `{PREFIX}sheet gear add [@player] <name> [qty] [2kg]`",
            )
            return

        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result
        ac_before = has_ac_gear(sheet)

        cleaned, parsed_qty, parsed_weight = parse_name_quantity_and_weight(name)
        quantity = parsed_qty or 1
        if not cleaned:
            await _gear_reply(ctx, "Item name cannot be empty.")
            return

        try:
            entry = await fivetools.search_equipment(query=cleaned)
            _matched, _custom, names = await add_catalog_equipment(sheet, entry, quantity)
            _persist_gear(ctx, owner_id, sheet, ac_gear_before=ac_before)
            label = target_label(member, sheet)
            if len(names) > 1:
                listed = ", ".join(f"**{name}**" for name in names)
                await _gear_reply(
                    ctx,
                    f"{label}: unpacked **{entry['name']}** into {listed}.{_load_note(sheet)}",
                )
                return
            added = sheet.equipment.find_item(names[0]) if names else None
            qty_text = f" ×{quantity}" if quantity > 1 else ""
            await _gear_reply(
                ctx,
                f"{label}: added **{entry['name']}**{qty_text} ({entry['kind']})"
                f"{_location_note(sheet, entry['name'], item=added)}.{_load_note(sheet)}",
            )
        except fivetools.Open5eNotFoundError:
            slug = custom_slug(cleaned)
            added = sheet.equipment.add_item(
                slug=slug,
                name=cleaned,
                kind=ITEM_KIND_CUSTOM,
                quantity=quantity,
                weight_lb=parsed_weight,
            )
            _persist_gear(ctx, owner_id, sheet, ac_gear_before=ac_before)
            label = target_label(member, sheet)
            qty_text = f" ×{quantity}" if quantity > 1 else ""
            weight_text = (
                f" · {format_pounds(parsed_weight)}"
                if parsed_weight is not None
                else f" · no weight (`{PREFIX}sheet gear weight {cleaned} <kg>`)"
            )
            await _gear_reply(
                ctx,
                f"{label}: added custom item **{cleaned}**{qty_text} (not in your 5etools export)"
                f"{weight_text}{_location_note(sheet, cleaned, item=added)}.{_load_note(sheet)}",
            )
        except fivetools.Open5eError as exc:
            await _gear_reply(ctx, str(exc))

    @sheet_gear_group.command(
        name="put",
        aliases=["store"],
        help=f"Store item(s) in a bag, pouch, or on a belt. Usage: `{PREFIX}sheet gear put [@player] <item|all> [in] <bag|belt>`",
    )
    async def sheet_gear_put(ctx: Context, member: discord.Member | None = None, *, name: str = "") -> None:
        if member is None:
            member, name = parse_mention_and_text(ctx, name)
        item_name, container_name = parse_put_args(name)
        if not item_name or not container_name:
            await _gear_reply(
                ctx,
                f"Missing item or destination. Usage: `{PREFIX}sheet gear put [@player] <item|all> in <bag|belt>`",
            )
            return

        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result
        ac_before = has_ac_gear(sheet)
        sheet.equipment.stow_unassigned()

        try:
            item = sheet.equipment.put_in(item_name, container_name)
        except ValueError as exc:
            await _gear_reply(ctx, str(exc))
            return

        _persist_gear(ctx, owner_id, sheet, ac_gear_before=ac_before)
        label = target_label(member, sheet)
        if item_name.strip().casefold() in {"all", "*", "tout"}:
            await _gear_reply(
                ctx,
                f"{label}: stored gear{_location_note(sheet, item.name, item=item)}.{_load_note(sheet)}",
            )
            return
        qty_text = f" ×{item.quantity}" if item.quantity > 1 else ""
        await _gear_reply(
            ctx,
            f"{label}: stored **{item.name}**{qty_text}{_location_note(sheet, item.name, item=item)}.{_load_note(sheet)}",
        )

    @sheet_gear_group.command(
        name="hold",
        help=f"Hold an item in a hand. Usage: `{PREFIX}sheet gear hold [@player] <name>`",
    )
    async def sheet_gear_hold(ctx: Context, member: discord.Member | None = None, *, name: str = "") -> None:
        if member is None:
            member, name = parse_mention_and_text(ctx, name)
        if not name:
            await _gear_reply(
                ctx,
                f"Missing item name. Usage: `{PREFIX}sheet gear hold [@player] <name>`",
            )
            return

        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result
        ac_before = has_ac_gear(sheet)
        sheet.equipment.stow_unassigned()

        try:
            item = sheet.equipment.hold(name.strip())
        except ValueError as exc:
            await _gear_reply(ctx, str(exc))
            return

        _persist_gear(ctx, owner_id, sheet, ac_gear_before=ac_before)
        label = target_label(member, sheet)
        ac_text = _ac_note(sheet) if sheet.equipment.is_shield(item) else ""
        await _gear_reply(
            ctx,
            f"{label}: holding **{item.name}**{_location_note(sheet, item.name)}.{ac_text}{_load_note(sheet)}",
        )

    @sheet_gear_group.command(
        name="belt",
        aliases=["ceinture"],
        help=f"Hang an item on your belt. Usage: `{PREFIX}sheet gear belt [@player] <name>`",
    )
    async def sheet_gear_belt(ctx: Context, member: discord.Member | None = None, *, name: str = "") -> None:
        if member is None:
            member, name = parse_mention_and_text(ctx, name)
        if not name:
            await _gear_reply(
                ctx,
                f"Missing item name. Usage: `{PREFIX}sheet gear belt [@player] <name>`",
            )
            return

        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result
        ac_before = has_ac_gear(sheet)
        sheet.equipment.stow_unassigned()

        try:
            item = sheet.equipment.hang_on_belt(name.strip())
        except ValueError as exc:
            await _gear_reply(ctx, str(exc))
            return

        _persist_gear(ctx, owner_id, sheet, ac_gear_before=ac_before)
        label = target_label(member, sheet)
        await _gear_reply(
            ctx,
            f"{label}: hung **{item.name}**{_location_note(sheet, item.name)}.{_load_note(sheet)}",
        )

    @sheet_gear_group.command(
        name="stow",
        aliases=["pack"],
        help=f"Pack loose items into bags. Usage: `{PREFIX}sheet gear stow [@player]`",
    )
    async def sheet_gear_stow(ctx: Context, member: discord.Member | None = None) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result
        ac_before = has_ac_gear(sheet)
        sheet.equipment.stow_unassigned()
        worn = sheet.equipment.wear_loose_armor()
        added_bag = sheet.equipment.ensure_pack_bag()
        moved = 0 if added_bag else sheet.equipment.stow_loose()
        _persist_gear(ctx, owner_id, sheet, ac_gear_before=ac_before)
        label = target_label(member, sheet)
        notes: list[str] = []
        if worn is not None:
            notes.append(f"equipped **{worn.name}**")
        if added_bag is not None:
            notes.append("added a **Backpack** and packed loose gear")
        elif moved:
            notes.append("packed loose gear into bags")
        leftover = any(item.stored_in == STORED_LOOSE for item in sheet.equipment.items)
        if notes:
            extra = "; leftover gear stays loose" if leftover else ""
            ac_text = _ac_note(sheet) if worn is not None else ""
            await _gear_reply(ctx, f"{label}: {'; '.join(notes)}.{extra}{ac_text}{_load_note(sheet)}")
            return
        if leftover:
            await _gear_reply(
                ctx,
                f"{label}: bags are full; leftover gear stays loose.{_load_note(sheet)}",
            )
            return
        await _gear_reply(ctx, f"{label}: nothing loose to pack.{_load_note(sheet)}")

    @sheet_gear_group.command(
        name="let",
        aliases=["leave", "laisser"],
        help=(
            f"Leave gear at a place. Usage: `{PREFIX}sheet gear let [@player] <item> [qty] "
            f"[at <place>] [-- note]`"
        ),
    )
    async def sheet_gear_let(ctx: Context, member: discord.Member | None = None, *, name: str = "") -> None:
        if member is None:
            member, name = parse_mention_and_text(ctx, name)
        args = parse_let_args(name)
        guild_id = resolve_guild_id(ctx)
        if guild_id is None:
            await _gear_reply(ctx, "This command can only be used in a server.")
            return

        place = resolve_place_name(args.place, ctx.channel)
        if args.list_only or not args.item:
            await _reply_stash_list(
                ctx,
                guild_id=guild_id,
                place=None if args.all_places else place,
                list_all=args.all_places or (not args.item and args.place is None and place is None),
            )
            return
        if not place:
            await _gear_reply(
                ctx,
                (
                    "Say where, or run this in a lieux thread. "
                    f"Usage: `{PREFIX}sheet gear let <item> [qty] at <place> [-- note]`"
                ),
            )
            return

        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result
        ac_before = has_ac_gear(sheet)

        try:
            detached = sheet.equipment.detach_for_stash(args.item, quantity=args.quantity)
        except ValueError as exc:
            await _gear_reply(ctx, str(exc))
            return
        if not detached:
            await _gear_reply(ctx, f"**{args.item}** is not on this sheet.")
            return

        stash = get_stash(guild_id=guild_id, place=place)
        if not stash.entries:
            stash.place_name = place
        stash.add_entries(
            detached,
            note=args.note,
            left_by=sheet.name,
            left_by_user_id=owner_id,
        )
        save_stash(stash)
        _persist_gear(ctx, owner_id, sheet, ac_gear_before=ac_before)

        label = target_label(member, sheet)
        left = detached[0]
        qty_text = f" ×{left.quantity}" if left.quantity > 1 else ""
        extra = f" (and {len(detached) - 1} inside)" if len(detached) > 1 else ""
        note_text = f" — {args.note}" if args.note else ""
        await _gear_reply(
            ctx,
            (
                f"{label}: left **{left.name}**{qty_text}{extra} at **{stash.place_name}**"
                f"{note_text}.{_load_note(sheet)}"
            ),
        )

    @sheet_gear_group.command(
        name="take",
        aliases=["pick", "prendre"],
        help=(
            f"Pick up gear left at a place. Usage: `{PREFIX}sheet gear take [@player] <item> [qty] "
            f"[at <place>]`"
        ),
    )
    async def sheet_gear_take(ctx: Context, member: discord.Member | None = None, *, name: str = "") -> None:
        if member is None:
            member, name = parse_mention_and_text(ctx, name)
        args = parse_let_args(name)
        guild_id = resolve_guild_id(ctx)
        if guild_id is None:
            await _gear_reply(ctx, "This command can only be used in a server.")
            return

        place = resolve_place_name(args.place, ctx.channel)
        if not args.item or args.list_only:
            await _reply_stash_list(ctx, guild_id=guild_id, place=place, list_all=place is None)
            return
        if not place:
            await _gear_reply(
                ctx,
                (
                    "Say where, or run this in a lieux thread. "
                    f"Usage: `{PREFIX}sheet gear take <item> [qty] at <place>`"
                ),
            )
            return

        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result

        stash = get_stash(guild_id=guild_id, place=place)
        try:
            taken = stash.take_items(args.item, quantity=args.quantity)
        except ValueError as exc:
            await _gear_reply(ctx, str(exc))
            return
        if not taken:
            await _gear_reply(ctx, f"Nothing matching **{args.item}** at **{stash.place_name}**.")
            return

        sheet.equipment.restore_stash_items(taken)
        save_stash(stash)
        _persist_gear(ctx, owner_id, sheet, ac_gear_before=has_ac_gear(sheet))

        label = target_label(member, sheet)
        picked = taken[0]
        qty_text = f" ×{picked.quantity}" if picked.quantity > 1 else ""
        extra = f" (and {len(taken) - 1} inside)" if len(taken) > 1 else ""
        await _gear_reply(
            ctx,
            (
                f"{label}: took **{picked.name}**{qty_text}{extra} from **{stash.place_name}**."
                f"{_load_note(sheet)}"
            ),
        )

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
        ac_before = has_ac_gear(sheet)

        cleaned, quantity, _ = parse_name_quantity_and_weight(name)

        try:
            removed = sheet.equipment.remove_item(cleaned, quantity=quantity)
        except ValueError as exc:
            await _gear_reply(ctx, str(exc))
            return

        if removed is None:
            await _gear_reply(ctx, f"**{cleaned}** is not on this sheet.")
            return

        _persist_gear(ctx, owner_id, sheet, ac_gear_before=ac_before)
        label = target_label(member, sheet)
        qty_text = f" ×{removed.quantity}" if removed.quantity > 1 else ""
        await _gear_reply(ctx, f"{label}: removed **{removed.name}**{qty_text}.{_load_note(sheet)}")

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
        ac_before = has_ac_gear(sheet)

        try:
            item = sheet.equipment.equip(name.strip())
        except ValueError as exc:
            await _gear_reply(ctx, str(exc))
            return

        _persist_gear(ctx, owner_id, sheet, ac_gear_before=ac_before)
        label = target_label(member, sheet)
        kind_label = {"weapon": "weapon", "armor": "armor"}.get(item.kind, "item")
        ac_text = ""
        if item.kind == "armor" or sheet.equipment.is_shield(item):
            ac_text = _ac_note(sheet)
        await _gear_reply(ctx, f"{label}: equipped **{item.name}** ({kind_label}).{ac_text}")

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
        ac_before = has_ac_gear(sheet)

        try:
            item = sheet.equipment.unequip(name.strip())
        except ValueError as exc:
            await _gear_reply(ctx, str(exc))
            return

        _persist_gear(ctx, owner_id, sheet, ac_gear_before=ac_before)
        label = target_label(member, sheet)
        ac_text = ""
        if item.kind == "armor" or sheet.equipment.is_shield(item):
            ac_text = _ac_note(sheet)
        await _gear_reply(ctx, f"{label}: unequipped **{item.name}**.{ac_text}")

    @sheet_gear_group.command(
        name="weight",
        help=f"Set an item's weight. Usage: `{PREFIX}sheet gear weight [@player] <name> <kg>`",
    )
    async def sheet_gear_weight(ctx: Context, member: discord.Member | None = None, *, name: str = "") -> None:
        if member is None:
            member, name = parse_mention_and_text(ctx, name)
        item_name, weight = parse_item_and_weight(name)
        if not item_name or weight is None:
            await _gear_reply(
                ctx,
                f"Missing name or weight. Usage: `{PREFIX}sheet gear weight [@player] <name> <kg>`",
            )
            return

        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result

        item = sheet.equipment.find_item(item_name)
        if item is None:
            await _gear_reply(ctx, f"**{item_name}** is not on this sheet.")
            return

        item.weight_lb = weight
        save_owner_sheet(ctx, owner_id, sheet)
        label = target_label(member, sheet)
        await _gear_reply(
            ctx,
            f"{label}: **{item.name}** weighs {format_pounds(weight)} each.{_load_note(sheet)}",
        )

    @sheet_gear_group.command(
        name="bag",
        aliases=["sac", "container"],
        help=(
            f"Mark a custom item as a bag. Usage: `{PREFIX}sheet gear bag [@player] <name> [kg]` "
            f"(default {format_pounds(DEFAULT_BAG_CAPACITY_LB)} · `0` to unmark)"
        ),
    )
    async def sheet_gear_bag(ctx: Context, member: discord.Member | None = None, *, name: str = "") -> None:
        if member is None:
            member, name = parse_mention_and_text(ctx, name)
        item_name, capacity = parse_item_and_weight(name)
        if not item_name:
            await _gear_reply(
                ctx,
                f"Missing item name. Usage: `{PREFIX}sheet gear bag [@player] <name> [kg]`",
            )
            return

        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result

        try:
            item = sheet.equipment.mark_as_bag(item_name, capacity)
        except ValueError as exc:
            await _gear_reply(ctx, str(exc))
            return

        save_owner_sheet(ctx, owner_id, sheet)
        label = target_label(member, sheet)
        if item.capacity_lb is None:
            await _gear_reply(ctx, f"{label}: **{item.name}** is no longer a bag.{_load_note(sheet)}")
            return
        await _gear_reply(
            ctx,
            f"{label}: **{item.name}** is a bag ({format_pounds(item.capacity_lb)})."
            f"{_location_note(sheet, item.name)}.{_load_note(sheet)}",
        )

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
