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
                    f"`{prefix}help sheet` · `{prefix}help combat` · `{prefix}help srd` · `{prefix}help hunger` · `/help`",
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
                    f"`{prefix}desc <text>` — narrate a scene (italic)\n"
                    f"`{prefix}image [prompt]` · `{prefix}dessine` — illustrate this channel's RP\n"
                    f"`{prefix}image` — local CPU model when ready, otherwise Pollinations\n"
                    f"`{prefix}get naked` — a gif of dismay\n"
                    f"`{prefix}time` — your campaign date (Calendar of Harptos)\n"
                    f"`{prefix}hunger` · `{prefix}faim` — hunger follows that clock",
                ),
            ),
            footer=f"Tip: {prefix}help hunger",
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
                    f"`{prefix}sheet import` — D&D Beyond PDF *(attach file; fills spells + gear)*",
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
                    f"`{prefix}roll` · `{prefix}r` — `1d20`, `athletics`, `discrétion`\n"
                    f"`adv` / `avantage` · `dis` / `désavantage` · `2d20kh1`\n"
                    "Heroic inspiration on the sheet is spent automatically on a 1d20 "
                    "(unless you already asked for advantage).",
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
            intro=f"Full guide: `{prefix}help srd`",
            fields=(
                (
                    "📖 5etools",
                    f"`{prefix}srd <type> <name>` — spell, monster, class, item…\n"
                    f"`/srd` — pick a type, then a name",
                ),
                (
                    "💻 Slash",
                    "`/srd` — pick a type, then a name",
                ),
            ),
            footer=f"Also: background, feat, armor, item · {prefix}help srd",
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
                        f"`{prefix}campaign document Titre -- texte` — parchemin illustré\n"
                        f"`{prefix}campaign forum lieux` — extra forum (defaults are created on startup)\n"
                        f"`{prefix}campaign channels` — file of every channel + category\n"
                        f"`{prefix}campaign wiki Eauprofonde` — aperçu du wiki FR des Royaumes Oubliés\n"
                        f"`{prefix}campaign import Padhiver` — cette page · `import Padhiver --liens` — + infobox\n"
                        f"`{prefix}campaign repair` — remplit « Import des liens… » et « … suite sur le wiki. »\n"
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
                        f"`{prefix}player list` · `{prefix}player sync` · `{prefix}player remove @member`",
                    ),
                    (
                        "⏳ Campaign time",
                        f"In a player section, omit @player — the channel picks the target\n"
                        f"`{prefix}time advance 2h` — every sheet · `{prefix}time advance @player 2h`\n"
                        f"`{prefix}time set 12 Hammer 1492 14:00` · `{prefix}time dawn|noon|dusk|midnight`\n"
                        "Each new calendar day ticks that player's hunger",
                    ),
                    (
                        "🍖 Hunger",
                        f"`{prefix}hunger all` — party status\n"
                        f"`{prefix}hunger eat @player` · `half` — stamp a meal on that clock\n"
                        f"`{prefix}hunger skip @player` — clock +1 day, no meal · `{prefix}hunger set @player 2`",
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
                    "Run these in that player's OOC or roleplay channel — each section has its own fight.\n"
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
                    f"`{prefix}combat board` — card dropdown, spell pages, End turn, View hand",
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
                    "• **Weapon Attack** — equipped weapon dice + ability + proficiency\n"
                    "• **Dodge** — halve all damage until your next turn",
                ),
                (
                    "✨ From your sheet",
                    f"• Spells listed in `{prefix}sheet spells`\n"
                    "• Every known spell is always in the play menu — pick a target when you cast\n"
                    "• One legal target skips the picker · extra spells paginate past Discord's 25-option cap\n"
                    "• Weapon and damaging spells roll d20 vs AC (conditions can grant adv/dis)\n"
                    "• Shield negates the next hit · Mage Armor −1d4 · Bless +1d4 damage\n"
                    "• Cantrips also appear in the draw · leveled spells use slots\n"
                    "• Attacks, heals, Dodge, and buffs (Shield, Mage Armor, Bless…)\n"
                    "• Homebrew spells get a generic attack card",
                ),
                (
                    "♻️ Discard",
                    "Played cards go to a discard pile. When the deck is empty, it is shuffled back in.",
                ),
                (
                    "🏁 Victory",
                    "Players vs monsters. Combat ends when one side is down. Attacks target the other side.",
                ),
                (
                    "❤️ HP",
                    "Player HP is shown on the board. Monster HP stays hidden. "
                    "Players at 0 HP stay in the fight and roll death saves (already on the sheet). "
                    f"`{prefix}combat add Wolf` loads the SRD profile (attack, AC, 1–2 traits). "
                    f"Damage and healing still update `{prefix}sheet hp` for players.",
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
            intro=f"Card combat uses the same turn order as `{prefix}init`. One tracker per player section.",
            fields=(
                (
                    "⚡ Commands",
                    f"`{prefix}init add @player` — rolls d20 + DEX from sheet\n"
                    f"`{prefix}init add Name 2` — NPC with a fixed bonus\n"
                    f"`{prefix}init next` — advance turn manually\n"
                    f"`{prefix}init show` — display the order\n"
                    f"`{prefix}init clear` — this player's section only",
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
                        f"Only in a player OOC/roleplay channel — FOX and MAX can fight at the same time.\n"
                        f"`{prefix}combat start` — start card combat from this section's initiative\n"
                        f"`{prefix}combat end` — stop this section's fight\n"
                        f"`{prefix}combat add Goblin` — add a monster from the SRD (HP stays hidden)\n"
                        f"`{prefix}combat add Name 30` — custom HP · `{prefix}combat add @player` — linked player",
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


def build_srd_help_sections(*, prefix: str) -> list[HelpSection]:
    return [
        _section(
            key="lookup",
            emoji="🔎",
            label="Look up rules",
            button="Lookup",
            intro="Official 2024 rules and your 5etools homebrew.",
            fields=(
                (
                    "📖 Command",
                    f"`{prefix}srd <type> <name>`",
                ),
                (
                    "✨ Magic & characters",
                    "`spell` · `class` · `species` · `background` · `feat`",
                ),
                (
                    "⚔️ Combat & gear",
                    "`monster` · `condition` · `weapon` · `armor` · `item`",
                ),
            ),
            footer=f"Example: {prefix}srd spell fireball",
            color=HELP_LOOKUP_COLOR,
        ),
        _section(
            key="search",
            emoji="💻",
            label="Search tips",
            button="Tips",
            fields=(
                (
                    "💻 Slash",
                    "`/srd` — choose a type, then start typing a name",
                ),
                (
                    "🏷️ Shortcuts",
                    f"`{prefix}srd race` → species · `{prefix}srd cond` → condition\n"
                    f"`{prefix}srd creature` → monster · `{prefix}srd gear` → item",
                ),
                (
                    "🔎 Approximate",
                    f"Partial names open a list: `{prefix}srd item potion`\n"
                    f"`{prefix}srd monster ~goblin` — list close names even if **Goblin** exists",
                ),
            ),
            footer="Partial names work · 2024 rules win over 2014 reprints",
            color=HELP_LOOKUP_COLOR,
        ),
    ]


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
                    f"`{prefix}sheet import` — D&D Beyond PDF *(attach file; fills spells + gear)*\n"
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
                    f"`{prefix}sheet gear add <name> [qty] [2kg]` · `remove` · `equip` · `show`\n"
                    f"`{prefix}sheet gear equip` updates AC from armor, shield, and Dex\n"
                    f"`{prefix}sheet gear put <item|all> in <bag|belt>` · `hold` · `belt` · `stow`\n"
                    f"`{prefix}sheet gear let <item> [qty] [at <place>] [-- note]` — leave gear\n"
                    f"`{prefix}sheet gear take <item> [qty] [at <place>]` — pick it up\n"
                    f"`{prefix}sheet gear weight <name> <kg>` — custom item weight (STR × 7.5 kg)\n"
                    f"`{prefix}sheet gear bag <name> [kg]` — mark a custom item as a bag (default 15 kg)\n"
                    "Over capacity slows speed (does not block carrying)\n"
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
                    "🍖 Hunger",
                    f"Tied to that player's `{prefix}time` clock · a meal covers that calendar day\n"
                    f"`{prefix}hunger` · `{prefix}faim` — status (3 + Con days, then 1 exhaustion/day)\n"
                    f"`{prefix}hunger eat` — consume a ration · `half` — half rations\n"
                    f"`{prefix}time advance 1d` — ticks hunger at midnight *(DM)*",
                ),
                (
                    "🏕️ Rest",
                    f"`{prefix}sheet rest short [dice]` — warlock pact slots recover\n"
                    f"`{prefix}sheet rest long` — HP, hit dice, spell slots, and +8h on that player's `{prefix}time`\n"
                    f"`{prefix}time rest long [@player]` — that player's clock +8 hours *(DM)*\n"
                    f"`{prefix}time rest long` — every character sheet *(DM)*",
                ),
                (
                    "🔎 Lookup",
                    f"`{prefix}help srd` — spells, monsters, items, conditions…",
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
                intro="Put `@player` before arguments, or run the command in that player's section.",
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


def build_hunger_help_sections(*, prefix: str, is_admin: bool) -> list[HelpSection]:
    fields: list[tuple[str, str]] = [
        (
            "🍖 Your character",
            "Hunger follows this player's campaign clock. A meal covers that calendar day; "
            "the next midnight starts a missed day.\n"
            f"`{prefix}hunger` · `{prefix}faim` — status (last meal + days without food)\n"
            f"`{prefix}hunger eat` · `manger` — eat a ration (resets hunger)\n"
            f"`{prefix}hunger half` · `demi` — half rations (counts as 0.5 day)",
        ),
        (
            "📜 PHB",
            "You can go **3 + Constitution modifier** days without food (minimum 1).\n"
            "Each day past that limit adds 1 exhaustion.",
        ),
    ]
    if is_admin:
        fields.append(
            (
                "🛡️ DM",
                f"`{prefix}time advance 1d` — ticks hunger at each new calendar day\n"
                f"`{prefix}hunger skip @player` — clock +1 day, no meal\n"
                f"`{prefix}hunger set @player 2` · `{prefix}hunger all` · `{prefix}hunger eatall`",
            )
        )
    return [
        _section(
            key="hunger",
            emoji="🍖",
            label="Hunger",
            button="Hunger",
            fields=tuple(fields),
            footer=f"Tip: {prefix}time shows hunger on the same clock",
            color=HELP_STATUS_COLOR,
        )
    ]


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
