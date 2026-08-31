"""Renders portfolios, positions and trades as Telegram HTML messages."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from html import escape

from .models import BUY, ParsedTrade, Trade
from .pnl import LONG, SHORT, Portfolio, Position, RoundTrip

ZERO = Decimal("0")

CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "RUB": "₽", "JPY": "¥", "INR": "₹"}


def quantize(value: Decimal, places: str = "0.01") -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def money(value: Decimal, currency: str = "USD", *, signed: bool = False) -> str:
    rounded = quantize(value)
    symbol = CURRENCY_SYMBOLS.get(currency.upper(), "")
    sign = ""
    if signed:
        sign = "+" if rounded > 0 else ("-" if rounded < 0 else "")
    body = f"{abs(rounded):,.2f}"
    suffix = "" if symbol else f" {currency.upper()}"
    return f"{sign}{symbol}{body}{suffix}"


def qty(value: Decimal) -> str:
    normalized = value.normalize()
    text = format(normalized, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def price(value: Decimal, currency: str = "USD") -> str:
    places = "0.0001" if 0 < abs(value) < Decimal("1") else "0.01"
    symbol = CURRENCY_SYMBOLS.get(currency.upper(), "")
    suffix = "" if symbol else f" {currency.upper()}"
    return f"{symbol}{quantize(value, places):,.{len(places.split('.')[1])}f}{suffix}"


def pct(value: Decimal | None) -> str:
    if value is None:
        return "—"
    return f"{quantize(value):+,.2f}%"


def emoji_for(value: Decimal) -> str:
    if value > 0:
        return "🟢"
    if value < 0:
        return "🔴"
    return "⚪️"


def date_str(moment) -> str:
    return moment.strftime("%Y-%m-%d") if moment else "—"


def _pnl_line(label: str, value: Decimal, currency: str) -> str:
    return f"{emoji_for(value)} <b>{escape(label)}:</b> {money(value, currency, signed=True)}"


def format_trade(trade: Trade) -> str:
    verb = "BUY" if trade.side == BUY else "SELL"
    fee = f" (fee {money(trade.fee, trade.currency)})" if trade.fee else ""
    ident = f" <code>#{trade.id}</code>" if trade.id else ""
    return (
        f"{'🟩' if trade.side == BUY else '🟥'} <b>{verb}</b> {qty(trade.quantity)} "
        f"{escape(trade.ticker)} @ {price(trade.price, trade.currency)}"
        f" = {money(trade.gross_value, trade.currency)}{fee}"
        f" · {date_str(trade.traded_at)}{ident}"
    )


def format_parsed_trade(trade: ParsedTrade, index: int | None = None) -> str:
    prefix = f"{index}. " if index is not None else ""
    verb = "BUY" if trade.side == BUY else "SELL"
    fee = f" · fee {money(trade.fee, trade.currency)}" if trade.fee else ""
    when = f" · {date_str(trade.traded_at)}" if trade.traded_at else " · date not shown"
    total = trade.quantity * trade.price
    return (
        f"{prefix}{'🟩' if trade.side == BUY else '🟥'} <b>{verb}</b> {qty(trade.quantity)} "
        f"<b>{escape(trade.ticker)}</b> @ {price(trade.price, trade.currency)}"
        f" = {money(total, trade.currency)}{fee}{when}"
    )


def format_import_preview(trades: list[ParsedTrade], warnings: list[str],
                          low_confidence: list[str]) -> str:
    lines = ["📸 <b>I read this from your screenshot:</b>", ""]
    lines += [format_parsed_trade(t, i) for i, t in enumerate(trades, start=1)]
    if low_confidence:
        lines += ["", "⚠️ <i>Double-check: " + escape(", ".join(low_confidence)) + "</i>"]
    if warnings:
        lines += ["", "<i>Notes:</i>"] + [f"• {escape(w)}" for w in warnings]
    lines += ["", "Save these to your ledger?"]
    return "\n".join(lines)


def format_position(position: Position, *, detailed: bool = False) -> str:
    cur = position.currency
    header = f"{emoji_for(position.total_pnl)} <b>{escape(position.ticker)}</b>"
    lines = [header]

    if position.round_trips:
        lines.append(
            f"   Realized: <b>{money(position.realized, cur, signed=True)}</b>"
            f" ({pct(position.realized_return_pct)})"
        )
    else:
        lines.append("   Realized: — (nothing closed yet)")

    if position.is_open:
        direction = "Long" if position.direction == LONG else "Short"
        avg = position.open_avg_price or ZERO
        line = (
            f"   {direction} {qty(abs(position.open_quantity))} @ avg {price(avg, cur)}"
            f" (cost {money(position.open_cost, cur)})"
        )
        lines.append(line)
        unrealized = position.unrealized
        if unrealized is not None:
            lines.append(
                f"   Open P&L @ {price(position.mark, cur)}: "
                f"<b>{money(unrealized, cur, signed=True)}</b>"
            )
        else:
            lines.append("   <i>Set a price with /mark to see open P&amp;L</i>")

    if position.fees_paid:
        lines.append(f"   Fees paid: {money(position.fees_paid, cur)}")

    if detailed and position.round_trips:
        lines.append("   <i>Closed round trips:</i>")
        for trip in position.round_trips:
            lines.append("   " + format_round_trip(trip))

    if detailed:
        record = f"   Trades: {position.trade_count}"
        if position.round_trips:
            record += f" · closed {len(position.round_trips)} ({position.wins}W/{position.losses}L"
            if position.win_rate_pct is not None:
                record += f", {pct(position.win_rate_pct).lstrip('+')} win rate"
            record += ")"
        lines.append(record)

    return "\n".join(lines)


def format_round_trip(trip: RoundTrip) -> str:
    arrow = "→"
    kind = "" if trip.direction == LONG else " (short)"
    return (
        f"{emoji_for(trip.pnl)} {qty(trip.quantity)} @ {price(trip.entry_price, trip.currency)}"
        f" {arrow} {price(trip.exit_price, trip.currency)}{kind}: "
        f"<b>{money(trip.pnl, trip.currency, signed=True)}</b> ({pct(trip.return_pct)})"
        f" · {date_str(trip.opened_at)} → {date_str(trip.closed_at)}"
    )


def format_summary(portfolio: Portfolio) -> str:
    if not portfolio.positions:
        return (
            "You have no trades yet.\n\n"
            "Send me a screenshot of a fill, or type something like "
            "<code>buy AAPL 10 @ 182.35</code>."
        )

    blocks: list[str] = ["📊 <b>Your P&amp;L</b>"]

    for currency in portfolio.currencies():
        realized = portfolio.realized(currency)
        unrealized = portfolio.unrealized(currency)
        fees = portfolio.fees(currency)
        section = [""]
        if len(portfolio.currencies()) > 1:
            section.append(f"<b>— {currency} —</b>")
        section.append(_pnl_line("Realized", realized, currency))
        marked = [p for p in portfolio.open_positions()
                  if p.currency == currency and p.unrealized is not None]
        if marked:
            section.append(_pnl_line("Open (at your marks)", unrealized, currency))
            section.append(_pnl_line("Total", realized + unrealized, currency))
        if fees:
            section.append(f"💸 <b>Fees paid:</b> {money(fees, currency)}")
        blocks.append("\n".join(section))

    closed = portfolio.closed_positions()
    open_positions = portfolio.open_positions()

    ranked = sorted(
        [p for p in portfolio.by_ticker() if p.round_trips],
        key=lambda p: p.realized,
        reverse=True,
    )
    if ranked:
        blocks.append("\n<b>By stock (realized)</b>")
        for position in ranked:
            blocks.append(
                f"{emoji_for(position.realized)} <b>{escape(position.ticker)}</b>  "
                f"{money(position.realized, position.currency, signed=True)}"
                f"  ({pct(position.realized_return_pct)})"
                + ("  · still open" if position.is_open else "")
            )
        best, worst = ranked[0], ranked[-1]
        if len(ranked) > 1 and best.realized != worst.realized:
            blocks.append(
                f"\n🏆 Best: <b>{escape(best.ticker)}</b> "
                f"{money(best.realized, best.currency, signed=True)}   "
                f"💀 Worst: <b>{escape(worst.ticker)}</b> "
                f"{money(worst.realized, worst.currency, signed=True)}"
            )

    if open_positions:
        blocks.append("\n<b>Open positions</b>")
        for position in open_positions:
            direction = "long" if position.direction == LONG else "short"
            avg = position.open_avg_price or ZERO
            line = (
                f"• <b>{escape(position.ticker)}</b> {direction} {qty(abs(position.open_quantity))}"
                f" @ avg {price(avg, position.currency)}"
            )
            if position.unrealized is not None:
                line += f" · {money(position.unrealized, position.currency, signed=True)}"
            blocks.append(line)

    if not closed and not any(p.round_trips for p in portfolio.by_ticker()):
        blocks.append("\n<i>Nothing closed yet — realized P&amp;L shows up once you sell.</i>")

    return "\n".join(blocks)


def format_positions(portfolio: Portfolio) -> str:
    open_positions = portfolio.open_positions()
    if not open_positions:
        return "You have no open positions — everything you bought has been sold."
    lines = ["📌 <b>Open positions</b>", ""]
    for position in open_positions:
        lines.append(format_position(position))
        lines.append("")
    return "\n".join(lines).strip()


def format_history(trades: list[Trade]) -> str:
    if not trades:
        return "No trades recorded yet."
    lines = ["🧾 <b>Recent trades</b> (newest first)", ""]
    lines += [format_trade(trade) for trade in trades]
    lines += ["", "<i>Remove one with</i> <code>/delete &lt;id&gt;</code>"]
    return "\n".join(lines)


HELP_TEXT = """\
<b>Stock P&amp;L bot</b> — send screenshots, get your numbers.

<b>📸 Screenshots</b>
Send a photo of a fill, an order confirmation or an order-history list. I read the
ticker, side, quantity, price and fees, show you what I found, and save it once you
tap <b>Save</b>. Add a caption if something needs clarifying (e.g. "this is in EUR").

<b>⌨️ Typing trades</b>
<code>buy AAPL 10 @ 182.35</code>
<code>sold 5 TSLA at $240.10 fee 1.20 on 2026-03-14</code>
Several lines in one message work too.

<b>Commands</b>
/pnl — everything: realized P&amp;L, per-stock breakdown, open positions
/stock TICKER — full history and round trips for one stock
/positions — what you're still holding
/history [TICKER] — recent trades with their ids
/mark TICKER PRICE — set the current price so open P&amp;L is calculated
/marks — list your saved prices
/undo — remove the trades from the last thing I saved
/delete ID — remove one trade
/export — a CSV of everything
/reset — wipe your ledger (asks first)

<b>How the maths works</b>
Positions are matched first-in-first-out. Selling closes your oldest lot first, and the
profit on that round trip is booked to that stock. Commissions are amortised per share,
so every fee lands in the P&amp;L of the trade that paid it. Shorts work too — selling
what you don't hold opens a short, and buying it back closes it.
"""
