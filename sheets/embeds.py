import discord

from sheets.armor import format_ac_field
from sheets.data import ABILITIES, CharacterSheet, ability_modifier, format_modifier
from sheets.hunger import format_hunger_line, hunger_state
from sheets.skills import format_skills_block
from srd.embeds import SHEET_COLOR, background_embed, class_embed, species_embed, titled, truncate

DISCORD_EMBED_DESCRIPTION_LIMIT = 4096


def _append_description(embed: discord.Embed, text: str) -> None:
    current = embed.description or ""
    embed.description = truncate(f"{current}{text}", DISCORD_EMBED_DESCRIPTION_LIMIT)


def build_sheet_embed(sheet: CharacterSheet) -> discord.Embed:
    prof = sheet.get_prof_bonus()
    class_line = sheet.char_class
    if sheet.subclass:
        class_line = f"{sheet.char_class} ({sheet.subclass})"

    embed = discord.Embed(
        title=titled("sheet", sheet.name),
        description=(
            f"**🧬 Species** {sheet.species or '—'} · "
            f"**⚔️ Class** {class_line or '—'} · "
            f"**📊 Level** {sheet.level} · "
            f"**📜 Background** {sheet.background or '—'}"
        ),
        color=SHEET_COLOR,
    )

    if sheet.equipment.items:
        summary = sheet.equipment.format_summary(limit=10, exclude_equipped=True)
        if summary:
            _append_description(embed, f"\n\n**🎒 Equipment**\n{summary}")

    _append_description(embed, f"\n\n{format_skills_block(sheet)}")

    ability_lines = []
    for ability in ABILITIES:
        score = sheet.abilities[ability]
        mod = ability_modifier(score)
        save_mod = sheet.get_save_modifier(ability)
        prof_mark = " ●" if ability in sheet.save_proficiencies else ""
        ability_lines.append(
            f"**{ability.upper()}** {score} ({format_modifier(mod)})"
            f" · Save {format_modifier(save_mod)}{prof_mark}"
        )
    embed.add_field(
        name=f"📊 Abilities · Prof {format_modifier(prof)}",
        value="\n".join(ability_lines),
        inline=False,
    )

    embed.add_field(name="🛡️ AC", value=format_ac_field(sheet), inline=True)
    embed.add_field(
        name="❤️ HP",
        value=f"{sheet.hp_current}/{sheet.hp_max}" if sheet.hp_max else "—",
        inline=True,
    )
    embed.add_field(name="👟 Speed", value=sheet.format_speed(), inline=True)
    hands_name, hands_value = sheet.equipment.format_hands_field()
    embed.add_field(name=hands_name, value=hands_value, inline=True)
    belt_name, belt_value = sheet.equipment.format_belt_field()
    embed.add_field(name=belt_name, value=belt_value, inline=True)
    embed.add_field(name="💰 Money", value=sheet.currency.format(), inline=True)
    embed.add_field(name="⚖️ Load", value=sheet.format_load(), inline=True)

    status_bits: list[str] = []
    if sheet.inspired:
        status_bits.append("✨ **Heroic Inspiration**")
    if hunger_state(sheet) != "fed" or sheet.fed_today:
        status_bits.append(f"🍖 {format_hunger_line(sheet)}")
    if sheet.conditions:
        status_bits.append("Conditions: " + ", ".join(c.title() for c in sheet.conditions))
    if sheet.death_save_successes or sheet.death_save_failures:
        status_bits.append(
            f"Death saves: {sheet.death_save_successes} successes / "
            f"{sheet.death_save_failures} failures"
        )
    if sheet.hit_dice_remaining != sheet.level:
        status_bits.append(f"Hit dice: **{sheet.hit_dice_remaining}/{sheet.level}**")
    if sheet.spell_slots.has_slots():
        status_bits.append(f"Spell slots: {sheet.spell_slots.format()}")
    if status_bits:
        embed.add_field(name="📌 Status", value="\n".join(status_bits), inline=False)

    if sheet.notes:
        embed.add_field(name="📝 Notes", value=sheet.notes[:1024], inline=False)

    if sheet.spells or sheet.homebrew_spells:
        spell_parts: list[str] = []
        if sheet.spells:
            spell_parts.append(sheet.format_spells_summary())
        if sheet.homebrew_spells:
            homebrew = ", ".join(sheet.homebrew_spells[:5])
            extra = f" (+{len(sheet.homebrew_spells) - 5} more)" if len(sheet.homebrew_spells) > 5 else ""
            spell_parts.append(f"Homebrew: {homebrew}{extra}")
        embed.add_field(name="✨ Spells", value="\n".join(spell_parts), inline=False)

    embed.set_footer(text="● proficient · ◆ expertise")
    return embed


def sheet_info_embeds(
    sheet_name: str,
    species: dict | None,
    char_class: dict | None,
    background: dict | None,
    subclass: dict | None = None,
    missing: list[str] | None = None,
) -> list[discord.Embed]:
    embeds: list[discord.Embed] = []

    if species:
        embed = species_embed(species)
        embed.title = f"{sheet_name} — {embed.title}"
        embeds.append(embed)

    if char_class:
        embed = class_embed(char_class, subclass=subclass)
        embed.title = f"{sheet_name} — {embed.title}"
        embeds.append(embed)

    if background:
        embed = background_embed(background)
        embed.title = f"{sheet_name} — {embed.title}"
        embeds.append(embed)

    if missing:
        note = discord.Embed(
            title=f"⚠️ {sheet_name} — Not in 5etools export",
            description="The following sheet fields were not found in your 5etools export:\n"
            + "\n".join(f"• {entry}" for entry in missing),
            color=discord.Color.orange(),
        )
        embeds.append(note)

    return embeds
