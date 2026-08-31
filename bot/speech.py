import re
from re import Match, Pattern

ACTION_PREFIX: Pattern[str] = re.compile(r"^\(([^)]+)\)\s*", re.DOTALL)
_PARENTHETICAL_ONLY: Pattern[str] = re.compile(r"^(\([^)]+\)\s*)+$", re.DOTALL)
_INNER_PARENS: Pattern[str] = re.compile(r"\(([^)]+)\)", re.DOTALL)
_SENTENCE_ENDINGS: frozenset[str] = frozenset(".!?")


def _format_sentence(sentence: str) -> str:
    sentence = sentence.strip()
    if not sentence:
        return sentence

    sentence = sentence[0].upper() + sentence[1:]
    if sentence[-1] not in _SENTENCE_ENDINGS:
        sentence = f"{sentence}."
    return sentence


def _format_dialogue_line(line: str) -> str:
    line = line.strip()
    if not line:
        return line

    parts = re.split(r"(?<=[.!?])\s+", line)
    return " ".join(_format_sentence(part) for part in parts if part.strip())


def format_dialogue(text: str) -> str:
    text = text.strip()
    if not text:
        return text

    lines = text.split("\n")
    return "\n".join(
        _format_dialogue_line(line) if line.strip() else line for line in lines
    )


def format_npc_speech(name: str, dialogue: str, action: str | None = None) -> str:
    dialogue = format_dialogue(dialogue)
    if action:
        return f">>> ***{name}** ({action})* :\n{dialogue}"
    return f">>> ***{name}*** :\n{dialogue}"


def format_thought(name: str, text: str) -> str:
    thought = format_dialogue(text)
    return f">>> ***{name}** (pense)* :\n||{thought}||"


def format_emote(name: str, action: str) -> str:
    action = action.strip()
    if not action:
        return ""
    if action[-1] not in _SENTENCE_ENDINGS:
        action = f"{action}."
    return f"*{name} {action}*"


def format_ooc(text: str) -> str:
    return f"**OOC** — {text.strip()}"


def format_whisper_public(speaker: str, listener: str) -> str:
    return f"*{speaker} se penche vers {listener} et chuchote.*"


def format_whisper_private(speaker: str, listener: str, text: str) -> str:
    dialogue = format_dialogue(text)
    return f"**{speaker}** chuchote à **{listener}** :\n{dialogue}"


def parse_dialogue(text: str) -> tuple[str | None, str]:
    match: Match[str] | None = ACTION_PREFIX.match(text)
    if match:
        return match.group(1), text[match.end() :]
    return None, text


def parenthetical_only_narration(text: str) -> str | None:
    stripped = text.strip()
    if not stripped or not _PARENTHETICAL_ONLY.fullmatch(stripped):
        return None
    parts = [part.strip() for part in _INNER_PARENS.findall(stripped)]
    narration = " ".join(part for part in parts if part)
    return narration or None
