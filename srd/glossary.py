import logging
import re
from dataclasses import dataclass, field

from srd import fivetools
from srd.fivetools import DEFAULT_SOURCE, entry_url, entry_url_for_item, item_source
from srd.fivetools.loader import ensure_index_loaded
from srd.fivetools.paths import content_fingerprint
from srd.glossary_cache import load_glossary as load_cached_glossary
from srd.glossary_cache import save_glossary

logger = logging.getLogger(__name__)

MIN_TERM_LENGTH = 3

ENDPOINTS: tuple[tuple[str, str, str], ...] = (
    ("spells", "spell", "spells"),
    ("species", "species", "races"),
    ("classes", "class", "classes"),
    ("backgrounds", "background", "backgrounds"),
    ("feats", "feat", "feats"),
)


@dataclass(frozen=True)
class GlossaryEntry:
    name: str
    kind: str
    slug: str
    url: str
    parent_slug: str | None = None


@dataclass
class _GlossaryStore:
    by_key: dict[str, GlossaryEntry] = field(default_factory=dict)
    by_length: list[GlossaryEntry] = field(default_factory=list)
    matcher: re.Pattern[str] | None = None
    loaded: bool = False
    dirty: bool = False

    def rebuild_index(self) -> None:
        self.by_length = sorted(self.by_key.values(), key=lambda entry: len(entry.name), reverse=True)
        self.matcher = _compile_matcher(self.by_length)
        self.dirty = False


_store = _GlossaryStore()


def _compile_matcher(entries: list[GlossaryEntry]) -> re.Pattern[str] | None:
    """One IGNORECASE alternation, longest names first, compiled once per rebuild."""
    names: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        key = entry.name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(re.escape(entry.name))
    if not names:
        return None
    return re.compile(rf"(?<![\w\[])(?:{'|'.join(names)})(?![\w\]])", re.IGNORECASE)


def reset_store() -> None:
    """Clear in-memory glossary state. Used by tests."""
    _store.by_key.clear()
    _store.by_length.clear()
    _store.matcher = None
    _store.loaded = False
    _store.dirty = False


def _ensure_index() -> None:
    if _store.dirty:
        _store.rebuild_index()


def is_loaded() -> bool:
    return _store.loaded


def _entry_key(name: str) -> str:
    return name.lower().strip()


def register(entry: GlossaryEntry) -> None:
    if len(entry.name) < MIN_TERM_LENGTH:
        return

    key = _entry_key(entry.name)
    existing = _store.by_key.get(key)
    if existing and len(existing.name) >= len(entry.name):
        return

    _store.by_key[key] = entry
    _store.dirty = True


def register_item(
    *,
    name: str,
    kind: str,
    slug: str,
    source: str | None = None,
    parent_slug: str | None = None,
    url: str | None = None,
) -> None:
    resolved_source = source or DEFAULT_SOURCE
    register(
        GlossaryEntry(
            name=name,
            kind=kind,
            slug=slug,
            url=url or entry_url(kind, name, source=resolved_source),
            parent_slug=parent_slug,
        )
    )


def register_from_api_item(*, item: dict, kind: str) -> None:
    slug = item.get("slug") or fivetools.short_slug(item.get("key") or item["name"])
    register_item(
        name=item["name"],
        kind=kind,
        slug=slug,
        source=item_source(item),
        url=item.get("url") or entry_url_for_item(kind, item),
    )


def _register_skills() -> None:
    from sheets.context import format_skill_name
    from sheets.data import SKILL_ABILITIES
    from srd.fivetools.loader import get_index

    index = get_index()
    for skill in SKILL_ABILITIES:
        display_name = format_skill_name(skill)
        indexed = index.skills_by_slug.get(skill) or index.skills_by_name.get(display_name.lower())
        if indexed is not None:
            register_item(
                name=indexed["name"],
                kind="skill",
                slug=skill,
                source=item_source(indexed),
                url=entry_url_for_item("skill", indexed),
            )
            continue
        register_item(
            name=display_name,
            kind="skill",
            slug=skill,
            source=DEFAULT_SOURCE,
        )


def entries() -> list[GlossaryEntry]:
    _ensure_index()
    return _store.by_length


def _current_fingerprint() -> str:
    return content_fingerprint()


async def load(*, force_refresh: bool = False) -> None:
    await ensure_index_loaded()
    fingerprint = _current_fingerprint()

    if not force_refresh:
        cached = load_cached_glossary(fingerprint=fingerprint)
        if cached:
            for item in cached:
                register(
                    GlossaryEntry(
                        name=item["name"],
                        kind=item["kind"],
                        slug=item["slug"],
                        url=item["url"],
                        parent_slug=item.get("parent_slug"),
                    )
                )
            _store.rebuild_index()
            _store.loaded = True
            logger.info("Rules glossary loaded from cache (%s entries).", len(_store.by_key))
            _register_skills()
            _store.rebuild_index()
            return

    for endpoint, kind, _web_path in ENDPOINTS:
        items = await fivetools.fetch_all(endpoint=endpoint)
        for item in items:
            if endpoint == "classes" and item.get("subclass_of"):
                parent = item["subclass_of"]
                parent_key = parent.get("key") if isinstance(parent, dict) else str(parent)
                register_item(
                    name=item["name"],
                    kind="subclass",
                    slug=fivetools.short_slug(item.get("slug") or item.get("key") or item["name"]),
                    source=item_source(item),
                    parent_slug=fivetools.short_slug(parent_key),
                )
                continue

            register_from_api_item(item=item, kind=kind)

    for item in await fivetools.fetch_all(endpoint="conditions"):
        normalized = fivetools.normalize_condition(item)
        if normalized is None:
            continue
        register_from_api_item(item=normalized, kind="condition")

    for item in (await fivetools.fetch_all(endpoint="weapons")) + (await fivetools.fetch_all(endpoint="armor")):
        kind = "weapon" if item.get("weapon") else "armor"
        register_from_api_item(item=item, kind=kind)

    for item in await fivetools.fetch_all(endpoint="items"):
        register_from_api_item(item=item, kind="item")

    for item in await fivetools.fetch_all(endpoint="monsters"):
        register_from_api_item(item=item, kind="monster")

    _register_skills()

    _store.rebuild_index()
    _store.loaded = True
    save_glossary(list(_store.by_key.values()), fingerprint=fingerprint)
    logger.info("Rules glossary loaded from 5etools (%s entries).", len(_store.by_key))


def iter_mention_spans(text: str) -> list[tuple[int, int, str, GlossaryEntry]]:
    """Return non-overlapping mention spans as (start, end, original, entry)."""
    if not text or not _store.loaded:
        return []

    _ensure_index()
    matcher = _store.matcher
    if matcher is None:
        return []

    spans: list[tuple[int, int, str, GlossaryEntry]] = []
    for match in matcher.finditer(text):
        original = match.group(0)
        entry = _store.by_key.get(_entry_key(original))
        if entry is None:
            continue
        spans.append((match.start(), match.end(), original, entry))
    return spans


def find_mentions(text: str) -> list[GlossaryEntry]:
    mentioned: dict[str, GlossaryEntry] = {}
    for _start, _end, _original, entry in iter_mention_spans(text):
        mentioned[_entry_key(entry.name)] = entry
    return sorted(mentioned.values(), key=lambda entry: entry.name.lower())


def lookup(name: str) -> GlossaryEntry | None:
    return _store.by_key.get(_entry_key(name))
