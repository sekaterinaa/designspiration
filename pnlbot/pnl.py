"""FIFO profit-and-loss engine.

Trades are matched first-in-first-out per (ticker, currency). Opening a
position in either direction is supported: buying into a flat or long book
opens/extends a long, selling into a flat or short book opens/extends a short,
and a trade in the opposite direction closes existing lots and realises P&L.

Fees are amortised per share: the opening trade's fee rides along with the lot
and is charged when the lot is closed, and the closing trade's fee is split
across the quantity it closes. That way every dollar of commission lands in the
realised P&L of the round trip that paid it.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .models import BUY, Trade

ZERO = Decimal("0")
LONG = "long"
SHORT = "short"


@dataclass
class OpenLot:
    """An still-open parcel of shares."""

    quantity: Decimal
    price: Decimal
    fee_per_share: Decimal
    opened_at: datetime
    trade_id: int | None
    direction: str

    @property
    def cost(self) -> Decimal:
        """Money tied up in the lot, including the entry fee."""
        return self.quantity * (self.price + self.fee_per_share)


@dataclass(frozen=True)
class RoundTrip:
    """One closed parcel: quantity matched between an opening and closing fill."""

    ticker: str
    currency: str
    direction: str
    quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal
    fees: Decimal
    opened_at: datetime
    closed_at: datetime
    open_trade_id: int | None
    close_trade_id: int | None

    @property
    def gross_pnl(self) -> Decimal:
        move = self.exit_price - self.entry_price
        if self.direction == SHORT:
            move = -move
        return move * self.quantity

    @property
    def pnl(self) -> Decimal:
        return self.gross_pnl - self.fees

    @property
    def cost_basis(self) -> Decimal:
        return self.entry_price * self.quantity

    @property
    def return_pct(self) -> Decimal | None:
        if self.cost_basis == ZERO:
            return None
        return self.pnl / self.cost_basis * Decimal("100")

    @property
    def holding_days(self) -> int:
        return max((self.closed_at - self.opened_at).days, 0)


@dataclass
class Position:
    """Everything known about one ticker in one currency."""

    ticker: str
    currency: str
    round_trips: list[RoundTrip] = field(default_factory=list)
    open_lots: list[OpenLot] = field(default_factory=list)
    trade_count: int = 0
    fees_paid: Decimal = ZERO
    mark: Decimal | None = None
    first_trade_at: datetime | None = None
    last_trade_at: datetime | None = None

    @property
    def realized(self) -> Decimal:
        return sum((rt.pnl for rt in self.round_trips), ZERO)

    @property
    def realized_cost_basis(self) -> Decimal:
        return sum((rt.cost_basis for rt in self.round_trips), ZERO)

    @property
    def realized_return_pct(self) -> Decimal | None:
        basis = self.realized_cost_basis
        if basis == ZERO:
            return None
        return self.realized / basis * Decimal("100")

    @property
    def wins(self) -> int:
        return sum(1 for rt in self.round_trips if rt.pnl > 0)

    @property
    def losses(self) -> int:
        return sum(1 for rt in self.round_trips if rt.pnl < 0)

    @property
    def win_rate_pct(self) -> Decimal | None:
        decided = self.wins + self.losses
        if not decided:
            return None
        return Decimal(self.wins) / Decimal(decided) * Decimal("100")

    @property
    def direction(self) -> str | None:
        return self.open_lots[0].direction if self.open_lots else None

    @property
    def open_quantity(self) -> Decimal:
        """Signed: positive when long, negative when short, zero when flat."""
        qty = sum((lot.quantity for lot in self.open_lots), ZERO)
        return -qty if self.direction == SHORT else qty

    @property
    def open_cost(self) -> Decimal:
        return sum((lot.cost for lot in self.open_lots), ZERO)

    @property
    def open_avg_price(self) -> Decimal | None:
        qty = sum((lot.quantity for lot in self.open_lots), ZERO)
        if qty == ZERO:
            return None
        return self.open_cost / qty

    @property
    def is_open(self) -> bool:
        return bool(self.open_lots)

    @property
    def market_value(self) -> Decimal | None:
        if self.mark is None or not self.open_lots:
            return None
        return abs(self.open_quantity) * self.mark

    @property
    def unrealized(self) -> Decimal | None:
        """Open P&L at the last mark the user gave us, if any."""
        if self.mark is None or not self.open_lots:
            return None
        total = ZERO
        for lot in self.open_lots:
            move = self.mark - (lot.price + lot.fee_per_share)
            if lot.direction == SHORT:
                move = -move
            total += move * lot.quantity
        return total

    @property
    def total_pnl(self) -> Decimal:
        return self.realized + (self.unrealized or ZERO)


@dataclass
class Portfolio:
    """All positions, keyed by (ticker, currency)."""

    positions: dict[tuple[str, str], Position] = field(default_factory=dict)

    def by_ticker(self) -> list[Position]:
        return sorted(self.positions.values(), key=lambda p: (p.ticker, p.currency))

    def currencies(self) -> list[str]:
        return sorted({p.currency for p in self.positions.values()})

    def for_ticker(self, ticker: str) -> list[Position]:
        ticker = ticker.upper()
        return [p for p in self.by_ticker() if p.ticker == ticker]

    def realized(self, currency: str) -> Decimal:
        return sum((p.realized for p in self.positions.values() if p.currency == currency), ZERO)

    def unrealized(self, currency: str) -> Decimal:
        return sum(
            (p.unrealized or ZERO for p in self.positions.values() if p.currency == currency),
            ZERO,
        )

    def fees(self, currency: str) -> Decimal:
        return sum((p.fees_paid for p in self.positions.values() if p.currency == currency), ZERO)

    def open_positions(self) -> list[Position]:
        return [p for p in self.by_ticker() if p.is_open]

    def closed_positions(self) -> list[Position]:
        return [p for p in self.by_ticker() if not p.is_open and p.round_trips]

    def round_trips(self) -> list[RoundTrip]:
        trips = [rt for p in self.positions.values() for rt in p.round_trips]
        return sorted(trips, key=lambda rt: rt.closed_at)


def build_portfolio(trades: list[Trade], marks: dict[str, Decimal] | None = None) -> Portfolio:
    """Replay trades in time order and produce per-ticker P&L."""

    marks = {k.upper(): v for k, v in (marks or {}).items()}
    portfolio = Portfolio()
    lots_by_key: dict[tuple[str, str], deque[OpenLot]] = {}

    for trade in sorted(trades, key=_chronological):
        key = (trade.ticker.upper(), trade.currency.upper())
        position = portfolio.positions.get(key)
        if position is None:
            position = Position(ticker=key[0], currency=key[1], mark=marks.get(key[0]))
            portfolio.positions[key] = position
            lots_by_key[key] = deque()

        position.trade_count += 1
        position.fees_paid += trade.fee
        if position.first_trade_at is None or trade.traded_at < position.first_trade_at:
            position.first_trade_at = trade.traded_at
        if position.last_trade_at is None or trade.traded_at > position.last_trade_at:
            position.last_trade_at = trade.traded_at

        lots = lots_by_key[key]
        incoming_direction = LONG if trade.side == BUY else SHORT
        remaining = trade.quantity
        exit_fee_per_share = trade.fee_per_share

        # Close opposing lots first, oldest one first.
        while remaining > ZERO and lots and lots[0].direction != incoming_direction:
            lot = lots[0]
            matched = min(remaining, lot.quantity)
            fees = matched * (lot.fee_per_share + exit_fee_per_share)
            position.round_trips.append(
                RoundTrip(
                    ticker=key[0],
                    currency=key[1],
                    direction=lot.direction,
                    quantity=matched,
                    entry_price=lot.price,
                    exit_price=trade.price,
                    fees=fees,
                    opened_at=lot.opened_at,
                    closed_at=trade.traded_at,
                    open_trade_id=lot.trade_id,
                    close_trade_id=trade.id,
                )
            )
            lot.quantity -= matched
            remaining -= matched
            if lot.quantity <= ZERO:
                lots.popleft()

        # Anything left opens (or extends) a position in the trade's direction.
        if remaining > ZERO:
            lots.append(
                OpenLot(
                    quantity=remaining,
                    price=trade.price,
                    fee_per_share=exit_fee_per_share,
                    opened_at=trade.traded_at,
                    trade_id=trade.id,
                    direction=incoming_direction,
                )
            )

        position.open_lots = list(lots)

    return portfolio


def _chronological(trade: Trade) -> tuple[datetime, int]:
    return (trade.traded_at, trade.id or 0)
