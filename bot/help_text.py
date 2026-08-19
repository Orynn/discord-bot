from dataclasses import dataclass

import discord

HELP_COLOR = 0xC9A227
HELP_ROLEPLAY_COLOR = 0x9B59B6
HELP_SHEET_COLOR = 0x8B0000
HELP_COMBAT_COLOR = 0xC0392B
HELP_INIT_COLOR = 0xF1C40F
HELP_DICE_COLOR = 0xD4A017
HELP_LOOKUP_COLOR = 0x4A6741
HELP_MAGIC_COLOR = 0x6C5CE7
HELP_ADMIN_COLOR = 0x566573
HELP_STATUS_COLOR = 0x27AE60


@dataclass(frozen=True)
class HelpSection:
    key: str
    emoji: str
    label: str
    body: str
    footer: str | None = None
    color: int = HELP_COLOR
    intro: str = ""
    fields: tuple[tuple[str, str], ...] = ()
    button_label: str = ""


def _section(
    *,
    key: str,
    emoji: str,
    label: str,
    intro: str = "",
    fields: tuple[tuple[str, str], ...] = (),
    footer: str | None = None,
    color: int = HELP_COLOR,
    button: str | None = None,
) -> HelpSection:
    chunks = [intro] if intro else []
    chunks.extend(value for _name, value in fields)
    return HelpSection(
        key=key,
        emoji=emoji,
        label=label,
        body="\n\n".join(chunks),
        footer=footer,
        color=color,
        intro=intro,
        fields=fields,
        button_label=button or label,
    )


def _help_embed(
    *,
    title: str,
    section: HelpSection,
    index: int,
    total: int,
) -> discord.Embed:
    description = f"**{section.label}**"
    if section.intro:
        description = f"{description}\n{section.intro}"
    elif not section.fields:
        description = f"{description}\n\n{section.body}"

    embed = discord.Embed(
        title=f"{section.emoji} {title}",
        description=description,
        color=section.color,
    )
    for name, value in section.fields:
        embed.add_field(name=name, value=value, inline=False)

    footer_parts = [f"{index + 1}/{total}"]
    if section.footer:
        footer_parts.append(section.footer)
    footer_parts.append("Buttons switch sections")
    embed.set_footer(text=" · ".join(footer_parts))
    return embed


