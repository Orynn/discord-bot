import json

from data.db import db_connection
from sheets.currency import Currency


def get_party_currency(guild_id: int) -> Currency:
    with db_connection() as connection:
        row = connection.execute(
            "SELECT currency FROM party_treasury WHERE guild_id = ?",
            (str(guild_id),),
        ).fetchone()
    if row is None:
        return Currency()
    return Currency.from_dict(json.loads(row["currency"]))


def save_party_currency(guild_id: int, currency: Currency) -> None:
    with db_connection() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO party_treasury (guild_id, currency)
            VALUES (?, ?)
            """,
            (str(guild_id), json.dumps(currency.to_dict(), ensure_ascii=False)),
        )
