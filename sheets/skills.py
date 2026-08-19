from sheets.context import format_skill_name
from sheets.data import SKILL_ABILITIES, format_modifier

from srd.linkify import markdown_link
from srd.fivetools import DEFAULT_SOURCE, entry_url, entry_url_for_item
from srd.fivetools.loader import get_index


def skill_rule_slug(skill: str) -> str:
    return skill.replace("_", "-")


def skill_url(skill: str) -> str:
    display_name = format_skill_name(skill)
    index = get_index()
    indexed = index.skills_by_slug.get(skill) or index.skills_by_name.get(display_name.lower())
    if indexed is not None:
        return entry_url_for_item("skill", indexed)
    return entry_url("skill", display_name, source=DEFAULT_SOURCE)


def format_skill_line(*, skill: str, ability: str, modifier: str, marks: str = "") -> str:
    name = format_skill_name(skill)
    return f"{markdown_link(name, skill_url(skill))} ({ability.upper()}) {modifier}{marks}"


def format_skills_block(sheet) -> str:
    lines: list[str] = []
    for skill, ability in SKILL_ABILITIES.items():
        mod = sheet.get_skill_modifier(skill)
        marks = ""
        if skill in sheet.skill_proficiencies:
            marks = " ●"
        if skill in sheet.skill_expertise:
            marks = " ◆"
        lines.append(
            format_skill_line(
                skill=skill,
                ability=ability,
                modifier=format_modifier(mod),
                marks=marks,
            )
        )
    return "**Skills**\n" + "\n".join(lines)
