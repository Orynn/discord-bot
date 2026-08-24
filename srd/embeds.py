import re

import discord

from srd.fivetools_parser import format_weight_from_lb

SRD_COLOR = 0x4A6741
SHEET_COLOR = 0x8B0000

SPELL_SCHOOL_COLORS: dict[str, int] = {
    "Abjuration": 0x3498DB,
    "Conjuration": 0x9B59B6,
    "Divination": 0xF1C40F,
    "Enchantment": 0xE91E63,
    "Evocation": 0xE74C3C,
    "Illusion": 0x1ABC9C,
    "Necromancy": 0x566573,
    "Transmutation": 0x27AE60,
}

KIND_COLORS: dict[str, int] = {
    "species": 0x2E8B57,
    "class": 0xC9A227,
    "background": 0x8B6914,
    "feat": 0xE67E22,
    "condition": 0x7F8C8D,
    "skill": 0x2980B9,
    "weapon": 0x5D6D7E,
    "armor": 0x566573,
    "item": 0xA0826D,
    "spell_list": 0x6C5CE7,
}

KIND_EMOJI: dict[str, str] = {
    "spell": "✨",
    "species": "🧬",
    "class": "⚔️",
    "background": "📜",
    "feat": "🏅",
    "condition": "🩹",
    "skill": "🎯",
    "weapon": "🗡️",
    "armor": "🛡️",
    "item": "🎒",
    "sheet": "📋",
    "spell_list": "📖",
}

MONSTER_TYPE_COLORS: dict[str, int] = {
    "aberration": 0x7B2CBF,
    "beast": 0xA0714F,
    "celestial": 0xF4B942,
    "construct": 0x78909C,
    "dragon": 0xC0392B,
    "elemental": 0x1E88E5,
    "fey": 0x43A047,
    "fiend": 0x8E0000,
    "giant": 0xEF6C00,
    "humanoid": 0x607D8B,
    "monstrosity": 0x6A1B9A,
    "ooze": 0x558B2F,
    "plant": 0x2E7D32,
    "undead": 0x455A64,
}

MONSTER_TYPE_EMOJI: dict[str, str] = {
    "aberration": "🌀",
    "beast": "🐾",
    "celestial": "✨",
    "construct": "⚙️",
    "dragon": "🐉",
    "elemental": "🔥",
    "fey": "🍃",
    "fiend": "😈",
    "giant": "🗿",
    "humanoid": "🧑",
    "monstrosity": "👁️",
    "ooze": "🫧",
    "plant": "🌿",
    "undead": "💀",
}
MARKDOWN_HEADERS = re.compile(r"^#{1,6}\s+", re.MULTILINE)


DISCORD_FIELD_LIMIT = 1024
DISCORD_FIELD_NAME_LIMIT = 256
DISCORD_DESCRIPTION_LIMIT = 4096
MAX_EMBED_FIELDS = 25


def truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"


