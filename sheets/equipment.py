import re
from dataclasses import dataclass, field
from typing import Any

ITEM_KIND_WEAPON = "weapon"
ITEM_KIND_ARMOR = "armor"
ITEM_KIND_ITEM = "item"
ITEM_KIND_CUSTOM = "custom"

CUSTOM_PREFIX = "custom:"

_QUANTITY_SUFFIX = re.compile(r"^(.+?)\s+[x×*](\d+)$", re.IGNORECASE)


@dataclass
class InventoryItem:
    slug: str
    name: str
    kind: str = ITEM_KIND_ITEM
    quantity: int = 1
    equipped: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "kind": self.kind,
            "quantity": self.quantity,
            "equipped": self.equipped,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InventoryItem":
        return cls(
            slug=data.get("slug", ""),
            name=data.get("name", ""),
            kind=data.get("kind", ITEM_KIND_ITEM),
            quantity=max(1, int(data.get("quantity", 1))),
            equipped=bool(data.get("equipped", False)),
            notes=data.get("notes", ""),
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
        cleaned = query.strip()
        if not cleaned:
            return None

        query_lower = cleaned.lower()
        for item in self.items:
            if item.name.lower() == query_lower or item.slug.lower() == query_lower:
                return item

        partial = [
            item
            for item in self.items
            if query_lower in item.name.lower() or query_lower in item.slug.lower()
        ]
        if len(partial) == 1:
            return partial[0]
        return None

    def add_item(
        self,
        *,
        slug: str,
        name: str,
        kind: str,
        quantity: int = 1,
    ) -> bool:
        if quantity < 1:
            raise ValueError("Quantity must be at least 1.")

        existing = self.find_item(name) or self.find_item(slug)
        if existing:
            if existing.slug == slug:
                existing.quantity += quantity
                return True
            if existing.name.lower() == name.lower():
                was_equipped = existing.equipped
                notes = existing.notes
                existing.slug = slug
                existing.name = name
                existing.kind = kind
                existing.quantity += quantity
                existing.equipped = was_equipped
                existing.notes = notes
                return True

        self.items.append(
            InventoryItem(
                slug=slug,
                name=name,
                kind=kind,
                quantity=quantity,
            )
        )
        return True

    def remove_item(self, query: str, *, quantity: int | None = None) -> InventoryItem | None:
        item = self.find_item(query)
        if item is None:
            return None

        if quantity is None or quantity >= item.quantity:
            self.items.remove(item)
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
        )
        if item.equipped and item.quantity > 1:
            item.equipped = False
        return removed

    def equip(self, query: str) -> InventoryItem:
        item = self.find_item(query)
        if item is None:
            raise ValueError(f"Item not found: {query}")

        if item.kind == ITEM_KIND_ARMOR:
            for other in self.items:
                if other.kind == ITEM_KIND_ARMOR and other is not item:
                    other.equipped = False

        item.equipped = True
        return item

    def unequip(self, query: str) -> InventoryItem:
        item = self.find_item(query)
        if item is None:
            raise ValueError(f"Item not found: {query}")
        item.equipped = False
        return item

    def equipped_items(self) -> list[InventoryItem]:
        return [item for item in self.items if item.equipped]

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


def format_item_line(item: InventoryItem, *, limit: int | None = None) -> str:
    prefix = ""
    if item.equipped:
        prefix = "⚔️ " if item.kind == ITEM_KIND_WEAPON else "🛡️ " if item.kind == ITEM_KIND_ARMOR else "✓ "
    qty = f" ×{item.quantity}" if item.quantity > 1 else ""
    name = item.name if limit is None else item.name[:limit]
    url = equipment_url(item.slug, name=item.name)
    if url:
        return f"{prefix}{markdown_link(name, url)}{qty}"
    return f"{prefix}**{name}**{qty}"
