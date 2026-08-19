from __future__ import annotations

import io
import asyncio
import re
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from urllib.parse import quote, unquote

import aiohttp
import discord

from campaign.forums import DEFAULT_FORUM_EMOJIS, normalize_section_key

WIKI_NAME = "Wiki Le Monde des Royaumes Oubliés"
API_URL = "https://le-monde-des-royaumes-oublies.fandom.com/fr/api.php"
WIKI_BASE = "https://le-monde-des-royaumes-oublies.fandom.com/fr/wiki/"
USER_AGENT = "ArkannBot/1.0 (import lore Royaumes Oubliés pour un Discord privé)"

_WIKI_URL = re.compile(
    r"https?://(?:le-monde-des-royaumes-oublies\.fandom\.com/fr|forgottenrealms\.fandom\.com)/wiki/([^?#]+)",
    re.IGNORECASE,
)
_BOLD = re.compile(r"'{3}(.+?)'{3}", re.DOTALL)
_ITALIC = re.compile(r"'{2}(.+?)'{2}", re.DOTALL)
_LINK_PIPE = re.compile(r"\[\[([^\]|]+)\|([^\]]+)\]\]")
_LINK = re.compile(r"\[\[([^\]]+)\]\]")
_EXTERNAL = re.compile(r"\[https?://[^\s\]]+\s+([^\]]+)\]")
_HEADING = re.compile(r"^(={2,4})\s*(.+?)\s*\1\s*$", re.MULTILINE)
_FILE = re.compile(r"\[\[(?:File|Image|Fichier)\s*:[^\]]*\]\]", re.IGNORECASE)
_REF = re.compile(r"<ref\b[^>]*>.*?</ref>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<(?!https?:)[^>]+>", re.IGNORECASE)
_CITE = re.compile(r"\{\{\s*Cite[^{}]*\}\}", re.IGNORECASE)
_YEAR = re.compile(r"\{\{\s*YearlinkName\|([^}]+)\}\}", re.IGNORECASE)
_TH = re.compile(r"\{\{\s*th\s*\}\}", re.IGNORECASE)

_SKIP_HEADINGS = {
    "appendix",
    "appendices",
    "notes",
    "references",
    "références",
    "appearances",
    "apparitions",
    "gallery",
    "galerie",
    "see also",
    "voir aussi",
    "voir également",
    "external links",
    "liens externes",
    "further reading",
    "sources",
    "citations",
}

_SKIP_TEMPLATES = {
    "otheruses",
    "otheruses4",
    "hatnote",
    "for",
    "about",
    "redirect",
    "incomplete",
    "stub",
    "refs",
    "ref",
    "notes",
    "appearances",
    "map",
    "displaytitle",
    "homonymie",
    "ébauche",
    "ebauche",
    "références",
    "references",
    "wikipédia",
    "wikipedia",
    "navbox",
    "année",
    "annee",
    "ordinal",
    "clr",
    "tocright",
    "sommaireàdroite",
    "documentation",
    "source",
    "source_livre",
    "structuredquote",
}

_INFOBOX_SECTION = {
    "location": "lieux",
    "settlement": "lieux",
    "building": "lieux",
    "dungeon": "lieux",
    "plane": "lieux",
    "road": "lieux",
    "ship": "lieux",
    "lieu": "lieux",
    "région_ou_pays": "lieux",
    "region_ou_pays": "lieux",
    "batiment": "lieux",
    "bâtiment": "lieux",
    "plan": "lieux",
    "person": "pnj",
    "personnage": "pnj",
    "creature": "créatures",
    "créature": "créatures",
    "plante": "flore",
    "flore": "flore",
    "deity": "pantheon",
    "god": "pantheon",
    "divinité": "pantheon",
    "divinite": "pantheon",
    "organization": "organisations",
    "org": "organisations",
    "organisation": "organisations",
    "organisation_et_églises": "organisations",
    "église": "organisations",
    "eglise": "organisations",
    "event": "quêtes",
    "adventure": "quêtes",
    "évènement_historique": "quêtes",
    "evenement_historique": "quêtes",
    "item": "objets",
    "objet": "objets",
    "monnaie": "objets",
    "currency": "objets",
    "ethnie": "race",
    "race": "race",
    "classe": "classe",
    "class": "classe",
    "spell": "sorts",
    "sort": "sorts",
}

