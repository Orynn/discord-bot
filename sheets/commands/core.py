import discord
from discord.ext.commands import Group
from discord.ext.commands.context import Context

from bot.command_helpers import command_reply, delete_command
from bot.help_text import command_help
from bot.messaging import send_message
from combat.engine import apply_hp_to_live_combat
from combat.scope import scope_id_for_channel
from config import PREFIX
from sheets.context import (
    get_sheet_for_owner,
    parse_mention_and_text,
    resolve_guild_id,
    resolve_owner,
    save_owner_sheet,
    target_label,
)
from sheets.data import CharacterSheet
from sheets.embeds import build_sheet_embed, sheet_info_embeds
from sheets.handlers import apply_hp
from sheets.portrait import (
    CLEAR_WORDS,
    cache_portrait_from_url,
    clear_portrait_file,
    parse_image_url,
    portrait_path,
    save_portrait_attachment,
)
from sheets.storage import delete_sheet, get_sheet, set_character_name
from srd import fivetools


def register_core_commands(sheet_group: Group) -> None:
    @sheet_group.command(
        name="create",
        help=command_help(
            "Crée une fiche de personnage.",
            f"`{PREFIX}sheet create [@joueur] <nom>`",
        ),
    )
    async def sheet_create(
        ctx: Context,
        member: discord.Member | None = None,
        *,
        name: str,
    ) -> None:
        name = name.strip()
        if not name:
            await command_reply(
                ctx,
                f"Name cannot be empty. Usage: `{PREFIX}sheet create [@player] <name>`",
            )
            return

        owner_id = await resolve_owner(ctx, member)
        if owner_id is None:
            return

        guild_id = resolve_guild_id(ctx)
        if guild_id is None:
            await command_reply(ctx, "Cette commande marche seulement sur le serveur.")
            return

        if get_sheet(user_id=owner_id, guild_id=guild_id) is not None:
            target = member.display_name if member else "You"
            await command_reply(
                ctx,
                f"{target} already have a character sheet. Use `{PREFIX}sheet delete` first.",
            )
            return

        sheet = CharacterSheet(name=name)
        save_owner_sheet(ctx, owner_id, sheet)
        set_character_name(user_id=owner_id, guild_id=guild_id, name=name)
        label = target_label(member, sheet)
        await command_reply(
            ctx,
            (
                f"Character sheet created for {label}.\n"
                f"Use `{PREFIX}sheet set <field> <value>` to fill in details, "
                f"then `{PREFIX}sheet show` to view it."
            ),
        )
        await delete_command(ctx)

    @sheet_group.command(
        name="show",
        help=command_help(
            "Affiche la fiche de personnage.",
            f"`{PREFIX}sheet show [@joueur]`",
        ),
    )
    async def sheet_show(ctx: Context, member: discord.Member | None = None) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result
        sheet.equipment.stow_unassigned()
        save_owner_sheet(ctx, owner_id, sheet)

        guild_id = resolve_guild_id(ctx)
        portrait = (
            portrait_path(guild_id=guild_id, user_id=owner_id)
            if guild_id is not None
            else None
        )
        filename = f"portrait{portrait.suffix}" if portrait is not None else None
        embed = build_sheet_embed(sheet=sheet, portrait_filename=filename)
        if portrait is not None and filename is not None:
            await send_message(
                ctx,
                embed=embed,
                file=discord.File(portrait, filename=filename),
            )
        else:
            await send_message(ctx, embed=embed)
        await delete_command(ctx)

    @sheet_group.command(
        name="set",
        help=command_help(
            "Modifie un champ de la fiche.",
            f"`{PREFIX}sheet set [@joueur] <champ> <valeur>`",
            "Champs : name, species, char_class, subclass, level, background, ac, speed, notes, str, dex, con, int, wis, cha",
        ),
    )
    async def sheet_set(
        ctx: Context,
        member: discord.Member | None = None,
        field_name: str = "",
        *,
        value: str,
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result

        if not field_name:
            await command_reply(
                ctx,
                f"Missing field name. Usage: `{PREFIX}sheet set [@player] <field> <value>`",
            )
            return

        field_name = field_name.lower().replace("class", "char_class")
        try:
            sheet.set_field(field_name=field_name, value=value)
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            return

        save_owner_sheet(ctx, owner_id, sheet)
        guild_id = resolve_guild_id(ctx)
        if field_name == "name" and guild_id is not None:
            set_character_name(user_id=owner_id, guild_id=guild_id, name=sheet.name)

        label = target_label(member, sheet)
        await command_reply(
            ctx, f"{label}: **{field_name}** set to **{value.strip()}**."
        )
        await delete_command(ctx)

    @sheet_group.command(
        name="image",
        aliases=("portrait", "avatar"),
        help=command_help(
            "Définit le portrait du personnage.",
            f"`{PREFIX}sheet image [@joueur]`",
            "Joins une image, ou colle une URL · `clear` pour retirer",
        ),
    )
    async def sheet_image(
        ctx: Context,
        member: discord.Member | None = None,
        *,
        args: str = "",
        file: discord.Attachment | None = None,
    ) -> None:
        if member is None:
            member, args = parse_mention_and_text(ctx, args)
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result
        guild_id = resolve_guild_id(ctx)
        if guild_id is None:
            await command_reply(ctx, "Cette commande marche seulement sur le serveur.")
            return

        attachment = file
        if attachment is None and ctx.message is not None and ctx.message.attachments:
            attachment = ctx.message.attachments[0]

        cleaned = args.strip()
        label = target_label(member, sheet)
        if cleaned.casefold() in CLEAR_WORDS:
            sheet.image_url = ""
            clear_portrait_file(guild_id=guild_id, user_id=owner_id)
            save_owner_sheet(ctx, owner_id, sheet)
            await command_reply(ctx, f"{label}: portrait removed.")
            await delete_command(ctx)
            return

        if attachment is not None:
            try:
                await save_portrait_attachment(
                    attachment, guild_id=guild_id, user_id=owner_id
                )
            except ValueError as exc:
                await command_reply(ctx, str(exc))
                return
            sheet.image_url = ""
            save_owner_sheet(ctx, owner_id, sheet)
            await command_reply(
                ctx, f"{label}: portrait updated. `{PREFIX}sheet show` to see it."
            )
            await delete_command(ctx)
            return

        if not cleaned:
            await command_reply(
                ctx,
                (
                    f"Attach a picture or pass a URL.\n"
                    f"`{PREFIX}sheet image` + image\n"
                    f"`{PREFIX}sheet image https://…`\n"
                    f"`{PREFIX}sheet image clear`"
                ),
            )
            return

        try:
            sheet.image_url = parse_image_url(cleaned)
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            return
        cached = cache_portrait_from_url(
            guild_id=guild_id, user_id=owner_id, url=sheet.image_url
        )
        save_owner_sheet(ctx, owner_id, sheet)
        token_note = (
            ""
            if cached is not None
            else " Token uses initials until the image can be downloaded."
        )
        await command_reply(
            ctx,
            f"{label}: portrait URL set. `{PREFIX}sheet show` to see it.{token_note}",
        )
        await delete_command(ctx)

    @sheet_group.command(
        name="hp",
        help=command_help(
            "Fixe les points de vie.",
            f"`{PREFIX}sheet hp [@joueur] <actuel> [max]`",
        ),
    )
    async def sheet_hp(
        ctx: Context,
        member: discord.Member | None = None,
        current: int | None = None,
        maximum: int | None = None,
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result

        if current is None:
            await command_reply(
                ctx,
                f"Missing HP value. Usage: `{PREFIX}sheet hp [@player] <current> [max]`",
            )
            return

        try:
            apply_hp(sheet, current, maximum)
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            return

        save_owner_sheet(ctx, owner_id, sheet)
        label = target_label(member, sheet)
        combat_note = ""
        if ctx.guild is not None:
            scope_id = scope_id_for_channel(guild=ctx.guild, channel=ctx.channel)
            if scope_id is not None:
                fighter = apply_hp_to_live_combat(
                    guild_id=ctx.guild.id,
                    scope_id=scope_id,
                    user_id=owner_id,
                    hp=sheet.hp_current,
                    max_hp=sheet.hp_max,
                )
                if fighter is not None and sheet.hp_current > 0:
                    combat_note = f" **{fighter}** is up in combat."
        await command_reply(
            ctx,
            f"{label}: HP set to **{sheet.hp_current}/{sheet.hp_max}**.{combat_note}",
        )
        await delete_command(ctx)

    @sheet_group.command(
        name="info",
        help=command_help(
            "Infos 5etools pour l’espèce, la classe et l’historique.",
            f"`{PREFIX}sheet info [@joueur]`",
        ),
    )
    async def sheet_info(ctx: Context, member: discord.Member | None = None) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        _, sheet = result

        if not sheet.species and not sheet.char_class and not sheet.background:
            await command_reply(
                ctx,
                (
                    f"No species, class or background set on this sheet.\n"
                    f"Use `{PREFIX}sheet set species/class/background <value>` first."
                ),
            )
            return

        species_data = None
        class_data = None
        background_data = None
        subclass_data = None
        missing: list[str] = []

        if sheet.species:
            try:
                species_data = await fivetools.search_species(query=sheet.species)
            except fivetools.Open5eError:
                missing.append(f"Species **{sheet.species}**")

        if sheet.char_class:
            try:
                class_data = await fivetools.search_class(query=sheet.char_class)
                if sheet.subclass and class_data:
                    subclass_data = fivetools.find_subclass(
                        char_class=class_data, query=sheet.subclass
                    )
            except fivetools.Open5eError:
                missing.append(f"Class **{sheet.char_class}**")

        if sheet.background:
            try:
                background_data = await fivetools.search_background(
                    query=sheet.background
                )
            except fivetools.Open5eError:
                missing.append(f"Background **{sheet.background}**")

        if not species_data and not class_data and not background_data:
            await command_reply(
                ctx,
                "Nothing from this sheet was found in your 5etools export.\n"
                + ("\n".join(missing) if missing else "Check your export on 5e.tools."),
            )
            return

        embeds = sheet_info_embeds(
            sheet_name=sheet.name,
            species=species_data,
            char_class=class_data,
            background=background_data,
            subclass=subclass_data,
            missing=missing,
        )
        await send_message(ctx, embeds=embeds)
        await delete_command(ctx)

    @sheet_group.command(
        name="delete",
        help=command_help(
            "Supprime la fiche de personnage.",
            f"`{PREFIX}sheet delete [@joueur]`",
        ),
    )
    async def sheet_delete(ctx: Context, member: discord.Member | None = None) -> None:
        owner_id = await resolve_owner(ctx, member)
        if owner_id is None:
            return

        guild_id = resolve_guild_id(ctx)
        if guild_id is None:
            await command_reply(ctx, "Cette commande marche seulement sur le serveur.")
            return

        sheet = get_sheet(user_id=owner_id, guild_id=guild_id)
        if not delete_sheet(user_id=owner_id, guild_id=guild_id):
            target = member.display_name if member else "You"
            await command_reply(ctx, f"{target} have no character sheet.")
            return

        label = target_label(member, sheet) if sheet else "Character sheet"
        await command_reply(ctx, f"{label} deleted.")
        await delete_command(ctx)
