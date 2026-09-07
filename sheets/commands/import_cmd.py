import discord
from discord.ext.commands import Group
from discord.ext.commands.context import Context

from bot.command_helpers import command_reply, defer_if_slash, delete_command
from bot.help_text import command_help
from config import PREFIX
from sheets.context import (
    resolve_guild_id,
    resolve_owner,
    save_owner_sheet,
    target_label,
)
from sheets.data import CharacterSheet
from sheets.ddb_pdf import fill_sheet_equipment, format_import_summary, parse_ddb_pdf
from sheets.storage import get_sheet, set_character_name
from srd import fivetools


def preserve_live_sheet_fields(sheet: CharacterSheet, existing: CharacterSheet) -> None:
    sheet.hunger_days = existing.hunger_days
    sheet.fed_today = existing.fed_today
    sheet.hunger_meal_year = existing.hunger_meal_year
    sheet.hunger_meal_day = existing.hunger_meal_day
    sheet.hunger_meal_kind = existing.hunger_meal_kind
    sheet.image_url = existing.image_url
    sheet.currency = existing.currency


def register_import_commands(sheet_group: Group) -> None:
    @sheet_group.command(
        name="import",
        help=command_help(
            "Importe une fiche D&D Beyond (PDF).",
            f"`{PREFIX}sheet import [@joueur]`",
            "Joins un fichier `.pdf` au message.",
        ),
    )
    async def sheet_import(
        ctx: Context,
        member: discord.Member | None = None,
        file: discord.Attachment | None = None,
    ) -> None:
        await defer_if_slash(ctx)
        owner_id = await resolve_owner(ctx, member)
        if owner_id is None:
            return

        guild_id = resolve_guild_id(ctx)
        if guild_id is None:
            await command_reply(ctx, "Cette commande marche seulement sur le serveur.")
            return

        existing = get_sheet(user_id=owner_id, guild_id=guild_id)

        attachment = file
        if attachment is None and ctx.message is not None and ctx.message.attachments:
            attachment = ctx.message.attachments[0]
        if attachment is None:
            await command_reply(
                ctx,
                (
                    f"Attach a D&D Beyond character PDF to this command.\n"
                    f"Usage: `{PREFIX}sheet import [@player]` + PDF attachment"
                ),
            )
            return

        if not attachment.filename.lower().endswith(".pdf"):
            await command_reply(ctx, "The attachment must be a `.pdf` file.")
            return

        if attachment.size and attachment.size > 10 * 1024 * 1024:
            await command_reply(ctx, "PDF file is too large (max 10 MB).")
            return

        try:
            pdf_bytes = await attachment.read()
            imported = parse_ddb_pdf(pdf_bytes)
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            return

        sheet = imported.sheet
        homebrew_count = 0

        for spell_name in imported.spell_names:
            try:
                spell = await fivetools.search_spell(query=spell_name)
            except fivetools.Open5eError:
                if sheet.add_homebrew_spell(spell_name):
                    homebrew_count += 1
                continue
            sheet.add_spell(slug=spell["slug"])

        matched_gear, custom_gear = await fill_sheet_equipment(
            sheet,
            entries=imported.equipment_entries,
            equipped_names=imported.equipped_names,
            weights=imported.equipment_weights,
        )
        if existing is not None:
            preserve_live_sheet_fields(sheet, existing)

        save_owner_sheet(ctx, owner_id, sheet)
        set_character_name(user_id=owner_id, guild_id=guild_id, name=sheet.name)

        label = target_label(member, sheet)
        summary = format_import_summary(
            sheet=sheet,
            spell_count=len(sheet.spells),
            homebrew_count=homebrew_count,
            gear_count=matched_gear + custom_gear,
            custom_gear_count=custom_gear,
            warnings=imported.warnings,
        )
        await command_reply(ctx, f"{label}\n{summary}")
        await delete_command(ctx)