_CATEGORY_SECTION: tuple[tuple[tuple[str, ...], str], ...] = (
    (("ethnie", "ethnies", "race", "races", "ethnicities"), "race"),
    (("classe", "classes", "prestige class", "classe de prestige"), "classe"),
    (("divinités", "divinité", "deities", "gods", "greater deities", "lesser deities", "dead powers"), "pantheon"),
    (
        (
            "organisation",
            "organizations",
            "factions",
            "guildes",
            "guilds",
            "église",
            "eglise",
            "adventuring companies",
            "churches",
        ),
        "organisations",
    ),
    (("sort", "spells"), "sorts"),
    (
        (
            "objet",
            "arme magique",
            "armure magique",
            "artéfact",
            "magic items",
            "items",
            "weapons",
            "armor",
            "wondrous items",
            "nourriture",
            "boisson",
            "alcool",
            "food and drink",
            "food",
            "drink",
            "monnaie",
            "currency",
            "coin",
            "coins",
        ),
        "objets",
    ),
    (
        (
            "plante",
            "flore",
            "flora",
            "végétation",
            "vegetation",
            "arbuste",
        ),
        "flore",
    ),
    (("créature", "creature", "monstre", "monsters"), "créatures"),
    (("personnage", "inhabitants", "people", "year of birth", "year of death"), "pnj"),
    (
        (
            "lieu",
            "ville",
            "cité",
            "cite-état",
            "cité-état",
            "port",
            "locations",
            "settlements",
            "ruins",
            "buildings",
            "dungeons",
            "forests",
            "mountains",
            "islands",
            "cities",
            "towns",
            "villages",
            "planes",
            "roads",
        ),
        "lieux",
    ),
    (("évènement", "evenement", "guerre", "bataille", "events", "adventures", "wars", "battles"), "quêtes"),
)

_INFOBOX_FIELDS = (
    ("type", "Type"),
    ("alias", "Alias"),
    ("nom vo", "Nom VO"),
    ("nom_vo", "Nom VO"),
    ("titres", "Titres"),
    ("titles", "Titres"),
    ("race", "Race"),
    ("races", "Races"),
    ("classe5e", "Classe"),
    ("classe3e", "Classe"),
    ("classe", "Classe"),
    ("class", "Classe"),
    ("occupation", "Occupation"),
    ("sexe", "Genre"),
    ("sex", "Genre"),
    ("alignement5e", "Alignement"),
    ("alignement3e", "Alignement"),
    ("alignement", "Alignement"),
    ("alignment", "Alignement"),
    ("région", "Région"),
    ("region", "Région"),
    ("lieu_actuel", "Foyer"),
    ("home", "Foyer"),
    ("religion", "Religion"),
    ("divinité", "Religion"),
    ("pantheon5e", "Panthéon"),
    ("panthéon5e", "Panthéon"),
    ("panthéon3e", "Panthéon"),
    ("pantheon", "Panthéon"),
    ("attributions5e", "Attributions"),
    ("attributions3e", "Attributions"),
    ("portfolio", "Attributions"),
    ("gouvernement", "Gouvernement"),
    ("government", "Gouvernement"),
    ("dirigeant", "Dirigeant"),
    ("ruler", "Dirigeant"),
    ("ruler1", "Dirigeant"),
    ("population", "Population"),
    ("allegiance", "Allégeance"),
    ("base", "Siège"),
    ("members", "Membres"),
)

_STARTER_LIMIT = 1900
_FOLLOWUP_LIMIT = 1900
_MAX_FOLLOWUPS = 5
MAX_RELATED_PAGES = 40
MAX_IMPORT_PAGES = 400
_WIKI_FETCH_DELAY = 0.3

