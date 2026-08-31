"""FIFO engine tests — the maths the whole bot rests on."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from pnlbot.models import Trade
from pnlbot.pnl import LONG, SHORT, build_portfolio

BASE = datetime(2026, 3, 1, tzinfo=timezone.utc)


def trade(ticker, side, qty, price, *, fee="0", day=0, trade_id=None, currency="USD"):
    return Trade(
        ticker=ticker,
        side=side,
        quantity=Decimal(str(qty)),
        price=Decimal(str(price)),
        fee=Decimal(fee),
        currency=currency,
        traded_at=BASE + timedelta(days=day),
        id=trade_id,
    )


def position(trades, ticker="AAPL", currency="USD", marks=None):
    return build_portfolio(trades, marks).positions[(ticker, currency)]


def test_simple_round_trip():
    pos = position([
        trade("AAPL", "buy", 10, 100, day=0),
        trade("AAPL", "sell", 10, 110, day=1),
    ])
    assert pos.realized == Decimal("100")
    assert pos.open_quantity == 0
    assert not pos.is_open
    assert pos.wins == 1 and pos.losses == 0
    assert pos.realized_return_pct == Decimal("10")


def test_partial_sell_leaves_position_open():
    pos = position([
        trade("AAPL", "buy", 10, 100),
        trade("AAPL", "sell", 4, 120, day=1),
    ])
    assert pos.realized == Decimal("80")
    assert pos.open_quantity == Decimal("6")
    assert pos.open_avg_price == Decimal("100")
    assert pos.open_cost == Decimal("600")


def test_fifo_uses_oldest_lot_first():
    pos = position([
        trade("AAPL", "buy", 10, 100, day=0),
        trade("AAPL", "buy", 10, 200, day=1),
        trade("AAPL", "sell", 10, 150, day=2),
    ])
    # The $100 lot is the one that closes: +$500.
    assert pos.realized == Decimal("500")
    assert pos.open_quantity == Decimal("10")
    assert pos.open_avg_price == Decimal("200")


def test_sell_spanning_two_lots():
    pos = position([
        trade("AAPL", "buy", 5, 100, day=0),
        trade("AAPL", "buy", 5, 120, day=1),
        trade("AAPL", "sell", 8, 130, day=2),
    ])
    # 5 @ +30 and 3 @ +10.
    assert pos.realized == Decimal("180")
    assert len(pos.round_trips) == 2
    assert pos.open_quantity == Decimal("2")
    assert pos.open_avg_price == Decimal("120")


def test_fees_are_amortised_into_the_round_trip():
    pos = position([
        trade("AAPL", "buy", 10, 100, fee="10", day=0),
        trade("AAPL", "sell", 5, 110, fee="4", day=1),
    ])
    # 5 shares closed: gross +50, entry fee 5 (half of 10), exit fee 4.
    assert pos.realized == Decimal("41")
    assert pos.fees_paid == Decimal("14")
    # The other half of the entry fee still rides with the open lot.
    assert pos.open_cost == Decimal("505")


def test_losses_are_reported_as_losses():
    pos = position([
        trade("AAPL", "buy", 10, 100),
        trade("AAPL", "sell", 10, 90, day=1),
    ])
    assert pos.realized == Decimal("-100")
    assert pos.wins == 0 and pos.losses == 1
    assert pos.win_rate_pct == Decimal("0")


def test_short_position_round_trip():
    pos = position([
        trade("AAPL", "sell", 10, 100, day=0),
        trade("AAPL", "buy", 10, 80, day=1),
    ])
    assert pos.realized == Decimal("200")
    assert pos.round_trips[0].direction == SHORT
    assert not pos.is_open


def test_sell_beyond_holdings_flips_to_short():
    pos = position([
        trade("AAPL", "buy", 5, 100, day=0),
        trade("AAPL", "sell", 8, 120, day=1),
    ])
    assert pos.realized == Decimal("100")  # 5 shares closed at +20
    assert pos.direction == SHORT
    assert pos.open_quantity == Decimal("-3")


def test_unrealized_uses_the_mark():
    pos = position(
        [trade("AAPL", "buy", 10, 100)],
        marks={"AAPL": Decimal("130")},
    )
    assert pos.unrealized == Decimal("300")
    assert pos.total_pnl == Decimal("300")
    assert pos.market_value == Decimal("1300")


def test_unrealized_on_a_short_is_inverted():
    pos = position(
        [trade("AAPL", "sell", 10, 100)],
        marks={"AAPL": Decimal("90")},
    )
    assert pos.unrealized == Decimal("100")


def test_unrealized_is_none_without_a_mark():
    pos = position([trade("AAPL", "buy", 10, 100)])
    assert pos.unrealized is None
    assert pos.total_pnl == Decimal("0")


def test_trades_are_replayed_in_time_order():
    pos = position([
        trade("AAPL", "sell", 10, 150, day=2),
        trade("AAPL", "buy", 10, 200, day=1),
        trade("AAPL", "buy", 10, 100, day=0),
    ])
    assert pos.realized == Decimal("500")
    assert pos.open_avg_price == Decimal("200")


def test_portfolio_totals_and_ranking():
    portfolio = build_portfolio([
        trade("AAPL", "buy", 10, 100, day=0),
        trade("AAPL", "sell", 10, 110, day=1),
        trade("TSLA", "buy", 10, 200, day=0),
        trade("TSLA", "sell", 10, 180, day=1),
        trade("NVDA", "buy", 1, 900, day=0),
    ])
    assert portfolio.realized("USD") == Decimal("-100")
    assert [p.ticker for p in portfolio.open_positions()] == ["NVDA"]
    assert {p.ticker for p in portfolio.closed_positions()} == {"AAPL", "TSLA"}
    assert len(portfolio.round_trips()) == 2


def test_currencies_are_kept_apart():
    portfolio = build_portfolio([
        trade("AAPL", "buy", 10, 100, currency="USD", day=0),
        trade("AAPL", "sell", 10, 110, currency="USD", day=1),
        trade("SAP", "buy", 10, 100, currency="EUR", day=0),
        trade("SAP", "sell", 10, 130, currency="EUR", day=1),
    ])
    assert portfolio.realized("USD") == Decimal("100")
    assert portfolio.realized("EUR") == Decimal("300")
    assert portfolio.currencies() == ["EUR", "USD"]


def test_fractional_shares():
    pos = position([
        trade("AAPL", "buy", "0.5", 200, day=0),
        trade("AAPL", "sell", "0.25", 240, day=1),
    ])
    assert pos.realized == Decimal("10")
    assert pos.open_quantity == Decimal("0.25")


def test_round_trip_metadata():
    pos = position([
        trade("AAPL", "buy", 10, 100, day=0, trade_id=1),
        trade("AAPL", "sell", 10, 110, day=5, trade_id=2),
    ])
    trip = pos.round_trips[0]
    assert trip.direction == LONG
    assert trip.open_trade_id == 1 and trip.close_trade_id == 2
    assert trip.holding_days == 5
    assert trip.return_pct == Decimal("10")


def test_trade_validation():
    with pytest.raises(ValueError):
        trade("AAPL", "buy", 0, 100)
    with pytest.raises(ValueError):
        trade("AAPL", "hold", 1, 100)
