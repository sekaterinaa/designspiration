"""Parses trades typed as text, e.g. "buy AAPL 10 @ 182.35 fee 1 on 2026-03-14"."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .models import BUY, SELL, ParsedTrade, to_decimal

BUY_WORDS = {"buy", "bought", "b", "long", "+"}
SELL_WORDS = {"sell", "sold", "s", "short", "-"}

CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "₽": "RUB", "¥": "JPY", "₹": "INR"}

# A single number: 10, 2.5, 1,234.56 or 1234,56 — never split across a boundary.
_NUMBER = (
    r"(?<![\d.,])(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)(?![\d.,]*\d)"
)
_MONEY = r"[$\u20ac\u00a3\u20bd\u00a5\u20b9]?\s*" + _NUMBER
_TICKER = r"[A-Za-z][A-Za-z0-9.\-]{0,14}"

_DATE_RE = re.compile(
    r"\b(?:on\s+)?(\d{4}-\d{2}-\d{2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?"
    r"|\d{1,2}[./]\d{1,2}[./]\d{2,4})\b"
)
_FEE_RE = re.compile(r"\b(?:fee|fees|commission|comm)\s*[:=]?\s*(" + _MONEY + r")", re.I)


class ParseError(ValueError):
    """Raised when a typed trade cannot be understood."""


def _to_number(raw: str) -> Decimal:
    cleaned = raw.strip()
    for symbol in CURRENCY_SYMBOLS:
        cleaned = cleaned.replace(symbol, "")
    cleaned = cleaned.replace("_", "").replace(" ", "")
    # 1,234.56 -> 1234.56 ; 1234,56 -> 1234.56
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    elif cleaned.count(",") == 1 and len(cleaned.split(",")[1]) in (1, 2):
        cleaned = cleaned.replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        return to_decimal(cleaned)
    except (InvalidOperation, ValueError) as exc:
        raise ParseError(f"'{raw}' is not a number I can read.") from exc


def _find_currency(text: str, default: str) -> str:
    for symbol, code in CURRENCY_SYMBOLS.items():
        if symbol in text:
            return code
    match = re.search(r"\b(USD|EUR|GBP|CHF|JPY|CAD|AUD|SEK|NOK|PLN|RUB|INR|HKD)\b", text, re.I)
    return match.group(1).upper() if match else default


def _find_date(text: str) -> tuple[datetime | None, str]:
    match = _DATE_RE.search(text)
    if not match:
        return None, text
    raw = match.group(1)
    remainder = (text[: match.start()] + " " + text[match.end():]).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d.%m.%y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc), remainder
        except ValueError:
            continue
    return None, remainder


def parse_trade_line(line: str, default_currency: str = "USD") -> ParsedTrade:
    """Understand one typed trade. Raises ParseError with a helpful message."""

    text = " ".join(line.strip().split())
    if not text:
        raise ParseError("Nothing to parse.")
    # A comma followed by a space separates words, never digits: "buy, AAPL, 10".
    text = re.sub(r",(?=\s)", " ", text)
    text = " ".join(text.split())

    currency = _find_currency(text, default_currency)

    fee = Decimal("0")
    fee_match = _FEE_RE.search(text)
    if fee_match:
        fee = _to_number(fee_match.group(1))
        text = (text[: fee_match.start()] + " " + text[fee_match.end():]).strip()

    traded_at, text = _find_date(text)

    tokens = [t for t in text.split() if t]
    side = None
    kept: list[str] = []
    for token in tokens:
        word = token.strip("().").lower()
        if side is None and word in BUY_WORDS:
            side = BUY
            continue
        if side is None and word in SELL_WORDS:
            side = SELL
            continue
        kept.append(token)

    if side is None:
        raise ParseError("I couldn't tell whether that was a buy or a sell.")

    rest = " ".join(kept)
    pattern = re.compile(
        rf"(?P<ticker>{_TICKER})\s+(?P<qty>{_NUMBER})\s*(?:@|at|for|x)?\s*"
        rf"(?P<price>{_MONEY})",
        re.I,
    )
    match = pattern.search(rest)
    if not match:
        # Also accept "10 AAPL @ 182.35"
        pattern = re.compile(
            rf"(?P<qty>{_NUMBER})\s+(?P<ticker>{_TICKER})\s*(?:@|at|for|x)?\s*"
            rf"(?P<price>{_MONEY})",
            re.I,
        )
        match = pattern.search(rest)
    if not match:
        raise ParseError("I need a ticker, a quantity and a price, e.g. <code>buy AAPL 10 @ 182.35</code>.")

    ticker = match.group("ticker").upper()
    quantity = _to_number(match.group("qty"))
    price = _to_number(match.group("price"))

    if quantity <= 0:
        raise ParseError("Quantity has to be greater than zero.")
    if price < 0:
        raise ParseError("Price can't be negative.")

    return ParsedTrade(
        ticker=ticker,
        side=side,
        quantity=quantity,
        price=price,
        fee=abs(fee),
        currency=currency,
        traded_at=traded_at,
    )


def parse_trade_lines(text: str, default_currency: str = "USD") -> list[ParsedTrade]:
    """Parse a multi-line message; every line must be a valid trade."""
    trades = []
    for raw_line in text.splitlines():
        if raw_line.strip():
            trades.append(parse_trade_line(raw_line, default_currency))
    if not trades:
        raise ParseError("Nothing to parse.")
    return trades


def looks_like_trade(text: str) -> bool:
    """Cheap check so we don't answer every chat message with a parse error."""
    lowered = text.lower()
    has_side = any(re.search(rf"(^|\W){re.escape(word)}(\W|$)", lowered) for word in BUY_WORDS | SELL_WORDS)
    has_number = re.search(r"\d", lowered) is not None
    return has_side and has_number