ProgressCallback = Callable[[str], Awaitable[None]]

_SKIP_NAMESPACES = (
    "file:",
    "image:",
    "fichier:",
    "category:",
    "catégorie:",
    "template:",
    "modèle:",
    "modele:",
    "wikipedia:",
    "wikipédia:",
    "wp:",
    "user:",
    "utilisateur:",
    "talk:",
    "discussion:",
    "help:",
    "aide:",
    "special:",
    "spécial:",
)

_SKIP_TITLE_RE = re.compile(
    r"^(?:dd|add|adnd)\s*\d|"
    r"^dd\d\s*-|"
    r"\((?:langue|roman)\)\s*$",
    re.IGNORECASE,
)
_INTERWIKI_TITLE = re.compile(r"^[a-z]{2,3}(?:-[a-z]{2,3})?:", re.IGNORECASE)

GENERIC_SKIP = frozenset(
    {
        "human",
        "humans",
        "humain",
        "humains",
        "elf",
        "elves",
        "elfe",
        "elfes",
        "dwarf",
        "dwarves",
        "nain",
        "nains",
        "halfling",
        "halflings",
        "halfelin",
        "halfelins",
        "gnome",
        "gnomes",
        "half-elf",
        "half-elves",
        "demi-elfe",
        "demi-elfes",
        "half-orc",
        "half-orcs",
        "demi-orque",
        "demi-orques",
        "orc",
        "orcs",
        "orque",
        "orques",
        "dragon",
        "dragons",
        "gold",
        "platinum",
        "silver",
        "timber",
        "ore",
        "leather",
        "cold iron",
        "apple",
        "cider",
        "wizard",
        "wizards",
        "magicien",
        "magiciens",
        "mage",
        "enchanter",
        "paladin",
        "fighter",
        "guerrier",
        "cleric",
        "prêtre",
        "pretre",
        "rogue",
        "roublard",
        "bard",
        "barde",
        "druid",
        "druide",
        "adventurer",
        "adventurers",
        "aventurier",
        "aventuriers",
        "adventuring company",
        "toril",
        "faerûn",
        "faerun",
    }
)

_WIKI_INTERNAL = re.compile(
    r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]"
)


def _normalize_template_name(raw: str) -> str:
    name = raw.split(":", 1)[0].strip()
    return re.sub(r"[\s_]+", "_", name).casefold()


def _is_skipped_template(name: str) -> bool:
    key = _normalize_template_name(name)
    for skipped in _SKIP_TEMPLATES:
        if key == skipped:
            return True
        if len(skipped) < 5:
            continue
        if key.startswith(f"{skipped}_") or key.startswith(f"{skipped}/"):
            return True
    return False

_session: aiohttp.ClientSession | None = None


class WikiError(Exception):
    pass


class WikiNotFoundError(WikiError):
    pass


@dataclass(frozen=True)
class WikiClusterResult:
    pages: list[WikiPage]
    aliases: dict[str, str]
    truncated: bool
    missing: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()


