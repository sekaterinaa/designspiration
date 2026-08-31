"""Reads trades out of broker screenshots using Claude's vision + structured outputs."""

from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime, timezone
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from .models import ParsedTrade, to_decimal

log = logging.getLogger(__name__)

SUPPORTED_MEDIA_TYPES = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"RIFF": "image/webp",
}

SYSTEM_PROMPT = """\
You read screenshots from stock brokers and trading apps (Robinhood, IBKR, Trading 212, \
Revolut, Fidelity, Schwab, eToro, Tinkoff, order confirmations, emails, and so on) and \
extract the individual executed trades shown in them.

Rules:
- Extract one entry per executed fill or order. If a screenshot shows an order history \
list, extract every row that is an executed buy or sell.
- `price` is always the price PER SHARE. If the screenshot only shows a total amount and \
a quantity, divide to get the per-share price. If it only shows a total and a per-share \
price, do not invent a different quantity - derive it by dividing.
- `quantity` is always positive; the direction lives in `side`.
- `fee` is commission plus any explicit fees for that fill, in the same currency. Use 0 \
when none is shown.
- `traded_at` is the execution date/time in ISO-8601 (e.g. "2026-03-14" or \
"2026-03-14T15:30:00"). Leave it empty when the screenshot does not show one. If a year \
is missing, use the most plausible recent year.
- `currency` is the ISO code of the money shown ($ -> USD, EUR -> EUR, GBP -> GBP, etc.).
- `ticker` is the trading symbol in upper case (AAPL, TSLA, NVDA). If only a company name \
is shown, use the symbol you are confident it trades under; otherwise use the name.
- Pending, cancelled, rejected or not-yet-filled orders are NOT trades - skip them and say \
so in `warnings`.
- Dividends, deposits, interest and transfers are NOT trades - skip them.
- Never guess a number that is not legible. If a required field is unreadable, skip that \
row and explain it in `warnings`.
- A screenshot showing only a position summary or a P&L chart (no buy/sell fills) yields \
no trades - set `is_trade_screenshot` to false and explain in `warnings`.
"""


class ExtractedTrade(BaseModel):
    ticker: str = Field(description="Trading symbol in upper case, e.g. AAPL")
    side: Literal["buy", "sell"]
    quantity: float = Field(description="Number of shares, always positive")
    price: float = Field(description="Execution price per share")
    fee: float = Field(default=0.0, description="Commission and fees for this fill, 0 if none")
    currency: str = Field(default="USD", description="ISO currency code, e.g. USD")
    traded_at: str = Field(default="", description="ISO-8601 execution date/time, empty if unknown")
    confidence: Literal["high", "medium", "low"] = Field(
        description="How legible this row was in the screenshot"
    )


class ScreenshotExtraction(BaseModel):
    is_trade_screenshot: bool = Field(
        description="True if the image shows executed buy/sell trades"
    )
    trades: list[ExtractedTrade] = Field(default_factory=list)
    warnings: list[str] = Field(
        default_factory=list,
        description="Anything skipped, ambiguous or worth double-checking",
    )


class VisionError(RuntimeError):
    """Raised when the screenshot could not be read."""


class ScreenshotResult:
    """Extraction outcome: the trades we found plus anything the model flagged."""

    def __init__(self, trades: list[ParsedTrade], warnings: list[str],
                 is_trade_screenshot: bool, low_confidence: list[str]) -> None:
        self.trades = trades
        self.warnings = warnings
        self.is_trade_screenshot = is_trade_screenshot
        self.low_confidence = low_confidence


def detect_media_type(data: bytes, fallback: str = "image/jpeg") -> str:
    for magic, media_type in SUPPORTED_MEDIA_TYPES.items():
        if data.startswith(magic):
            return media_type
    return fallback


def _parse_timestamp(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    candidates = [raw, raw.replace("Z", "+00:00"), raw.replace(" ", "T")]
    for candidate in candidates:
        try:
            moment = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%b %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    log.warning("Could not parse traded_at %r from screenshot", raw)
    return None


class ScreenshotReader:
    """Wraps the Anthropic client used to read screenshots."""

    def __init__(self, api_key: str, model: str = "claude-opus-5") -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    async def read(self, image: bytes, media_type: str | None = None,
                   hint: str | None = None) -> ScreenshotResult:
        """Extract trades from one screenshot. Runs the blocking SDK call off the loop."""
        return await asyncio.to_thread(self.read_sync, image, media_type, hint)

    def read_sync(self, image: bytes, media_type: str | None = None,
                  hint: str | None = None) -> ScreenshotResult:
        content: list[dict] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type or detect_media_type(image),
                    "data": base64.standard_b64encode(image).decode("utf-8"),
                },
            },
            {
                "type": "text",
                "text": "Extract every executed trade in this screenshot."
                + (f"\n\nContext from the user: {hint}" if hint else ""),
            },
        ]

        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=8000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
                output_format=ScreenshotExtraction,
            )
        except anthropic.RateLimitError as exc:
            raise VisionError("Claude is rate limiting me right now — try again in a minute.") from exc
        except anthropic.APIStatusError as exc:
            log.exception("Anthropic API error while reading a screenshot")
            raise VisionError(f"The image reader returned an error ({exc.status_code}).") from exc
        except anthropic.APIConnectionError as exc:
            raise VisionError("I couldn't reach Claude to read the screenshot.") from exc

        if response.stop_reason == "refusal":
            raise VisionError("Claude declined to read that image.")

        parsed = response.parsed_output
        if parsed is None:
            raise VisionError("I couldn't make sense of that screenshot.")

        trades: list[ParsedTrade] = []
        low_confidence: list[str] = []
        warnings = list(parsed.warnings)

        for item in parsed.trades:
            if item.quantity <= 0 or item.price < 0:
                warnings.append(f"Skipped {item.ticker}: quantity/price did not look sane.")
                continue
            trades.append(
                ParsedTrade(
                    ticker=item.ticker.strip().upper(),
                    side=item.side,
                    quantity=to_decimal(item.quantity),
                    price=to_decimal(item.price),
                    fee=to_decimal(max(item.fee, 0.0)),
                    currency=(item.currency or "USD").strip().upper()[:3],
                    traded_at=_parse_timestamp(item.traded_at),
                )
            )
            if item.confidence != "high":
                low_confidence.append(f"{item.ticker} ({item.confidence} confidence)")

        return ScreenshotResult(
            trades=trades,
            warnings=warnings,
            is_trade_screenshot=parsed.is_trade_screenshot,
            low_confidence=low_confidence,
        )
