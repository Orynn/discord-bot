import re
from dataclasses import dataclass, field
from typing import Any

from sheets.containers import (
    BELT_ALIASES,
    BELT_SLOTS,
    DEFAULT_BAG_CAPACITY_LB,
    HAND_ALIASES,
    HAND_SLOTS,
    MAX_BELT_CONTAINER_LB,
    SPECIAL_LOCATIONS,
    STORED_BELT,
    STORED_HANDS,
    STORED_LOOSE,
    STORED_WORN,
    container_capacity_from_raw,
    custom_container_capacity,
    is_shield_raw,
    is_two_handed_raw,
)
from srd.fivetools_parser import kg_to_lb, parse_weight_lb, format_weight_from_lb

ITEM_KIND_WEAPON = "weapon"
ITEM_KIND_ARMOR = "armor"
ITEM_KIND_ITEM = "item"
ITEM_KIND_CUSTOM = "custom"

CUSTOM_PREFIX = "custom:"
CARRY_CAPACITY_PER_STR = 15

_QUANTITY_SUFFIX = re.compile(r"^(.+?)\s+[x×*](\d+)$", re.IGNORECASE)
_MASS_TOKEN = re.compile(
    r"^(?P<weight>\d+(?:[.,]\d+)?)\s*(?P<unit>kg|kgs|kilo|kilos|kilogrammes?|lb|lbs|pounds?)?\.?$",
    re.IGNORECASE,
)
_MASS_SUFFIX = re.compile(
    r"^(?P<body>.+?)\s+(?P<weight>\d+(?:[.,]\d+)?)\s*(?P<unit>kg|kgs|kilo|kilos|kilogrammes?|lb|lbs|pounds?)\.?\s*$",
    re.IGNORECASE,
)


@dataclass
class InventoryItem:
    slug: str
    name: str
    kind: str = ITEM_KIND_ITEM
    quantity: int = 1
    equipped: bool = False
    notes: str = ""
    weight_lb: float | None = None
    stored_in: str | None = None
    capacity_lb: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "slug": self.slug,
            "name": self.name,
            "kind": self.kind,
            "quantity": self.quantity,
            "equipped": self.equipped,
            "notes": self.notes,
        }
        if self.weight_lb is not None:
            data["weight_lb"] = self.weight_lb
        if self.stored_in:
            data["stored_in"] = self.stored_in
        if self.capacity_lb is not None:
            data["capacity_lb"] = self.capacity_lb
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InventoryItem":
        weight = data.get("weight_lb")
        stored_in = data.get("stored_in")
        capacity = data.get("capacity_lb")
        return cls(
            slug=data.get("slug", ""),
            name=data.get("name", ""),
            kind=data.get("kind", ITEM_KIND_ITEM),
            quantity=max(1, int(data.get("quantity", 1))),
            equipped=bool(data.get("equipped", False)),
            notes=data.get("notes", ""),
            weight_lb=parse_weight_lb(weight) if weight is not None else None,
            stored_in=str(stored_in) if stored_in else None,
            capacity_lb=parse_weight_lb(capacity) if capacity is not None else None,
        )


