# Momentum Scanner — Architecture

A semi-automated trading bot that scans for high-momentum large/mid-cap stocks, sends picks to Telegram for human approval, then monitors and auto-exits approved trades.

**No strategies or buckets.** One unified pipeline per scan. You decide which picks to trade.

## How it works

```
9:15am ET           9:30am ET      9:45am ET         Every 30min           4:00pm ET
   │                   │               │              10am–3:30pm              │
   ▼                   ▼               ▼                   ▼                   ▼
[Pre-market       [Capture SPY   [Post-open         [Monitor open        [EOD job:
 scan]             open price]    scan]              positions]           fill prices,
   │                                │                   │                daily summary,
   └──────────────────┬─────────────┘                   │                reset state]
                      │                                  │
                      ▼                                  │
              5-step pipeline                            │
              ─────────────                              │
              1. Screen (Finnhub)                        │
              2. Enrich (Alpaca+pandas-ta)               │
              3. Score (0-100)                           │
              4. Validate (news+sector ETF)              │
              5. Telegram alert                          │
                      │                                  │
                      ▼                                  │
              You reply: YES NVDA ──────────────────────►│
                                                         │
                                              Bot buys, monitors:
                                              - Stop hit → sell
                                              - Target hit → sell
                                              - RSI > 72 → sell
                                              - SPY -1.5% → sell all
                                              - EOD → force close
```

## Pipeline detail

### 1. Screen — `scanner.py`
- **Tier 1**: always checks 20 core tickers (NVDA, AAPL, MSFT, TSLA, META, COIN, PLTR…)
- **Tier 2**: broader liquid universe (SNAP, CRWD, NET, SHOP, ABNB…)
- Hard filters: price > $10, change > +1.5%, volume > 750K × 1.5x ratio

### 2. Enrich — `enricher.py`
- Fetches 60 days of daily OHLCV bars from Alpaca IEX
- Calculates via pandas-ta: EMA(9), EMA(20), RSI(14), ATR(14)
- Fetches 1-min intraday bars for VWAP

### 3. Score — `scorer.py`
Scores each ticker 0–100. Hard disqualifiers exit early:
- RSI > 70 (overbought) or RSI < 45 (no momentum)
- Price below EMA9 or VWAP
- Volume ratio < 1.5x
- Already up 8%+ (no-chase rule)

Scoring weights:
| Signal | Points |
|---|---|
| Volume surge | 25 |
| Price momentum | 20 |
| RSI sweet spot (50–65) | 15 |
| Catalyst (news) | 15 |
| EMA position | 10 |
| VWAP position | 10 |
| Sector ETF green | 10 |
| Premarket gap | 10 |

Entry/stop/target: `entry = price`, `stop = price - ATR(14)`, `target = price + 2×ATR(14)` → always 2:1 R/R minimum.

### 4. Validate — `validator.py`
Top 5 picks only:
- Checks Finnhub company news for catalyst keywords (earnings, upgrade, partnership, FDA…)
- Checks sector ETF (SOXX for semis, QQQ for tech) direction via Alpaca quote

### 5. Telegram alert — `telegram_bot.py`
Sends formatted picks table. You reply `YES NVDA` to approve. Bot executes market buy.

## Exit logic — `monitor.py`
Runs every 30 minutes (10am–3:30pm ET). Checks in priority order:
1. **SPY circuit breaker** — SPY down ≥ 1.5% from open → exit all, halt trading
2. **Daily loss limit** — daily P&L ≤ -$200 → halt new trades
3. **Stop loss** — price ≤ stop → sell
4. **Target hit** — price ≥ target → sell
5. **RSI overbought** — RSI > 72 → sell
6. **Max hold** — position held 2+ days → force close
7. **EOD** — 3:45pm force close

## Stack