def build_help_sections(*, prefix: str, is_admin: bool) -> list[HelpSection]:
    sections = [
        _section(
            key="overview",
            emoji="📖",
            label="Quick start",
            button="Start",
            intro="Three steps to play, then open a guide when you need it.",
            fields=(
                (
                    "🚀 First session",
                    f"**1.** `{prefix}sheet create <name>` or `/sheet create`\n"
                    f"**2.** `{prefix}init add @you` or `/init add`\n"
                    f"**3.** `{prefix}combat board` or `/combat board` *(after start)*",
                ),
                (
                    "📚 Guides",
                    f"`{prefix}help sheet` · `{prefix}help combat` · `/help`",
                ),
            ),
            footer="Tip: /help and ;help are the same · ;aide works too",
            color=HELP_COLOR,
        ),
        _section(
            key="roleplay",
            emoji="🎭",
            label="Roleplay",
            button="RP",
            fields=(
                (
                    "🗣️ In character",
                    f"`{prefix}pcname <name>` — set your character name\n"
                    f"`{prefix}pc <text>` · `{prefix}speak` — speak in character\n"
                    f"`{prefix}pc (action) <text>` — action + dialogue",
                ),
                (
                    "🎬 Narration",
                    f"`{prefix}desc <text>` — narrate a scene (italic)",
                ),
            ),
            footer=f"Tip: {prefix}help sheet",
            color=HELP_ROLEPLAY_COLOR,
        ),
        _section(
            key="sheet",
            emoji="📋",
            label="Character sheet",
            button="Sheet",
            intro=f"Full guide: `{prefix}help sheet`",
            fields=(
                (
                    "🧰 Setup",
                    f"`{prefix}sheet create <name>` · `show` · `set` · `delete`\n"
                    f"`{prefix}sheet import` — D&D Beyond PDF *(attach file)*",
                ),
                (
                    "❤️ Play",
                    f"`{prefix}sheet hp` · `money` · `gear` · `prof`\n"
                    f"`{prefix}sheet spells` · `slots` · `condition` · `rest` · `info`",
                ),
            ),
            footer=f"Tip: {prefix}sheet slots auto",
            color=HELP_SHEET_COLOR,
        ),
        _section(
            key="combat",
            emoji="🃏",
            label="Card combat",
            button="Combat",
            intro=f"Full guide: `{prefix}help combat`",
            fields=(
                (
                    "▶️ Flow",
                    f"`{prefix}init add` → `{prefix}combat start` → `{prefix}combat board`\n"
                    "Decks come from your sheet and your 5etools export.",
                ),
                (
                    "🎯 On your turn",
                    f"`{prefix}combat hand`\n"
                    f"`{prefix}combat play <card> [target]`\n"
                    f"`{prefix}combat pass`",
                ),
            ),
            footer=f"Tip: {prefix}combat play weapon Goblin",
            color=HELP_COMBAT_COLOR,
        ),
        _section(
            key="initiative",
            emoji="⚡",
            label="Initiative & party",
            button="Init",
            fields=(
                (
                    "⚡ Turn order",
                    f"`{prefix}init add @player` — roll from your sheet\n"
                    f"`{prefix}init add Name 2` — add an NPC (+2)\n"
                    f"`{prefix}init next` · `{prefix}init show`",
                ),
                (
                    "💰 Party",
                    f"`{prefix}party money show` — shared treasury",
                ),
            ),
            footer=f"Tip: {prefix}init next",
            color=HELP_INIT_COLOR,
        ),
        _section(
            key="dice",
            emoji="🎲",
            label="Dice",
            button="Dice",
            fields=(
                (
                    "🎲 Rolls",
                    f"`{prefix}roll` · `{prefix}r` — `1d20`, `athletics`, `dex save`\n"
                    f"`adv` / `dis` · `2d20kh1`",
                ),
                (
                    "💻 Slash commands",
                    "`/` opens the same commands: `/help` · `/roll` · `/sheet show` · "
                    "`/combat board` · `/init next` · `/srd`",
                ),
            ),
            footer=f"Tip: {prefix}roll adv perception",
            color=HELP_DICE_COLOR,
        ),
        _section(
            key="lookup",
            emoji="🔎",
            label="Lookup",
            button="SRD",
            fields=(
                (
                    "📖 5etools",
                    f"`{prefix}srd spell|species|class|background|feat|condition|monster|weapon|armor|item <name>`",
                ),
            ),
            footer=f"Tip: {prefix}srd spell fireball",
            color=HELP_LOOKUP_COLOR,
        ),
    ]

    if is_admin:
        sections.append(
            _section(
                key="admin",
                emoji="🛡️",
                label="Admin",
                button="Admin",
                fields=(
                    (
                        "🎭 Roleplay & lore",
                        f"`{prefix}npc <name> <text>` · `{prefix}say` — make an NPC speak\n"
                        f"`{prefix}campaign [query]` · `{prefix}lore` — browse CAMPAIGN forums\n"
                        f"`{prefix}campaign post lieux <title> -- <text>` — new post *(attach an image)*\n"
                        f"`{prefix}campaign forum lieux` — extra forum (defaults are created on startup)\n"
                        f"`{prefix}campaign channels` — file of every channel + category\n"
                        f"`{prefix}campaign wiki Eauprofonde` — aperçu du wiki FR des Royaumes Oubliés\n"
                        f"`{prefix}campaign import Padhiver` — cette page · `import Padhiver --liens` — + infobox\n"
                        f"`{prefix}campaign repair` — remplit les posts restés sur « Import des liens… »\n"
                        f"`{prefix}campaign move pnj Padhiver` — déplace un post et met à jour les liens\n"
                        f"`{prefix}campaign audit` — vérifie le forum de chaque post wiki (`audit fix` pour corriger)",
                    ),
                    (
                        "📋 Sheets & rolls",
                        f"Put `@player` before args to manage another sheet / roll\n"
                        f"`{prefix}sheet hp @Alice 12` · `{prefix}roll @Alice athletics`\n"
                        f"`{prefix}sheet money set|add @player <amount>`",
                    ),
                    (
                        "⚔️ Initiative & combat",
                        f"`{prefix}init remove <name>` · `{prefix}init clear`\n"
                        f"`{prefix}combat start` · `{prefix}combat end` · `{prefix}combat add <name> <hp>`\n"
                        f"See `{prefix}help combat` for the full card combat guide.",
                    ),
                    (
                        "💰 Party & players",
                        f"`{prefix}party money set|add|spend <amount>`\n"
                        f"`{prefix}player setup @member [name]` — category + sheet + welcome\n"
                        f"`{prefix}player list` · `{prefix}player remove @member`",
                    ),
                ),
                footer="Only visible to server administrators",
                color=HELP_ADMIN_COLOR,
            )
        )

    return sections