@dataclass(frozen=True)
class WikiPage:
    title: str
    url: str
    summary: str
    body: str
    section: str
    thumbnail_url: str | None = None
    categories: tuple[str, ...] = field(default_factory=tuple)
    outgoing: tuple[str, ...] = field(default_factory=tuple)
    infobox_outgoing: tuple[str, ...] = field(default_factory=tuple)
    suggested_from: str | None = None

    def discord_chunks(self) -> list[str]:
        attribution = f"\n\n— [{WIKI_NAME}]({self.url}) · CC BY-SA"
        starter_budget = _STARTER_LIMIT - len(attribution)
        parts = [self.summary, self.body] if self.summary and self.body else [self.summary or self.body]
        text = "\n\n".join(part for part in parts if part).strip()
        if not text:
            text = f"**{self.title}**"

        chunks = _chunk_text(text, limit=starter_budget)
        if not chunks:
            chunks = [f"**{self.title}**"]
        chunks[0] = f"{chunks[0].rstrip()}{attribution}"
        extra: list[str] = []
        if len(chunks) > 1:
            remainder = "\n\n".join(chunks[1:])
            extra = _chunk_text(remainder, limit=_FOLLOWUP_LIMIT)[:_MAX_FOLLOWUPS]
            if len(_chunk_text(remainder, limit=_FOLLOWUP_LIMIT)) > _MAX_FOLLOWUPS:
                extra[-1] = f"{extra[-1].rstrip()}\n\n_… suite sur le wiki._"
        return [chunks[0], *extra]

    def with_connections(self, block: str) -> WikiPage:
        if not block.strip():
            return self
        body = f"{self.body}\n\n{block}".strip() if self.body else block
        return replace(self, body=body)

    def with_section(self, section: str) -> WikiPage:
        if section == self.section:
            return self
        return replace(self, section=section)

    def with_suggested_from(self, original: str) -> WikiPage:
        if not original or original.casefold() == self.title.casefold():
            return self
        return replace(self, suggested_from=original)


def page_title_from_query(query: str) -> str:
    cleaned = query.strip()
    match = _WIKI_URL.search(cleaned)
    if match:
        cleaned = unquote(match.group(1)).replace("_", " ")
    return cleaned.strip()


def wiki_page_url(title: str) -> str:
    slug = title.strip().replace(" ", "_")
    return f"{WIKI_BASE}{quote(slug, safe=':()!*,.-')}"


def markdown_wiki_link(*, label: str, title: str) -> str:
    display = label.replace("]", ")").strip() or title
    return f"[{display}](<{wiki_page_url(title)}>)"


def normalize_wiki_title(raw: str) -> str | None:
    title = raw.strip().replace("_", " ")
    title = re.sub(r"\s+", " ", title)
    if not title:
        return None
    lowered = title.casefold()
    if any(lowered.startswith(prefix) for prefix in _SKIP_NAMESPACES):
        return None
    if re.fullmatch(r"-?\d{2,5}(?:\s*(?:dr|cv))?", lowered):
        return None
    if _INTERWIKI_TITLE.match(title):
        return None
    return title


def is_generic_wiki_title(title: str) -> bool:
    folded = title.casefold().strip()
    if folded in GENERIC_SKIP:
        return True
    return _SKIP_TITLE_RE.search(folded) is not None


def extract_wiki_links(wikitext: str) -> list[str]:
    titles: list[str] = []
    seen: set[str] = set()
    for match in _WIKI_INTERNAL.finditer(wikitext):
        title = normalize_wiki_title(match.group(1))
        if title is None or is_generic_wiki_title(title):
            continue
        key = title.casefold()
        if key in seen:
            continue
        seen.add(key)
        titles.append(title)
    return titles


def _cut_reference_sections(wikitext: str) -> str:
    return re.split(
        r"^==\s*(?:Appendix|Appendices|Références|References)\s*==",
        wikitext,
        maxsplit=1,
        flags=re.IGNORECASE | re.MULTILINE,
    )[0]


def _first_infobox_and_rest(wikitext: str) -> tuple[str | None, str]:
    remaining = _cut_reference_sections(wikitext)
    for _ in range(12):
        span = extract_template(remaining)
        if span is None:
            return None, remaining
        start, end = span
        raw = remaining[start:end]
        name, _fields = parse_template(raw)
        remaining = remaining[:start] + remaining[end:]
        if _is_skipped_template(name):
            continue
        return raw, remaining
    return None, remaining


def _dedupe_titles(*groups: list[str], limit: int) -> list[str]:
    titles: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for title in group:
            key = title.casefold()
            if key in seen:
                continue
            seen.add(key)
            titles.append(title)
            if len(titles) >= limit:
                return titles
    return titles


def collect_infobox_titles(wikitext: str, *, limit: int = MAX_RELATED_PAGES) -> list[str]:
    raw, _remaining = _first_infobox_and_rest(wikitext)
    if not raw:
        return []
    return _dedupe_titles(extract_wiki_links(raw), limit=limit)


