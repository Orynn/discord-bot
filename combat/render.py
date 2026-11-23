"""The tracker message: initiative order, HP or monster state, conditions."""

import discord

from combat.encounter import (
    Combatant,
    Encounter,
    condition_key,
    condition_label,
    monster_state,
)
from combat.attacks import Attack, damage_type_label
from config import PREFIX
from sheets.data import CharacterSheet

TRACKER_COLOR = 0xA93226
ENDED_COLOR = 0x566573
_DESCRIPTION_LIMIT = 4000


def _conditions_text(combatant: Combatant, sheet: CharacterSheet | None) -> list[str]:
    timed = dict(combatant.conditions)
    keys: list[str] = []
    if sheet is not None:
        keys.extend(condition_key(raw) for raw in sheet.conditions)
    keys.extend(key for key in timed if key not in keys)
    parts: list[str] = []
    for key in keys:
        rounds = timed.get(key)
        label = condition_label(key)
        parts.append(f"{label} ({rounds})" if rounds else label)
    return parts


def _death_saves(sheet: CharacterSheet) -> str:
    if sheet.death_save_successes >= 3:
        return "🩹 stabilisé"
    return (
        f"✅ {min(sheet.death_save_successes, 3)}/3 · "
        f"❌ {min(sheet.death_save_failures, 3)}/3"
    )


def _hp_text(combatant: Combatant, sheet: CharacterSheet | None, *, mj: bool) -> str:
    temp = f" (+{combatant.temp_hp} temp.)" if combatant.temp_hp else ""
    if combatant.is_player:
        if combatant.dead:
            return "☠️ mort"
        if sheet is None:
            return "fiche introuvable"
        if sheet.hp_max and sheet.hp_current <= 0:
            return f"🛌 à terre (0/{sheet.hp_max} PV) · {_death_saves(sheet)}"
        return f"PV {sheet.hp_current}/{sheet.hp_max}{temp}"
    if mj:
        ac = f" · CA {combatant.ac}" if combatant.ac is not None else ""
        return f"PV {combatant.hp}/{combatant.hp_max}{temp}{ac} · {monster_state(combatant)}"
    return monster_state(combatant)


def _attack_summary(combatant: Combatant) -> str:
    parts: list[str] = []
    for data in combatant.attacks:
        attack = Attack.from_dict(data)
        damage = " + ".join(
            f"{part.dice}{f' {damage_type_label(part.type)}' if part.type else ''}"
            for part in attack.damage
            if not part.needs_advantage
        )
        parts.append(f"{attack.name} {attack.hit:+d} ({damage or '—'})")
    defenses = []
    for label, values in (
        ("résiste", combatant.resist),
        ("immunisé", combatant.immune),
        ("vulnérable", combatant.vulnerable),
    ):
        if values:
            defenses.append(
                f"{label} : {', '.join(damage_type_label(v) for v in values)}"
            )
    return " · ".join(parts + defenses)


def _mj_field(encounter: Encounter) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for combatant in encounter.order():
        if combatant.is_player:
            continue
        key = combatant.source or combatant.name
        if key in seen:
            continue
        seen.add(key)
        summary = _attack_summary(combatant)
        if summary:
            lines.append(f"**{key}** — {summary}")
    return "\n".join(lines)[:1024]


def tracker_line(
    combatant: Combatant,
    sheet: CharacterSheet | None,
    *,
    current: bool,
    mj: bool,
) -> str:
    marker = "▶" if current else "▫️"
    name = f"~~{combatant.name}~~" if combatant.is_out else f"**{combatant.name}**"
    parts = [_hp_text(combatant, sheet, mj=mj), *_conditions_text(combatant, sheet)]
    if combatant.concentration:
        parts.append(f"🧠 {combatant.concentration.get('spell', '?')}")
    if combatant.reaction_used:
        parts.append("↩️ réaction utilisée")
    return f"{marker} `{combatant.initiative:>2}` {name} — " + " · ".join(parts)


def tracker_embed(
    encounter: Encounter,
    sheets: dict[int, CharacterSheet | None],
    *,
    mj: bool = False,
    ended: bool = False,
) -> discord.Embed:
    if ended:
        title = f"🏁 Combat terminé — {encounter.round} round(s)"
    elif encounter.round == 0:
        title = "⚔️ Combat — préparation"
    else:
        title = f"⚔️ Combat — Round {encounter.round}"
    if mj:
        title += " (vue MJ)"

    lines = [
        tracker_line(
            combatant,
            sheets.get(combatant.user_id) if combatant.user_id is not None else None,
            current=combatant.id == encounter.current_id and not ended,
            mj=mj,
        )
        for combatant in encounter.order()
    ]
    description = "\n".join(lines) or "*Personne pour l’instant.*"
    if len(description) > _DESCRIPTION_LIMIT:
        description = description[: _DESCRIPTION_LIMIT - 1] + "…"

    embed = discord.Embed(
        title=title,
        description=description,
        color=ENDED_COLOR if ended else TRACKER_COLOR,
    )
    if mj:
        details = _mj_field(encounter)
        if details:
            embed.add_field(name="🗡️ Attaques et défenses", value=details, inline=False)
    if not ended:
        if encounter.round == 0:
            hint = (
                f"{PREFIX}combat add gobelin x3 · {PREFIX}combat join · "
                f"{PREFIX}next pour commencer"
            )
        else:
            hint = (
                f"{PREFIX}atk <cible> · {PREFIX}cast <sort> sur <cibles> · "
                f"{PREFIX}combat dmg <cible> <dégâts> · {PREFIX}next"
            )
        embed.set_footer(text=hint)
    return embed
