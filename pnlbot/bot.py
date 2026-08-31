"""Telegram handlers: screenshots in, P&L out."""

from __future__ import annotations

import csv
import io
import logging
from decimal import Decimal, InvalidOperation
from functools import wraps

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    Update,
    constants,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import formatting as fmt
from .config import Config
from .db import Database, new_batch_id
from .models import ParsedTrade, to_decimal, utcnow
from .pnl import build_portfolio
from .textparse import ParseError, looks_like_trade, parse_trade_lines
from .vision import ScreenshotReader, VisionError

log = logging.getLogger(__name__)

HTML = constants.ParseMode.HTML
MAX_IMAGE_BYTES = 12 * 1024 * 1024


def restricted(handler):
    """Ignore anyone not on the allow-list."""

    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        config: Config = context.application.bot_data["config"]
        user = update.effective_user
        if user is None or not config.is_allowed(user.id):
            log.warning("Ignoring message from unauthorised user %s", user.id if user else "?")
            if update.effective_message:
                await update.effective_message.reply_text(
                    "This bot is private. Ask its owner to add your Telegram id "
                    f"({user.id if user else 'unknown'}) to ALLOWED_USER_IDS."
                )
            return None
        return await handler(update, context)

    return wrapper


def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


def _config(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.application.bot_data["config"]


def _reader(context: ContextTypes.DEFAULT_TYPE) -> ScreenshotReader:
    return context.application.bot_data["reader"]


def _portfolio_for(context: ContextTypes.DEFAULT_TYPE, user_id: int, ticker: str | None = None):
    db = _db(context)
    trades = db.list_trades(user_id, ticker=ticker)
    return build_portfolio(trades, db.get_marks(user_id))


# --------------------------------------------------------------------- commands


@restricted
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = update.effective_user.first_name or "there"
    await update.effective_message.reply_text(
        f"Hi {name}! 👋\n\n"
        "Send me a screenshot every time you buy or sell a stock. I'll read the ticker, "
        "quantity and price out of it, match your sells against your buys first-in-first-out, "
        "and keep a running tally of how much you've made on each stock.\n\n"
        "Try it now: send a screenshot, or type <code>buy AAPL 10 @ 182.35</code>.\n\n"
        "/help shows everything I can do.",
        parse_mode=HTML,
    )


@restricted
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(fmt.HELP_TEXT, parse_mode=HTML)


@restricted
async def cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    portfolio = _portfolio_for(context, update.effective_user.id)
    await update.effective_message.reply_text(fmt.format_summary(portfolio), parse_mode=HTML)


@restricted
async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    portfolio = _portfolio_for(context, update.effective_user.id)
    await update.effective_message.reply_text(fmt.format_positions(portfolio), parse_mode=HTML)


@restricted
async def cmd_stock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not context.args:
        await message.reply_text("Which stock? e.g. <code>/stock AAPL</code>", parse_mode=HTML)
        return

    ticker = context.args[0].upper()
    user_id = update.effective_user.id
    portfolio = _portfolio_for(context, user_id, ticker=ticker)
    positions = portfolio.for_ticker(ticker)
    if not positions:
        await message.reply_text(f"No trades recorded for <b>{ticker}</b> yet.", parse_mode=HTML)
        return

    blocks = [fmt.format_position(position, detailed=True) for position in positions]
    trades = _db(context).list_trades(user_id, ticker=ticker, limit=25)
    blocks.append("\n<b>Trades</b>")
    blocks += [fmt.format_trade(trade) for trade in trades]
    await message.reply_text("\n".join(blocks), parse_mode=HTML)


@restricted
async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    ticker = context.args[0].upper() if context.args else None
    trades = _db(context).list_trades(update.effective_user.id, ticker=ticker, limit=30)
    await update.effective_message.reply_text(fmt.format_history(trades), parse_mode=HTML)


@restricted
async def cmd_mark(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if len(context.args) < 2:
        await message.reply_text(
            "Give me a ticker and its current price, e.g. <code>/mark AAPL 195.40</code>.\n"
            "That's what I use to work out the P&amp;L on positions you still hold.",
            parse_mode=HTML,
        )
        return

    ticker = context.args[0].upper()
    try:
        price = to_decimal(context.args[1].replace(",", "."))
    except (InvalidOperation, ValueError):
        await message.reply_text(f"<code>{context.args[1]}</code> isn't a price I can read.",
                                 parse_mode=HTML)
        return
    if price <= 0:
        await message.reply_text("The price has to be greater than zero.")
        return

    user_id = update.effective_user.id
    _db(context).set_mark(user_id, ticker, price)
    portfolio = _portfolio_for(context, user_id, ticker=ticker)
    positions = portfolio.for_ticker(ticker)
    reply = f"📍 Marked <b>{ticker}</b> at {fmt.price(price)}."
    if positions:
        reply += "\n\n" + "\n".join(fmt.format_position(p) for p in positions)
    await message.reply_text(reply, parse_mode=HTML)


@restricted
async def cmd_marks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    marks = _db(context).get_marks(update.effective_user.id)
    if not marks:
        await update.effective_message.reply_text(
            "No prices saved. Use <code>/mark AAPL 195.40</code> so I can value what you hold.",
            parse_mode=HTML,
        )
        return
    lines = ["📍 <b>Saved prices</b>", ""]
    lines += [f"• <b>{ticker}</b> {fmt.price(price)}" for ticker, price in sorted(marks.items())]
    lines += ["", "<i>Clear one with</i> <code>/unmark TICKER</code>"]
    await update.effective_message.reply_text("\n".join(lines), parse_mode=HTML)


@restricted
async def cmd_unmark(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("Which one? e.g. <code>/unmark AAPL</code>",
                                                  parse_mode=HTML)
        return
    ticker = context.args[0].upper()
    removed = _db(context).clear_mark(update.effective_user.id, ticker)
    await update.effective_message.reply_text(
        f"Cleared the price for <b>{ticker}</b>." if removed
        else f"No saved price for <b>{ticker}</b>.",
        parse_mode=HTML,
    )


@restricted
async def cmd_undo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    user_id = update.effective_user.id
    batch_id = db.last_batch_id(user_id)
    if not batch_id:
        await update.effective_message.reply_text("There's nothing to undo.")
        return
    removed = db.delete_batch(user_id, batch_id)
    await update.effective_message.reply_text(
        f"↩️ Removed the last {removed} trade{'s' if removed != 1 else ''}."
    )


@restricted
async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not context.args:
        await message.reply_text(
            "Which trade? Use <code>/history</code> to see the ids, then "
            "<code>/delete 12</code>.",
            parse_mode=HTML,
        )
        return
    try:
        trade_id = int(context.args[0].lstrip("#"))
    except ValueError:
        await message.reply_text("Trade ids are numbers, e.g. <code>/delete 12</code>.",
                                 parse_mode=HTML)
        return

    db = _db(context)
    user_id = update.effective_user.id
    trade = db.get_trade(user_id, trade_id)
    if trade is None:
        await message.reply_text(f"No trade with id #{trade_id}.")
        return
    db.delete_trade(user_id, trade_id)
    await message.reply_text("🗑 Deleted:\n" + fmt.format_trade(trade), parse_mode=HTML)


@restricted
async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    trades = _db(context).list_trades(user_id)
    if not trades:
        await update.effective_message.reply_text("Nothing to export yet.")
        return

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "traded_at", "ticker", "side", "quantity", "price",
                     "fee", "currency", "gross_value", "source", "note"])
    for trade in sorted(trades, key=lambda t: (t.traded_at, t.id or 0)):
        writer.writerow([
            trade.id,
            trade.traded_at.isoformat(),
            trade.ticker,
            trade.side,
            fmt.qty(trade.quantity),
            trade.price,
            trade.fee,
            trade.currency,
            trade.gross_value,
            trade.source,
            trade.note or "",
        ])
    data = buffer.getvalue().encode("utf-8")
    await update.effective_message.reply_document(
        document=InputFile(io.BytesIO(data), filename="trades.csv"),
        caption=f"🧾 {len(trades)} trade{'s' if len(trades) != 1 else ''}.",
    )


@restricted
async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("Yes, delete everything", callback_data="reset:yes"),
            InlineKeyboardButton("Cancel", callback_data="reset:no"),
        ]]
    )
    await update.effective_message.reply_text(
        "⚠️ This deletes <b>all</b> your trades and saved prices. There's no undo — "
        "run /export first if you want a copy.",
        parse_mode=HTML,
        reply_markup=keyboard,
    )