def collect_related_titles(wikitext: str, *, limit: int = MAX_RELATED_PAGES) -> list[str]:
    raw, remaining = _first_infobox_and_rest(wikitext)
    infobox_links = extract_wiki_links(raw) if raw else []
    return _dedupe_titles(infobox_links, extract_wiki_links(remaining), limit=limit)


def rewrite_imported_links(text: str, jump_urls: dict[str, str]) -> str:
    rewritten = text
    for title, jump_url in sorted(jump_urls.items(), key=lambda item: len(item[0]), reverse=True):
        wiki_url = wiki_page_url(title)
        rewritten = rewritten.replace(f"(<{wiki_url}>)", f"({jump_url})")
        rewritten = rewritten.replace(f"({wiki_url})", f"({jump_url})")
        rewritten = rewritten.replace(wiki_url, jump_url)
    return rewritten


def connections_block(
    *,
    outgoing: tuple[str, ...],
    jump_urls: dict[str, str],
    sections: dict[str, str],
) -> str:
    by_key = {title.casefold(): (title, url) for title, url in jump_urls.items()}
    lines: list[str] = []
    seen: set[str] = set()
    for title in outgoing:
        key = title.casefold()
        mapped = by_key.get(key)
        if mapped is None or key in seen:
            continue
        seen.add(key)
        _canonical, jump = mapped
        section = sections.get(key, "")
        prefix = f"{section} — " if section else ""
        lines.append(f"• {prefix}[{title}]({jump})")
    if not lines:
        return ""
    return "**Liens**\n" + "\n".join(lines)


_FOLLOW_LINKS_FLAG = re.compile(r"(?:(?<=\s)|^)--liens\b", re.IGNORECASE)


def split_import_query(query: str, extra_sections: tuple[str, ...] = ()) -> tuple[str | None, str, bool]:
    text = query.strip()
    if not text:
        raise WikiError(
            "Page wiki manquante. Exemple : `Eauprofonde`, `lieux Padhiver` ou `Padhiver --liens`."
        )
    follow_links = bool(_FOLLOW_LINKS_FLAG.search(text))
    if follow_links:
        text = _FOLLOW_LINKS_FLAG.sub(" ", text)
        text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise WikiError(
            "Page wiki manquante. Exemple : `Eauprofonde`, `lieux Padhiver` ou `Padhiver --liens`."
        )
    keys = {normalize_section_key(name) for name in extra_sections}
    keys.update(DEFAULT_FORUM_EMOJIS)
    parts = text.split(None, 1)
    if len(parts) == 2 and normalize_section_key(parts[0]) in keys:
        return parts[0], parts[1], follow_links
    return None, text, follow_links


def _category_needle_hits(category: str, needle: str) -> bool:
    cleaned = re.sub(r"^(?:category|catégorie):\s*", "", category, flags=re.IGNORECASE).casefold()
    token = needle.casefold().strip()
    if not token:
        return False
    if " " in token:
        return token in cleaned
    return re.search(rf"(?<!\w){re.escape(token)}\w{{0,2}}(?!\w)", cleaned) is not None


def _infobox_type_value(fields: dict[str, str] | None) -> str:
    if not fields:
        return ""
    return (fields.get("type") or fields.get("Type") or "").casefold().strip()


def _type_is_class(type_value: str) -> bool:
    token = type_value.casefold().strip()
    return token in {"classe", "class", "classes"} or token.startswith("classe ")


def guess_section(
    *,
    infobox_name: str | None,
    categories: list[str],
    infobox_fields: dict[str, str] | None = None,
) -> str:
    type_value = _infobox_type_value(infobox_fields)
    if _type_is_class(type_value):
        return "classe"
    if infobox_name:
        mapped = _INFOBOX_SECTION.get(_normalize_template_name(infobox_name))
        if mapped == "organisations" and any(
            any(_category_needle_hits(category, needle) for needle in ("classe", "classes"))
            for category in categories
        ):
            return "classe"
        if mapped:
            return mapped
    for needles, section in _CATEGORY_SECTION:
        if any(
            any(_category_needle_hits(category, needle) for needle in needles)
            for category in categories
        ):
            return section
    return "divers"


