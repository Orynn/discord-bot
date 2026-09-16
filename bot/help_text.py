import re
from dataclasses import dataclass

import discord

HELP_COLOR = 0xC9A227
HELP_ROLEPLAY_COLOR = 0x9B59B6
HELP_SHEET_COLOR = 0x8B0000
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


_USAGE_LABEL = re.compile(r"(?i)\b(?:usage|utilisation)\s*:\s*")
_GLUED_USAGE = re.compile(
    r"^(?P<desc>.+?[.!?])[ \t]+(?P<usage>`[^`]+`"
    r"(?:[ \t]*(?:·|•|,|ou|or)[ \t]*`[^`]+`)*)"
    r"[ \t]*(?P<rest>[^\n]*)\s*$"
)
_EXAMPLE_HEADER = re.compile(r"(?i)^(?:examples?|exemples?)\s*:?\s*$")
_FIELD_LIMIT = 1024


def command_help(description: str, usage: str, *examples: str) -> str:
    blocks = [description.strip()]
    usage = usage.strip()
    if usage:
        if not _USAGE_LABEL.match(usage):
            usage = f"Usage: {usage}"
        blocks.append(usage)
    extra = [line.strip() for line in examples if line.strip()]
    if extra:
        blocks.append("\n".join(extra))
    return "\n\n".join(blocks)


def split_command_help(text: str) -> tuple[str, str | None, tuple[str, ...]]:
    cleaned = (text or "").strip()
    if not cleaned:
        return "", None, ()

    match = _USAGE_LABEL.search(cleaned)
    if match:
        description = cleaned[: match.start()].strip()
        rest = cleaned[match.end() :].strip()
        lines = [line.strip() for line in rest.splitlines() if line.strip()]
        if lines:
            return description, lines[0], tuple(lines[1:])
        return description, None, ()

    glued = _GLUED_USAGE.match(cleaned)
    if glued:
        rest = glued.group("rest").strip()
        extras = (rest,) if rest else ()
        return glued.group("desc").strip(), glued.group("usage"), extras

    paragraphs = re.split(r"\n\s*\n", cleaned, maxsplit=1)
    description = paragraphs[0].strip()
    extras_block = paragraphs[1].strip() if len(paragraphs) > 1 else ""
    extra_lines = [line.strip() for line in extras_block.splitlines() if line.strip()]
    if extra_lines and _EXAMPLE_HEADER.match(extra_lines[0]):
        extra_lines = extra_lines[1:]
    return description, None, tuple(extra_lines)


def command_help_summary(text: str) -> str:
    description, _usage, _extras = split_command_help(text)
    if not description:
        return ""
    first = description.split("\n", 1)[0].strip()
    if len(first) > 90:
        return first[:87] + "…"
    return first


def _add_text_field(embed: discord.Embed, name: str, lines: list[str]) -> None:
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        extra = len(line) + (1 if current else 0)
        if current and size + extra > _FIELD_LIMIT:
            chunks.append("\n".join(current))
            current = [line]
            size = len(line)
        else:
            current.append(line)
            size += extra
    if current:
        chunks.append("\n".join(current))
    for index, chunk in enumerate(chunks):
        label = name if index == 0 else f"{name} (suite)"
        embed.add_field(name=label, value=chunk, inline=False)


def build_command_help_embed(
    *,
    qualified_name: str,
    help_text: str,
    usage: str,
    aliases: list[str],
    footer: str | None = None,
) -> discord.Embed:
    description, parsed_usage, extras = split_command_help(help_text)
    embed = discord.Embed(
        title=f"❓ {qualified_name}",
        description=description or None,
        color=HELP_COLOR,
    )
    embed.add_field(name="⌨️ Usage", value=parsed_usage or usage, inline=False)
    if extras:
        _add_text_field(embed, "📌 Exemples", list(extras))
    if aliases:
        embed.add_field(name="🏷️ Alias", value=", ".join(aliases), inline=False)
    embed.set_footer(text=footer or "Astuce : -h · --help · help")
    return embed


def build_group_help_embed(
    *,
    qualified_name: str,
    help_text: str,
    usage: str,
    subcommands: list[tuple[str, str]],
    aliases: list[str],
    footer: str | None = None,
) -> discord.Embed:
    description, parsed_usage, extras = split_command_help(help_text)
    embed = discord.Embed(
        title=f"❓ {qualified_name}",
        description=description or None,
        color=HELP_COLOR,
    )
    embed.add_field(name="⌨️ Usage", value=parsed_usage or usage, inline=False)
    if extras:
        _add_text_field(embed, "📌 Exemples", list(extras))
    if subcommands:
        lines = []
        for signature, summary in subcommands:
            if summary:
                lines.append(f"• {signature} — {summary}")
            else:
                lines.append(f"• {signature}")
        _add_text_field(embed, "📂 Sous-commandes", lines)
    if aliases:
        embed.add_field(name="🏷️ Alias", value=", ".join(aliases), inline=False)
    embed.set_footer(text=footer or "Astuce : -h · --help · help")
    return embed


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
    nav_hint: bool = True,
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
    if nav_hint:
        footer_parts.append("Les boutons changent de section")
    embed.set_footer(text=" · ".join(footer_parts))
    return embed


