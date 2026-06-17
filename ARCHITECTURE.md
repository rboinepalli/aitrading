# AI Trading Bot — Architecture Overview

A paper-trading bot that trades leveraged ETFs (TQQQ/SQQQ) using a regime-aware signal system.
Built to learn Python, cloud deployment, and algorithmic trading concepts end-to-end.

## What it does

Every 5 minutes during market hours (9:30am–3:45pm ET), the bot:

1. **Detects the market regime** — BULL, BEAR, or CHOPPY — using VIX and the SPY 200-day moving average
2. **Generates an entry signal** — RSI + EMA crossover on TQQQ (bull) or SQQQ (bear)
3. **Manages one open position at a time** — max $2,000 size
4. **Exits via take profit (+15%), stop loss (-10%), or hard close at 3:45pm**
5. **Enforces a $500/day max loss limit** before placing any new trades
6. **Writes every trade and signal to Supabase** for the dashboard to display

## System diagram

```
┌─────────────────────────────────────────┐
│           Railway (Python bot)          │
│                                         │
│  main.py  ──► regime.py ──► entry.py   │
│               │                         │
│               └──► exit_manager.py      │
│                    daily_limiter.py     │
│                    position_manager.py  │
│                                         │
│  alpaca_client.py  ◄──► Alpaca API      │
│  supabase_client.py ──► Supabase DB     │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│         Supabase (Postgres)             │
│                                         │
│  trades  │  signals  │  daily_summary   │
└─────────────────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────┐
│           Vercel (React dashboard)      │
│                                         │
│  TradeLog  │  LivePosition              │
└─────────────────────────────────────────┘
```

## Stack

| Layer | Technology | Purpose |
|---|---|---|
| Bot | Python 3.12 | Core trading logic |
| Scheduler | APScheduler | 5-min loop, market-hours aware |
| Broker | Alpaca (paper) | Order execution, position data |
| Market data | yfinance | VIX + SPY historical bars (free) |
| Indicators | pandas-ta | RSI, EMA, SMA calculations |
| Database | Supabase (Postgres) | Trades, signals, daily summaries |
| Dashboard | React + TypeScript | Read-only trade log + live position |
| Deployment | Railway + Vercel | Worker + static site |

## Key files

```
bot/
├── main.py              ← start here to understand the loop
├── config.py            ← all tunable parameters in one place
├── signals/regime.py    ← BULL/BEAR/CHOPPY classification
├── signals/entry.py     ← BUY signal generation
├── exits/exit_manager.py← when to close a position
└── risk/daily_limiter.py← circuit breaker
```

## Running locally

```bash
cd bot
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # fill in your Alpaca + Supabase keys
python main.py
```

## v1 scope

- [x] Regime detection (VIX + 200-DMA)
- [x] Entry signals (RSI + EMA crossover)
- [x] Exit rules (TP / SL / EOD close)
- [x] Risk gates ($2k position, $500 daily loss)
- [x] Supabase persistence
- [x] React dashboard

## v2 roadmap

- [ ] Telegram notifications
- [ ] Overnight swing trades (Fed/CPI calendar gate)
- [ ] UPRO / SPXS as alternate tickers
- [ ] Equity curve chart
- [ ] Backtesting harness
