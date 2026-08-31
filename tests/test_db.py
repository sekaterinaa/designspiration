"""Storage round-trip tests."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from pnlbot.db import Database, new_batch_id
from pnlbot.models import ParsedTrade, Trade
from pnlbot.pnl import build_portfolio

USER = 4242


@pytest.fixture()
def db(tmp_path):
    return Database(tmp_path / "test.db")


def make_trade(**kwargs):
    defaults = dict(
        ticker="AAPL",
        side="buy",
        quantity=Decimal("10"),
        price=Decimal("100.25"),
        fee=Decimal("1.5"),
        currency="USD",
        traded_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        user_id=USER,
        source="manual",
        batch_id="batch1",
    )
    defaults.update(kwargs)
    return Trade(**defaults)


def test_add_and_read_back(db):
    ids = db.add_trades([make_trade()])
    assert len(ids) == 1
    stored = db.list_trades(USER)[0]
    assert stored.ticker == "AAPL"
    assert stored.quantity == Decimal("10")
    assert stored.price == Decimal("100.25")
    assert stored.fee == Decimal("1.5")
    assert stored.traded_at == datetime(2026, 3, 1, tzinfo=timezone.utc)


def test_trades_are_scoped_per_user(db):
    db.add_trades([make_trade(), make_trade(user_id=99, ticker="TSLA")])
    assert [t.ticker for t in db.list_trades(USER)] == ["AAPL"]
    assert [t.ticker for t in db.list_trades(99)] == ["TSLA"]


def test_ticker_filter_and_limit(db):
    db.add_trades([make_trade(), make_trade(ticker="TSLA")])
    assert len(db.list_trades(USER, ticker="TSLA")) == 1
    assert len(db.list_trades(USER, limit=1)) == 1


def test_delete_trade_and_batch(db):
    ids = db.add_trades([make_trade(), make_trade(ticker="TSLA")])
    assert db.delete_trade(USER, ids[0]) is True
    assert db.delete_trade(99, ids[1]) is False  # other user's trade is untouchable
    assert db.last_batch_id(USER) == "batch1"
    assert db.delete_batch(USER, "batch1") == 1
    assert db.list_trades(USER) == []


def test_marks(db):
    db.set_mark(USER, "aapl", Decimal("195.4"))
    assert db.get_marks(USER) == {"AAPL": Decimal("195.4")}
    db.set_mark(USER, "AAPL", Decimal("200"))
    assert db.get_marks(USER)["AAPL"] == Decimal("200")
    assert db.clear_mark(USER, "AAPL") is True
    assert db.get_marks(USER) == {}


def test_pending_import_round_trip(db):
    parsed = [ParsedTrade(ticker="AAPL", side="buy", quantity=Decimal("3"),
                          price=Decimal("101.5"), fee=Decimal("0.25"),
                          traded_at=datetime(2026, 3, 2, tzinfo=timezone.utc))]
    pending_id = db.save_pending(USER, parsed, source_ref="file123")
    loaded, source_ref = db.load_pending(USER, pending_id)
    assert source_ref == "file123"
    assert loaded[0].quantity == Decimal("3")
    assert loaded[0].price == Decimal("101.5")
    assert loaded[0].traded_at == parsed[0].traded_at
    assert db.load_pending(99, pending_id) is None
    db.drop_pending(USER, pending_id)
    assert db.load_pending(USER, pending_id) is None


def test_duplicate_screenshot_detection(db):
    db.add_trades([make_trade(source="screenshot", source_ref="fileA")])
    assert db.count_by_source_ref(USER, "fileA") == 1
    assert db.count_by_source_ref(USER, "fileB") == 0


def test_reset_clears_everything(db):
    db.add_trades([make_trade()])
    db.set_mark(USER, "AAPL", Decimal("1"))
    assert db.delete_all_trades(USER) == 1
    assert db.list_trades(USER) == []
    assert db.get_marks(USER) == {}


def test_end_to_end_pnl_through_storage(db):
    db.add_trades([
        make_trade(batch_id=new_batch_id()),
        make_trade(side="sell", price=Decimal("120"), fee=Decimal("0.5"),
                   traded_at=datetime(2026, 3, 5, tzinfo=timezone.utc)),
    ])
    portfolio = build_portfolio(db.list_trades(USER), db.get_marks(USER))
    pos = portfolio.for_ticker("AAPL")[0]
    assert pos.realized == Decimal("195.5")  # (120 - 100.25) * 10 - 2.0 in fees
    assert not pos.is_open
