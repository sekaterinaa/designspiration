# Stock P&L Telegram bot

Send the bot a screenshot every time you buy or sell. It reads the ticker, side,
quantity, price and fees out of the image, matches your sells against your buys
first-in-first-out, and keeps a running tally of how much you've made on each stock.

```
📸  you: <screenshot of a Robinhood fill>
🤖  bot: I read this from your screenshot:
         🟥 SELL 10 NVDA @ $1,010.00 = $10,100.00 · fee $0.50 · 2026-03-21
         [ ✅ Save ]  [ ❌ Discard ]

📸  you: /pnl
🤖  bot: 🟢 Realized: +$239.17
         🟢 NVDA  +$208.17  (+11.49%)  · still open
         🟢 AAPL  +$126.50  (+6.94%)
         🔴 TSLA   -$95.50  (-7.96%)
```

## What it does

- **Reads screenshots.** Order confirmations, fill notifications, order-history lists —
  Robinhood, IBKR, Trading 212, Revolut, Schwab, eToro, brokerage emails. Multiple fills
  in one screenshot are all picked up. Reading is done by Claude's vision model, so it
  copes with layouts no regex would.
- **Always asks before saving.** You see exactly what it read and tap Save or Discard,
  so a misread number never quietly lands in your ledger.
- **Counts P&L properly.** FIFO lot matching per stock: a sell closes your oldest lot
  first and books the profit on that round trip. Partial sells, several buys at different
  prices, fractional shares, short positions and multiple currencies all work.
- **Amortises fees.** Commission on the buy rides with the lot and is charged when it
  closes; commission on the sell is split across the shares it closes. Every fee lands in
  the round trip that paid it.
- **Tracks open positions**, with average cost and — once you give it a current price
  with `/mark` — unrealized P&L.
- **Typing works too**: `buy AAPL 10 @ 182.35`, for when there's no screenshot.

## Setup

1. **Create the bot.** Message [@BotFather](https://t.me/BotFather) on Telegram, send
   `/newbot`, follow the prompts, copy the token it gives you.
2. **Get an Anthropic API key** from [console.anthropic.com](https://console.anthropic.com).
3. **Install and configure:**

   ```bash
   git clone <this repo> && cd designspiration
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt

   cp .env.example .env
   # then edit .env and fill in TELEGRAM_BOT_TOKEN and ANTHROPIC_API_KEY
   ```

4. **Run it:**

   ```bash
   python run.py
   ```

   Then open your bot in Telegram and send `/start`.

### Keep it private

The bot answers anyone who finds it. Once you've sent `/start`, set `ALLOWED_USER_IDS`
in `.env` to your own Telegram user id (the bot tells any stranger what their id is; you
can also get yours from [@userinfobot](https://t.me/userinfobot)) and restart. Everyone
else is then politely ignored. Data is per-user regardless, so several people can share
one instance without seeing each other's trades.

### Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `TELEGRAM_BOT_TOKEN` | — | Required. From @BotFather. |
| `ANTHROPIC_API_KEY` | — | Required. Used to read screenshots. |
| `ANTHROPIC_MODEL` | `claude-opus-5` | The vision model that reads your screenshots. |
| `PNL_DB_PATH` | `pnl.db` | SQLite file holding your trades. |
| `DEFAULT_CURRENCY` | `USD` | Assumed when a typed trade has no currency symbol. |
| `ALLOWED_USER_IDS` | empty | Comma-separated Telegram ids. Empty means anyone. |

## Commands

| Command | What it does |
| --- | --- |
| `/pnl` | Realized P&L, the per-stock breakdown, best and worst, open positions |
| `/stock TICKER` | Everything about one stock: every round trip and every trade |
| `/positions` | What you're still holding, with average cost |
| `/history [TICKER]` | Recent trades with their ids |
| `/mark TICKER PRICE` | Save the current price so open positions get an unrealized P&L |
| `/marks`, `/unmark TICKER` | List / clear saved prices |
| `/add buy AAPL 10 @ 182.35` | Add a trade by typing it (plain messages work too) |
| `/undo` | Remove the trades from the last thing you saved |
| `/delete ID` | Remove one trade (ids come from `/history`) |
| `/export` | Download everything as CSV |
| `/reset` | Wipe your ledger (asks for confirmation first) |

### Typing trades

Both orders parse, with or without fees, dates and currency symbols. One trade per line,
several lines per message:

```
buy AAPL 10 @ 182.35
sold 5 TSLA at $240.10 fee 1.20 on 2026-03-14
b nvda 2.5 @ 1,234.56
sell MSFT 3 @ 410,50 EUR
```

## How the P&L is calculated

Trades are replayed in execution order and matched FIFO per (ticker, currency):

- Buying with no position, or on top of a long, opens or extends a **long lot**.
- Selling closes your **oldest** open lot first. The realized P&L of that round trip is
  `(exit − entry) × quantity − fees`, and it's booked against that stock.
- Selling more than you hold closes what you have and opens a **short** for the rest.
  Buying it back closes the short, where profit is `(entry − exit) × quantity − fees`.
- Fees are amortised per share, so a fee is never double counted and never lost.
- **Unrealized** P&L is only shown for stocks you've given a price to via `/mark` — the
  bot never fetches quotes, so nothing is guessed about what you're holding right now.
- Currencies are never mixed: EUR trades and USD trades are totalled separately.

## Notes

- **What leaves your machine:** the screenshot image and its caption go to the Anthropic
  API to be read. Nothing else does — your ledger is a local SQLite file, and the trades
  themselves are never sent anywhere.
- **Back it up.** Everything lives in `pnl.db`. Copy that file (or run `/export`) before
  you move machines. In Docker it's in the `/data` volume.
- **Cost:** one API call per screenshot, a handful of thousand tokens each — cents per
  month at any realistic trading frequency. Typed trades cost nothing.
- **Screenshots it can't use:** pending or cancelled orders, dividends and transfers are
  deliberately skipped, and a position-summary screen with no fills has nothing to read.
  The bot says so rather than inventing numbers, and anything it found hard to read is
  flagged for you to double-check before you tap Save.

## Deployment

Docker:

```bash
docker build -t stock-pnl-bot .
docker run -d --name pnl-bot --env-file .env -v pnl-data:/data --restart unless-stopped stock-pnl-bot
```

systemd (`/etc/systemd/system/pnl-bot.service`):

```ini
[Service]
WorkingDirectory=/opt/pnl-bot
ExecStart=/opt/pnl-bot/.venv/bin/python run.py
Restart=always

[Install]
WantedBy=multi-user.target
```

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest tests -q
```

| Module | Responsibility |
| --- | --- |
| `pnlbot/pnl.py` | FIFO engine — round trips, open lots, per-stock totals |
| `pnlbot/vision.py` | Screenshot → structured trades, via Claude vision |
| `pnlbot/textparse.py` | `buy AAPL 10 @ 182.35` → a trade |
| `pnlbot/db.py` | SQLite storage: trades, marks, pending imports |
| `pnlbot/formatting.py` | Telegram HTML rendering |
| `pnlbot/bot.py` | Handlers and the confirm-before-save flow |
