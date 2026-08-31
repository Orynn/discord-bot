import json
from collections.abc import Callable

from data.db import db_connection
from sheets.currency import Currency
from sheets.data import CharacterSheet
from sheets.portrait import clear_portrait_file
from srd.spell_slugs import migrate_spell_slugs


def get_sheet(*, user_id: int, guild_id: int) -> CharacterSheet | None:
    with db_connection() as connection:
        row = connection.execute(
            "SELECT data FROM sheets WHERE user_id = ? AND guild_id = ?",
            (str(user_id), str(guild_id)),
        ).fetchone()
    if row is None:
        return None
    return CharacterSheet.from_dict(json.loads(row["data"]))


def save_sheet(*, user_id: int, guild_id: int, sheet: CharacterSheet) -> None:
    migrated, _ = migrate_spell_slugs(sheet.spells)
    sheet.spells = migrated
    payload = json.dumps(sheet.to_dict(), ensure_ascii=False)
    with db_connection() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO sheets (user_id, guild_id, data) VALUES (?, ?, ?)",
            (str(user_id), str(guild_id), payload),
        )


def update_sheet(
    *, user_id: int, guild_id: int, updater: Callable[[CharacterSheet], None]
) -> CharacterSheet:
    with db_connection() as connection:
        row = connection.execute(
            "SELECT data FROM sheets WHERE user_id = ? AND guild_id = ?",
            (str(user_id), str(guild_id)),
        ).fetchone()
        if row is None:
            raise ValueError("Character sheet not found.")

        sheet = CharacterSheet.from_dict(json.loads(row["data"]))
        updater(sheet)
        connection.execute(
            "UPDATE sheets SET data = ? WHERE user_id = ? AND guild_id = ?",
            (
                json.dumps(sheet.to_dict(), ensure_ascii=False),
                str(user_id),
                str(guild_id),
            ),
        )
        return sheet


def transfer_currency(
    *, guild_id: int, payer_id: int, recipient_id: int, payment: Currency
) -> None:
    with db_connection() as connection:
        payer_row = connection.execute(
            "SELECT data FROM sheets WHERE user_id = ? AND guild_id = ?",
            (str(payer_id), str(guild_id)),
        ).fetchone()
        recipient_row = connection.execute(
            "SELECT data FROM sheets WHERE user_id = ? AND guild_id = ?",
            (str(recipient_id), str(guild_id)),
        ).fetchone()
        if payer_row is None or recipient_row is None:
            raise ValueError("Both players must have character sheets.")

        payer_sheet = CharacterSheet.from_dict(json.loads(payer_row["data"]))
        recipient_sheet = CharacterSheet.from_dict(json.loads(recipient_row["data"]))

        if not payer_sheet.currency.subtract(payment):
            raise ValueError(f"Cannot afford **{payment.format()}**.")

        recipient_sheet.currency.add(payment)
        connection.execute(
            "UPDATE sheets SET data = ? WHERE user_id = ? AND guild_id = ?",
            (
                json.dumps(payer_sheet.to_dict(), ensure_ascii=False),
                str(payer_id),
                str(guild_id),
            ),
        )
        connection.execute(
            "UPDATE sheets SET data = ? WHERE user_id = ? AND guild_id = ?",
            (
                json.dumps(recipient_sheet.to_dict(), ensure_ascii=False),
                str(recipient_id),
                str(guild_id),
            ),
        )


def delete_sheet(*, user_id: int, guild_id: int) -> bool:
    with db_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM sheets WHERE user_id = ? AND guild_id = ?",
            (str(user_id), str(guild_id)),
        )
        removed = cursor.rowcount > 0
    if removed:
        clear_portrait_file(guild_id=guild_id, user_id=user_id)
    return removed


def get_character_name(*, user_id: int, guild_id: int) -> str | None:
    sheet = get_sheet(user_id=user_id, guild_id=guild_id)
    return sheet.name if sheet else None


def set_character_name(*, user_id: int, guild_id: int, name: str) -> None:
    sheet = get_sheet(user_id=user_id, guild_id=guild_id)
    if sheet is None:
        sheet = CharacterSheet(name=name.strip())
    else:
        sheet.name = name.strip()
    save_sheet(user_id=user_id, guild_id=guild_id, sheet=sheet)


def get_all_pc_names(*, guild_id: int) -> set[str]:
    return get_all_sheet_names(guild_id=guild_id)


def list_sheet_user_ids(*, guild_id: int) -> list[int]:
    with db_connection() as connection:
        rows = connection.execute(
            "SELECT user_id FROM sheets WHERE guild_id = ?",
            (str(guild_id),),
        ).fetchall()
    ids: list[int] = []
    for row in rows:
        try:
            ids.append(int(row["user_id"]))
        except (TypeError, ValueError):
            continue
    return ids


def get_all_sheet_names(*, guild_id: int) -> set[str]:
    with db_connection() as connection:
        rows = connection.execute(
            "SELECT data FROM sheets WHERE guild_id = ?",
            (str(guild_id),),
        ).fetchall()
    names: set[str] = set()
    for row in rows:
        data = json.loads(row["data"])
        if data.get("name"):
            names.add(data["name"])
    return names


def find_user_id_by_character_name(*, guild_id: int, name: str) -> int | None:
    needle = name.strip().casefold()
    if not needle:
        return None
    with db_connection() as connection:
        rows = connection.execute(
            "SELECT user_id, data FROM sheets WHERE guild_id = ?",
            (str(guild_id),),
        ).fetchall()
    for row in rows:
        data = json.loads(row["data"])
        sheet_name = str(data.get("name") or "").strip()
        if sheet_name.casefold() == needle:
            try:
                return int(row["user_id"])
            except (TypeError, ValueError):
                continue
    return None