# ------------------------------------------------------------------- messages


@restricted
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user_id = update.effective_user.id
    db = _db(context)

    photo_file = None
    source_ref = None
    if message.photo:
        largest = message.photo[-1]
        source_ref = largest.file_unique_id
        photo_file = await largest.get_file()
    elif message.document:
        if (message.document.file_size or 0) > MAX_IMAGE_BYTES:
            await message.reply_text("That image is too big for me to read (max 12 MB).")
            return
        source_ref = message.document.file_unique_id
        photo_file = await message.document.get_file()

    if photo_file is None:
        return

    status = await message.reply_text("🔍 Reading your screenshot…")
    try:
        image_bytes = bytes(await photo_file.download_as_bytearray())
        result = await _reader(context).read(image_bytes, hint=message.caption)
    except VisionError as exc:
        await status.edit_text(f"⚠️ {exc}")
        return
    except Exception:  # noqa: BLE001 - surface a usable message, log the detail
        log.exception("Failed to read a screenshot")
        await status.edit_text("⚠️ Something went wrong reading that image. Try again?")
        return

    if not result.trades:
        note = "\n\n" + "\n".join(f"• {w}" for w in result.warnings) if result.warnings else ""
        await status.edit_text(
            "I couldn't find any executed buys or sells in that image."
            + note
            + "\n\nYou can always type it instead, e.g. buy AAPL 10 @ 182.35"
        )
        return

    already = db.count_by_source_ref(user_id, source_ref) if source_ref else 0
    pending_id = db.save_pending(user_id, result.trades, source_ref)

    text = fmt.format_import_preview(result.trades, result.warnings, result.low_confidence)
    if already:
        text = ("♻️ <i>Heads up: I've already saved trades from this exact screenshot.</i>\n\n"
                + text)

    keyboard = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ Save", callback_data=f"save:{pending_id}"),
            InlineKeyboardButton("❌ Discard", callback_data=f"drop:{pending_id}"),
        ]]
    )
    await status.edit_text(text, parse_mode=HTML, reply_markup=keyboard)


