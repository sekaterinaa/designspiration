"""SQLite storage for trades, marks and pending screenshot imports."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterator

from .models import ParsedTrade, Trade, to_decimal, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    ticker      TEXT    NOT NULL,
    side        TEXT    NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity    REAL    NOT NULL CHECK (quantity > 0),
    price       REAL    NOT NULL CHECK (price >= 0),
    fee         REAL    NOT NULL DEFAULT 0,
    currency    TEXT    NOT NULL DEFAULT 'USD',
    traded_at   TEXT    NOT NULL,
    source      TEXT    NOT NULL DEFAULT 'manual',
    source_ref  TEXT,
    batch_id    TEXT,
    note        TEXT,
    created_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trades_user ON trades (user_id, traded_at);
CREATE INDEX IF NOT EXISTS idx_trades_user_ticker ON trades (user_id, ticker, traded_at);
CREATE INDEX IF NOT EXISTS idx_trades_source_ref ON trades (user_id, source_ref);

CREATE TABLE IF NOT EXISTS marks (
    user_id    INTEGER NOT NULL,
    ticker     TEXT    NOT NULL,
    price      REAL    NOT NULL,
    updated_at TEXT    NOT NULL,
    PRIMARY KEY (user_id, ticker)
);

CREATE TABLE IF NOT EXISTS pending_imports (
    id         TEXT    PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    payload    TEXT    NOT NULL,
    source_ref TEXT,
    created_at TEXT    NOT NULL
);
"""


def _iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def _parse_iso(raw: str) -> datetime:
    moment = datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


class Database:
    """Thin, thread-safe wrapper: every call opens its own short-lived connection."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if self.path.parent and str(self.path.parent) not in ("", "."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def migrate(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    # ------------------------------------------------------------------ trades

    def add_trades(self, trades: list[Trade]) -> list[int]:
        now = _iso(utcnow())
        ids: list[int] = []
        with self.connect() as conn:
            for trade in trades:
                cursor = conn.execute(
                    """
                    INSERT INTO trades (user_id, ticker, side, quantity, price, fee,
                                        currency, traded_at, source, source_ref,
                                        batch_id, note, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trade.user_id,
                        trade.ticker.upper(),
                        trade.side,
                        float(trade.quantity),
                        float(trade.price),
                        float(trade.fee),
                        trade.currency.upper(),
                        _iso(trade.traded_at),
                        trade.source,
                        trade.source_ref,
                        trade.batch_id,
                        trade.note,
                        now,
                    ),
                )
                ids.append(int(cursor.lastrowid))
        return ids

    def list_trades(self, user_id: int, ticker: str | None = None,
                    limit: int | None = None) -> list[Trade]:
        sql = "SELECT * FROM trades WHERE user_id = ?"
        params: list = [user_id]
        if ticker:
            sql += " AND ticker = ?"
            params.append(ticker.upper())
        sql += " ORDER BY traded_at DESC, id DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_trade(row) for row in rows]

    def get_trade(self, user_id: int, trade_id: int) -> Trade | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM trades WHERE user_id = ? AND id = ?", (user_id, trade_id)
            ).fetchone()
        return _row_to_trade(row) if row else None

    def delete_trade(self, user_id: int, trade_id: int) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM trades WHERE user_id = ? AND id = ?", (user_id, trade_id)
            )
        return cursor.rowcount > 0

    def delete_batch(self, user_id: int, batch_id: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM trades WHERE user_id = ? AND batch_id = ?", (user_id, batch_id)
            )
        return cursor.rowcount

    def last_batch_id(self, user_id: int) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT batch_id FROM trades
                WHERE user_id = ? AND batch_id IS NOT NULL
                ORDER BY id DESC LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        return row["batch_id"] if row else None

    def delete_all_trades(self, user_id: int) -> int:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM trades WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM marks WHERE user_id = ?", (user_id,))
        return cursor.rowcount

    def count_by_source_ref(self, user_id: int, source_ref: str) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM trades WHERE user_id = ? AND source_ref = ?",
                (user_id, source_ref),
            ).fetchone()
        return int(row["n"])

    # ------------------------------------------------------------------- marks

    def set_mark(self, user_id: int, ticker: str, price: Decimal) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO marks (user_id, ticker, price, updated_at) VALUES (?, ?, ?, ?)
                ON CONFLICT (user_id, ticker)
                DO UPDATE SET price = excluded.price, updated_at = excluded.updated_at
                """,
                (user_id, ticker.upper(), float(price), _iso(utcnow())),
            )

    def clear_mark(self, user_id: int, ticker: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM marks WHERE user_id = ? AND ticker = ?", (user_id, ticker.upper())
            )
        return cursor.rowcount > 0

    def get_marks(self, user_id: int) -> dict[str, Decimal]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT ticker, price FROM marks WHERE user_id = ?", (user_id,)
            ).fetchall()
        return {row["ticker"]: to_decimal(row["price"]) for row in rows}

    # -------------------------------------------------------- pending imports

    def save_pending(self, user_id: int, trades: list[ParsedTrade],
                     source_ref: str | None = None) -> str:
        pending_id = uuid.uuid4().hex[:12]
        payload = json.dumps([_parsed_to_dict(t) for t in trades])
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_imports (id, user_id, payload, source_ref, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (pending_id, user_id, payload, source_ref, _iso(utcnow())),
            )
        return pending_id

    def load_pending(self, user_id: int, pending_id: str) -> tuple[list[ParsedTrade], str | None] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload, source_ref FROM pending_imports WHERE id = ? AND user_id = ?",
                (pending_id, user_id),
            ).fetchone()
        if row is None:
            return None
        parsed = [_dict_to_parsed(item) for item in json.loads(row["payload"])]
        return parsed, row["source_ref"]

    def drop_pending(self, user_id: int, pending_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "DELETE FROM pending_imports WHERE id = ? AND user_id = ?", (pending_id, user_id)
            )


def _row_to_trade(row: sqlite3.Row) -> Trade:
    return Trade(
        id=int(row["id"]),
        user_id=int(row["user_id"]),
        ticker=row["ticker"],
        side=row["side"],
        quantity=to_decimal(row["quantity"]),
        price=to_decimal(row["price"]),
        fee=to_decimal(row["fee"]),
        currency=row["currency"],
        traded_at=_parse_iso(row["traded_at"]),
        source=row["source"],
        source_ref=row["source_ref"],
        batch_id=row["batch_id"],
        note=row["note"],
    )


def _parsed_to_dict(trade: ParsedTrade) -> dict:
    return {
        "ticker": trade.ticker,
        "side": trade.side,
        "quantity": str(trade.quantity),
        "price": str(trade.price),
        "fee": str(trade.fee),
        "currency": trade.currency,
        "traded_at": _iso(trade.traded_at) if trade.traded_at else None,
        "note": trade.note,
    }


def _dict_to_parsed(data: dict) -> ParsedTrade:
    return ParsedTrade(
        ticker=data["ticker"],
        side=data["side"],
        quantity=to_decimal(data["quantity"]),
        price=to_decimal(data["price"]),
        fee=to_decimal(data.get("fee", "0")),
        currency=data.get("currency", "USD"),
        traded_at=_parse_iso(data["traded_at"]) if data.get("traded_at") else None,
        note=data.get("note"),
    )


def new_batch_id() -> str:
    return uuid.uuid4().hex[:12]