def extract_template(wikitext: str, start: int = 0) -> tuple[int, int] | None:
    index = wikitext.find("{{", start)
    if index < 0:
        return None
    depth = 0
    cursor = index
    while cursor < len(wikitext) - 1:
        pair = wikitext[cursor : cursor + 2]
        if pair == "{{":
            depth += 1
            cursor += 2
            continue
        if pair == "}}":
            depth -= 1
            cursor += 2
            if depth == 0:
                return index, cursor
            continue
        cursor += 1
    return None


def parse_template(raw: str) -> tuple[str, dict[str, str]]:
    inner = raw[2:-2].strip()
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for char in inner:
        if char == "{" :
            depth += 1
            buf.append(char)
            continue
        if char == "}":
            depth = max(0, depth - 1)
            buf.append(char)
            continue
        if char == "|" and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
            continue
        buf.append(char)
    if buf:
        parts.append("".join(buf).strip())
    name = parts[0].strip() if parts else ""
    fields: dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().casefold()
        value = wiki_to_plain(value).strip()
        if key and value:
            fields[key] = value
    return name, fields


def _replace_wiki_link(match: re.Match[str]) -> str:
    title = normalize_wiki_title(match.group(1))
    label = (match.group(2) or match.group(1)).strip().replace("_", " ")
    if title is None:
        return label
    return markdown_wiki_link(label=label, title=title)


def strip_templates(text: str) -> str:
    remaining = text
    while True:
        match = extract_template(remaining)
        if match is None:
            return remaining
        start, end = match
        remaining = remaining[:start] + " " + remaining[end:]


def wiki_to_plain(text: str) -> str:
    cleaned = _REF.sub("", text)
    cleaned = _FILE.sub("", cleaned)
    cleaned = _CITE.sub(" ", cleaned)
    cleaned = _YEAR.sub(r"\1", cleaned)
    cleaned = _TH.sub("th", cleaned)
    cleaned = strip_templates(cleaned)
    cleaned = _TAG.sub("", cleaned)
    cleaned = _WIKI_INTERNAL.sub(_replace_wiki_link, cleaned)
    cleaned = _EXTERNAL.sub(r"\1", cleaned)
    cleaned = _BOLD.sub(r"**\1**", cleaned)
    cleaned = _ITALIC.sub(r"*\1*", cleaned)
    cleaned = cleaned.replace("&mdash;", "—").replace("&ndash;", "–")
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def wikitext_to_body(wikitext: str) -> tuple[str | None, dict[str, str], str]:
    remaining = wikitext
    infobox_name: str | None = None
    infobox_fields: dict[str, str] = {}
    safety = 0
    while safety < 12:
        safety += 1
        span = extract_template(remaining)
        if span is None:
            break
        start, end = span
        raw = remaining[start:end]
        name, fields = parse_template(raw)
        remaining = remaining[:start] + remaining[end:]
        if _is_skipped_template(name):
            continue
        infobox_name = name
        infobox_fields = fields
        break

    plain = wiki_to_plain(remaining)
    lines: list[str] = []
    for line in plain.splitlines():
        heading = _HEADING.match(line.strip())
        if heading:
            title = heading.group(2).strip()
            if title.casefold() in _SKIP_HEADINGS:
                break
            lines.append(f"**{title}**")
            continue
        stripped = line.strip()
        if re.match(r"^\*+\s+", stripped):
            lines.append(f"• {stripped.lstrip('*').strip()}")
            continue
        if stripped.startswith(";"):
            lines.append(f"**{stripped.lstrip(';').strip()}**")
            continue
        lines.append(line.rstrip())
    body = "\n".join(lines).strip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    return infobox_name, infobox_fields, body


