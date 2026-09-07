import re
from dataclasses import dataclass

from bot.speech import parse_dialogue

_PROMPT_SEPARATORS = (" -- ", " — ", " – ")
_NO_CONTEXT_FLAGS = frozenset({"--no-context", "--nocontext", "--sans-contexte", "-nc"})

SYSTEM_NARRATE = (
    "Tu es le maître du jeu d’une table D&D 5e francophone "
    "(Royaumes Oubliés, calendrier de Harptos).\n"
    "Tu écris uniquement de la fiction : narration sensorielle, PNJ, conséquences.\n"
    "Interdit : inventer un résultat de dé ; demander un jet de dé "
    "(compétence, sauvegarde, attaque, initiative) ; dire au joueur de lancer "
    "les dés ou d’utiliser une commande de jet ; modifier une fiche, l’inventaire, "
    "les PV, l’or ou la faim ; dire que tu es une IA ; mettre un titre.\n"
    "Si une action serait incertaine, décris seulement ce qui est visible ou "
    "possible. Ne résous rien par un jet : le MJ s’en charge.\n"
    "Appuie-toi sur le canon CAMPAIGN, le contexte MJ et les derniers messages "
    "du salon pour la continuité.\n"
    "Le canon CAMPAIGN et le contexte MJ font autorité : ne les contredis pas.\n"
    "Réponds en français, présent de narration, sans préambule, moins de 1200 caractères."
)

SYSTEM_NPC = (
    "Tu incarnes un PNJ de D&D 5e. Tu parles uniquement en personnage.\n"
    "Réponds exactement dans ce format, rien d’autre :\n"
    "(action courte optionnelle)\n"
    "réplique parlée\n"
    "Interdit : inventer un jet de dé, demander un jet, sortir du personnage, "
    "mentionner une IA.\n"
    "Tiens compte du canon CAMPAIGN, du contexte MJ et des derniers messages du salon."
)

_ROLL_ASK = re.compile(
    r"(?i)\b("
    r"fais(?:ez)? un jet|faites un jet|"
    r"lance(?:r|z)? (?:un )?(?:dé|d20|jet)|"
    r"jette(?:r|z)? un (?:dé|d20)|"
    r"jet de (?:force|dextérité|constitution|intelligence|sagesse|charisme|"
    r"survie|perception|discrétion|athlétisme|acrobatie|intimidation|"
    r"persuasion|tromperie|histoire|investigation|médecine|nature|"
    r"dressage|représentation|religion|arcane|sauvegarde)|"
    r"commande de jet|"
    r"`?<?;?(?:roll|jet|check)\b"
    r")"
)


@dataclass(frozen=True)
class SceneBrief:
    title: str = ""
    mood: str = ""
    note: str = ""
    present: tuple[str, ...] = ()
    clock: str = ""
    place: str = ""
    context: str = ""
    lore: str = ""
    lines: tuple[str, ...] = ()


def format_scene_brief(brief: SceneBrief) -> str:
    parts: list[str] = []
    if brief.title:
        parts.append(f"Lieu : {brief.title}")
    if brief.mood:
        parts.append(f"Ambiance : {brief.mood}")
    if brief.note:
        parts.append(f"Note : {brief.note}")
    if brief.present:
        parts.append("Présents : " + ", ".join(brief.present))
    if brief.clock:
        parts.append(f"Temps : {brief.clock}")
    if brief.place and brief.place.casefold() != brief.title.casefold():
        if brief.title or brief.mood or brief.note or brief.present or brief.lines:
            parts.append(f"Salon : {brief.place}")
        else:
            parts.append(f"Description du salon :\n{brief.place}")
    if brief.context:
        parts.append(f"Contexte MJ :\n{brief.context}")
    if brief.lore:
        parts.append(f"Canon CAMPAIGN :\n{brief.lore}")
    if brief.lines:
        parts.append(
            f"Derniers messages ({len(brief.lines)}) :\n" + "\n".join(brief.lines)
        )
    return "\n".join(parts) if parts else "Aucune scène posée."


def parse_ai_prompt(text: str) -> tuple[str, str]:
    cleaned = text.strip()
    if not cleaned:
        return "", ""
    for prefix in ("-- ", "— ", "– "):
        if cleaned.startswith(prefix):
            return "", cleaned[len(prefix) :].strip()
    for separator in _PROMPT_SEPARATORS:
        if separator in cleaned:
            left, right = cleaned.split(separator, 1)
            return left.strip(), right.strip()
    return cleaned, ""


def strip_ai_flags(text: str) -> tuple[str, bool]:
    tokens = text.split()
    no_context = False
    kept: list[str] = []
    for token in tokens:
        if token.casefold() in _NO_CONTEXT_FLAGS:
            no_context = True
            continue
        kept.append(token)
    return " ".join(kept), no_context


def parse_ai_request(text: str) -> tuple[str, str, bool]:
    remainder, no_context = strip_ai_flags(text)
    instruction, extra = parse_ai_prompt(remainder)
    if no_context:
        return instruction, "", True
    return instruction, extra, False


def merge_ai_context(*chunks: str) -> str:
    return "\n\n".join(part.strip() for part in chunks if part and part.strip())


def build_narrate_prompt(brief: SceneBrief, instruction: str) -> str:
    scene = format_scene_brief(brief)
    cleaned = instruction.strip()
    if cleaned:
        return f"{scene}\n\nConsigne du MJ / joueur : {cleaned}"
    return (
        f"{scene}\n\n"
        "Continue la scène d’un souffle : ce qui se passe maintenant autour des présents."
    )


def build_npc_prompt(brief: SceneBrief, *, name: str, instruction: str) -> str:
    scene = format_scene_brief(brief)
    cleaned = instruction.strip()
    extra = f"\nConsigne : {cleaned}" if cleaned else ""
    return f"{scene}\n\nPNJ : {name}{extra}\nParle."


def parse_npc_reply(text: str) -> tuple[str | None, str]:
    action, dialogue = parse_dialogue(text.strip())
    dialogue = dialogue.strip()
    if not dialogue and action:
        return None, action
    return action, dialogue


def looks_formatted(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith((">>>", "*", "_"))


def strip_roll_asks(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return ""
    blocks = [block.strip() for block in re.split(r"\n\s*\n", cleaned) if block.strip()]
    kept = [block for block in blocks if not _ROLL_ASK.search(block)]
    if kept:
        return "\n\n".join(kept)
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    leftover = [sentence for sentence in sentences if not _ROLL_ASK.search(sentence)]
    return " ".join(leftover).strip()
