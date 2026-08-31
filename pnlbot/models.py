"""Core value objects shared by the storage, P&L and formatting layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

BUY = "buy"
SELL = "sell"


def to_decimal(value) -> Decimal:
    """Convert floats/ints/strings to Decimal without binary float artefacts."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Trade:
    """A single fill: one buy or one sell of one ticker."""

    ticker: str
    side: str
    quantity: Decimal
    price: Decimal
    traded_at: datetime
    fee: Decimal = Decimal("0")
    currency: str = "USD"
    id: int | None = None
    user_id: int | None = None
    source: str = "manual"
    source_ref: str | None = None
    batch_id: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if self.side not in (BUY, SELL):
            raise ValueError(f"side must be {BUY!r} or {SELL!r}, got {self.side!r}")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive; use side to express direction")
        if self.price < 0:
            raise ValueError("price cannot be negative")

    @property
    def signed_quantity(self) -> Decimal:
        return self.quantity if self.side == BUY else -self.quantity

    @property
    def gross_value(self) -> Decimal:
        """Cash value of the fill before fees (always positive)."""
        return self.quantity * self.price

    @property
    def fee_per_share(self) -> Decimal:
        return self.fee / self.quantity if self.quantity else Decimal("0")


@dataclass(frozen=True)
class ParsedTrade:
    """A trade the model read out of a screenshot, before the user confirms it."""

    ticker: str
    side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal = Decimal("0")
    currency: str = "USD"
    traded_at: datetime | None = None
    note: str | None = None

    def to_trade(self, *, user_id: int, source: str, source_ref: str | None,
                 batch_id: str, fallback_time: datetime | None = None) -> Trade:
        return Trade(
            ticker=self.ticker,
            side=self.side,
            quantity=self.quantity,
            price=self.price,
            fee=self.fee,
            currency=self.currency,
            traded_at=self.traded_at or fallback_time or utcnow(),
            user_id=user_id,
            source=source,
            source_ref=source_ref,
            batch_id=batch_id,
            note=self.note,
        )
