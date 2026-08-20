from sheets.data import CharacterSheet, fold_lookup_key
from sheets.hunger import exhaustion_level

_CONDITION_ALIASES: dict[str, str] = {
    "poisoned": "poisoned",
    "empoisonne": "poisoned",
    "frightened": "frightened",
    "effraye": "frightened",
    "peur": "frightened",
    "blinded": "blinded",
    "aveugle": "blinded",
    "restrained": "restrained",
    "entrave": "restrained",
    "prone": "prone",
    "a_terre": "prone",
    "terre": "prone",
    "paralyzed": "paralyzed",
    "paralyse": "paralyzed",
    "unconscious": "unconscious",
    "inconscient": "unconscious",
    "stunned": "stunned",
    "etourdi": "stunned",
    "incapacitated": "incapacitated",
    "incapacite": "incapacitated",
}

CHECK_DISADVANTAGE = frozenset({"poisoned", "frightened", "exhaustion"})
ATTACKER_DISADVANTAGE = frozenset({"poisoned", "frightened", "blinded", "restrained", "prone"})
DEFENDER_ADVANTAGE = frozenset(
    {"blinded", "restrained", "prone", "paralyzed", "unconscious", "stunned", "incapacitated"}
)

_CANONICAL = frozenset(_CONDITION_ALIASES.values())


def normalize_condition(name: str) -> str | None:
    key = fold_lookup_key(name)
    if key.startswith("exhaust"):
        return "exhaustion"
    aliased = _CONDITION_ALIASES.get(key)
    if aliased:
        return aliased
    if key in _CANONICAL:
        return key
    return None


def sheet_condition_keys(sheet: CharacterSheet) -> set[str]:
    keys: set[str] = set()
    for raw in sheet.conditions:
        canon = normalize_condition(str(raw))
        if canon:
            keys.add(canon)
    if exhaustion_level(sheet) >= 1:
        keys.add("exhaustion")
    return keys


def ability_check_disadvantage_source(sheet: CharacterSheet) -> str | None:
    keys = sheet_condition_keys(sheet)
    for name in ("poisoned", "frightened", "exhaustion"):
        if name in keys:
            return name
    return None