def build_help_sections(*, prefix: str, is_admin: bool) -> list[HelpSection]:
    sections = [
        _section(
            key="overview",
            emoji="📖",
            label="Pour commencer",
            button="Début",
            intro="Trois étapes pour jouer, puis ouvre un guide si besoin.",
            fields=(
                (
                    "🚀 Première session",
                    f"**1.** `{prefix}sheet create <nom>` ou `/sheet create`\n"
                    f"**2.** `{prefix}init add @toi` ou `/init add`\n"
                    f"**3.** `{prefix}init add @toi` ou `/init add`",
                ),
                (
                    "📚 Guides",
                    f"`{prefix}tuto` · `/tuto` — tutoriel pour débuter\n"
                    f"`{prefix}help sheet` · `{prefix}help srd` · `{prefix}help hunger` · `{prefix}help roleplay` · `/help`\n"
                    f"`{prefix}help all` — tout envoyer en MP\n"
                    f"`{prefix}commande -h` · `{prefix}commande --help` · `{prefix}commande help`",
                ),
            ),
            footer="Astuce : /help et ;help c’est pareil · ;help all en MP · ;aide aussi · -h / --help / help partout",
            color=HELP_COLOR,
        ),
        _section(
            key="roleplay",
            emoji="🎭",
            label="Jeu de rôle",
            button="RP",
            fields=(
                (
                    "🗣️ En personnage",
                    f"`{prefix}pcname <nom>` — nom du personnage\n"
                    f"`{prefix}pc <texte>` · `{prefix}speak` — parler en personnage\n"
                    f"`{prefix}pc (action) <texte>` — action + dialogue\n"
                    f"`{prefix}pc (action)` — comme `{prefix}desc`\n"
                    f"`{prefix}think <texte>` · `{prefix}pense` — pensée (spoilers)\n"
                    f"`{prefix}whisper @joueur <texte>` · `{prefix}chuchote` — chuchoter (MP)\n"
                    f"`{prefix}do <action>` · `{prefix}me` — action à la 3e personne\n"
                    f"`{prefix}ooc <texte>` — hors personnage",
                ),
                (
                    "🎭 Scène",
                    f"`{prefix}scene` · `{prefix}look` — carte du salon (lieu, ambiance, présents)\n"
                    f"`{prefix}scene set <titre> -- <ambiance>`\n"
                    f"`{prefix}arrive` · `{prefix}leave` — entrer / sortir\n"
                    f"`{prefix}look <cible>` · `{prefix}regarde` — regarder quelque chose",
                ),
                (
                    "🎬 Narration",
                    f"`{prefix}desc <texte>` — italique · joindre une image\n"
                    f"`{prefix}desc set <texte>` — description du salon seulement\n"
                    f"`{prefix}desc clear` — efface la description du salon\n"
                    f"`{prefix}image [prompt]` · `{prefix}dessine` — illustrer le RP de ce salon\n"
                    f"`{prefix}image` — modèle local CPU s’il est prêt, sinon Pollinations\n"
                    f"`{prefix}get naked` — un gif de consternation\n"
                    f"`{prefix}time` — ta date de campagne (calendrier de Harptos)\n"
                    f"`{prefix}hunger` · `{prefix}faim` — la faim suit cette horloge",
                ),
            ),
            footer=f"Astuce : {prefix}help roleplay",
            color=HELP_ROLEPLAY_COLOR,
        ),
        _section(
            key="sheet",
            emoji="📋",
            label="Fiche de personnage",
            button="Fiche",
            intro=f"Guide complet : `{prefix}help sheet`",
            fields=(
                (
                    "🧰 Création",
                    f"`{prefix}sheet create <nom>` · `show` · `set` · `delete`\n"
                    f"`{prefix}sheet image` — portrait *(joindre une image ou coller une URL)*\n"
                    f"`{prefix}sheet import` — PDF D&D Beyond *(joindre le fichier ; sorts + équipement)*",
                ),
                (
                    "❤️ En jeu",
                    f"`{prefix}status` · `{prefix}sheet status` — faim, repos, états, PV\n"
                    f"`{prefix}sheet hp` · `money` · `gear` · `prof`\n"
                    f"`{prefix}sheet spells` · `slots` · `condition` · `rest` · `info`",
                ),
            ),
            footer=f"Astuce : {prefix}sheet slots auto",
            color=HELP_SHEET_COLOR,
        ),
        _section(
            key="initiative",
            emoji="⚡",
            label="Initiative & groupe",
            button="Init",
            fields=(
                (
                    "⚡ Ordre de tour",
                    f"`{prefix}init add @joueur` — jet depuis la fiche\n"
                    f"`{prefix}init add Nom 2` — ajouter un PNJ (+2)\n"
                    f"`{prefix}init next` · `{prefix}init show`",
                ),
                (
                    "💰 Groupe",
                    f"`{prefix}party money show` — trésor commun",
                ),
            ),
            footer=f"Astuce : {prefix}init next",
            color=HELP_INIT_COLOR,
        ),
        _section(
            key="dice",
            emoji="🎲",
            label="Dés",
            button="Dés",
            fields=(
                (
                    "🎲 Jets",
                    f"`{prefix}roll` · `{prefix}r` — `1d20`, `athletics`, `discrétion`\n"
                    f"`adv` / `avantage` · `dis` / `désavantage` · `2d20kh1`\n"
                    f"`/roll` — options `bonus` et `avantage` / `désavantage`\n"
                    "L’inspiration héroïque de la fiche est dépensée automatiquement sur un 1d20 "
                    "(sauf si tu as déjà demandé l’avantage).\n"
                    "Un **20** naturel s’affiche en 🌟 Critique, un **1** en 💀 Échec critique.",
                ),
                (
                    "💻 Commandes slash",
                    "`/` ouvre les mêmes commandes : `/help` · `/roll` · `/sheet show` · "
                    "`/init next` · `/srd`",
                ),
            ),
            footer=f"Astuce : {prefix}roll adv perception",
            color=HELP_DICE_COLOR,
        ),
        _section(
            key="lookup",
            emoji="🔎",
            label="Règles",
            button="SRD",
            intro=f"Guide complet : `{prefix}help srd`",
            fields=(
                (
                    "📖 5etools",
                    f"`{prefix}srd <type> <name>` — sort, monstre, classe, objet…\n"
                    f"`/srd` — choisir un type, puis un nom",
                ),
            ),
            footer=f"Aussi : background, feat, armor, item · {prefix}help srd",
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
                        f"`{prefix}ai [consigne]` · `{prefix}gemini` · `{prefix}mj` — Gemini narre la scène\n"
                        f"`{prefix}ai context <texte>` · `{prefix}ai npc <nom>` — contexte MJ / PNJ\n"
                        f"`{prefix}npc <nom> <texte>` · `{prefix}say` — faire parler un PNJ\n"
                        f"`{prefix}campaign [recherche]` · `{prefix}lore` — parcourir les forums CAMPAGNE\n"
                        f"`{prefix}campaign post lieux <titre> -- <texte>` — nouveau post *(joindre une image)*\n"
                        f"`{prefix}campaign document Titre -- texte` — parchemin illustré\n"
                        f"`{prefix}campaign forum lieux` — forum en plus (les défauts sont créés au démarrage)\n"
                        f"`{prefix}campaign channels` — liste de tous les salons + catégories\n"
                        f"`{prefix}campaign wiki Eauprofonde` — aperçu du wiki FR des Royaumes Oubliés\n"
                        f"`{prefix}campaign import Padhiver` — cette page · `import Padhiver --liens` — + infobox\n"
                        f"`{prefix}campaign repair` — remplit « Import des liens… » et « … suite sur le wiki. »\n"
                        f"`{prefix}campaign move pnj Padhiver` — déplace un post et met à jour les liens\n"
                        f"`{prefix}campaign audit` — vérifie le forum de chaque post wiki (`audit fix` pour corriger)",
                    ),
                    (
                        "📋 Fiches & jets",
                        f"Mets `@joueur` avant les arguments pour une autre fiche / un autre jet\n"
                        f"`{prefix}sheet hp @Alice 12` · `{prefix}roll @Alice athletics`\n"
                        f"`{prefix}sheet money set|add @joueur <montant>`",
                    ),
                    (
                        "⚡ Initiative",
                        f"`{prefix}init remove <nom>` · `{prefix}init clear`\n"
                        f"`{prefix}init add @joueur` · `{prefix}init next` · `{prefix}init show`",
                    ),
                    (
                        "💰 Groupe & joueurs",
                        f"`{prefix}party money set|add|spend <montant>`\n"
                        f"`{prefix}player setup @membre [nom]` — catégorie + fiche + bienvenue\n"
                        f"`{prefix}player list` · `{prefix}player sync` · `{prefix}player remove @membre`\n"
                        f"`{prefix}purge` · `/purge` — vider le salon (confirmation)\n"
                        f"`{prefix}trash` · `{prefix}trash reset` — mock isolé dans `#🚯trash`",
                    ),
                    (
                        "⏳ Temps de campagne",
                        f"Dans une section joueur, omets @joueur — le salon choisit la cible\n"
                        f"`{prefix}time advance 2h` — toutes les fiches · `{prefix}time advance @joueur 2h`\n"
                        f"`{prefix}time set 12 Hammer 1492 14:00` · `{prefix}time dawn|noon|dusk|midnight`\n"
                        "Chaque nouveau jour de calendrier fait avancer la faim de ce joueur",
                    ),
                    (
                        "🍖 Faim",
                        f"`{prefix}hunger all` — état du groupe\n"
                        f"`{prefix}hunger eat @joueur` · `half` — noter un repas sur cette horloge\n"
                        f"`{prefix}hunger skip @joueur` — horloge +1 jour, sans repas · `{prefix}hunger set @joueur 2`",
                    ),
                ),
                footer="Visible seulement pour le staff",
                color=HELP_ADMIN_COLOR,
            )
        )

    return sections


