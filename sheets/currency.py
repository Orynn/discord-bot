import re
from dataclasses import dataclass

COIN_TYPES: tuple[str, ...] = ("cp", "sp", "ep", "gp", "pp")
COIN_VALUES: dict[str, int] = {"cp": 1, "sp": 10, "ep": 50, "gp": 100, "pp": 1000}
COIN_PATTERN = re.compile(r"(\d+)\s*(cp|sp|ep|gp|pp)\b", re.IGNORECASE)


@dataclass
class Currency:
    cp: int = 0
    sp: int = 0
    ep: int = 0
    gp: int = 0
    pp: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, int] | None) -> "Currency":
        if not data:
            return cls()
        return cls(**{coin: max(0, int(data.get(coin, 0))) for coin in COIN_TYPES})

    def to_dict(self) -> dict[str, int]:
        return {coin: getattr(self, coin) for coin in COIN_TYPES}

    def total_cp(self) -> int:
        return sum(getattr(self, coin) * COIN_VALUES[coin] for coin in COIN_TYPES)

    def normalize(self) -> "Currency":
        total = self.total_cp()
        remaining = total
        coins: dict[str, int] = {}
        for coin in reversed(COIN_TYPES):
            value = COIN_VALUES[coin]
            coins[coin], remaining = divmod(remaining, value)
        return Currency(**coins)

    def format(self) -> str:
        total = self.total_cp()
        if total == 0:
            return "0 gp"

        gp, remainder = divmod(total, 100)
        sp, cp = divmod(remainder, 10)
        parts = []
        if gp:
            parts.append(f"{gp} gp")
        if sp:
            parts.append(f"{sp} sp")
        if cp:
            parts.append(f"{cp} cp")
        return ", ".join(parts)

    def add(self, other: "Currency") -> None:
        merged = Currency.from_dict(
            {coin: getattr(self, coin) + getattr(other, coin) for coin in COIN_TYPES}
        ).normalize()
        for coin in COIN_TYPES:
            setattr(self, coin, getattr(merged, coin))

    def subtract(self, other: "Currency") -> bool:
        if self.total_cp() < other.total_cp():
            return False
        remaining = self.total_cp() - other.total_cp()
        normalized = Currency()
        for coin in reversed(COIN_TYPES):
            value = COIN_VALUES[coin]
            amount, remaining = divmod(remaining, value)
            setattr(normalized, coin, amount)
        for coin in COIN_TYPES:
            setattr(self, coin, getattr(normalized, coin))
        return True


def parse_currency(text: str) -> Currency:
    matches = COIN_PATTERN.findall(text)
    if not matches:
        raise ValueError(
            "Invalid amount. Examples: `50 gp`, `5 gp 3 sp`, `100 cp`"
        )

    coins = dict.fromkeys(COIN_TYPES, 0)
    for amount, coin in matches:
        coins[coin.lower()] += int(amount)

    return Currency.from_dict(coins).normalize()