def _split_oversize_line(line: str, limit: int) -> list[str]:
    if len(line) <= limit:
        return [line]
    parts: list[str] = []
    rest = line
    while len(rest) > limit:
        cut = rest.rfind(" ", 0, limit)
        if cut < max(1, limit // 2):
            cut = limit
        parts.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        parts.append(rest)
    return parts


def chunk_field_value(text: str, *, limit: int = DISCORD_FIELD_LIMIT) -> list[str]:
    cleaned = (text or "").strip() or "—"
    if len(cleaned) <= limit:
        return [cleaned]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in cleaned.split("\n"):
        for piece in _split_oversize_line(line, limit):
            extra = len(piece) + (1 if current else 0)
            if current and current_len + extra > limit:
                chunks.append("\n".join(current))
                current = [piece]
                current_len = len(piece)
            else:
                current.append(piece)
                current_len += extra
    if current:
        chunks.append("\n".join(current))
    return chunks or ["—"]


def add_chunked_field(
    embed: discord.Embed,
    name: str,
    text: str,
    *,
    inline: bool = False,
) -> None:
    remaining = MAX_EMBED_FIELDS - len(embed.fields)
    if remaining <= 0:
        return
    chunks = chunk_field_value(text)
    for index, chunk in enumerate(chunks):
        if index >= remaining:
            return
        label = name if index == 0 else f"{name} (cont.)"
        embed.add_field(
            name=truncate(label, DISCORD_FIELD_NAME_LIMIT),
            value=chunk,
            inline=inline and index == 0,
        )


def clamp_embed_limits(embed: discord.Embed) -> discord.Embed:
    if embed.title and len(embed.title) > 256:
        embed.title = truncate(embed.title, 256)
    if embed.description and len(embed.description) > DISCORD_DESCRIPTION_LIMIT:
        embed.description = truncate(embed.description, DISCORD_DESCRIPTION_LIMIT)
    if embed.footer.text and len(embed.footer.text) > 2048:
        embed.set_footer(
            text=truncate(embed.footer.text, 2048), icon_url=embed.footer.icon_url
        )

    if len(embed.fields) <= MAX_EMBED_FIELDS and all(
        len(field.name) <= DISCORD_FIELD_NAME_LIMIT
        and len(field.value) <= DISCORD_FIELD_LIMIT
        for field in embed.fields
    ):
        return embed

    original = list(embed.fields)
    embed.clear_fields()
    for field in original:
        add_chunked_field(embed, field.name, field.value, inline=field.inline)
    return embed


def clean_markdown(text: str) -> str:
    text = MARKDOWN_HEADERS.sub("", text)
    text = text.replace("***", "**")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def kind_embed_color(kind: str) -> int:
    return KIND_COLORS.get(kind, SRD_COLOR)


def spell_embed_color(spell: dict) -> int:
    school = str(spell.get("school") or "")
    return SPELL_SCHOOL_COLORS.get(school, SRD_COLOR)


def titled(kind: str, name: str) -> str:
    emoji = KIND_EMOJI.get(kind, "")
    return f"{emoji} {name}" if emoji else name


def spell_embed(spell: dict) -> discord.Embed:
    embed = discord.Embed(
        title=titled("spell", spell["name"]),
        description=truncate(clean_markdown(spell.get("desc", "")), 2000),
        color=spell_embed_color(spell),
        url=spell.get("url"),
    )
    embed.add_field(name="📊 Level", value=spell.get("level", "—"), inline=True)
    embed.add_field(name="🏫 School", value=spell.get("school", "—"), inline=True)
    embed.add_field(
        name="⏱️ Casting Time", value=spell.get("casting_time", "—"), inline=True
    )
    embed.add_field(name="📏 Range", value=spell.get("range", "—"), inline=True)
    embed.add_field(name="⌛ Duration", value=spell.get("duration", "—"), inline=True)
    embed.add_field(
        name="🧪 Components", value=spell.get("components", "—"), inline=True
    )

    if spell.get("material"):
        embed.add_field(
            name="🔮 Material", value=truncate(spell["material"], 1024), inline=False
        )
    if spell.get("higher_level"):
        embed.add_field(
            name="⬆️ At Higher Levels",
            value=truncate(clean_markdown(spell["higher_level"]), 1024),
            inline=False,
        )
    if spell.get("dnd_class"):
        embed.add_field(name="🎓 Classes", value=spell["dnd_class"], inline=False)

    embed.set_footer(text=spell.get("document__title", "5etools"))
    return embed


def species_embed(species: dict) -> discord.Embed:
    speed = species.get("speed", {})
    walk_speed = speed.get("walk") if isinstance(speed, dict) else None
    if walk_speed is None:
        walk_speed = species.get("speed_desc", "—")

    embed = discord.Embed(
        title=titled("species", species["name"]),
        description=truncate(clean_markdown(species.get("desc", "")), 1000),
        color=kind_embed_color("species"),
        url=species.get("url"),
    )
    if species.get("asi_desc"):
        embed.add_field(
            name="📊 Ability Scores",
            value=clean_markdown(species["asi_desc"]),
            inline=False,
        )
    embed.add_field(name="📐 Size", value=species.get("size_raw", "—"), inline=True)
    if isinstance(walk_speed, int):
        speed_value = f"{walk_speed} ft."
    else:
        speed_value = str(walk_speed)
    embed.add_field(name="👟 Speed", value=speed_value, inline=True)
    if species.get("vision"):
        embed.add_field(
            name="👁️ Vision",
            value=truncate(clean_markdown(species["vision"]), 1024),
            inline=False,
        )
    if species.get("traits"):
        embed.add_field(
            name="✦ Traits",
            value=truncate(clean_markdown(species["traits"]), 1024),
            inline=False,
        )

    subraces = species.get("subraces", [])
    if subraces:
        names = ", ".join(subrace["name"] for subrace in subraces[:6])
        embed.add_field(name="🧬 Subraces", value=names, inline=False)

    embed.set_footer(text=species.get("document__title", "5etools"))
    return embed


def class_embed(char_class: dict, subclass: dict | None = None) -> discord.Embed:
    title = char_class["name"]
    if subclass:
        title = f"{char_class['name']} — {subclass['name']}"

    embed = discord.Embed(
        title=titled("class", title),
        color=kind_embed_color("class"),
        url=(subclass or char_class).get("url") or char_class.get("url"),
    )
    embed.add_field(
        name="🎲 Hit Dice", value=char_class.get("hit_dice", "—"), inline=True
    )
    embed.add_field(
        name="❤️ HP at 1st", value=char_class.get("hp_at_1st_level", "—"), inline=True
    )
    if char_class.get("spellcasting_ability"):
        embed.add_field(
            name="🔮 Spellcasting",
            value=char_class["spellcasting_ability"],
            inline=True,
        )
    embed.add_field(
        name="🎲 Saving Throws",
        value=char_class.get("prof_saving_throws", "—"),
        inline=False,
    )
    embed.add_field(
        name="🎯 Skills", value=char_class.get("prof_skills", "—"), inline=False
    )
    embed.add_field(
        name="🛡️ Armor", value=char_class.get("prof_armor", "—"), inline=True
    )
    embed.add_field(
        name="🗡️ Weapons",
        value=truncate(char_class.get("prof_weapons", "—"), 1024),
        inline=False,
    )

    if not subclass:
        archetypes = char_class.get("archetypes") or []
        if archetypes:
            names = ", ".join(
                str(entry.get("name")) for entry in archetypes[:12] if entry.get("name")
            )
            extra = f" (+{len(archetypes) - 12})" if len(archetypes) > 12 else ""
            embed.add_field(
                name="📚 Subclasses",
                value=truncate(f"{names}{extra}", 1024),
                inline=False,
            )

    description = subclass.get("desc") if subclass else char_class.get("desc", "")
    if description:
        embed.description = truncate(clean_markdown(description), 2000)

    embed.set_footer(text=char_class.get("document__title", "5etools"))
    return embed


def background_embed(background: dict) -> discord.Embed:
    embed = discord.Embed(
        title=titled("background", background["name"]),
        description=truncate(clean_markdown(background.get("desc", "")), 1500),
        color=kind_embed_color("background"),
        url=background.get("url"),
    )
    if background.get("skill_proficiencies"):
        embed.add_field(
            name="🎯 Skill Proficiencies",
            value=background["skill_proficiencies"],
            inline=False,
        )
    if background.get("feature"):
        feature_text = background.get("feature_desc") or background["feature"]
        embed.add_field(
            name=f"✦ Feature: {background['feature']}",
            value=truncate(clean_markdown(feature_text), 1024),
            inline=False,
        )
    if background.get("equipment"):
        embed.add_field(
            name="🎒 Equipment",
            value=truncate(background["equipment"], 1024),
            inline=False,
        )

    embed.set_footer(text=background.get("document__title", "5etools"))
    return embed


def feat_embed(feat: dict) -> discord.Embed:
    embed = discord.Embed(
        title=titled("feat", feat["name"]),
        description=truncate(clean_markdown(feat.get("desc", "")), 2000),
        color=kind_embed_color("feat"),
        url=feat.get("url"),
    )
    if feat.get("prerequisite"):
        embed.add_field(
            name="📋 Prerequisite",
            value=truncate(str(feat["prerequisite"]), 1024),
            inline=False,
        )
    embed.set_footer(text=feat.get("document__title", "5etools"))
    return embed


def condition_embed(condition: dict) -> discord.Embed:
    embed = discord.Embed(
        title=titled("condition", condition["name"]),
        description=truncate(clean_markdown(condition.get("desc", "")), 4096),
        color=kind_embed_color("condition"),
        url=condition.get("url"),
    )
    embed.set_footer(text=condition.get("document__title", "5etools"))
    return embed


def skill_embed(skill: dict) -> discord.Embed:
    embed = discord.Embed(
        title=titled("skill", skill["name"]),
        description=truncate(clean_markdown(skill.get("desc", "")), 4096),
        color=kind_embed_color("skill"),
        url=skill.get("url"),
    )
    embed.add_field(name="📊 Ability", value=skill.get("ability", "—"), inline=True)
    embed.set_footer(text=skill.get("document__title", "5etools"))
    return embed


def weapon_embed(weapon: dict) -> discord.Embed:
    embed = discord.Embed(
        title=titled("weapon", weapon["name"]),
        color=kind_embed_color("weapon"),
        url=weapon.get("url"),
    )
    embed.add_field(name="🏷️ Category", value=weapon.get("category", "—"), inline=True)
    embed.add_field(name="💥 Damage", value=weapon.get("damage", "—"), inline=True)
    embed.add_field(
        name="💥 Damage Type", value=weapon.get("damage_type", "—"), inline=True
    )
    embed.add_field(name="📏 Range", value=weapon.get("range", "—"), inline=True)
    embed.add_field(name="⚖️ Weight", value=weapon.get("weight", "—"), inline=True)
    embed.add_field(
        name="✦ Properties", value=weapon.get("properties", "—"), inline=False
    )
    embed.set_footer(text=weapon.get("document__title", "5etools"))
    return embed


def armor_embed(armor: dict) -> discord.Embed:
    embed = discord.Embed(
        title=titled("armor", armor["name"]),
        color=kind_embed_color("armor"),
        url=armor.get("url"),
    )
    embed.add_field(name="🏷️ Category", value=armor.get("category", "—"), inline=True)
    embed.add_field(name="🛡️ AC", value=armor.get("ac", "—"), inline=True)
    stealth = "Disadvantage" if armor.get("stealth_disadvantage") else "—"
    embed.add_field(name="🤫 Stealth", value=stealth, inline=True)
    strength = armor.get("strength_required")
    if strength:
        embed.add_field(name="💪 Strength Required", value=str(strength), inline=True)
    embed.add_field(name="⚖️ Weight", value=armor.get("weight", "—"), inline=True)
    embed.set_footer(text=armor.get("document__title", "5etools"))
    return embed


def item_embed(item: dict) -> discord.Embed:
    embed = discord.Embed(
        title=titled("item", item["name"]),
        description=truncate(clean_markdown(item.get("desc", "")), 2000),
        color=kind_embed_color("item"),
        url=item.get("url"),
    )
    embed.add_field(name="🏷️ Category", value=item.get("category", "—"), inline=True)
    embed.add_field(name="💰 Cost", value=item.get("cost", "—"), inline=True)
    embed.add_field(name="⚖️ Weight", value=item.get("weight", "—"), inline=True)
    capacity = item.get("container_capacity_lb")
    if capacity not in (None, ""):
        label = format_weight_from_lb(float(capacity))
        if item.get("container_weightless"):
            label += " (contents are weightless)"
        embed.add_field(name="🎒 Holds", value=label, inline=True)
    embed.set_footer(text=item.get("document__title", "5etools"))
    return embed


def equipment_embed(entry: dict) -> discord.Embed:
    kind = entry.get("kind")
    if kind == "weapon":
        return weapon_embed(entry)
    if kind == "armor":
        return armor_embed(entry)
    return item_embed(entry)


def _monster_defenses(monster: dict) -> str | None:
    parts: list[str] = []
    for label, key in (
        ("Damage Vulnerabilities", "vulnerable"),
        ("Damage Resistances", "resist"),
        ("Damage Immunities", "immune"),
        ("Condition Immunities", "condition_immune"),
    ):
        value = monster.get(key)
        if value and value != "—":
            parts.append(f"**{label}** {value}")
    return "\n".join(parts) if parts else None


def _monster_field(text: str | None) -> str:
    if not text:
        return "—"
    return clean_markdown(text)


def _parse_cr_value(cr: str) -> float | None:
    if not cr or cr == "—":
        return None
    try:
        if "/" in cr:
            num, den = cr.split("/", 1)
            return float(num) / float(den)
        return float(cr)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _cr_badge(cr: str) -> str:
    value = _parse_cr_value(cr)
    if value is None:
        return f"CR {cr}"
    if value >= 17:
        return f"🔴 CR {cr}"
    if value >= 11:
        return f"🟠 CR {cr}"
    if value >= 5:
        return f"🟡 CR {cr}"
    return f"🟢 CR {cr}"


def monster_embed_color(monster: dict) -> int:
    type_key = str(monster.get("creature_type_key") or "").lower()
    return MONSTER_TYPE_COLORS.get(type_key, SRD_COLOR)


def monster_embed(monster: dict) -> discord.Embed:
    type_key = str(monster.get("creature_type_key") or "").lower()
    type_emoji = MONSTER_TYPE_EMOJI.get(type_key, "👾")
    subtitle_parts = [monster.get("stat_line", "")]
    if monster.get("cr") and monster.get("cr") != "—":
        subtitle_parts.append(_cr_badge(str(monster["cr"])))
    embed = discord.Embed(
        title=f"{type_emoji} {monster['name']}",
        description=truncate(" · ".join(part for part in subtitle_parts if part), 500),
        color=monster_embed_color(monster),
        url=monster.get("url"),
    )
    embed.add_field(name="🛡️ AC", value=monster.get("ac", "—"), inline=True)
    embed.add_field(name="❤️ HP", value=monster.get("hp", "—"), inline=True)
    embed.add_field(name="👟 Speed", value=monster.get("speed", "—"), inline=True)
    add_chunked_field(embed, "📊 Abilities", str(monster.get("abilities") or "—"))

    if monster.get("saves") and monster["saves"] != "—":
        add_chunked_field(embed, "🎲 Saving Throws", monster["saves"], inline=True)
    if monster.get("skills") and monster["skills"] != "—":
        add_chunked_field(embed, "🎯 Skills", monster["skills"], inline=True)

    defenses = _monster_defenses(monster)
    if defenses:
        add_chunked_field(embed, "🛡️ Defenses", defenses)

    add_chunked_field(embed, "👁️ Senses", str(monster.get("senses") or "—"))
    add_chunked_field(embed, "💬 Languages", str(monster.get("languages") or "—"))

    for field_name, key in (
        ("✦ Traits", "traits"),
        ("🔮 Spellcasting", "spellcasting"),
        ("⚔️ Actions", "actions"),
        ("⚡ Bonus Actions", "bonus_actions"),
        ("🔄 Reactions", "reactions"),
        ("👑 Legendary Actions", "legendary"),
    ):
        text = monster.get(key)
        if text:
            add_chunked_field(embed, field_name, _monster_field(text))

    embed.set_footer(text=monster.get("document__title", "5etools"))
    return embed