def build_srd_help_sections(*, prefix: str) -> list[HelpSection]:
    return [
        _section(
            key="lookup",
            emoji="🔎",
            label="Chercher une règle",
            button="Recherche",
            intro="Règles officielles 2024 et ton homebrew 5etools.",
            fields=(
                (
                    "📖 Commande",
                    f"`{prefix}srd <type> <name>`",
                ),
                (
                    "✨ Magie & persos",
                    "`spell` · `class` · `subclass` · `species` · `background` · `feat`",
                ),
                (
                    "⚔️ Combat & matériel",
                    "`monster` · `condition` · `weapon` · `armor` · `item`",
                ),
            ),
            footer=f"Exemple : {prefix}srd spell fireball",
            color=HELP_LOOKUP_COLOR,
        ),
        _section(
            key="search",
            emoji="💻",
            label="Astuces de recherche",
            button="Astuces",
            fields=(
                (
                    "💻 Slash",
                    "`/srd` — choisir un type, puis taper un nom",
                ),
                (
                    "🏷️ Raccourcis",
                    f"`{prefix}srd race` → species · `{prefix}srd cond` → condition\n"
                    f"`{prefix}srd creature` → monster · `{prefix}srd gear` → item\n"
                    f"`{prefix}srd archetype` → subclass",
                ),
                (
                    "🔎 Approximatif",
                    f"Un nom partiel ouvre une liste : `{prefix}srd item potion`\n"
                    f"`{prefix}srd monster ~goblin` — noms proches même si **Goblin** existe",
                ),
            ),
            footer="Les noms partiels marchent · les règles 2024 priment sur les reprints 2014",
            color=HELP_LOOKUP_COLOR,
        ),
    ]