@restricted
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    text = (message.text or "").strip()
    if not text:
        return

    config = _config(context)
    if not looks_like_trade(text):
        await message.reply_text(
            "Send me a screenshot of a trade, or type one like "
            "<code>buy AAPL 10 @ 182.35</code>.\n/help has the rest.",
            parse_mode=HTML,
        )
        return

    try:
        parsed = parse_trade_lines(text, config.default_currency)
    except ParseError as exc:
        await message.reply_text(f"⚠️ {exc}", parse_mode=HTML)
        return

    await _save_trades(update, context, parsed, source="manual", source_ref=None)


@restricted
async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    raw = " ".join(context.args)
    if not raw:
        await message.reply_text(
            "Add a trade like this:\n<code>/add buy AAPL 10 @ 182.35</code>", parse_mode=HTML
        )
        return
    try:
        parsed = parse_trade_lines(raw, _config(context).default_currency)
    except ParseError as exc:
        await message.reply_text(f"⚠️ {exc}", parse_mode=HTML)
        return
    await _save_trades(update, context, parsed, source="manual", source_ref=None)


# ------------------------------------------------------------------ callbacks


@restricted
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    action, _, argument = (query.data or "").partition(":")
    user_id = update.effective_user.id
    db = _db(context)

    if action == "reset":
        if argument != "yes":
            await query.edit_message_text("Nothing was deleted.")
            return
        removed = db.delete_all_trades(user_id)
        await query.edit_message_text(f"🧹 Deleted {removed} trades. Starting fresh.")
        return

    if action == "drop":
        db.drop_pending(user_id, argument)
        await query.edit_message_text("❌ Discarded — nothing was saved.")
        return

    if action != "save":
        return

    loaded = db.load_pending(user_id, argument)
    if loaded is None:
        await query.edit_message_text("That import has expired. Send the screenshot again.")
        return

    parsed, source_ref = loaded
    db.drop_pending(user_id, argument)
    summary = await _persist(context, user_id, parsed, source="screenshot", source_ref=source_ref)
    await query.edit_message_text(summary, parse_mode=HTML)


