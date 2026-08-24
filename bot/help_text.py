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
                    f"**3.** `{prefix}combat board` ou `/combat board` *(après le start)*",
                ),
                (
                    "📚 Guides",
                    f"`{prefix}help sheet` · `{prefix}help combat` · `{prefix}help srd` · `{prefix}help hunger` · `/help`\n"
                    f"`{prefix}commande -h` — l’aide de n’importe quelle commande (`--help` aussi)",
                ),
            ),
            footer="Astuce : /help et ;help c’est pareil · ;aide aussi · -h partout",
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
                    f"`{prefix}pc (action) <texte>` — action + dialogue",
                ),
                (
                    "🎬 Narration",
                    f"`{prefix}desc <texte>` — narrer une scène (italique)\n"
                    f"`{prefix}image [prompt]` · `{prefix}dessine` — illustrer le RP de ce salon\n"
                    f"`{prefix}image` — modèle local CPU s’il est prêt, sinon Pollinations\n"
                    f"`{prefix}get naked` — un gif de consternation\n"
                    f"`{prefix}time` — ta date de campagne (calendrier de Harptos)\n"
                    f"`{prefix}hunger` · `{prefix}faim` — la faim suit cette horloge",
                ),
            ),
            footer=f"Astuce : {prefix}help hunger",
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
                    f"`{prefix}sheet import` — PDF D&D Beyond *(joindre le fichier ; sorts + équipement)*",
                ),
                (
                    "❤️ En jeu",
                    f"`{prefix}sheet hp` · `money` · `gear` · `prof`\n"
                    f"`{prefix}sheet spells` · `slots` · `condition` · `rest` · `info`",
                ),
            ),
            footer=f"Astuce : {prefix}sheet slots auto",
            color=HELP_SHEET_COLOR,
        ),
        _section(
            key="combat",
            emoji="🃏",
            label="Combat à cartes",
            button="Combat",
            intro=f"Guide complet : `{prefix}help combat`",
            fields=(
                (
                    "▶️ Déroulement",
                    f"`{prefix}init add` → `{prefix}combat start` → `{prefix}combat board`\n"
                    "Les decks viennent de ta fiche et de l’export 5etools.",
                ),
                (
                    "🎯 À ton tour",
                    f"`{prefix}combat hand`\n"
                    f"`{prefix}combat play <carte> [cible]`\n"
                    f"`{prefix}combat pass`",
                ),
            ),
            footer=f"Astuce : {prefix}combat play weapon Gobelin",
            color=HELP_COMBAT_COLOR,
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
                    "L’inspiration héroïque de la fiche est dépensée automatiquement sur un 1d20 "
                    "(sauf si tu as déjà demandé l’avantage).",
                ),
                (
                    "💻 Commandes slash",
                    "`/` ouvre les mêmes commandes : `/help` · `/roll` · `/sheet show` · "
                    "`/combat board` · `/init next` · `/srd`",
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
                (
                    "💻 Slash",
                    "`/srd` — choisir un type, puis un nom",
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
                        "⚔️ Initiative & combat",
                        f"`{prefix}init remove <nom>` · `{prefix}init clear`\n"
                        f"`{prefix}combat start [monstre] [2h]` · `{prefix}combat end` · `{prefix}combat add <nom> <pv>`\n"
                        f"Voir `{prefix}help combat` pour le guide complet.",
                    ),
                    (
                        "💰 Groupe & joueurs",
                        f"`{prefix}party money set|add|spend <montant>`\n"
                        f"`{prefix}player setup @membre [nom]` — catégorie + fiche + bienvenue\n"
                        f"`{prefix}player list` · `{prefix}player sync` · `{prefix}player remove @membre`",
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


def build_combat_help_sections(*, prefix: str, is_admin: bool) -> list[HelpSection]:
    sections = [
        _section(
            key="start",
            emoji="🎯",
            label="Pour commencer",
            button="Début",
            fields=(
                (
                    "🧰 Préparer les persos",
                    f"`{prefix}sheet create <nom>` · `{prefix}sheet set class fighter`\n"
                    f"`{prefix}sheet spells add fire-bolt` — sorts de l’export 5etools\n"
                    f"`{prefix}sheet slots auto` — suivre les emplacements *(optionnel)*",
                ),
                (
                    "⚔️ Lancer le combat",
                    "Dans le salon OOC ou roleplay du joueur — chaque section a son propre combat.\n"
                    f"`{prefix}init add @joueur` · `{prefix}init add Gobelin 2`\n"
                    f"`{prefix}combat start [monstre] [2h]` — ajoute le joueur de la section, le monstre, et avance l’horloge *(staff)*\n"
                    f"`{prefix}combat board` — ouvrir la table",
                ),
            ),
            footer=f"Astuce : {prefix}init show pour voir l’ordre",
            color=HELP_COLOR,
        ),
        _section(
            key="play",
            emoji="🃏",
            label="Jouer son tour",
            button="Jouer",
            fields=(
                (
                    "🖥️ Table",
                    f"`{prefix}combat board` — menu de cartes, pages de sorts, Fin de tour, Voir la main",
                ),
                (
                    "⌨️ Commandes",
                    f"`{prefix}combat play <carte> [cible]`\n"
                    f"`{prefix}combat hand` — tes cartes actuelles\n"
                    f"`{prefix}combat pass` — finir le tour sans jouer",
                ),
                (
                    "📌 Exemples",
                    f"`{prefix}combat play weapon Gobelin`\n"
                    f"`{prefix}combat play fire-bolt Gobelin`\n"
                    f"`{prefix}combat play cure-wounds @Alice`",
                ),
            ),
            footer="Astuce : les noms de cartes suivent les sorts de l’export, ou weapon/dodge",
            color=HELP_COMBAT_COLOR,
        ),
        _section(
            key="deck",
            emoji="📚",
            label="Dans le deck",
            button="Deck",
            fields=(
                (
                    "⚔️ Toujours là",
                    "• **Attaque d’arme** — dés de l’arme équipée + caractéristique + maîtrise\n"
                    "• **Esquive** — moitié des dégâts jusqu’à ton prochain tour",
                ),
                (
                    "✨ Depuis la fiche",
                    f"• Sorts listés dans `{prefix}sheet spells`\n"
                    "• Chaque sort connu est toujours dans le menu — choisis une cible en le lançant\n"
                    "• Une seule cible légale saute le menu · les sorts en trop paginent au-delà de 25 options Discord\n"
                    "• Arme et sorts d’attaque : d20 vs CA (les états peuvent donner av/désav)\n"
                    "• Sorts à jet de sauvegarde : DD de la fiche (demi-dégâts ou état selon le sort)\n"
                    "• Bouclier annule le prochain coup · Armure du mage −1d4 · Bénédiction +1d4 dégâts\n"
                    "• Les tours de magie apparaissent aussi à la pioche · les sorts de niveau consomment des emplacements\n"
                    "• Attaques, soins, Esquive, et buffs (Bouclier, Armure du mage, Bénédiction…)\n"
                    "• Les sorts homebrew ont une carte d’attaque générique",
                ),
                (
                    "♻️ Défausse",
                    "Les cartes jouées vont à la défausse. Deck vide : on mélange et on recommence.",
                ),
                (
                    "🏁 Victoire",
                    "Joueurs contre monstres. Le combat s’arrête quand un camp est à terre. Les attaques visent l’autre camp.",
                ),
                (
                    "❤️ PV",
                    "Les PV des joueurs s’affichent. Ceux des monstres restent cachés. "
                    "Un PJ à 0 PV reste dans le combat et fait des jets de mort (déjà sur la fiche). "
                    f"`{prefix}combat add Loup` charge le profil SRD (attaque, CA, 1–2 traits). "
                    f"Dégâts et soins mettent à jour `{prefix}sheet hp` pour les joueurs.",
                ),
            ),
            footer=f"Astuce : {prefix}srd spell fireball pour voir un sort",
            color=HELP_MAGIC_COLOR,
        ),
        _section(
            key="init",
            emoji="⚡",
            label="Initiative",
            button="Init",
            intro=f"Le combat à cartes utilise le même ordre que `{prefix}init`. Un tracker par section joueur.",
            fields=(
                (
                    "⚡ Commandes",
                    f"`{prefix}init add @joueur` — d20 + DEX de la fiche\n"
                    f"`{prefix}init add Nom 2` — PNJ avec un bonus fixe\n"
                    f"`{prefix}init next` — passer le tour à la main\n"
                    f"`{prefix}init show` — afficher l’ordre\n"
                    f"`{prefix}init clear` — cette section joueur seulement",
                ),
            ),
            footer=f"Astuce : {prefix}init next marche aussi hors combat à cartes",
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
                        f"Seulement dans un salon OOC/roleplay du joueur — FOX et MAX peuvent se battre en même temps.\n"
                        f"`{prefix}combat start [monstre] [2h]` — ajoute le joueur de la section + le monstre, puis lance le combat\n"
                        f"`{prefix}combat end` — arrêter le combat de cette section\n"
                        f"`{prefix}combat add Gobelin` — ajouter un monstre SRD (PV cachés)\n"
                        f"`{prefix}combat add Nom 30` — PV perso · `{prefix}combat add @joueur` — joueur lié",
                    ),
                    (
                        "⚡ Initiative",
                        f"`{prefix}init remove <nom>` · `{prefix}init clear`",
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
                    "`spell` · `class` · `species` · `background` · `feat`",
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
                    f"`{prefix}srd creature` → monster · `{prefix}srd gear` → item",
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
                    "🎒 Équipement & compétences",
                    f"`{prefix}sheet gear` — équipement de l’export 5etools\n"
                    f"`{prefix}sheet gear add <nom> [qté] [2kg]` · `remove` · `equip` · `show`\n"
                    f"`{prefix}sheet gear equip` met à jour la CA selon armure, bouclier et Dex\n"
                    f"`{prefix}sheet gear put <objet|all> in <sac|ceinture>` · `hold` · `belt` · `stow`\n"
                    f"`{prefix}sheet gear let <objet> [qté] [at <lieu>] [-- note]` — laisser du matériel\n"
                    f"`{prefix}sheet gear take <objet> [qté] [at <lieu>]` — le reprendre\n"
                    f"`{prefix}sheet gear weight <nom> <kg>` — poids d’un objet perso (FOR × 7,5 kg)\n"
                    f"`{prefix}sheet gear bag <nom> [kg]` — marquer un objet perso comme sac (15 kg par défaut)\n"
                    "Au-delà de la capacité, la vitesse baisse (porter reste possible)\n"
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
    return [build_help_embed(title="Arkann — commandes", sections=sections, index=0)]


def build_sheet_help_embeds(*, prefix: str, is_admin: bool) -> list[discord.Embed]:
    sections = build_sheet_help_sections(prefix=prefix, is_admin=is_admin)
    return [build_help_embed(title="Fiche de personnage", sections=sections, index=0)]


def build_combat_help_embeds(*, prefix: str, is_admin: bool) -> list[discord.Embed]:
    sections = build_combat_help_sections(prefix=prefix, is_admin=is_admin)
    return [build_help_embed(title="Combat à cartes", sections=sections, index=0)]


def build_combat_help_message(*, prefix: str, is_admin: bool) -> str:
    sections = build_combat_help_sections(prefix=prefix, is_admin=is_admin)
    parts = ["**Combat à cartes**"]
    for section in sections:
        parts.append(f"\n{section.emoji} **{section.label}**\n{section.body}")
    return "\n".join(parts)


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
