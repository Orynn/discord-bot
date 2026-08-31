from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import discord

from data.db import db_connection
from sheets.containers import SPECIAL_LOCATIONS, custom_container_capacity
from sheets.equipment import (
    InventoryItem,
    format_item_line,
    parse_name_quantity_and_weight,
)

LIST_ALIASES = frozenset({"list", "here", "ici", "show", "places"})
ALL_GEAR_ALIASES = frozenset({"all", "tout", "*"})
_NOTE_SEPARATORS = (" -- ", " — ", " – ")
_AT_SPLIT = re.compile(r"(?:^|\s+)(?:at|à)\s+", re.IGNORECASE)
_THREAD_TYPES = {
    discord.ChannelType.public_thread,
    discord.ChannelType.private_thread,
    discord.ChannelType.news_thread,
}


@dataclass
class LetArgs:
    list_only: bool
    all_places: bool
    all_gear: bool
    item: str
    quantity: int | None
    place: str | None
    note: str


@dataclass
class StashEntry:
    item: InventoryItem
    note: str = ""
    left_by: str = ""
    left_by_user_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "item": self.item.to_dict(),
            "note": self.note,
            "left_by": self.left_by,
        }
        if self.left_by_user_id is not None:
            data["left_by_user_id"] = self.left_by_user_id
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StashEntry":
        user_id = data.get("left_by_user_id")
        return cls(
            item=InventoryItem.from_dict(data.get("item") or data),
            note=str(data.get("note") or ""),
            left_by=str(data.get("left_by") or ""),
            left_by_user_id=int(user_id) if user_id is not None else None,
        )