def format_infobox_summary(*, title: str, fields: dict[str, str]) -> str:
    used_keys: set[str] = set()
    used_labels: set[str] = set()
    rows: list[str] = [f"**{title}**"]
    for key, label in _INFOBOX_FIELDS:
        if key in used_keys or label in used_labels:
            continue
        value = fields.get(key)
        if not value:
            continue
        used_keys.add(key)
        used_labels.add(label)
        rows.append(f"**{label}:** {value}")
    return "\n".join(rows)


def _chunk_text(text: str, *, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text] if text else []
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 3:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at < limit // 3:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    return chunks


def _category_names(entries: list[dict]) -> list[str]:
    names: list[str] = []
    for entry in entries:
        title = str(entry.get("title") or entry.get("*") or "")
        title = re.sub(r"^(?:Category|Catégorie):", "", title, flags=re.IGNORECASE).strip()
        if title:
            names.append(title)
    return names


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        timeout = aiohttp.ClientTimeout(total=25)
        _session = aiohttp.ClientSession(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=timeout,
        )
    return _session


async def close_session() -> None:
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None


async def _api(params: dict[str, str], *, version2: bool = True) -> dict | list:
    session = await _get_session()
    query = {"format": "json", **params}
    if version2:
        query["formatversion"] = "2"
    last_error = WikiError(f"{WIKI_NAME} est indisponible.")
    for attempt in range(6):
        async with session.get(API_URL, params=query) as response:
            if response.status in {429, 502, 503}:
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else min(2**attempt, 20)
                except ValueError:
                    delay = min(2**attempt, 20)
                last_error = WikiError(f"{WIKI_NAME} a renvoyé HTTP {response.status}.")
                await asyncio.sleep(delay)
                continue
            if response.status != 200:
                raise WikiError(f"{WIKI_NAME} a renvoyé HTTP {response.status}.")
            payload = await response.json()
        if payload is None:
            raise WikiError(f"{WIKI_NAME} a renvoyé des données invalides.")
        return payload
    raise last_error


async def _api_object(params: dict[str, str]) -> dict:
    payload = await _api(params)
    if not isinstance(payload, dict):
        raise WikiError(f"{WIKI_NAME} a renvoyé des données invalides.")
    return payload


async def suggest_pages(query: str) -> list[str]:
    needle = page_title_from_query(query)
    if not needle:
        return []
    payload = await _api(
        {
            "action": "opensearch",
            "search": needle,
            "limit": "10",
            "namespace": "0",
        },
        version2=False,
    )
    titles = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
    if not isinstance(titles, list):
        return []
    return [
        str(title)
        for title in titles
        if title and not is_generic_wiki_title(str(title))
    ]


