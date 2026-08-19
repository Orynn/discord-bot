from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from config import FIVETOOLS_DATA_DIR, FIVETOOLS_EXPORT_FILE, FIVETOOLS_HOMEBREW_FILE
from srd.fivetools.edition import should_replace
from srd.fivetools.paths import is_official_mirror_entry
from srd.fivetools.source import build_official_body
from srd.fivetools_parser import slugify

_index: FiveToolsIndex | None = None
_index_lock = asyncio.Lock()


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class FiveToolsIndex:
    def __init__(self) -> None:
        self.spells_by_slug: dict[str, dict[str, Any]] = {}
        self.spells_by_name: dict[str, dict[str, Any]] = {}
        self.races_by_slug: dict[str, dict[str, Any]] = {}
        self.races_by_name: dict[str, dict[str, Any]] = {}
        self.classes_by_slug: dict[str, dict[str, Any]] = {}
        self.classes_by_name: dict[str, dict[str, Any]] = {}
        self.subclasses: list[dict[str, Any]] = []
        self.backgrounds_by_slug: dict[str, dict[str, Any]] = {}
        self.backgrounds_by_name: dict[str, dict[str, Any]] = {}
        self.feats_by_slug: dict[str, dict[str, Any]] = {}
        self.feats_by_name: dict[str, dict[str, Any]] = {}
        self.conditions_by_slug: dict[str, dict[str, Any]] = {}
        self.conditions_by_name: dict[str, dict[str, Any]] = {}
        self.weapons_by_slug: dict[str, dict[str, Any]] = {}
        self.weapons_by_name: dict[str, dict[str, Any]] = {}
        self.armor_by_slug: dict[str, dict[str, Any]] = {}
        self.armor_by_name: dict[str, dict[str, Any]] = {}
        self.items_by_slug: dict[str, dict[str, Any]] = {}
        self.items_by_name: dict[str, dict[str, Any]] = {}
        self.skills_by_slug: dict[str, dict[str, Any]] = {}
        self.skills_by_name: dict[str, dict[str, Any]] = {}
        self.monsters_by_slug: dict[str, dict[str, Any]] = {}
        self.monsters_by_name: dict[str, dict[str, Any]] = {}
        self._property_names: dict[str, str] = {}
        self._subclass_features: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._class_features: dict[str, list[dict[str, Any]]] = {}
        self._source_titles: dict[str, str] = {}
        self.loaded_sources: list[str] = []

    def load(self) -> None:
        from srd.fivetools.paths import has_official_source, is_available

        if not is_available():
            raise FileNotFoundError(
                "No 5etools data found. Bundle official JSON under 5etools/data/ "
                "and/or export homebrew from 5e.tools to 5etools/homebrew.json."
            )

        self.loaded_sources.clear()

        if has_official_source():
            self._ingest_brew_body(build_official_body(FIVETOOLS_DATA_DIR))
            self.loaded_sources.append(str(FIVETOOLS_DATA_DIR))

        if FIVETOOLS_HOMEBREW_FILE.is_file():
            self._ingest_export_file(
                FIVETOOLS_HOMEBREW_FILE,
                skip_official_mirror=False,
            )
            self.loaded_sources.append(str(FIVETOOLS_HOMEBREW_FILE))
        elif FIVETOOLS_EXPORT_FILE.is_file():
            self._ingest_export_file(
                FIVETOOLS_EXPORT_FILE,
                skip_official_mirror=has_official_source(),
            )
            self.loaded_sources.append(str(FIVETOOLS_EXPORT_FILE))

    def source_title(self, source: str) -> str:
        return self._source_titles.get(source, source)

    def _ingest_export_file(self, path: Path, *, skip_official_mirror: bool) -> None:
        export = _load_json(path)
        for entry in export.get("async", {}).get("HOMEBREW_2_STORAGE", []):
            if skip_official_mirror and is_official_mirror_entry(entry):
                continue
            body = entry.get("body")
            if isinstance(body, dict):
                self._ingest_brew_body(body)

    def _resolve_unique_slug(self, slug: str, source: str, by_slug: dict[str, dict[str, Any]]) -> str:
        existing = by_slug.get(slug)
        if existing is None or existing.get("source") == source:
            return slug
        return f"{slug}__{source.lower()}"

    def _should_replace_name(self, existing: dict[str, Any] | None, item: dict[str, Any]) -> bool:
        return should_replace(existing, item)

    def _register(
        self,
        item: dict[str, Any],
        *,
        by_slug: dict[str, dict[str, Any]],
        by_name: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        slug = item["slug"]
        source = item.get("source", "brew")
        unique_slug = self._resolve_unique_slug(slug, source, by_slug)
        registered = {**item, "slug": unique_slug}
        by_slug[unique_slug] = registered
        name_key = registered["name"].lower()
        if self._should_replace_name(by_name.get(name_key), registered):
            by_name[name_key] = registered
        return registered

    def _index_source_titles(self, body: dict[str, Any]) -> None:
        meta = body.get("_meta") or {}
        for source in meta.get("sources") or []:
            code = source.get("json")
            if not code:
                continue
            self._source_titles[code] = source.get("full") or source.get("abbreviation") or code

    def _ingest_brew_body(self, body: dict[str, Any]) -> None:
        self._index_source_titles(body)

        for raw in body.get("itemProperty", []):
            abbreviation = raw.get("abbreviation")
            entries = raw.get("entries") or []
            first = entries[0] if entries else None
            if isinstance(first, dict):
                name = first.get("name")
            elif isinstance(first, str):
                name = first
            else:
                name = abbreviation
            if abbreviation and name:
                self._property_names[abbreviation] = name

        for raw in body.get("spell", []):
            slug = slugify(raw["name"])
            self._register({**raw, "slug": slug}, by_slug=self.spells_by_slug, by_name=self.spells_by_name)

        for raw in body.get("race", []):
            slug = slugify(raw["name"])
            self._register({**raw, "slug": slug}, by_slug=self.races_by_slug, by_name=self.races_by_name)

        class_features = body.get("classFeature", [])
        class_features_by_key: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
        for feature in class_features:
            key = (feature.get("className"), feature.get("source"))
            class_features_by_key.setdefault(key, []).append(feature)

        for raw in body.get("class", []):
            slug = slugify(raw["name"])
            registered = self._register(
                {**raw, "slug": slug},
                by_slug=self.classes_by_slug,
                by_name=self.classes_by_name,
            )
            self._class_features[registered["slug"]] = class_features_by_key.get(
                (raw["name"], raw.get("source")),
                [],
            )

        subclass_features = body.get("subclassFeature", [])
        subclass_features_by_key: dict[tuple[Any, Any, Any], list[dict[str, Any]]] = {}
        for feature in subclass_features:
            key = (feature.get("className"), feature.get("subclassShortName"), feature.get("source"))
            subclass_features_by_key.setdefault(key, []).append(feature)

        for raw in body.get("subclass", []):
            parent_slug = slugify(raw.get("className", ""))
            slug = slugify(raw.get("shortName") or raw["name"])
            item = {
                **raw,
                "slug": slug,
                "parent_slug": parent_slug,
                "class_slug": parent_slug,
            }
            self.subclasses.append(item)
            key = (raw.get("className", ""), raw.get("shortName") or raw["name"])
            self._subclass_features[key] = subclass_features_by_key.get(
                (raw.get("className"), raw.get("shortName"), raw.get("source")),
                [],
            )

        for raw in body.get("background", []):
            slug = slugify(raw["name"])
            self._register({**raw, "slug": slug}, by_slug=self.backgrounds_by_slug, by_name=self.backgrounds_by_name)

        for raw in body.get("feat", []):
            slug = slugify(raw["name"])
            self._register({**raw, "slug": slug}, by_slug=self.feats_by_slug, by_name=self.feats_by_name)

        for raw in body.get("condition", []):
            slug = slugify(raw["name"])
            self._register({**raw, "slug": slug}, by_slug=self.conditions_by_slug, by_name=self.conditions_by_name)

        for raw in body.get("skill", []):
            slug = slugify(raw["name"]).replace("-", "_")
            self._register({**raw, "slug": slug}, by_slug=self.skills_by_slug, by_name=self.skills_by_name)

        for raw in body.get("baseitem", []):
            slug = slugify(raw["name"])
            item = {**raw, "slug": slug}
            if raw.get("weapon"):
                self._register(item, by_slug=self.weapons_by_slug, by_name=self.weapons_by_name)
            elif raw.get("armor"):
                self._register(item, by_slug=self.armor_by_slug, by_name=self.armor_by_name)

        for raw in body.get("item", []):
            if raw.get("weapon") or raw.get("armor"):
                continue
            slug = slugify(raw["name"])
            self._register({**raw, "slug": slug}, by_slug=self.items_by_slug, by_name=self.items_by_name)

        for raw in body.get("monster", []):
            if not raw.get("name"):
                continue
            if raw.get("_copy") and not raw.get("hp") and not raw.get("ac"):
                continue
            slug = slugify(raw["name"])
            self._register({**raw, "slug": slug}, by_slug=self.monsters_by_slug, by_name=self.monsters_by_name)

    def property_name(self, code: str) -> str:
        base = code.split("|", 1)[0]
        return self._property_names.get(base, base)

    def subclass_features(self, *, class_name: str, short_name: str) -> list[dict[str, Any]]:
        return self._subclass_features.get((class_name, short_name), [])

    def class_features(self, class_slug: str) -> list[dict[str, Any]]:
        return self._class_features.get(class_slug, [])


def _build_index() -> FiveToolsIndex:
    index = FiveToolsIndex()
    index.load()
    return index


def peek_index() -> FiveToolsIndex | None:
    return _index


def get_index() -> FiveToolsIndex:
    global _index
    if _index is None:
        _index = _build_index()
    return _index


def reload_index() -> FiveToolsIndex:
    global _index
    from srd.fivetools.lookup import clear_render_cache

    _index = _build_index()
    clear_render_cache()
    return _index


async def ensure_index_loaded() -> FiveToolsIndex:
    global _index
    if _index is not None:
        return _index

    async with _index_lock:
        if _index is None:
            _index = await asyncio.to_thread(_build_index)
    return _index
