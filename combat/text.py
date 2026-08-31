from __future__ import annotations

from config import PREFIX

CONDITION_FR = {
    "poisoned": "empoisonné",
    "frightened": "effrayé",
    "blinded": "aveuglé",
    "restrained": "entravé",
    "prone": "à terre",
    "paralyzed": "paralysé",
    "unconscious": "inconscient",
    "stunned": "étourdi",
    "incapacitated": "incapacité",
    "grappled": "agrippé",
}


def condition_fr(key: str) -> str:
    return CONDITION_FR.get(key.lower(), key)


def combatant_missing(name: str) -> str:
    return f"Combattant **{name}** introuvable."


def not_your_turn(name: str) -> str:
    return f"C’est le tour de **{name}**."


def already_acted(name: str) -> str:
    return (
        f"**{name}** a déjà utilisé son action ce tour. "
        "Déplace-toi ou termine le tour."
    )


def already_attacked(name: str) -> str:
    return f"**{name}** a déjà attaqué ce tour."


def no_combat() -> str:
    return "Aucun combat en cours."


def no_active() -> str:
    return "Aucun combattant actif."


def not_in_combat() -> str:
    return "Tu n’es pas dans ce combat."


def only_controller(name: str) -> str:
    return f"Seul le MJ ou ce joueur peut jouer **{name}**."


def unknown_card(labels: str) -> str:
    return f"Carte inconnue. Ta main : {labels}"


def combat_ended() -> str:
    return "Combat terminé."


def play_in_browser(url: str | None) -> str:
    if url:
        return f"Le combat se joue dans le navigateur : {url}"
    return (
        "Le combat se joue dans le navigateur. "
        f"Ouvre le plateau via `{PREFIX}combat board` (Arkann doit être allumé)."
    )


def discord_board_unavailable() -> str:
    return (
        "Impossible de mettre à jour le message Discord pour le moment. "
        f"Réessaie `{PREFIX}combat board`."
    )


def combat_started() -> str:
    return "Le combat commence — déplace-toi, puis une action (attaque ou carte)."


def turn_passed(name: str) -> str:
    return f"Au tour de **{name}**."


def ends_turn(name: str) -> str:
    return f"**{name}** termine son tour."


def moves_to(name: str, cell: str, left: int) -> str:
    return f"**{name}** se déplace en **{cell}** ({left} cases restantes)."


def party_wins() -> str:
    return "Le groupe remporte le combat !"


def monsters_win() -> str:
    return "Les monstres remportent le combat !"


def named_wins(name: str) -> str:
    return f"**{name}** remporte le combat !"


def no_survivors() -> str:
    return "Tout le monde est à terre — le combat s’arrête."


def defeated(name: str) -> str:
    return f"**{name}** est vaincu !"


def drops_dying(name: str) -> str:
    return f"**{name}** tombe à 0 PV et est mourant."


def dies(name: str) -> str:
    return f"**{name}** meurt."


def stable(name: str) -> str:
    return f"**{name}** est stable."


def dying_skip(name: str, prefix: str) -> str:
    return (
        f"**{name}** est mourant et passe son tour. "
        f"Soigne-le avec `{prefix}sheet hp` ou un sort de soin."
    )


def skips_condition(name: str, key: str) -> str:
    return f"**{name}** est {condition_fr(key)} et passe son tour."


def skips_stable(name: str) -> str:
    return f"**{name}** est stable et passe son tour."


def opportunity(attacker: str, mover: str) -> str:
    return f"**{mover}** quitte la mêlée : **{attacker}** porte une attaque d’opportunité."


def concentration_lost(name: str, reason: str) -> str:
    return f"**{name}** perd sa concentration ({reason})."


def concentration_held(name: str) -> str:
    return f"**{name}** maintient sa concentration."


def aoe_empty(actor: str, label: str, cell: str) -> str:
    return f"**{actor}** lance **{label}** sur **{cell}** — personne dans la zone."


def pick_enemy() -> str:
    return "Choisis une cible ennemie."


def pick_ally() -> str:
    return "Choisis une cible alliée."


def cannot_attack_self() -> str:
    return "Tu ne peux pas t’attaquer toi-même."


def out_of_range(name: str, dest: str, reach: str) -> str:
    return f"**{name}** est hors de portée ({dest}, {reach}). Approche-toi."


def cannot_reach(cell: str) -> str:
    return f"Impossible d’atteindre {cell} — bloqué ou hors carte."


def not_enough_move(cost: int, cell: str, left: int) -> str:
    return f"Pas assez de mouvement ({cost} cases jusqu’à {cell}, {left} restantes)."


def cannot_move(key: str) -> str:
    return f"Impossible de se déplacer ({condition_fr(key)})."


_LOG_STYLES: tuple[tuple[str, str, str], ...] = (
    ("remporte", "win", "🏆"),
    ("commence", "start", "⚔️"),
    ("personne dans la zone", "miss", "💨"),
    ("attaque d’opportunité", "attack", "⚡"),
    ("opportunité", "attack", "⚡"),
    ("jet de mort", "save", "🎲"),
    ("vaincu", "down", "💀"),
    ("meurt", "down", "💀"),
    ("mourant", "down", "☠️"),
    ("stable", "heal", "💚"),
    ("soigne", "heal", "💚"),
    ("se déplace", "move", "👟"),
    ("raté", "miss", "💨"),
    ("esquive", "buff", "🛡️"),
    ("concentration", "focus", "🔮"),
    ("termine son tour", "turn", "⏭️"),
    ("au tour de", "turn", "➤"),
    ("passe son tour", "turn", "⏭️"),
    ("résiste", "miss", "🛡️"),
    ("lance", "spell", "✨"),
    ("attaque", "attack", "⚔️"),
    ("dégâts", "attack", "💥"),
    ("touché", "spell", "✨"),
)


def classify_log_line(line: str) -> tuple[str, str]:
    text = line.lower()
    for needle, kind, emoji in _LOG_STYLES:
        if needle in text:
            return kind, emoji
    return "note", "•"


def format_log_line(line: str) -> str:
    _kind, emoji = classify_log_line(line)
    return f"{emoji} {line}"
