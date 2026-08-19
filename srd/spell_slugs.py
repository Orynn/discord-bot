HOMEBREW_PREFIX = "homebrew:"

_LEGACY_PREFIXES = ("srd-2024_", "wotc-srd_", "srd_")


def normalize_stored_spell_slug(slug: str) -> str:
    """Normalize a stored spell slug to the short key (e.g. fireball)."""
    if slug.startswith(HOMEBREW_PREFIX):
        return slug
    for prefix in _LEGACY_PREFIXES:
        if slug.startswith(prefix):
            return slug[len(prefix) :]
    return slug


def slug_from_query(query: str) -> str:
    return query.strip().lower().replace(" ", "-")


def find_spell_slug_on_sheet(spells: list[str], query: str) -> str | None:
    """Match a sheet spell slug by exact slug only (no substring matching)."""
    needle = slug_from_query(query)
    if not needle:
        return None
    for slug in spells:
        if normalize_stored_spell_slug(slug).lower() == needle:
            return slug
    return None


def migrate_spell_slugs(spells: list[str]) -> tuple[list[str], bool]:
    """Return deduplicated migrated slugs and whether the list changed."""
    migrated: list[str] = []
    seen: set[str] = set()
    changed = False

    for slug in spells:
        normalized = normalize_stored_spell_slug(slug)
        if normalized != slug:
            changed = True
        if normalized in seen:
            changed = True
            continue
        seen.add(normalized)
        migrated.append(normalized)

    return migrated, changed