| Layer | Technology | Purpose |
|---|---|---|
| Bot | Python 3.12 | Core trading logic |
| Scheduler | APScheduler | Cron jobs for scan/monitor/EOD |
| Broker | Alpaca (paper/live) | Order execution, quotes, bars |
| Market data | Alpaca IEX | OHLCV historical + real-time |
| Screener | Finnhub | Stock movers, company news |
| Indicators | pandas-ta | EMA, RSI, ATR, VWAP |
| Notifications | python-telegram-bot v21 | Alerts + YES/NO approval |
| Database | Supabase (Postgres) | scans, trades, daily_summary, bot_state |
| Dashboard | React + TypeScript | Scan log, trade log, daily P&L |
| Bot deploy | Railway | Always-on worker |
| Dashboard deploy | Vercel | Static React app |

## Circuit breakers

| Rule | Threshold | Action |
|---|---|---|
| SPY drop | -1.5% from open | Exit all, halt trading |
| Daily loss | -$200 | Halt new trades |
| Max positions | 2 | Reject approval if at limit |
| No-chase | +8% already today | Disqualify at scoring |
| Max hold | 2 days | Force close |
| RSI exit | > 72 | Sell (extended, take gains) |

## Database schema

```
scans          — every ticker evaluated (even ones not traded)
  id, scanned_at, ticker, score, rsi, volume_ratio, price_at_scan
  ema9_above, ema20_above, vwap_above
  catalyst_found, catalyst_text, sector_etf, sector_etf_green
  price_1day_later, price_2days_later   ← filled by EOD job (forward-test data)

trades         — every approved trade, full lifecycle
  id, scan_id, ticker, phase (paper/live)
  entry_price, stop_loss, target, shares
  entry_time, exit_time, exit_price, exit_reason
  pnl_dollars, pnl_percent, hold_hours

daily_summary  — one row per trading day
  date, trades_taken, trades_won, trades_lost, total_pnl
  avg_hold_hrs, best_ticker, worst_ticker

bot_state      — key/value store (survives restarts)
  daily_loss, positions_open, trading_halted, halt_reason
```

## File map

```
bot/
├── scheduler.py       ← Railway entry point (APScheduler cron jobs)
├── main.py            ← pipeline orchestrator + CLI (scan | monitor | eod | test)
├── config.py          ← all env vars, universe, thresholds
├── scanner.py         ← Tier 1 + Tier 2 screening
├── enricher.py        ← Alpaca bars + pandas-ta indicators
├── scorer.py          ← 0-100 scoring, disqualifiers, ATR sizing
├── validator.py       ← Finnhub news catalyst + sector ETF check
├── telegram_bot.py    ← alerts, YES approval flow, /stats /positions
├── monitor.py         ← 30-min polling, exit signals, circuit breakers
├── eod_job.py         ← fill scan prices, daily summary, state reset
├── alpaca_client.py   ← Alpaca SDK wrapper (quotes, bars, orders)
├── db.py              ← all Supabase operations
└── config.py          ← credentials + tunable parameters

dashboard/src/
├── App.tsx
├── components/
│   ├── BotStatus.tsx      ← header: active/halted, open positions, daily P&L
│   ├── DailySummary.tsx   ← 4 stat cards: P&L, trades, win rate, best/worst
│   ├── TradeLog.tsx       ← all trades with entry/stop/target/exit/P&L
│   └── ScanLog.tsx        ← every scan with score bar + signal checkmarks
└── hooks/
    ├── useBotState.ts
    ├── useTrades.ts
    ├── useScans.ts
    └── useDailySummary.ts

supabase/migrations/
└── 004_momentum_scanner.sql   ← current schema

```

## Running locally

```bash
cd bot
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Test full pipeline (bypasses hard filters, forces NVDA+MSFT through)
python main.py test --no-telegram

# Manual scan (uses real market filters)
python main.py scan --no-telegram

# Check open positions
python main.py monitor --no-telegram
```

## Capital plan

| Phase | Capital | Mode |
|---|---|---|
| Week 1 | $5,000 | Paper trading (TRADING_PHASE=paper) |
| Month 1 | $2,000 | Live trading (TRADING_PHASE=live) |
| Month 2 | $5,000 | Scale up if win rate > 50% |
| Month 3 | $10,000 | Full deployment |

Key Railway env vars: `TRADING_PHASE`, `MAX_POSITION_USD`, `MAX_DAILY_LOSS_USD`