def build_combat_help_sections(*, prefix: str, is_admin: bool) -> list[HelpSection]:
    sections = [
        _section(
            key="start",
            emoji="🎯",
            label="Getting started",
            button="Start",
            fields=(
                (
                    "🧰 Prepare characters",
                    f"`{prefix}sheet create <name>` · `{prefix}sheet set class fighter`\n"
                    f"`{prefix}sheet spells add fire-bolt` — spells from your 5etools export\n"
                    f"`{prefix}sheet slots auto` — track spell slots *(optional)*",
                ),
                (
                    "⚔️ Set up the fight",
                    f"`{prefix}init add @player` · `{prefix}init add Goblin 2`\n"
                    f"`{prefix}combat start` — deal decks *(admin)*\n"
                    f"`{prefix}combat board` — open the play table",
                ),
            ),
            footer=f"Tip: run {prefix}init show to check turn order",
            color=HELP_COLOR,
        ),
        _section(
            key="play",
            emoji="🃏",
            label="Playing your turn",
            button="Play",
            fields=(
                (
                    "🖥️ Board",
                    f"`{prefix}combat board` — card dropdown, End turn, View hand",
                ),
                (
                    "⌨️ Commands",
                    f"`{prefix}combat play <card> [target]`\n"
                    f"`{prefix}combat hand` — your current cards\n"
                    f"`{prefix}combat pass` — end turn without playing",
                ),
                (
                    "📌 Examples",
                    f"`{prefix}combat play weapon Goblin`\n"
                    f"`{prefix}combat play fire-bolt Goblin`\n"
                    f"`{prefix}combat play cure-wounds @Alice`",
                ),
            ),
            footer="Tip: card names match spell names from your export or weapon/dodge",
            color=HELP_COMBAT_COLOR,
        ),
        _section(
            key="deck",
            emoji="📚",
            label="What's in your deck",
            button="Deck",
            fields=(
                (
                    "⚔️ Always included",
                    "• **Weapon Attack** — class hit die + ability + proficiency\n"
                    "• **Dodge** — halve the next damage you take",
                ),
                (
                    "✨ From your sheet",
                    f"• Spells listed in `{prefix}sheet spells`\n"
                    "• Cantrips appear more often · leveled spells use slots\n"
                    "• Homebrew spells get a generic attack card",
                ),
                (
                    "❤️ HP",
                    f"Damage and healing update `{prefix}sheet hp` automatically.",
                ),
            ),
            footer=f"Tip: {prefix}srd spell fireball to preview a spell",
            color=HELP_MAGIC_COLOR,
        ),
        _section(
            key="init",
            emoji="⚡",
            label="Initiative",
            button="Init",
            intro=f"Card combat uses the same turn order as `{prefix}init`.",
            fields=(
                (
                    "⚡ Commands",
                    f"`{prefix}init add @player` — rolls d20 + DEX from sheet\n"
                    f"`{prefix}init add Name 2` — NPC with a fixed bonus\n"
                    f"`{prefix}init next` — advance turn manually\n"
                    f"`{prefix}init show` — display the order",
                ),
            ),
            footer=f"Tip: {prefix}init next also works outside card combat",
            color=HELP_INIT_COLOR,
        ),
    ]

    if is_admin:
        sections.append(
            _section(
                key="admin",
                emoji="🛡️",
                label="Admin",
                button="Admin",
                fields=(
                    (
                        "🃏 Combat",
                        f"`{prefix}combat start` — start card combat from initiative\n"
                        f"`{prefix}combat end` — stop the current fight\n"
                        f"`{prefix}combat add Name 30` — add a combatant mid-fight\n"
                        f"`{prefix}combat add @player 30` — add a linked player",
                    ),
                    (
                        "⚡ Initiative",
                        f"`{prefix}init remove <name>` · `{prefix}init clear`",
                    ),
                ),
                footer="Only visible to server administrators",
                color=HELP_ADMIN_COLOR,
            )
        )

    return sections


