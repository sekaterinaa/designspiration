"""Handler-level tests with a stand-in Telegram context."""

import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest

from pnlbot.bot import _persist, restricted
from pnlbot.config import Config
from pnlbot.db import Database
from pnlbot.models import ParsedTrade

USER = 7


def make_context(tmp_path, allowed=()):
    config = Config(
        telegram_token="t",
        anthropic_api_key="k",
        db_path=tmp_path / "bot.db",
        allowed_user_ids=frozenset(allowed),
    )
    bot_data = {"config": config, "db": Database(config.db_path), "reader": None}
    return SimpleNamespace(application=SimpleNamespace(bot_data=bot_data)), bot_data["db"]


def parsed(ticker, side, qty, price):
    return ParsedTrade(ticker=ticker, side=side, quantity=Decimal(str(qty)),
                       price=Decimal(str(price)))


def test_persist_saves_and_summarises(tmp_path):
    context, db = make_context(tmp_path)
    summary = asyncio.run(
        _persist(context, USER, [parsed("AAPL", "buy", 10, 100)],
                 source="manual", source_ref=None)
    )
    assert "Saved 1 trade." in summary
    assert "AAPL" in summary
    trades = db.list_trades(USER)
    assert len(trades) == 1 and trades[0].batch_id is not None

    summary = asyncio.run(
        _persist(context, USER, [parsed("AAPL", "sell", 10, 130)],
                 source="screenshot", source_ref="fileX")
    )
    assert "+$300.00" in summary
    assert db.count_by_source_ref(USER, "fileX") == 1


def test_persist_groups_a_multi_trade_screenshot(tmp_path):
    context, db = make_context(tmp_path)
    summary = asyncio.run(
        _persist(context, USER,
                 [parsed("AAPL", "buy", 1, 100), parsed("TSLA", "buy", 2, 200)],
                 source="screenshot", source_ref="fileY")
    )
    assert "Saved 2 trades." in summary
    assert {t.ticker for t in db.list_trades(USER)} == {"AAPL", "TSLA"}
    # One screenshot is one batch, so /undo takes the whole thing back.
    batch = db.last_batch_id(USER)
    assert db.delete_batch(USER, batch) == 2


def test_allow_list_blocks_strangers(tmp_path):
    context, _ = make_context(tmp_path, allowed=[USER])
    calls = []

    @restricted
    async def handler(update, ctx):
        calls.append(update.effective_user.id)

    replies = []
    message = SimpleNamespace(reply_text=lambda text, **kw: _record(replies, text))
    stranger = SimpleNamespace(effective_user=SimpleNamespace(id=999),
                               effective_message=message)
    owner = SimpleNamespace(effective_user=SimpleNamespace(id=USER),
                            effective_message=message)

    asyncio.run(handler(stranger, context))
    assert calls == []
    assert "private" in replies[0]

    asyncio.run(handler(owner, context))
    assert calls == [USER]


async def _record(sink, text):
    sink.append(text)


def test_config_allow_list_parsing(tmp_path, monkeypatch):
    from pnlbot.config import ConfigError, load_config

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    monkeypatch.setenv("ALLOWED_USER_IDS", "1, 2 ,3")
    config = load_config(env_file=None)
    assert config.allowed_user_ids == frozenset({1, 2, 3})
    assert config.is_allowed(2) and not config.is_allowed(9)

    monkeypatch.setenv("ALLOWED_USER_IDS", "")
    assert load_config(env_file=None).is_allowed(12345)  # empty list = open to all

    monkeypatch.setenv("ALLOWED_USER_IDS", "abc")
    with pytest.raises(ConfigError):
        load_config(env_file=None)

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        load_config(env_file=None)