@dataclass
class PlaceStash:
    guild_id: int
    place_key: str
    place_name: str
    entries: list[StashEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "place_name": self.place_name,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    @classmethod
    def from_dict(
        cls, *, guild_id: int, place_key: str, data: dict[str, Any]
    ) -> "PlaceStash":
        entries = [StashEntry.from_dict(entry) for entry in data.get("entries") or []]
        return cls(
            guild_id=guild_id,
            place_key=place_key,
            place_name=str(data.get("place_name") or place_key),
            entries=entries,
        )

    def item_count(self) -> int:
        return sum(entry.item.quantity for entry in self.entries)

    def add_entries(
        self,
        items: list[InventoryItem],
        *,
        note: str = "",
        left_by: str = "",
        left_by_user_id: int | None = None,
    ) -> list[StashEntry]:
        added: list[StashEntry] = []
        for item in items:
            copy = InventoryItem.from_dict(item.to_dict())
            copy.equipped = False
            if copy.stored_in in SPECIAL_LOCATIONS:
                copy.stored_in = None
            entry = StashEntry(
                item=copy,
                note=note if copy.stored_in is None else "",
                left_by=left_by,
                left_by_user_id=left_by_user_id,
            )
            merged = self._merge_entry(entry)
            added.append(merged)
        return added

    def _merge_entry(self, entry: StashEntry) -> StashEntry:
        if _is_container_item(entry.item):
            self.entries.append(entry)
            return entry
        for existing in self.entries:
            if _is_container_item(existing.item):
                continue
            if not _same_stash_stack(existing, entry):
                continue
            existing.item.quantity += entry.item.quantity
            return existing
        self.entries.append(entry)
        return entry

    def find_entries(self, query: str) -> list[StashEntry]:
        cleaned = query.strip()
        if not cleaned:
            return []
        query_lower = cleaned.lower()
        exact = [
            entry
            for entry in self.entries
            if entry.item.name.lower() == query_lower
            or entry.item.slug.lower() == query_lower
        ]
        if exact:
            return exact
        return [
            entry
            for entry in self.entries
            if query_lower in entry.item.name.lower()
            or query_lower in entry.item.slug.lower()
        ]

    def take_items(
        self, query: str, *, quantity: int | None = None
    ) -> list[InventoryItem]:
        matches = self.find_entries(query)
        if not matches:
            return []
        entry = _prefer_stash_entry(matches)
        take_all = quantity is None or quantity >= entry.item.quantity
        has_nested = any(
            child is not entry and _is_nested_in(child.item, entry.item, self.entries)
            for child in self.entries
        )
        if take_all and (has_nested or _is_container_item(entry.item)):
            nested_entries = [
                child
                for child in self.entries
                if child is not entry
                and _is_nested_in(child.item, entry.item, self.entries)
            ]
            skip = {id(entry), *(id(child) for child in nested_entries)}
            taken = [entry.item, *[child.item for child in nested_entries]]
            self.entries = [child for child in self.entries if id(child) not in skip]
            return taken

        if take_all:
            self.entries.remove(entry)
            return [entry.item]

        if quantity is not None and quantity < 1:
            raise ValueError("Quantity must be at least 1.")

        entry.item.quantity -= quantity or 0
        split = InventoryItem.from_dict(entry.item.to_dict())
        split.quantity = quantity or 0
        return [split]

    def format_lines(self) -> list[str]:
        if not self.entries:
            return ["Nothing left here."]
        parent_slugs = {entry.item.slug for entry in self.entries}
        lines: list[str] = []
        for entry in self.entries:
            parent = entry.item.stored_in
            nested = (
                bool(parent)
                and parent not in SPECIAL_LOCATIONS
                and parent in parent_slugs
            )
            if nested:
                continue
            lines.append(_format_stash_line(entry, nested=False))
            for child in self.entries:
                if child.item.stored_in == entry.item.slug:
                    lines.append(f"  {_format_stash_line(child, nested=True)}")
        return lines or ["Nothing left here."]


def normalize_place_key(name: str) -> str:
    return " ".join(name.strip().split()).casefold()


def display_place_name(name: str) -> str:
    return " ".join(name.strip().split())


def parse_let_args(text: str) -> LetArgs:
    cleaned = (text or "").strip()
    note = ""
    for separator in _NOTE_SEPARATORS:
        if separator in cleaned:
            cleaned, note = cleaned.split(separator, 1)
            note = note.strip()
            cleaned = cleaned.strip()
            break

    place: str | None = None
    matches = list(_AT_SPLIT.finditer(cleaned))
    if matches:
        match = matches[-1]
        place = display_place_name(cleaned[match.end() :]) or None
        cleaned = cleaned[: match.start()].strip()

    list_only = False
    all_places = False
    first, _, rest = cleaned.partition(" ")
    if first.lower() in LIST_ALIASES:
        list_only = True
        all_places = first.lower() == "places" or rest.strip().lower() == "places"
        cleaned = "" if all_places else rest.strip()
    elif not cleaned:
        list_only = True

    item, quantity, _ = (
        parse_name_quantity_and_weight(cleaned) if cleaned else ("", None, None)
    )
    if item.lower() in LIST_ALIASES:
        list_only = True
        all_places = item.lower() == "places"
        item = ""
        quantity = None
    all_gear = item.casefold() in ALL_GEAR_ALIASES
    if all_gear:
        quantity = None
    return LetArgs(
        list_only=list_only,
        all_places=all_places,
        all_gear=all_gear,
        item=item,
        quantity=quantity,
        place=place,
        note=note,
    )


def infer_place_from_channel(channel: Any) -> str | None:
    if channel is None:
        return None
    channel_type = getattr(channel, "type", None)
    is_thread = channel_type in _THREAD_TYPES or isinstance(channel, discord.Thread)
    if not is_thread:
        return None
    name = display_place_name(str(getattr(channel, "name", "") or ""))
    return name or None


def resolve_place_name(explicit: str | None, channel: Any) -> str | None:
    if explicit:
        return display_place_name(explicit)
    return infer_place_from_channel(channel)


def get_stash(*, guild_id: int, place: str) -> PlaceStash:
    place_name = display_place_name(place)
    place_key = normalize_place_key(place_name)
    with db_connection() as connection:
        row = connection.execute(
            "SELECT place_name, items_json FROM stashed_gear WHERE guild_id = ? AND place_key = ?",
            (str(guild_id), place_key),
        ).fetchone()
    if row is None:
        return PlaceStash(guild_id=guild_id, place_key=place_key, place_name=place_name)
    data = json.loads(row["items_json"])
    if isinstance(data, list):
        data = {"place_name": row["place_name"], "entries": data}
    stash = PlaceStash.from_dict(guild_id=guild_id, place_key=place_key, data=data)
    if row["place_name"]:
        stash.place_name = str(row["place_name"])
    return stash


def save_stash(stash: PlaceStash) -> None:
    with db_connection() as connection:
        if not stash.entries:
            connection.execute(
                "DELETE FROM stashed_gear WHERE guild_id = ? AND place_key = ?",
                (str(stash.guild_id), stash.place_key),
            )
            return
        connection.execute(
            """
            INSERT OR REPLACE INTO stashed_gear (guild_id, place_key, place_name, items_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                str(stash.guild_id),
                stash.place_key,
                stash.place_name,
                json.dumps(stash.to_dict(), ensure_ascii=False),
            ),
        )


def list_stashes(*, guild_id: int) -> list[PlaceStash]:
    with db_connection() as connection:
        rows = connection.execute(
            "SELECT place_key, place_name, items_json FROM stashed_gear WHERE guild_id = ? ORDER BY place_name",
            (str(guild_id),),
        ).fetchall()
    stashes: list[PlaceStash] = []
    for row in rows:
        data = json.loads(row["items_json"])
        if isinstance(data, list):
            data = {"place_name": row["place_name"], "entries": data}
        stash = PlaceStash.from_dict(
            guild_id=guild_id,
            place_key=str(row["place_key"]),
            data=data,
        )
        if row["place_name"]:
            stash.place_name = str(row["place_name"])
        if stash.entries:
            stashes.append(stash)
    return stashes


def _same_stash_stack(existing: StashEntry, incoming: StashEntry) -> bool:
    same_item = (
        existing.item.slug == incoming.item.slug
        or existing.item.name.lower() == incoming.item.name.lower()
    )
    return (
        same_item
        and existing.item.stored_in == incoming.item.stored_in
        and existing.note == incoming.note
        and existing.left_by.casefold() == incoming.left_by.casefold()
    )


def _is_container_item(item: InventoryItem) -> bool:
    if item.capacity_lb is not None and item.capacity_lb > 0:
        return True
    return custom_container_capacity(item.name) is not None


def _is_nested_in(
    item: InventoryItem, container: InventoryItem, entries: list[StashEntry]
) -> bool:
    current = item.stored_in
    seen: set[str] = set()
    slugs = {entry.item.slug: entry.item for entry in entries}
    while current and current not in seen:
        if current == container.slug:
            return True
        seen.add(current)
        parent = slugs.get(current)
        current = parent.stored_in if parent is not None else None
    return False


def _prefer_stash_entry(entries: list[StashEntry]) -> StashEntry:
    return sorted(
        entries,
        key=lambda entry: (
            1
            if entry.item.stored_in and entry.item.stored_in not in SPECIAL_LOCATIONS
            else 0,
            -entry.item.quantity,
        ),
    )[0]


def _format_stash_line(entry: StashEntry, *, nested: bool) -> str:
    line = format_item_line(entry.item)
    extras: list[str] = []
    if entry.left_by and not nested:
        extras.append(entry.left_by)
    if entry.note and not nested:
        extras.append(entry.note)
    if extras:
        return f"{line} — {': '.join(extras) if len(extras) == 2 else extras[0]}"
    return line