async def fetch_wiki_page(query: str, *, suggest: bool = True) -> WikiPage:
    title = page_title_from_query(query)
    if not title:
        raise WikiError("Nom de page wiki manquant.")

    meta = await _api_object(
        {
            "action": "query",
            "prop": "categories|pageimages|info",
            "titles": title,
            "redirects": "1",
            "inprop": "url",
            "pithumbsize": "800",
            "cllimit": "50",
        }
    )
    pages = meta.get("query", {}).get("pages", [])
    page = pages[0] if pages else {}
    if page.get("missing") or not page.get("title"):
        if not suggest:
            raise WikiNotFoundError(f"Aucune page **{title}** sur le {WIKI_NAME}.")
        for candidate in await suggest_pages(title):
            if candidate.casefold() == title.casefold():
                continue
            resolved = await fetch_wiki_page(candidate, suggest=False)
            return resolved.with_suggested_from(title)
        raise WikiNotFoundError(f"Aucune page **{title}** sur le {WIKI_NAME}.")

    parsed = await _api_object(
        {
            "action": "parse",
            "page": page["title"],
            "prop": "wikitext",
            "redirects": "1",
            "disablelimitreport": "1",
        }
    )
    wikitext = parsed.get("parse", {}).get("wikitext")
    if isinstance(wikitext, dict):
        wikitext = wikitext.get("*", "")
    if not isinstance(wikitext, str) or not wikitext.strip():
        raise WikiError(f"No usable text on **{page['title']}**.")

    infobox_name, fields, body = wikitext_to_body(wikitext)
    categories = _category_names(page.get("categories") or [])
    section = guess_section(
        infobox_name=infobox_name,
        categories=categories,
        infobox_fields=fields,
    )
    summary = format_infobox_summary(title=page["title"], fields=fields)
    thumbnail = None
    thumb = page.get("thumbnail") or {}
    if isinstance(thumb, dict):
        thumbnail = thumb.get("source")
    url = page.get("fullurl") or f"{WIKI_BASE}{page['title'].replace(' ', '_')}"
    skip_self = page["title"].casefold()
    outgoing = tuple(
        title for title in collect_related_titles(wikitext) if title.casefold() != skip_self
    )
    infobox_outgoing = tuple(
        title for title in collect_infobox_titles(wikitext) if title.casefold() != skip_self
    )
    return WikiPage(
        title=page["title"],
        url=url,
        summary=summary,
        body=body,
        section=section,
        thumbnail_url=thumbnail,
        categories=tuple(categories),
        outgoing=outgoing,
        infobox_outgoing=infobox_outgoing,
    )


def _follow_titles(page: WikiPage, *, infobox_only: bool) -> tuple[str, ...]:
    return page.infobox_outgoing if infobox_only else page.outgoing


async def fetch_wiki_cluster(
    root: WikiPage,
    *,
    limit: int = MAX_IMPORT_PAGES,
    depth: int = 0,
    infobox_only: bool = False,
    on_progress: ProgressCallback | None = None,
) -> WikiClusterResult:
    pages = [root]
    aliases: dict[str, str] = {}
    queued = {root.title.casefold()}
    seen_pages = {root.title.casefold()}
    queue: deque[tuple[str, int]] = deque()
    missing: list[str] = []
    failed: list[str] = []
    cap = max(1, limit)

    def enqueue(titles: tuple[str, ...] | list[str], *, hop: int) -> None:
        if hop > depth:
            return
        for title in titles:
            key = title.casefold()
            if key in queued:
                continue
            queued.add(key)
            queue.append((title, hop))

    enqueue(_follow_titles(root, infobox_only=infobox_only), hop=1)

    while queue and len(pages) < cap:
        title, hop = queue.popleft()
        if title.casefold() in seen_pages:
            continue
        try:
            related = await fetch_wiki_page(title, suggest=False)
        except WikiNotFoundError:
            missing.append(title)
            continue
        except WikiError:
            failed.append(title)
            continue
        aliases[title] = related.title
        key = related.title.casefold()
        queued.add(key)
        if key in seen_pages:
            continue
        seen_pages.add(key)
        pages.append(related)
        enqueue(_follow_titles(related, infobox_only=infobox_only), hop=hop + 1)
        if on_progress is not None and (len(pages) == 2 or len(pages) % 5 == 0 or not queue):
            await on_progress(
                f"📖 Récupération des pages wiki… **{len(pages)}/{cap}** (`{related.title}`)"
            )
        await asyncio.sleep(_WIKI_FETCH_DELAY)

    truncated = len(pages) >= cap and bool(queue)
    return WikiClusterResult(
        pages=pages,
        aliases=aliases,
        truncated=truncated,
        missing=tuple(missing),
        failed=tuple(failed),
    )


async def download_thumbnail(url: str) -> discord.File | None:
    session = await _get_session()
    try:
        async with session.get(url) as response:
            if response.status != 200:
                return None
            data = await response.read()
    except aiohttp.ClientError:
        return None
    if not data or len(data) > 8 * 1024 * 1024:
        return None
    name = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1] or "wiki.png"
    if "." not in name:
        name = f"{name}.png"
    return discord.File(io.BytesIO(data), filename=name[:64])