def build_sheet_help_sections(*, prefix: str, is_admin: bool) -> list[HelpSection]:
    sections = [
        _section(
            key="setup",
            emoji="🧰",
            label="Setup",
            button="Setup",
            fields=(
                (
                    "📋 Character",
                    f"`{prefix}sheet create <name>` — create\n"
                    f"`{prefix}sheet import` — D&D Beyond PDF *(attach file)*\n"
                    f"`{prefix}sheet show` — display\n"
                    f"`{prefix}sheet delete` — delete",
                ),
                (
                    "✏️ Edit",
                    f"`{prefix}sheet set <field> <value>` — name, species, class, level, stats…\n"
                    f"`{prefix}sheet info` — 5etools info for species / class / background",
                ),
            ),
            color=HELP_SHEET_COLOR,
        ),
        _section(
            key="resources",
            emoji="💰",
            label="Resources",
            button="Gear",
            fields=(
                (
                    "❤️ Survival",
                    f"`{prefix}sheet hp <current> [max]` — hit points\n"
                    f"`{prefix}sheet money` — wallet (`show` / `spend` / `pay`)",
                ),
                (
                    "🎒 Equipment & skills",
                    f"`{prefix}sheet gear` — equipment from your 5etools export\n"
                    f"`{prefix}sheet gear add|remove|equip|show <name>`\n"
                    f"`{prefix}sheet prof save <ability>` — save proficiency\n"
                    f"`{prefix}sheet prof skill <skill> [expertise]` — skill proficiency",
                ),
            ),
            color=HELP_COLOR,
        ),
        _section(
            key="magic",
            emoji="✨",
            label="Magic",
            button="Magic",
            fields=(
                (
                    "📖 Spells",
                    f"`{prefix}sheet spells` — known spells list\n"
                    f"`{prefix}sheet spells add|remove|show <name>`",
                ),
                (
                    "🔮 Slots",
                    f"`{prefix}sheet slots` — spell slot tracking\n"
                    f"`{prefix}sheet slots use <level> [count]` — ex: `{prefix}sheet slots use 1`\n"
                    f"`{prefix}sheet slots recover` · `set` · `auto` (PHB from class/level)",
                ),
            ),
            color=HELP_MAGIC_COLOR,
        ),
        _section(
            key="status",
            emoji="❤️",
            label="Status & rest",
            button="Status",
            fields=(
                (
                    "📌 Conditions",
                    f"`{prefix}sheet condition <name>` — toggle condition\n"
                    f"`{prefix}sheet inspire` — heroic inspiration\n"
                    f"`{prefix}sheet deathsave success|failure`",
                ),
                (
                    "🏕️ Rest",
                    f"`{prefix}sheet rest short [dice]` — warlock pact slots recover\n"
                    f"`{prefix}sheet rest long` — HP, hit dice, spell slots",
                ),
                (
                    "🔎 Lookup",
                    f"`{prefix}srd spell|species|class|background|feat|condition|monster|weapon|armor|item <name>`",
                ),
            ),
            color=HELP_STATUS_COLOR,
        ),
    ]

    if is_admin:
        sections.append(
            _section(
                key="admin",
                emoji="🛡️",
                label="Admin",
                button="Admin",
                intro="Put `@player` before arguments to manage another sheet.",
                fields=(
                    (
                        "👤 Other players",
                        f"`{prefix}sheet show @Alice` · `{prefix}sheet hp @Alice 12` · `{prefix}sheet slots use @Alice 1`\n"
                        f"`{prefix}sheet money set|add @player <amount>`\n"
                        f"`{prefix}sheet create @player <name>` · `{prefix}sheet import @player` · `{prefix}sheet delete @player`",
                    ),
                ),
                footer="Only visible to server administrators",
                color=HELP_ADMIN_COLOR,
            )
        )

    return sections


def build_help_embed(
    *,
    title: str,
    sections: list[HelpSection],
    index: int = 0,
) -> discord.Embed:
    index = max(0, min(index, len(sections) - 1))
    return _help_embed(
        title=title,
        section=sections[index],
        index=index,
        total=len(sections),
    )


def build_simple_help_embed(
    *,
    title: str,
    description: str,
    footer: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"📖 {title}" if not title.startswith(("📖", "❓", "⚠️")) else title,
        description=description,
        color=HELP_COLOR,
    )
    if footer:
        embed.set_footer(text=footer)
    return embed


# Compatibility helpers used by older call sites / tests.
def build_help_embeds(*, prefix: str, is_admin: bool) -> list[discord.Embed]:
    sections = build_help_sections(prefix=prefix, is_admin=is_admin)
    return [build_help_embed(title="Arkann — commands", sections=sections, index=0)]


def build_sheet_help_embeds(*, prefix: str, is_admin: bool) -> list[discord.Embed]:
    sections = build_sheet_help_sections(prefix=prefix, is_admin=is_admin)
    return [build_help_embed(title="Character sheet", sections=sections, index=0)]


def build_combat_help_embeds(*, prefix: str, is_admin: bool) -> list[discord.Embed]:
    sections = build_combat_help_sections(prefix=prefix, is_admin=is_admin)
    return [build_help_embed(title="Card combat", sections=sections, index=0)]


def build_combat_help_message(*, prefix: str, is_admin: bool) -> str:
    sections = build_combat_help_sections(prefix=prefix, is_admin=is_admin)
    parts = ["**Card combat**"]
    for section in sections:
        parts.append(f"\n{section.emoji} **{section.label}**\n{section.body}")
    return "\n".join(parts)


def build_help_message(*, prefix: str, is_admin: bool) -> str:
    sections = build_help_sections(prefix=prefix, is_admin=is_admin)
    parts = ["**Arkann — commands**"]
    for section in sections:
        parts.append(f"\n{section.emoji} **{section.label}**\n{section.body}")
    return "\n".join(parts)


def build_sheet_help_message(*, prefix: str, is_admin: bool) -> str:
    sections = build_sheet_help_sections(prefix=prefix, is_admin=is_admin)
    parts = ["**Character sheet**"]
    for section in sections:
        parts.append(f"\n{section.emoji} **{section.label}**\n{section.body}")
    return "\n".join(parts)
