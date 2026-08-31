"""Typed-trade parsing tests."""

from datetime import timezone
from decimal import Decimal

import pytest

from pnlbot.textparse import ParseError, looks_like_trade, parse_trade_line, parse_trade_lines


def test_basic_buy():
    t = parse_trade_line("buy AAPL 10 @ 182.35")
    assert (t.side, t.ticker, t.quantity, t.price) == ("buy", "AAPL", Decimal("10"), Decimal("182.35"))
    assert t.fee == Decimal("0") and t.currency == "USD"


def test_sell_with_fee_and_date():
    t = parse_trade_line("sold 5 TSLA at $240.10 fee 1.20 on 2026-03-14")
    assert t.side == "sell"
    assert t.ticker == "TSLA"
    assert t.quantity == Decimal("5")
    assert t.price == Decimal("240.10")
    assert t.fee == Decimal("1.20")
    assert t.traded_at.date().isoformat() == "2026-03-14"
    assert t.traded_at.tzinfo is timezone.utc


def test_quantity_first_ordering():
    t = parse_trade_line("bought 10 AAPL 182.35")
    assert t.quantity == Decimal("10") and t.price == Decimal("182.35")


def test_thousand_separators_and_decimal_commas():
    assert parse_trade_line("b NVDA 2 @ 1,234.56").price == Decimal("1234.56")
    assert parse_trade_line("sell MSFT 3 @ 410,50 EUR").price == Decimal("410.50")


def test_currency_detection():
    assert parse_trade_line("buy SAP 10 @ €120").currency == "EUR"
    assert parse_trade_line("buy VOD 10 @ £1.20").currency == "GBP"
    assert parse_trade_line("buy AAPL 10 @ 180", default_currency="CHF").currency == "CHF"


def test_dotted_and_comma_separated_input():
    assert parse_trade_line("buy brk.b 1 @ 405").ticker == "BRK.B"
    assert parse_trade_line("buy, TSLA, 3, 240").quantity == Decimal("3")


def test_european_date_format():
    t = parse_trade_line("buy TSLA 1 @ 240 on 14/03/2026")
    assert t.traded_at.date().isoformat() == "2026-03-14"


def test_multiline():
    trades = parse_trade_lines("buy AAPL 10 @ 180\nsell AAPL 10 @ 190")
    assert [t.side for t in trades] == ["buy", "sell"]


def test_errors_are_helpful():
    with pytest.raises(ParseError, match="buy or a sell"):
        parse_trade_line("AAPL 10 @ 180")
    with pytest.raises(ParseError):
        parse_trade_line("buy something")
    with pytest.raises(ParseError):
        parse_trade_line("")


def test_looks_like_trade_gate():
    assert looks_like_trade("sold 3 tsla at 240")
    assert not looks_like_trade("hey, how's my portfolio?")
    assert not looks_like_trade("buy me a coffee")


def test_ticker_is_html_escaped_in_output():
    from decimal import Decimal as D

    from pnlbot.formatting import format_parsed_trade, format_trade
    from pnlbot.models import ParsedTrade

    rendered = format_parsed_trade(
        ParsedTrade(ticker="A<B>", side="buy", quantity=D("1"), price=D("2"))
    )
    assert "A&lt;B&gt;" in rendered and "<B>" not in rendered