@dataclass
class Equipment:
    items: list[InventoryItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"items": [item.to_dict() for item in self.items]}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Equipment":
        if not data:
            return cls()
        return cls(items=[InventoryItem.from_dict(entry) for entry in data.get("items", [])])

    def find_item(self, query: str) -> InventoryItem | None:
        matches = self.find_items(query)
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]
        return self._prefer_item(matches)

    def find_items(self, query: str) -> list[InventoryItem]:
        cleaned = query.strip()
        if not cleaned:
            return []
        query_lower = cleaned.lower()
        exact = [
            item
            for item in self.items
            if item.name.lower() == query_lower or item.slug.lower() == query_lower
        ]
        if exact:
            return exact
        return [
            item
            for item in self.items
            if query_lower in item.name.lower() or query_lower in item.slug.lower()
        ]

    def _prefer_item(self, items: list[InventoryItem]) -> InventoryItem:
        rank = {
            STORED_HANDS: 0,
            STORED_BELT: 1,
            STORED_WORN: 2,
            STORED_LOOSE: 4,
        }
        return sorted(
            items,
            key=lambda item: (0 if item.equipped else 1, rank.get(item.stored_in or "", 2)),
        )[0]

    def add_item(
        self,
        *,
        slug: str,
        name: str,
        kind: str,
        quantity: int = 1,
        weight_lb: float | None = None,
        stored_in: str | None = None,
        auto_stow: bool = True,
    ) -> InventoryItem:
        if quantity < 1:
            raise ValueError("Quantity must be at least 1.")

        if stored_in is not None or not auto_stow:
            return self._merge_or_append(
                slug=slug,
                name=name,
                kind=kind,
                quantity=quantity,
                weight_lb=weight_lb,
                stored_in=stored_in,
            )

        added = self._auto_stow_new(
            slug=slug,
            name=name,
            kind=kind,
            quantity=quantity,
            weight_lb=weight_lb,
        )
        if self.is_container(added):
            self.stow_loose()
        return added

    def wear_loose_armor(self) -> InventoryItem | None:
        if any(
            item.equipped and item.kind == ITEM_KIND_ARMOR and not self.is_shield(item)
            for item in self.items
        ):
            return None
        for item in list(self.items):
            if item.stored_in != STORED_LOOSE:
                continue
            if item.kind != ITEM_KIND_ARMOR or self.is_shield(item):
                continue
            try:
                return self.equip(item.name)
            except ValueError:
                continue
        return None

    def ensure_pack_bag(self) -> InventoryItem | None:
        if self.containers():
            return None
        if not any(item.stored_in == STORED_LOOSE for item in self.items):
            return None
        return self.add_item(
            slug="backpack",
            name="Backpack",
            kind=ITEM_KIND_ITEM,
            weight_lb=5,
        )

    def remove_item(self, query: str, *, quantity: int | None = None) -> InventoryItem | None:
        item = self.find_item(query)
        if item is None:
            return None

        if quantity is None or quantity >= item.quantity:
            self.items.remove(item)
            if self.is_container(item):
                self._release_contents(item)
            return item

        if quantity < 1:
            raise ValueError("Quantity must be at least 1.")

        item.quantity -= quantity
        removed = InventoryItem(
            slug=item.slug,
            name=item.name,
            kind=item.kind,
            quantity=quantity,
            equipped=False,
            notes=item.notes,
            weight_lb=item.weight_lb,
            stored_in=item.stored_in,
            capacity_lb=item.capacity_lb,
        )
        if item.equipped and item.quantity > 1:
            item.equipped = False
        return removed

    def contents_tree(self, container: InventoryItem) -> list[InventoryItem]:
        nested: list[InventoryItem] = []
        for item in self.items:
            if item.stored_in != container.slug:
                continue
            nested.append(item)
            if self.is_container(item):
                nested.extend(self.contents_tree(item))
        return nested

    def detach_for_stash(self, query: str, *, quantity: int | None = None) -> list[InventoryItem]:
        item = self.find_item(query)
        if item is None:
            return []

        take_all = quantity is None or quantity >= item.quantity
        if take_all and self.is_container(item):
            nested = self.contents_tree(item)
            for child in nested:
                self.items.remove(child)
            self.items.remove(item)
            item.equipped = False
            item.stored_in = None
            return [item, *nested]

        removed = self.remove_item(query, quantity=quantity)
        if removed is None:
            return []
        removed.equipped = False
        removed.stored_in = None
        return [removed]

    def restore_item(self, item: InventoryItem, *, auto_stow: bool = True) -> InventoryItem:
        stored_in = None if auto_stow else item.stored_in
        if auto_stow and self.is_container(item):
            stored_in = STORED_WORN
            auto_stow = False
        added = self.add_item(
            slug=item.slug,
            name=item.name,
            kind=item.kind,
            quantity=item.quantity,
            weight_lb=item.weight_lb,
            stored_in=stored_in,
            auto_stow=auto_stow,
        )
        if item.notes:
            added.notes = item.notes
        if item.capacity_lb is not None:
            added.capacity_lb = item.capacity_lb
        return added

    def restore_stash_items(self, items: list[InventoryItem]) -> list[InventoryItem]:
        pending = [InventoryItem.from_dict(item.to_dict()) for item in items]
        restored: list[InventoryItem] = []
        while pending:
            progress = False
            pending_slugs = {item.slug for item in pending}
            restored_slugs = {item.slug for item in restored}
            for item in list(pending):
                parent = item.stored_in
                waiting = bool(parent) and parent in pending_slugs
                if waiting:
                    continue
                parent_restored = bool(parent) and parent in restored_slugs
                auto_stow = not parent_restored
                if auto_stow:
                    item.stored_in = None
                restored.append(self.restore_item(item, auto_stow=auto_stow))
                pending.remove(item)
                progress = True
            if not progress:
                leftover = pending.pop(0)
                leftover.stored_in = None
                restored.append(self.restore_item(leftover, auto_stow=True))
        return restored

    def equip(self, query: str) -> InventoryItem:
        item = self.find_item(query)
        if item is None:
            raise ValueError(f"Item not found: {query}")

        if item.quantity > 1:
            item = self._split_item(item, 1)

        if self.is_worn_when_equipped(item):
            for other in self.items:
                if other is item:
                    continue
                if other.kind == ITEM_KIND_ARMOR and not self.is_shield(other) and other.equipped:
                    other.equipped = False
                    self._stow_existing(other)
            item.stored_in = STORED_WORN
            item.equipped = True
            return item

        self._free_hands(self.required_hands(item))
        item.stored_in = STORED_HANDS
        item.equipped = True
        return item

    def unequip(self, query: str) -> InventoryItem:
        item = self.find_item(query)
        if item is None:
            raise ValueError(f"Item not found: {query}")
        item.equipped = False
        self._stow_existing(item)
        return item

    def equipped_items(self) -> list[InventoryItem]:
        return [item for item in self.items if item.equipped]

    def held_items(self) -> list[InventoryItem]:
        return [item for item in self.items if item.stored_in == STORED_HANDS]

    def belt_items(self) -> list[InventoryItem]:
        return [item for item in self.items if item.stored_in == STORED_BELT]

    def format_hands_field(self) -> tuple[str, str]:
        held_lines = [format_item_line(item) for item in self.held_items()] or ["—"]
        return (f"🖐️ Hands ({self.hands_used()}/{HAND_SLOTS})", "\n".join(held_lines))

    def format_belt_field(self) -> tuple[str, str]:
        belt_lines = [format_item_line(item) for item in self.belt_items()] or ["—"]
        return (f"🪢 Belt ({self.belt_slots_used()}/{BELT_SLOTS})", "\n".join(belt_lines))

    def format_summary(self, *, limit: int = 12, exclude_equipped: bool = False) -> str:
        items = [item for item in self.items if not exclude_equipped or not item.equipped]
        if not items:
            return ""

        lines: list[str] = []
        for item in items[:limit]:
            lines.append(format_item_line(item))

        if len(items) > limit:
            lines.append(f"… +{len(items) - limit} more")
        return "\n".join(lines)

    def unit_weight_lb(self, item: InventoryItem) -> float:
        if item.weight_lb is not None:
            return item.weight_lb
        looked_up = indexed_weight_lb(item.slug)
        return looked_up if looked_up is not None else 0.0

    def total_weight_lb(self) -> float:
        return sum(self.unit_weight_lb(item) * item.quantity for item in self.items)

    def _raw_for(self, item: InventoryItem) -> dict[str, Any] | None:
        indexed = _indexed_equipment(item.slug)
        return None if indexed is None else indexed[1]

    def container_info(self, item: InventoryItem) -> tuple[float, bool] | None:
        if item.capacity_lb is not None and item.capacity_lb > 0:
            return item.capacity_lb * item.quantity, False
        info = container_capacity_from_raw(self._raw_for(item))
        if info is not None:
            return info[0] * item.quantity, info[1]
        custom = custom_container_capacity(item.name)
        if custom is None:
            return None
        return custom[0] * item.quantity, custom[1]

    def is_container(self, item: InventoryItem) -> bool:
        return self.container_info(item) is not None

    def is_weightless_container(self, item: InventoryItem) -> bool:
        info = self.container_info(item)
        return bool(info and info[1])

    def is_shield(self, item: InventoryItem) -> bool:
        return is_shield_raw(self._raw_for(item), name=item.name)

    def is_two_handed(self, item: InventoryItem) -> bool:
        return is_two_handed_raw(self._raw_for(item))

    def is_worn_when_equipped(self, item: InventoryItem) -> bool:
        if self.is_shield(item):
            return False
        return item.kind == ITEM_KIND_ARMOR

    def required_hands(self, item: InventoryItem) -> int:
        if self.is_two_handed(item):
            return 2
        return min(max(item.quantity, 1), HAND_SLOTS)

    def hand_slots_for(self, item: InventoryItem) -> int:
        if item.stored_in != STORED_HANDS:
            return 0
        return self.required_hands(item)

    def hands_used(self) -> int:
        return sum(self.hand_slots_for(item) for item in self.items)

    def belt_slots_for(self, item: InventoryItem) -> int:
        if item.stored_in != STORED_BELT:
            return 0
        return max(item.quantity, 1)

    def belt_slots_used(self) -> int:
        return sum(self.belt_slots_for(item) for item in self.items)

    def can_hang_on_belt(self, item: InventoryItem) -> str | None:
        if self.is_worn_when_equipped(item):
            return f"**{item.name}** is worn, not hung on a belt."
        if not self.is_container(item):
            return None
        info = self.container_info(item)
        unit_capacity = (info[0] / max(item.quantity, 1)) if info else 0
        if unit_capacity > MAX_BELT_CONTAINER_LB:
            return f"**{item.name}** is too bulky for a belt."
        return None

    def find_container(self, query: str) -> InventoryItem | None:
        item = self.find_item(query)
        if item is not None and self.is_container(item):
            return item
        for candidate in self.items:
            if self.is_container(candidate) and (
                query.lower() == candidate.slug.lower()
                or query.lower() in candidate.name.lower()
            ):
                return candidate
        return None

    def containers(self) -> list[InventoryItem]:
        return [item for item in self.items if self.is_container(item)]

    def contents_weight_lb(self, container: InventoryItem, *, coin_lb: float = 0) -> float:
        used = 0.0
        for item in self.items:
            if item.stored_in != container.slug:
                continue
            used += self.unit_weight_lb(item) * item.quantity
            if self.is_container(item):
                used += self.contents_weight_lb(item, coin_lb=0)
        if self.coin_location(coin_lb) == container.slug:
            used += coin_lb
        return used

    def remaining_capacity_lb(self, container: InventoryItem, *, coin_lb: float = 0) -> float:
        info = self.container_info(container)
        if info is None:
            return 0.0
        return max(0.0, info[0] - self.contents_weight_lb(container, coin_lb=coin_lb))

    def counts_toward_load(self, item: InventoryItem) -> bool:
        location = item.stored_in
        seen: set[str] = set()
        while location and location not in SPECIAL_LOCATIONS:
            if location in seen:
                break
            seen.add(location)
            container = next((entry for entry in self.items if entry.slug == location), None)
            if container is None:
                break
            if self.is_weightless_container(container):
                return False
            location = container.stored_in
        return True

    def coin_location(self, coin_lb: float) -> str:
        if coin_lb <= 0:
            return STORED_LOOSE
        pouches = [
            item
            for item in self.containers()
            if custom_container_capacity(item.name) == (6.0, False)
            or "pouch" in item.name.lower()
            or "bourse" in item.name.lower()
        ]
        for container in pouches + self.containers():
            if self.remaining_capacity_lb(container, coin_lb=0) >= coin_lb:
                return container.slug
        if pouches:
            return pouches[0].slug
        containers = self.containers()
        if containers:
            return containers[0].slug
        return STORED_LOOSE

    def coins_count_toward_load(self, coin_lb: float) -> bool:
        location = self.coin_location(coin_lb)
        if location == STORED_LOOSE:
            return True
        container = next((item for item in self.items if item.slug == location), None)
        if container is None:
            return True
        return self.counts_toward_load(container) and not self.is_weightless_container(container)

    def carried_weight_lb(self, *, coin_lb: float = 0) -> float:
        self.stow_unassigned()
        total = 0.0
        for item in self.items:
            if self.counts_toward_load(item):
                total += self.unit_weight_lb(item) * item.quantity
        if self.coins_count_toward_load(coin_lb):
            total += coin_lb
        return total

    def _merge_or_append(
        self,
        *,
        slug: str,
        name: str,
        kind: str,
        quantity: int,
        weight_lb: float | None,
        stored_in: str | None,
        equipped: bool = False,
    ) -> InventoryItem:
        for existing in self.items:
            same_place = existing.stored_in == stored_in
            same_item = existing.slug == slug or existing.name.lower() == name.lower()
            if not (same_place and same_item):
                continue
            if self.is_container(existing):
                continue
            if existing.slug != slug:
                existing.slug = slug
                existing.name = name
                existing.kind = kind
            existing.quantity += quantity
            if weight_lb is not None:
                existing.weight_lb = weight_lb
            if equipped:
                existing.equipped = True
            return existing
        item = InventoryItem(
            slug=slug,
            name=name,
            kind=kind,
            quantity=quantity,
            weight_lb=weight_lb,
            stored_in=stored_in,
            equipped=equipped,
        )
        self.items.append(item)
        return item

    def _split_item(self, item: InventoryItem, quantity: int) -> InventoryItem:
        if quantity >= item.quantity:
            return item
        item.quantity -= quantity
        split = InventoryItem(
            slug=item.slug,
            name=item.name,
            kind=item.kind,
            quantity=quantity,
            equipped=False,
            notes=item.notes,
            weight_lb=item.weight_lb,
            stored_in=item.stored_in,
            capacity_lb=item.capacity_lb,
        )
        self.items.append(split)
        return split

    def _preferred_containers(self) -> list[InventoryItem]:
        def sort_key(item: InventoryItem) -> tuple[int, float]:
            name = item.name.lower()
            pouch = 0 if ("pouch" in name or "bourse" in name) else 1
            return pouch, -self.remaining_capacity_lb(item)

        return sorted(self.containers(), key=sort_key)

    def _auto_stow_new(
        self,
        *,
        slug: str,
        name: str,
        kind: str,
        quantity: int,
        weight_lb: float | None,
    ) -> InventoryItem:
        placeholder = InventoryItem(slug=slug, name=name, kind=kind, quantity=quantity, weight_lb=weight_lb)
        if self.is_container(placeholder):
            return self._merge_or_append(
                slug=slug,
                name=name,
                kind=kind,
                quantity=quantity,
                weight_lb=weight_lb,
                stored_in=STORED_WORN,
            )

        remaining = quantity
        unit = self.unit_weight_lb(placeholder)
        added: InventoryItem | None = None
        for container in self._preferred_containers():
            if remaining <= 0:
                break
            free = self.remaining_capacity_lb(container)
            if unit <= 0:
                fit = remaining
            elif free <= 0:
                continue
            else:
                fit = min(remaining, int(free // unit) if unit else remaining)
                if fit <= 0 and free >= unit:
                    fit = 1
                if fit <= 0:
                    continue
            stacked = self._merge_or_append(
                slug=slug,
                name=name,
                kind=kind,
                quantity=fit,
                weight_lb=weight_lb,
                stored_in=container.slug,
            )
            if added is None:
                added = stacked
            remaining -= fit

        if remaining > 0 and (
            kind == ITEM_KIND_WEAPON or self.is_shield(placeholder)
        ):
            free_hands = HAND_SLOTS - self.hands_used()
            if self.is_two_handed(placeholder):
                hold = 1 if free_hands >= 2 else 0
            else:
                hold = min(remaining, free_hands)
            if hold > 0:
                stacked = self._merge_or_append(
                    slug=slug,
                    name=name,
                    kind=kind,
                    quantity=hold,
                    weight_lb=weight_lb,
                    stored_in=STORED_HANDS,
                    equipped=True,
                )
                if added is None:
                    added = stacked
                remaining -= hold

        if remaining > 0:
            stacked = self._merge_or_append(
                slug=slug,
                name=name,
                kind=kind,
                quantity=remaining,
                weight_lb=weight_lb,
                stored_in=STORED_LOOSE,
            )
            if added is None:
                added = stacked
        assert added is not None
        return added

    def stow_unassigned(self) -> None:
        unassigned = [item for item in self.items if not item.stored_in]
        for item in unassigned:
            if self.is_container(item):
                item.stored_in = STORED_WORN
                continue
            if item.equipped and self.is_worn_when_equipped(item):
                item.stored_in = STORED_WORN
                continue
            if item.equipped:
                item.stored_in = STORED_HANDS
                continue
            self._stow_existing(item)
        self.coalesce_stacks()

    def _shares_stack(self, left: InventoryItem, right: InventoryItem) -> bool:
        if left is right:
            return False
        if not left.stored_in or left.stored_in != right.stored_in:
            return False
        if self.is_container(left) or self.is_container(right):
            return False
        return left.slug == right.slug or left.name.lower() == right.name.lower()

    def _merge_into_location(self, item: InventoryItem) -> InventoryItem:
        if item not in self.items:
            return item
        for existing in self.items:
            if not self._shares_stack(existing, item):
                continue
            existing.quantity += item.quantity
            if item.equipped:
                existing.equipped = True
            if item.weight_lb is not None:
                existing.weight_lb = item.weight_lb
            if is_custom_slug(existing.slug) and not is_custom_slug(item.slug):
                existing.slug = item.slug
                existing.name = item.name
                existing.kind = item.kind
            self.items.remove(item)
            return existing
        return item

    def coalesce_stacks(self) -> None:
        index = 0
        while index < len(self.items):
            item = self.items[index]
            merged = self._merge_into_location(item)
            if merged is not item:
                continue
            index += 1

    def _stow_existing(self, item: InventoryItem) -> None:
        if self.is_container(item):
            item.stored_in = STORED_WORN
            item.equipped = False
            return
        remaining = item
        unit = self.unit_weight_lb(remaining)
        for container in self._preferred_containers():
            if remaining.quantity <= 0:
                break
            if remaining.slug == container.slug:
                continue
            free = self.remaining_capacity_lb(container)
            if unit <= 0:
                fit = remaining.quantity
            elif free <= 0:
                continue
            else:
                fit = min(remaining.quantity, int(free // unit) if unit else remaining.quantity)
                if fit <= 0:
                    continue
            if fit < remaining.quantity:
                moved = self._split_item(remaining, fit)
                moved.stored_in = container.slug
                moved.equipped = False
                self._merge_into_location(moved)
            else:
                remaining.stored_in = container.slug
                remaining.equipped = False
                self._merge_into_location(remaining)
                return
        if remaining.quantity > 0:
            remaining.stored_in = STORED_LOOSE
            remaining.equipped = False
            self._merge_into_location(remaining)

    def _free_hands(self, needed: int) -> None:
        used = self.hands_used()
        if used + needed <= HAND_SLOTS:
            return
        held = [item for item in self.items if item.stored_in == STORED_HANDS]
        for item in held:
            if self.hands_used() + needed <= HAND_SLOTS:
                return
            self._stow_existing(item)

    def _release_contents(self, container: InventoryItem) -> None:
        for item in list(self.items):
            if item.stored_in == container.slug:
                self._stow_existing(item)

    def _move_to_container(self, item: InventoryItem, container: InventoryItem) -> InventoryItem:
        if item is container:
            raise ValueError("An item cannot be stored inside itself.")
        unit = self.unit_weight_lb(item)
        free = self.remaining_capacity_lb(container)
        if unit > 0:
            fit = min(item.quantity, int(free // unit) if unit else item.quantity)
            if fit <= 0 and free >= unit:
                fit = 1
            if fit <= 0:
                raise ValueError(f"**{container.name}** is full.")
            if fit < item.quantity:
                item = self._split_item(item, fit)
        item.stored_in = container.slug
        item.equipped = False
        return self._merge_into_location(item)

    def _put_candidates(
        self,
        query: str,
        *,
        all_gear: bool,
        destination: InventoryItem | None = None,
        skip_location: str | None = None,
    ) -> list[InventoryItem]:
        if all_gear:
            candidates = []
            for item in list(self.items):
                if destination is not None and item is destination:
                    continue
                if skip_location and item.stored_in == skip_location:
                    continue
                if destination is not None and item.stored_in == destination.slug:
                    continue
                if self.is_container(item) and item.stored_in == STORED_WORN:
                    continue
                if item.equipped and self.is_worn_when_equipped(item):
                    continue
                candidates.append(item)
            return candidates
        matches = [item for item in self.find_items(query) if destination is None or item is not destination]
        if skip_location:
            matches = [item for item in matches if item.stored_in != skip_location]
        if destination is not None:
            matches = [item for item in matches if item.stored_in != destination.slug]
        return matches

    def put_in(self, query: str, container_query: str) -> InventoryItem:
        cleaned = query.strip()
        lowered = cleaned.casefold()
        all_gear = lowered in {"all", "*", "tout"}
        if not all_gear and lowered.startswith("all "):
            cleaned = cleaned[4:].strip()
        elif not all_gear and lowered.endswith(" all"):
            cleaned = cleaned[:-4].strip()
        target = container_query.strip().lower()
        if target in HAND_ALIASES:
            if all_gear:
                raise ValueError("Hold a specific item, or store `all` in a bag.")
            return self.hold(cleaned)
        if target in BELT_ALIASES:
            return self._put_on_belt(cleaned, all_gear=all_gear)

        container = self.find_container(container_query)
        if container is None:
            raise ValueError(f"No bag, pouch, or belt named: {container_query}")
        if not all_gear and not self.find_items(cleaned):
            raise ValueError(f"Item not found: {cleaned}")

        candidates = self._put_candidates(cleaned, all_gear=all_gear, destination=container)
        if not candidates:
            already = [
                item
                for item in self.find_items(cleaned)
                if item.stored_in == container.slug
            ]
            if already and not all_gear:
                return already[0]
            raise ValueError("Nothing to store there.")

        moved: InventoryItem | None = None
        for item in candidates:
            if item not in self.items or item is container:
                continue
            try:
                moved = self._move_to_container(item, container)
            except ValueError:
                if moved is None:
                    raise
                break
        if moved is None:
            raise ValueError("Nothing to store there.")
        self.coalesce_stacks()
        return moved

    def _put_on_belt(self, query: str, *, all_gear: bool) -> InventoryItem:
        candidates = self._put_candidates(query, all_gear=all_gear, skip_location=STORED_BELT)
        if not candidates:
            raise ValueError("Nothing to hang on the belt.")
        moved: InventoryItem | None = None
        for item in candidates:
            if item not in self.items or item.stored_in == STORED_BELT:
                continue
            try:
                moved = self.hang_on_belt(item.name)
            except ValueError:
                if moved is None:
                    raise
                break
        if moved is None:
            raise ValueError("Nothing to hang on the belt.")
        return moved

    def hang_on_belt(self, query: str) -> InventoryItem:
        matches = self.find_items(query)
        if not matches:
            raise ValueError(f"Item not found: {query}")
        off_belt = [item for item in matches if item.stored_in != STORED_BELT]
        item = off_belt[0] if off_belt else matches[0]
        blocked = self.can_hang_on_belt(item)
        if blocked:
            raise ValueError(blocked)
        if item.stored_in == STORED_BELT:
            return item

        free = BELT_SLOTS - self.belt_slots_used()
        if free <= 0:
            raise ValueError(f"Belt is full ({BELT_SLOTS}/{BELT_SLOTS}).")
        qty = min(item.quantity, free)
        if qty < item.quantity:
            item = self._split_item(item, qty)
        item.stored_in = STORED_BELT
        item.equipped = False
        return self._merge_into_location(item)

    def hold(self, query: str) -> InventoryItem:
        item = self.find_item(query)
        if item is None:
            raise ValueError(f"Item not found: {query}")
        if self.is_container(item):
            item.stored_in = STORED_WORN
            return item
        if item.quantity > 1 and self.is_two_handed(item):
            item = self._split_item(item, 1)
        hold_qty = 1 if item.quantity > 1 else item.quantity
        self._free_hands(self.required_hands(InventoryItem(
            slug=item.slug,
            name=item.name,
            kind=item.kind,
            quantity=hold_qty,
            weight_lb=item.weight_lb,
        )))
        if item.quantity > 1 and not self.is_two_handed(item):
            item = self._split_item(item, 1)
        item.stored_in = STORED_HANDS
        if item.kind == ITEM_KIND_WEAPON or self.is_shield(item):
            item.equipped = True
        return self._merge_into_location(item)

    def mark_as_bag(self, query: str, capacity_lb: float | None = None) -> InventoryItem:
        item = self.find_item(query)
        if item is None:
            raise ValueError(f"Item not found: {query}")
        if not is_custom_slug(item.slug) and item.kind != ITEM_KIND_CUSTOM:
            raise ValueError("Only custom items can be marked as bags.")

        if capacity_lb is not None and capacity_lb <= 0:
            item.capacity_lb = None
            self._release_contents(item)
            return item

        item.capacity_lb = DEFAULT_BAG_CAPACITY_LB if capacity_lb is None else capacity_lb
        if item.stored_in in {STORED_HANDS, STORED_LOOSE, None}:
            item.stored_in = STORED_WORN
            item.equipped = False
        elif item.stored_in == STORED_BELT and item.capacity_lb > MAX_BELT_CONTAINER_LB:
            item.stored_in = STORED_WORN
            item.equipped = False
        self.stow_loose()
        return item

    def stow_loose(self) -> int:
        moved = 0
        for item in list(self.items):
            if item.stored_in == STORED_LOOSE:
                before = item.stored_in
                self._stow_existing(item)
                if item.stored_in != before:
                    moved += 1
        self.coalesce_stacks()
        return moved

    def format_storage_fields(self, *, coin_lb: float = 0, coin_text: str = "") -> list[tuple[str, str]]:
        self.stow_unassigned()
        self.coalesce_stacks()
        fields: list[tuple[str, str]] = []

        fields.append(self.format_hands_field())
        fields.append(self.format_belt_field())

        worn = [
            item
            for item in self.items
            if item.stored_in == STORED_WORN and not self.is_container(item)
        ]
        if worn:
            fields.append(("👕 Worn", "\n".join(format_item_line(item) for item in worn)))

        coin_loc = self.coin_location(coin_lb)
        for container in self.containers():
            info = self.container_info(container)
            if info is None:
                continue
            capacity, weightless = info
            used = self.contents_weight_lb(container, coin_lb=coin_lb)
            label = f"🎒 {container.name} ({format_pounds(used)}/{format_pounds(capacity)})"
            if weightless:
                label += " · weightless"
            lines = [
                format_item_line(item)
                for item in self.items
                if item.stored_in == container.slug
            ]
            if coin_loc == container.slug and coin_text:
                lines.append(f"💰 {coin_text}")
            fields.append((label, "\n".join(lines) or "— empty —"))

        loose = [item for item in self.items if item.stored_in == STORED_LOOSE]
        if loose or (coin_lb > 0 and coin_loc == STORED_LOOSE):
            lines = [format_item_line(item) for item in loose]
            if coin_lb > 0 and coin_loc == STORED_LOOSE and coin_text:
                lines.append(f"💰 {coin_text}")
            fields.append(("⚠️ Loose — not in a bag, hand, or belt", "\n".join(lines) or "—"))
        return fields


def _mass_amount_to_lb(amount: float, unit: str | None, *, default_unit: str = "kg") -> float:
    resolved = (unit or default_unit).lower()
    if resolved.startswith("kg") or resolved.startswith("kilo"):
        return kg_to_lb(amount)
    return amount


def parse_user_mass_lb(token: str, *, default_unit: str = "kg") -> float | None:
    match = _MASS_TOKEN.match(token.strip())
    if not match:
        return None
    amount = float(match.group("weight").replace(",", "."))
    return _mass_amount_to_lb(amount, match.group("unit"), default_unit=default_unit)


def parse_name_and_quantity(text: str) -> tuple[str, int | None]:
    cleaned = text.strip()
    if not cleaned:
        return "", None

    explicit = _QUANTITY_SUFFIX.match(cleaned)
    if explicit:
        quantity = int(explicit.group(2))
        if quantity >= 1:
            return explicit.group(1).strip(), quantity

    parts = cleaned.rsplit(maxsplit=1)
    if len(parts) == 2 and len(parts[0].split()) == 1:
        try:
            quantity = int(parts[1])
            if 1 <= quantity <= 99:
                return parts[0], quantity
        except ValueError:
            pass

    return cleaned, None


def parse_name_quantity_and_weight(text: str) -> tuple[str, int | None, float | None]:
    cleaned = text.strip()
    weight: float | None = None
    match = _MASS_SUFFIX.match(cleaned)
    if match:
        cleaned = match.group("body").strip()
        amount = float(match.group("weight").replace(",", "."))
        weight = _mass_amount_to_lb(amount, match.group("unit"))
    name, quantity = parse_name_and_quantity(cleaned)
    return name, quantity, weight


def parse_item_and_weight(text: str) -> tuple[str, float | None]:
    cleaned = text.strip()
    match = _MASS_SUFFIX.match(cleaned)
    if match:
        amount = float(match.group("weight").replace(",", "."))
        return match.group("body").strip(), _mass_amount_to_lb(amount, match.group("unit"))

    parts = cleaned.rsplit(maxsplit=1)
    if len(parts) == 2:
        weight = parse_user_mass_lb(parts[1])
        if weight is not None:
            return parts[0].strip(), weight
    return cleaned, None


def pack_bundle_contents(entry: dict[str, Any]) -> list[tuple[str, int]] | None:
    raw = entry.get("packContents")
    if not isinstance(raw, list) or len(raw) < 2:
        return None
    pieces: list[tuple[str, int]] = []
    has_bag = False
    for part in raw:
        if isinstance(part, str):
            slug = part.split("|", 1)[0]
            quantity = 1
        elif isinstance(part, dict) and part.get("item"):
            slug = str(part["item"]).split("|", 1)[0]
            try:
                quantity = max(1, int(part.get("quantity") or 1))
            except (TypeError, ValueError):
                quantity = 1
        else:
            continue
        query = slug.replace("-", " ").strip()
        if not query:
            continue
        pieces.append((query, quantity))
        lowered = query.lower()
        if "backpack" in lowered or "pouch" in lowered or "haversack" in lowered:
            has_bag = True
    if not has_bag or not pieces:
        return None
    return pieces


def custom_slug(name: str) -> str:
    return f"{CUSTOM_PREFIX}{name.strip()}"


def is_custom_slug(slug: str) -> bool:
    return slug.startswith(CUSTOM_PREFIX)


from srd.fivetools import entry_url, entry_url_for_item
from srd.linkify import markdown_link
from srd.fivetools.loader import get_index


def _indexed_equipment(slug: str) -> tuple[str, dict[str, Any]] | None:
    index = get_index()
    for kind, store in (
        ("weapon", index.weapons_by_slug),
        ("armor", index.armor_by_slug),
        ("item", index.items_by_slug),
    ):
        item = store.get(slug)
        if item is not None:
            return kind, item
    return None


def equipment_url(slug: str, *, name: str | None = None) -> str | None:
    if is_custom_slug(slug):
        return None
    indexed = _indexed_equipment(slug)
    if indexed is not None:
        kind, item = indexed
        return entry_url_for_item(kind, item)
    display_name = name or slug.replace("-", " ").title()
    return entry_url("item", display_name)


def indexed_weight_lb(slug: str) -> float | None:
    if not slug or is_custom_slug(slug):
        return None
    try:
        indexed = _indexed_equipment(slug)
    except FileNotFoundError:
        return None
    if indexed is None:
        return None
    _, item = indexed
    return parse_weight_lb(item.get("weight"))


def encumbered_speed(*, base_speed: int, carried_lb: float, capacity_lb: int) -> int:
    base = max(0, int(base_speed))
    if base <= 0:
        return 0
    if carried_lb <= capacity_lb:
        return base
    if capacity_lb <= 0:
        return 5
    raw = base * (capacity_lb / carried_lb)
    stepped = int((raw + 2.5) // 5 * 5)
    return max(5, min(base, stepped))


def format_pounds(value: float | int) -> str:
    return format_weight_from_lb(value)


def format_load_line(
    *,
    gear_lb: float,
    coin_lb: float,
    capacity_lb: int,
    speed_ft: int | None = None,
    base_speed: int | None = None,
) -> str:
    carried = gear_lb + coin_lb
    load = f"{format_pounds(carried)} / {format_pounds(capacity_lb)}"
    extra = ""
    if coin_lb > 0:
        extra = f"\n{format_pounds(gear_lb)} gear · {format_pounds(coin_lb)} coins"
    speed_bit = ""
    if (
        speed_ft is not None
        and base_speed is not None
        and speed_ft < base_speed
    ):
        speed_bit = f" · 👟 {speed_ft} ft. (−{base_speed - speed_ft})"
    if carried > capacity_lb:
        return f"⚠️ Encumbered — {load}{speed_bit}{extra}"
    remaining = max(0.0, capacity_lb - carried)
    return f"{load} · {format_pounds(remaining)} free{extra}"


def format_item_line(item: InventoryItem, *, limit: int | None = None) -> str:
    prefix = ""
    if item.equipped:
        prefix = "⚔️ " if item.kind == ITEM_KIND_WEAPON else "🛡️ " if item.kind == ITEM_KIND_ARMOR else "✓ "
    qty = f" ×{item.quantity}" if item.quantity > 1 else ""
    name = item.name if limit is None else item.name[:limit]
    url = equipment_url(item.slug, name=item.name)
    if url:
        return f"{prefix}{markdown_link(name, url)}{qty}"
    return f"{prefix}{name}{qty}"
