import re
from re import Match, Pattern

ACTION_PREFIX: Pattern[str] = re.compile(r"^\(([^)]+)\)\s*", re.DOTALL)
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


def parse_dialogue(text: str) -> tuple[str | None, str]:
    match: Match[str] | None = ACTION_PREFIX.match(text)
    if match:
        return match.group(1), text[match.end() :]
    return None, text