def build_sheet_help_sections(*, prefix: str, is_admin: bool) -> list[HelpSection]:
    sections = [
        _section(
            key="setup",
            emoji="🧰",
            label="Création",
            button="Création",
            fields=(
                (
                    "📋 Personnage",
                    f"`{prefix}sheet create <nom>` — créer\n"
                    f"`{prefix}sheet import` — PDF D&D Beyond *(joindre le fichier ; sorts + équipement)*\n"
                    f"`{prefix}sheet show` — afficher\n"
                    f"`{prefix}sheet delete` — supprimer",
                ),
                (
                    "✏️ Modifier",
                    f"`{prefix}sheet set <champ> <valeur>` — nom, espèce, classe, niveau, caracs…\n"
                    f"`{prefix}sheet image` — joindre une image, ou `{prefix}sheet image <url>` · `clear`\n"
                    f"`{prefix}sheet info` — infos 5etools pour espèce / classe / historique",
                ),
            ),
            color=HELP_SHEET_COLOR,
        ),
        _section(
            key="resources",
            emoji="💰",
            label="Ressources",
            button="Matos",
            fields=(
                (
                    "❤️ Survie",
                    f"`{prefix}sheet hp <actuel> [max]` — points de vie\n"
                    f"`{prefix}sheet money` — bourse (`show` / `spend` / `pay`)",
                ),
                (
                    "🎒 Équipement",
                    f"`{prefix}sheet gear` — inventaire de l’export 5etools\n"
                    f"`{prefix}sheet gear add <nom> [qté] [2kg]` — catalogue · `{prefix}sheet gear custom` — perso\n"
                    f"`{prefix}sheet gear bag <nom> [20kg]` — créer un sac perso (15 kg par défaut)\n"
                    f"`equip` · `unequip` · `remove` · `show` · `weight`\n"
                    f"`{prefix}sheet gear equip` met à jour la CA (armure, bouclier, Dex)\n"
                    f"`put <objet|all> in <sac|ceinture>` · `hold` · `belt` · `stow`\n"
                    f"`{prefix}sheet gear let <objet|all> [qté] [at <lieu>] [-- note]` — laisser du matériel\n"
                    f"`{prefix}sheet gear take <objet> [qté] [at <lieu>]` — le reprendre\n"
                    "Trop chargé : la vitesse baisse, mais on peut encore porter",
                ),
                (
                    "🎯 Compétences",
                    f"`{prefix}sheet prof save <carac>` — maîtrise de sauvegarde\n"
                    f"`{prefix}sheet prof skill <compétence> [expertise]` — maîtrise de compétence",
                ),
            ),
            color=HELP_COLOR,
        ),
        _section(
            key="magic",
            emoji="✨",
            label="Magie",
            button="Magie",
            fields=(
                (
                    "📖 Sorts",
                    f"`{prefix}sheet spells` — sorts connus\n"
                    f"`{prefix}sheet spells add|remove|show <nom>`",
                ),
                (
                    "🔮 Emplacements",
                    f"`{prefix}sheet slots` — suivi des emplacements\n"
                    f"`{prefix}sheet slots use <niveau> [nombre]` — ex. : `{prefix}sheet slots use 1`\n"
                    f"`{prefix}sheet slots recover` · `set` · `auto` (PHB selon classe/niveau)",
                ),
            ),
            color=HELP_MAGIC_COLOR,
        ),
        _section(
            key="status",
            emoji="❤️",
            label="États & repos",
            button="États",
            fields=(
                (
                    "📌 États",
                    f"`{prefix}status` · `{prefix}sheet status` — récap PV, faim, repos, conditions\n"
                    f"`{prefix}sheet condition <nom>` — activer/désactiver un état\n"
                    f"`{prefix}sheet inspire` — inspiration héroïque\n"
                    f"`{prefix}sheet deathsave success|failure`",
                ),
                (
                    "🍖 Faim",
                    f"Liée à l’horloge `{prefix}time` de ce joueur · un repas couvre ce jour de calendrier\n"
                    f"`{prefix}hunger` · `{prefix}faim` — état (3 + Con jours, puis 1 épuisement/jour)\n"
                    f"`{prefix}hunger eat` — manger une ration · `half` — demi-rations\n"
                    f"`{prefix}time advance 1d` — avance la faim à minuit *(MJ)*",
                ),
                (
                    "🏕️ Repos",
                    f"`{prefix}sheet rest short [dés]` — les emplacements de pacte du warlock reviennent\n"
                    f"`{prefix}sheet rest long` — PV, dés de vie, emplacements, et +8 h sur le `{prefix}time` de ce joueur\n"
                    f"`{prefix}time rest long [@joueur]` — horloge de ce joueur +8 heures *(MJ)*\n"
                    f"`{prefix}time rest long` — toutes les fiches *(MJ)*",
                ),
                (
                    "🔎 Recherche",
                    f"`{prefix}help srd` — sorts, monstres, objets, états…",
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
                intro="Mets `@joueur` avant les arguments, ou lance la commande dans sa section.",
                fields=(
                    (
                        "👤 Autres joueurs",
                        f"`{prefix}sheet show @Alice` · `{prefix}sheet hp @Alice 12` · `{prefix}sheet slots use @Alice 1`\n"
                        f"`{prefix}sheet money set|add @joueur <montant>`\n"
                        f"`{prefix}sheet create @joueur <nom>` · `{prefix}sheet import @joueur` · `{prefix}sheet delete @joueur`",
                    ),
                ),
                footer="Visible seulement pour le staff",
                color=HELP_ADMIN_COLOR,
            )
        )

    return sections


def build_hunger_help_sections(*, prefix: str, is_admin: bool) -> list[HelpSection]:
    fields: list[tuple[str, str]] = [
        (
            "🍖 Ton personnage",
            "La faim suit l’horloge de campagne de ce joueur. Un repas couvre ce jour de calendrier ; "
            "le minuit suivant commence un jour manqué.\n"
            f"`{prefix}hunger` · `{prefix}faim` — état (dernier repas + jours sans manger)\n"
            f"`{prefix}hunger eat` · `manger` — manger une ration (remet la faim à zéro)\n"
            f"`{prefix}hunger half` · `demi` — demi-rations (compte pour 0,5 jour)",
        ),
        (
            "📜 PHB",
            "Tu tiens **3 + modificateur de Constitution** jours sans manger (minimum 1).\n"
            "Chaque jour au-delà ajoute 1 épuisement.",
        ),
    ]
    if is_admin:
        fields.append(
            (
                "🛡️ MJ",
                f"`{prefix}time advance 1d` — avance la faim à chaque nouveau jour de calendrier\n"
                f"`{prefix}hunger skip @joueur` — horloge +1 jour, sans repas\n"
                f"`{prefix}hunger set @joueur 2` · `{prefix}hunger all` · `{prefix}hunger eatall`",
            )
        )
    return [
        _section(
            key="hunger",
            emoji="🍖",
            label="Faim",
            button="Faim",
            fields=tuple(fields),
            footer=f"Astuce : {prefix}time affiche la faim sur la même horloge",
            color=HELP_STATUS_COLOR,
        )
    ]


def build_help_embed(
    *,
    title: str,
    sections: list[HelpSection],
    index: int = 0,
    nav_hint: bool = True,
) -> discord.Embed:
    index = max(0, min(index, len(sections) - 1))
    return _help_embed(
        title=title,
        section=sections[index],
        index=index,
        total=len(sections),
        nav_hint=nav_hint,
    )


HELP_ALL_TOPICS = frozenset({"all", "tout", "toutes", "everything"})
ROLEPLAY_HELP_TOPICS = frozenset({"roleplay", "rp", "jdr"})


def is_roleplay_help_topic(query: str | None) -> bool:
    return (query or "").strip().casefold() in ROLEPLAY_HELP_TOPICS


AI_HELP_TOPICS = frozenset({"ai", "gemini", "mj"})
TUTO_HELP_TOPICS = frozenset({"tuto", "tutoriel", "guide", "debut", "début", "start"})


def is_ai_help_topic(query: str | None) -> bool:
    return (query or "").strip().casefold() in AI_HELP_TOPICS


def is_tuto_help_topic(query: str | None) -> bool:
    return (query or "").strip().casefold() in TUTO_HELP_TOPICS


def build_ai_help_sections(*, prefix: str) -> list[HelpSection]:
    return [
        _section(
            key="ai",
            emoji="✨",
            label="Gemini",
            button="IA",
            fields=(
                (
                    "📖 Narrer",
                    f"`{prefix}ai` · `{prefix}ai continue` — un souffle (carte + 20 derniers messages)\n"
                    f"`{prefix}ai un orage éclate` — même chose, avec ta consigne\n"
                    f"`{prefix}ai un orage -- Ils ont volé le sceau` — consigne + contexte de cette fois\n"
                    f"`{prefix}ai --no-context <consigne>` — description du salon + consigne, sans le fil\n"
                    f"`{prefix}gemini` · `{prefix}mj` — mêmes commandes",
                ),
                (
                    "📝 Contexte MJ",
                    f"`{prefix}ai context <texte>` · `{prefix}ai contexte` — à retenir pour ce salon\n"
                    f"`{prefix}ai context` — afficher · `{prefix}ai context clear` — effacer",
                ),
                (
                    "🗣️ PNJ",
                    f"`{prefix}ai npc <nom> [consigne]` — réplique au format `{prefix}npc`\n"
                    f"`{prefix}ai npc Garret un tavernier méfiant`",
                ),
                (
                    "⌨️ Aide",
                    f"`{prefix}ai -h` · `{prefix}ai --help` · `{prefix}ai help` · `{prefix}help ai`\n"
                    "Gemini voit le lieu, l’ambiance, le canon CAMPAIGN, le contexte MJ, "
                    "les présents et l’horloge. Il n’invente pas de jet et ne touche pas aux fiches.",
                ),
            ),
            footer="Staff seulement · clé : GEMINI_API_KEY · modèle : gemini-3.5-flash",
            color=HELP_ROLEPLAY_COLOR,
        )
    ]


def build_roleplay_help_sections(*, prefix: str) -> list[HelpSection]:
    return [
        _section(
            key="speech",
            emoji="🗣️",
            label="Parler en personnage",
            button="Parler",
            fields=(
                (
                    "💬 Dialogue",
                    f"`{prefix}sheet create <nom>` ou `{prefix}pcname <nom>` — une fois, puis le nom suit\n"
                    f"`{prefix}pc <texte>` · `{prefix}speak` — parle, la commande disparaît\n"
                    f"`{prefix}pc (sourire) Bonsoir.` — action + réplique\n"
                    f"`{prefix}pc (ouvre la porte)` — parenthèses seules = `{prefix}desc`",
                ),
                (
                    "🤫 À part",
                    f"`{prefix}think <texte>` · `{prefix}pense` — pensée en spoilers\n"
                    f"`{prefix}whisper @joueur <texte>` · `{prefix}chuchote Aelric …` — teaser public, texte en MP\n"
                    f"`{prefix}do <action>` · `{prefix}me` · `{prefix}agir` — *Nom fait ceci.*\n"
                    f"`{prefix}ooc <texte>` — clairement hors jeu",
                ),
            ),
            footer=f"Astuce : {prefix}arrive t’ajoute à la carte de scène",
            color=HELP_ROLEPLAY_COLOR,
        ),
        _section(
            key="scene",
            emoji="🎭",
            label="Tenir la scène",
            button="Scène",
            fields=(
                (
                    "📍 Carte du salon",
                    f"`{prefix}scene` · `{prefix}look` — lieu, ambiance, présents, horloge de campagne\n"
                    f"`{prefix}scene set La taverne -- feu de cheminée, odeur de rhum`\n"
                    f"`{prefix}scene mood <ambiance>` · `{prefix}scene note <texte>` · `{prefix}scene clear`",
                ),
                (
                    "🚶 Présence",
                    f"`{prefix}arrive` · `{prefix}ici` — entrer (option : `{prefix}arrive par le balcon`)\n"
                    f"`{prefix}leave` · `{prefix}pars` — sortir\n"
                    f"`{prefix}look la porte` · `{prefix}regarde` — regarder sans ouvrir la carte\n"
                    f"`{prefix}pc` / `{prefix}think` / `{prefix}do` t’ajoutent aussi parmi les présents",
                ),
            ),
            footer="Chaque salon a sa propre scène",
            color=HELP_ROLEPLAY_COLOR,
        ),
        _section(
            key="table",
            emoji="🎬",
            label="Autour de la table",
            button="Table",
            fields=(
                (
                    "🖼️ Décrire",
                    f"`{prefix}desc <texte>` — italique · joindre une image\n"
                    f"`{prefix}desc set <texte>` — description du salon seulement\n"
                    f"`{prefix}desc clear` — efface la description du salon\n"
                    f"`{prefix}image` · `{prefix}dessine` — illustrer le fil de ce salon\n"
                    f"`{prefix}get naked` — consternation",
                ),
                (
                    "⏳ Monde",
                    f"`{prefix}time` — date de Harptos de ce joueur\n"
                    f"`{prefix}hunger` · `{prefix}faim` — la faim suit cette horloge\n"
                    f"`{prefix}npc <nom> <texte>` — faire parler un PNJ *(staff)*\n"
                    f"`{prefix}ai [consigne]` · `{prefix}ai context` · `{prefix}ai npc <nom>` — Gemini *(staff)*",
                ),
            ),
            footer=f"Guide court : {prefix}help · tout en MP : {prefix}help all",
            color=HELP_ROLEPLAY_COLOR,
        ),
    ]


def build_tuto_help_sections(*, prefix: str) -> list[HelpSection]:
    return [
        _section(
            key="principle",
            emoji="🎲",
            label="Le principe",
            button="Principe",
            intro=(
                "D&D, c’est une histoire improvisée à plusieurs : le MJ pose le décor, "
                "tu incarnes ton personnage et tu dis ce qu’il fait ou dit. "
                "Arkann t’aide sur Discord — fiche, dés, initiative, narration."
            ),
            fields=(
                (
                    "🏠 Les salons",
                    "Chaque salon RP a sa **scène** : lieu, ambiance, qui est présent. "
                    f"Regarde avec `{prefix}scene` ou `/scene`.\n"
                    "Les commandes commencent par `;` ou `/`. "
                    "Souvent, ta commande disparaît après usage pour garder le fil lisible.",
                ),
                (
                    "🎭 Deux registres",
                    f"**En jeu** — `{prefix}pc`, `{prefix}do`, `{prefix}desc` : tu joues ton personnage.\n"
                    f"**Hors jeu** — `{prefix}ooc` : question ou remarque entre joueurs, hors narration.",
                ),
            ),
            footer=f"Suite : bouton **Jouer** · aide complète : `{prefix}help` ou `/help`",
            color=HELP_ROLEPLAY_COLOR,
        ),
        _section(
            key="play",
            emoji="🗣️",
            label="Jouer en personnage",
            button="Jouer",
            intro="Crée ton personnage une fois, puis parle et agis dans le salon RP.",
            fields=(
                (
                    "👤 Ton personnage",
                    f"`{prefix}sheet create <nom>` ou `/sheet create` — créer la fiche\n"
                    f"`{prefix}sheet import` — PDF D&D Beyond *(joindre le fichier)*\n"
                    f"`{prefix}pcname <nom>` — nom affiché si tu n’as pas encore de fiche",
                ),
                (
                    "💬 Parler & agir",
                    f"`{prefix}pc <texte>` ou `/pc` — dialogue en personnage\n"
                    f"`{prefix}pc (sourire) Bonjour.` — action + réplique\n"
                    f"`{prefix}pc (ouvre la porte)` — action seule *(comme `{prefix}desc`)*\n"
                    f"`{prefix}do <action>` · `{prefix}me` — *Nom fait ceci.*\n"
                    f"`{prefix}think <texte>` — pensée en spoilers\n"
                    f"`{prefix}whisper @joueur <texte>` — chuchoter *(MP)*",
                ),
                (
                    "📍 Scène",
                    f"`{prefix}arrive` — annoncer ta présence\n"
                    f"`{prefix}scene` · `{prefix}look` — carte du salon\n"
                    f"`{prefix}desc <texte>` — décrire l’ambiance *(MJ ou table)*",
                ),
            ),
            footer=f"Guide RP : `{prefix}help roleplay`",
            color=HELP_ROLEPLAY_COLOR,
        ),
        _section(
            key="sheet",
            emoji="📋",
            label="Fiche & dés",
            button="Fiche",
            intro="Ta fiche suit tes PV, ton équipement et tes bonus de jets.",
            fields=(
                (
                    "📖 Consulter",
                    f"`{prefix}sheet show` ou `/sheet show` — afficher la fiche\n"
                    f"`{prefix}status` — récap PV, faim, repos, conditions",
                ),
                (
                    "🎲 Lancer les dés",
                    f"`{prefix}roll 1d20` ou `/roll` — jet simple\n"
                    f"`{prefix}roll athletics` · `{prefix}roll discrétion` — compétence *(bonus auto)*\n"
                    f"`{prefix}roll adv perception` — avec avantage\n"
                    f"`{prefix}roll dex save` — sauvegarde",
                ),
                (
                    "❤️ En jeu",
                    f"`{prefix}sheet hp <actuel> [max]` — mettre à jour les PV\n"
                    f"`{prefix}sheet rest short` · `{prefix}sheet rest long` — repos",
                ),
            ),
            footer=f"Guide fiche : `{prefix}help sheet`",
            color=HELP_SHEET_COLOR,
        ),
        _section(
            key="init",
            emoji="⚡",
            label="Initiative & suite",
            button="Init",
            intro="L’initiative suit l’ordre des tours dans ta section joueur.",
            fields=(
                (
                    "⚡ Initiative",
                    f"`{prefix}init add @toi` ou `/init add` — entrer dans l’ordre *(d20 + DEX)*\n"
                    f"`{prefix}init show` — voir l’ordre · `{prefix}init next` — tour suivant",
                ),
                (
                    "📚 Règles & faim",
                    f"`{prefix}srd spell fireball` ou `/srd` — chercher une règle\n"
                    f"`{prefix}time` — date de campagne · `{prefix}hunger` — la faim suit l’horloge",
                ),
            ),
            footer=f"Guides : `{prefix}help srd` · `{prefix}help all` en MP",
            color=HELP_INIT_COLOR,
        ),
    ]


_DISCORD_MESSAGE_EMBED_LIMIT = 10
_DISCORD_MESSAGE_CHAR_LIMIT = 5500


def is_help_all_topic(query: str | None) -> bool:
    return (query or "").strip().casefold() in HELP_ALL_TOPICS


def embed_text_length(embed: discord.Embed) -> int:
    total = 0
    if embed.title:
        total += len(embed.title)
    if embed.description:
        total += len(embed.description)
    if embed.footer.text:
        total += len(embed.footer.text)
    if embed.author.name:
        total += len(embed.author.name)
    for field in embed.fields:
        total += len(field.name) + len(field.value)
    return total


def pack_embed_batches(
    embeds: list[discord.Embed],
    *,
    max_embeds: int = _DISCORD_MESSAGE_EMBED_LIMIT,
    max_chars: int = _DISCORD_MESSAGE_CHAR_LIMIT,
) -> list[list[discord.Embed]]:
    batches: list[list[discord.Embed]] = []
    current: list[discord.Embed] = []
    size = 0
    for embed in embeds:
        length = embed_text_length(embed)
        if current and (len(current) >= max_embeds or size + length > max_chars):
            batches.append(current)
            current = []
            size = 0
        current.append(embed)
        size += length
    if current:
        batches.append(current)
    return batches


def build_guide_help_embeds(*, prefix: str, is_admin: bool) -> list[discord.Embed]:
    catalogs = (
        ("Arkann — commandes", build_help_sections(prefix=prefix, is_admin=is_admin)),
        (
            "Fiche de personnage",
            build_sheet_help_sections(prefix=prefix, is_admin=is_admin),
        ),
        ("Recherche de règles", build_srd_help_sections(prefix=prefix)),
        ("Faim", build_hunger_help_sections(prefix=prefix, is_admin=is_admin)),
        ("Jeu de rôle", build_roleplay_help_sections(prefix=prefix)),
    )
    if is_admin:
        catalogs = (
            *catalogs,
            ("Gemini", build_ai_help_sections(prefix=prefix)),
        )
    embeds: list[discord.Embed] = []
    for title, sections in catalogs:
        for index in range(len(sections)):
            embeds.append(
                build_help_embed(
                    title=title,
                    sections=sections,
                    index=index,
                    nav_hint=False,
                )
            )
    return embeds


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
    return [build_help_embed(title="Arkann — commandes", sections=sections, index=0)]


def build_sheet_help_embeds(*, prefix: str, is_admin: bool) -> list[discord.Embed]:
    sections = build_sheet_help_sections(prefix=prefix, is_admin=is_admin)
    return [build_help_embed(title="Fiche de personnage", sections=sections, index=0)]


def build_help_message(*, prefix: str, is_admin: bool) -> str:
    sections = build_help_sections(prefix=prefix, is_admin=is_admin)
    parts = ["**Arkann — commandes**"]
    for section in sections:
        parts.append(f"\n{section.emoji} **{section.label}**\n{section.body}")
    return "\n".join(parts)


def build_sheet_help_message(*, prefix: str, is_admin: bool) -> str:
    sections = build_sheet_help_sections(prefix=prefix, is_admin=is_admin)
    parts = ["**Fiche de personnage**"]
    for section in sections:
        parts.append(f"\n{section.emoji} **{section.label}**\n{section.body}")
    return "\n".join(parts)