# ------------------------------------------------------------------- helpers


async def _persist(context: ContextTypes.DEFAULT_TYPE, user_id: int,
                   parsed: list[ParsedTrade], *, source: str, source_ref: str | None) -> str:
    db = _db(context)
    batch_id = new_batch_id()
    now = utcnow()
    trades = [
        item.to_trade(user_id=user_id, source=source, source_ref=source_ref,
                      batch_id=batch_id, fallback_time=now)
        for item in parsed
    ]
    db.add_trades(trades)

    tickers = sorted({trade.ticker for trade in trades})
    portfolio = build_portfolio(db.list_trades(user_id), db.get_marks(user_id))

    lines = [f"✅ Saved {len(trades)} trade{'s' if len(trades) != 1 else ''}.", ""]
    for ticker in tickers:
        for position in portfolio.for_ticker(ticker):
            lines.append(fmt.format_position(position))
            lines.append("")
    lines.append("<i>/pnl for the full picture · /undo to take this back</i>")
    return "\n".join(lines)


async def _save_trades(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       parsed: list[ParsedTrade], *, source: str, source_ref: str | None) -> None:
    summary = await _persist(context, update.effective_user.id, parsed,
                             source=source, source_ref=source_ref)
    await update.effective_message.reply_text(summary, parse_mode=HTML)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Unhandled error while processing an update", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ Sorry — something went wrong on my end. Your saved trades are fine."
            )
        except Exception:  # noqa: BLE001 - the reply itself may fail
            log.debug("Could not deliver the error message to the user")


async def _post_init(application: Application) -> None:
    from telegram import BotCommand

    await application.bot.set_my_commands([
        BotCommand("pnl", "Your P&L, by stock"),
        BotCommand("positions", "What you're still holding"),
        BotCommand("stock", "Everything about one ticker"),
        BotCommand("history", "Recent trades"),
        BotCommand("mark", "Set a stock's current price"),
        BotCommand("undo", "Undo the last save"),
        BotCommand("delete", "Delete one trade by id"),
        BotCommand("export", "Download a CSV"),
        BotCommand("help", "How to use this bot"),
    ])


def build_application(config: Config) -> Application:
    application = ApplicationBuilder().token(config.telegram_token).post_init(_post_init).build()
    application.bot_data["config"] = config
    application.bot_data["db"] = Database(config.db_path)
    application.bot_data["reader"] = ScreenshotReader(config.anthropic_api_key, config.model)

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler(["help", "howto"], cmd_help))
    application.add_handler(CommandHandler(["pnl", "summary", "stats"], cmd_pnl))
    application.add_handler(CommandHandler(["positions", "open"], cmd_positions))
    application.add_handler(CommandHandler(["stock", "ticker"], cmd_stock))
    application.add_handler(CommandHandler(["history", "trades"], cmd_history))
    application.add_handler(CommandHandler("mark", cmd_mark))
    application.add_handler(CommandHandler("marks", cmd_marks))
    application.add_handler(CommandHandler("unmark", cmd_unmark))
    application.add_handler(CommandHandler("undo", cmd_undo))
    application.add_handler(CommandHandler(["delete", "remove"], cmd_delete))
    application.add_handler(CommandHandler("export", cmd_export))
    application.add_handler(CommandHandler(["reset", "clear"], cmd_reset))
    application.add_handler(CommandHandler("add", cmd_add))

    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, on_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_error_handler(on_error)
    return application


def run(config: Config) -> None:
    build_application(config).run_polling(allowed_updates=Update.ALL_TYPES)
