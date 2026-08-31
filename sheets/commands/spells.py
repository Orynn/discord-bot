import discord
from discord.ext.commands import Group
from discord.ext.commands.context import Context

from bot.command_helpers import command_reply, delete_command
from bot.help_text import command_help
from bot.messaging import send_message
from config import PREFIX
from sheets.context import get_sheet_for_owner, save_owner_sheet, target_label
from sheets.spell_view import (
    build_sheet_spell_view,
    build_spell_list_embed,
    homebrew_slug,
)
from srd import fivetools
from srd.spell_slugs import find_spell_slug_on_sheet
from srd.embeds import kind_embed_color, spell_embed, titled


def register_spell_commands(sheet_group: Group) -> None:
    @sheet_group.group(
        name="spells",
        invoke_without_command=True,
        fallback="list",
        help=command_help(
            "Sorts connus sur la fiche (pas le suivi des emplacements).",
            f"`{PREFIX}sheet spells`",
        ),
    )
    async def sheet_spells_group(
        ctx: Context, member: discord.Member | None = None
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        _, sheet = result

        if not sheet.spells and not sheet.homebrew_spells:
            label = target_label(member, sheet)
            await command_reply(ctx, f"{label} has no spells saved.")
            await delete_command(ctx)
            return

        spell_entries: list[tuple[str, str, str]] = []
        for slug in sheet.spells:
            try:
                spell = await fivetools.get_spell(slug=slug)
                spell_entries.append((slug, spell["name"], spell.get("level", "")))
            except fivetools.Open5eError:
                spell_entries.append((slug, slug.replace("-", " ").title(), ""))

        for name in sheet.homebrew_spells:
            spell_entries.append((homebrew_slug(name), name, "Homebrew"))

        embed = build_spell_list_embed(
            title=f"{sheet.name} — Spells ({len(spell_entries)})",
            spell_entries=spell_entries,
        )
        view = build_sheet_spell_view(spell_entries)
        await send_message(
            ctx,
            embed=embed,
            view=view,
            definition_menu=False,
        )
        await delete_command(ctx)

    @sheet_spells_group.command(
        name="add",
        help=command_help(
            "Ajoute un sort à la fiche.",
            f"`{PREFIX}sheet spells add [@joueur] <nom>`",
        ),
    )
    async def sheet_spells_add(
        ctx: Context,
        member: discord.Member | None = None,
        *,
        name: str,
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result

        try:
            spell = await fivetools.search_spell(query=name.strip())
        except fivetools.Open5eError:
            cleaned = name.strip()
            if not cleaned:
                await command_reply(ctx, "Spell name cannot be empty.")
                return
            if not sheet.add_homebrew_spell(cleaned):
                await command_reply(
                    ctx, f"**{cleaned}** is already on this sheet (homebrew)."
                )
                return
            save_owner_sheet(ctx, owner_id, sheet)
            label = target_label(member, sheet)
            await command_reply(ctx, f"{label}: added homebrew spell **{cleaned}**.")
            await delete_command(ctx)
            return

        if not sheet.add_spell(slug=spell["slug"]):
            await command_reply(ctx, f"**{spell['name']}** is already on this sheet.")
            return

        save_owner_sheet(ctx, owner_id, sheet)
        label = target_label(member, sheet)
        await command_reply(
            ctx, f"{label}: added **{spell['name']}** ({spell.get('level', '?')})."
        )
        await delete_command(ctx)

    @sheet_spells_group.command(
        name="remove",
        help=command_help(
            "Retire un sort de la fiche.",
            f"`{PREFIX}sheet spells remove [@joueur] <nom>`",
        ),
    )
    async def sheet_spells_remove(
        ctx: Context,
        member: discord.Member | None = None,
        *,
        name: str,
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        owner_id, sheet = result

        query = name.strip().lower()
        slug = find_spell_slug_on_sheet(sheet.spells, query)
        if slug is None:
            homebrew_match = next(
                (
                    spell_name
                    for spell_name in sheet.homebrew_spells
                    if spell_name.lower() == query
                ),
                None,
            )
            if homebrew_match and sheet.remove_homebrew_spell(homebrew_match):
                save_owner_sheet(ctx, owner_id, sheet)
                label = target_label(member, sheet)
                await command_reply(
                    ctx, f"{label}: removed homebrew spell **{homebrew_match}**."
                )
                await delete_command(ctx)
                return

        if slug is None:
            try:
                spell = await fivetools.search_spell(query=name.strip())
                slug = spell["slug"]
            except fivetools.Open5eError as exc:
                await command_reply(ctx, str(exc))
                return

        if not sheet.remove_spell(slug=slug):
            await command_reply(ctx, f"**{name.strip()}** is not on this sheet.")
            return

        save_owner_sheet(ctx, owner_id, sheet)
        label = target_label(member, sheet)
        await command_reply(ctx, f"{label}: removed **{name.strip()}**.")
        await delete_command(ctx)

    @sheet_spells_group.command(
        name="show",
        help=command_help(
            "Affiche un sort de la fiche ou du SRD.",
            f"`{PREFIX}sheet spells show [@joueur] <nom>`",
        ),
    )
    async def sheet_spells_show(
        ctx: Context,
        member: discord.Member | None = None,
        *,
        name: str,
    ) -> None:
        result = await get_sheet_for_owner(ctx, member)
        if result is None:
            return
        _, sheet = result

        query = name.strip().lower()
        slug = find_spell_slug_on_sheet(sheet.spells, query)

        homebrew_match = next(
            (
                spell_name
                for spell_name in sheet.homebrew_spells
                if spell_name.lower() == query
            ),
            None,
        )
        if homebrew_match:
            embed = discord.Embed(
                title=titled("spell", homebrew_match),
                description="Homebrew spell (not in the SRD).",
                color=kind_embed_color("spell_list"),
            )
            await send_message(ctx, embed=embed)
            await delete_command(ctx)
            return

        try:
            if slug:
                spell = await fivetools.get_spell(slug=slug)
            else:
                spell = await fivetools.search_spell(query=name.strip())
        except fivetools.Open5eError as exc:
            await command_reply(ctx, str(exc))
            return

        await send_message(ctx, embed=spell_embed(spell))
        await delete_command(ctx)
