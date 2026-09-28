# Real-time market intelligence: research and build plan

Prepared 27 September 2026 for the Samruddhi AI project owner.

> **Status, 28 Sep 2026 (evening).** Phases 0 to 5 are built and deployed. Only data and decisions remain: the NSE Indices P/E, P/B and TRI downloads (so the valuation dial is still empty), a data licence before any public launch (section 10.4), and decisions 1, 2, 5 and 7 in section 13.
>
> Phase 5 as built:
> - **Delayed prices.** The pricer runs every 5 minutes, 09:15–15:45 IST. During the session every exchange price is the close of the newest 5-minute bar that ended at least 15 minutes earlier, so "15 min delayed" is true whatever the source's own delay. The same prices, the Nifty 50 and India VIX go to DynamoDB (`samruddhi-market-latest`, and `samruddhi-market-intraday` with a 7-day TTL; `terraform/10_market`, layout in `backend/database/src/market_live.py`). The source is still Yahoo Finance, labelled "demo data" everywhere; a licensed vendor replaces it before launch.
> - **`GET /api/market/snapshot`** reads only DynamoDB (a test swaps Aurora for a client that fails on any use). Measured signed in, over 257 requests: Lambda p95 38.5 ms, handler p95 26 ms. From India the round trip is about 300–460 ms, almost all of it network to us-east-1.
> - **Polling.** The browser asks for the snapshot every 60 s only while the tab is visible and prices can still change (until 15:50 IST), then wakes once for the next session's first delayed price at 09:36. The portfolio no longer reloads from Aurora every 2 minutes; live prices are applied on top of it.
> - **AppSync Events push: not built.** The task applies only at a cadence of 1 minute or faster, and the source updates every 5 minutes, so polling stays the design.
> - **Candlestick charts** (TradingView Lightweight Charts, Apache-2.0, logo shown) appear only on a holding's detail on the Holdings page, from `GET /api/instruments/{symbol}/bars`. NAV funds get a line, since they have one price a day.
>
> Earlier status, kept for reference: Phases 0 and 1 are built and deployed. Phase 2 is built and deployed except for data: the `backend/market` package and backtest harness, `terraform/10_market` (the 19:00 IST `market_eod` job), migration 004 (`market_charts`), `GET /api/market/context` and `/api/market/history`, the Market page and dashboard chip, and the Compliance Checker agent wired after the Reporter and Retirement agents. The valuation dial and zone table stay empty until the NSE Indices P/E, P/B and TRI history is downloaded by hand and loaded (`backend/market/README.md`); the backtest's check against section 5.2 runs then. Decisions 1, 2, 5, 6 and 7 in section 13 are still open; 3 and 4 are answered (bucket `samruddhi-vectors-184589966037`; 9_pricer deployed with the scheduler on).
>
> Changes from the text below, made while building Phase 2:
> - Charts are precomputed daily into a new `market_charts` table (migration 004), so the Phase 3 migration becomes **005**.
> - `/api/market/history` takes `chart=valuation|turbulence|perspective` and `range=1y|5y|10y|max`, not a `series` id, and returns `{fields, rows}` arrays.
> - The first `method_version` is `v1-expanding` (expanding window). `backtest.py` compares rolling 10- and 15-year windows for decision 5.

**Goal.** Show investors live or near-live market data in a way that helps them judge whether now is a relatively better or worse time to put money in. For example, should idle cash go in as a lump sum now, or be staggered? The app must do this without pretending to predict markets and without giving unregistered personalised investment advice.

**How this plan was made.** Four research agents worked in parallel:
1. Timing evidence and presentation
2. Data sources and AWS architecture
3. Indian regulation
4. A read-through of this codebase

Each agent re-checked its own key claims before reporting.
- 48 of the 52 findings are marked verified: a source was re-opened, or the code was read at the cited line.
- Several load-bearing codebase claims were checked again while writing this plan.
- The evidence stream downloaded NSE's official Nifty 50 history (1999 to Sep 2026) and ran its own backtests. Its scripts are in `plans/backtest-reference/`.
- Anything unconfirmed is labelled as such below.

This is product and engineering research, not legal advice. Section 10 lists what a securities lawyer needs to confirm.

---

## 1. Summary

Three findings shape everything else.

1. **Valuation is useful context over years, not months.** Across 1999–2026, cheaper Nifty valuations were followed by better 3–5 year returns and far fewer 1-year losses. P/B's rank correlation with 5-year forward returns is −0.62. Trend, India VIX and FII flows describe current turbulence, not future returns. There are only about five independent 5-year windows in that history, so everything must be shown as ranges with sample sizes, never as calls.
2. **Real-time ticks are a licensing problem, not an AWS problem.** NSE charges ₹25.5 lakh a year plus ₹875 per user per month to display real-time quotes. End-of-day data costs about ₹1 lakh a year per medium, and 15-minute-delayed snapshots about ₹1.2 lakh. Broker APIs (Kite, Upstox, Dhan) and Yahoo Finance are personal-use only. Every signal that matters for "invest now or stagger" is daily anyway. So the plan is **end-of-day first, optional 15-minute-delayed intraday, never real-time ticks**.
3. **Personalised timing advice needs SEBI registration.**
   - "Deploy your ₹2 lakh now" is investment advice, and the definition includes financial planning.
   - "NIFTYBEES is in a buy zone", shown to everyone, is a research service or trading call, even on a free tier.
   - What is clearly allowed while unregistered is index-level market commentary, statistical summaries, and arithmetic on the user's own holdings against targets the user set.

So the product we should build is:

- **A Market page** with two separate dials. A *valuation temperature* shows where Nifty 50 valuations sit against their own corrected history, with what happened next from each zone. A *turbulence* panel shows drawdown, trend and India VIX, labelled "describes risk now, not future returns".
- **A lump sum vs stagger explorer.** It shows, at index level, how investing at once compared with a 3/6/12-month staggered plan historically, from each valuation zone. The user drives it and it names no fund.
- **Honest, fresh prices everywhere**, each with an as-of time, a source and a delay label. Mutual-fund NAVs come from AMFI. Price history, day change and 52-week range follow.
- **Performance**: cost basis, XIRR and a comparison with the Nifty. This is what finally tells investors whether past deployments worked.
- **AI that narrates numbers computed in code**, behind a compliance checker and an audit log.

Before any of that, **fix what is broken today** (Phase 0):
- The Planner can write random ₹1–100 prices into the shared instruments table.
- The Reporter's knowledge-base lookup cannot reach its bucket.
- The pricer would queue about 360 full LLM analyses per user per month if its scheduler were switched on.
- The current prompts ask for "specific actionable recommendations".

## 2. Principles and guardrails

These apply to every task in the roadmap.

1. **Describe, don't prescribe.** Use past-tense, sourced statements. No buy, sell, hold, "good time", targets or forecasts.
2. **Timing context is index-level only.** Never attach a zone, colour or verdict to a named security. Keep the market panel visually separate from the user's holdings, and don't link it to any action.
3. **Two dials, never blended.** Valuation and turbulence often disagree. Today valuation reads "typical" (52/100) while Tickertape's mood index reads "Extreme Fear". A single "good time" score would hide that disagreement, and NSE's data policy may treat it as a custom composite index needing its own licence.
4. **Ranges and base rates, never point forecasts.** Every historical table shows the median, the 10th percentile, the share of negative outcomes and the number of distinct years behind it.
5. **Every number carries its as-of time, source and delay.** Stale data is shown as stale.
6. **Maths in code, words from the LLM.** Indicators, zones, returns and plans are deterministic and unit-tested. Nova Pro only explains them, and its output is checked against the computed numbers.
7. **Horizon first.** Under a 3-year horizon, no equity-timing context is shown.
8. **Calm by default.** No push alerts on market fear. Alerts fire at most weekly, on zone changes or breaches of the user's own targets.
9. **Compute market-wide data once and share it.** Per-user LLM work runs only on demand or once per trading day.

## 3. Where the codebase is today

| Area | Today (verified in code) | Problem | Fixed in |
|---|---|---|---|
| Planner price step | `planner/prices.py:59-65` uses US Polygon data. On any error it returns `random.randint(1, 100)`, and `planner/market.py` writes that into the shared `instruments.current_price`. | Random prices can reach every user. A US ticker that collides with an NSE symbol (e.g. INFY) can overwrite a ₹ price with a USD one. | Phase 0 |
| Pricer coverage | `pricer/refresh_prices.py` prices 7 hard-coded ETFs from Yahoo. HDFCLIQF, ICICICORP and UTINIFTY are never priced. User-added symbols start with a NULL price. The Tagger writes an LLM-guessed "USD" price. | Most prices are seed values or guesses shown as current. | Phases 0–1 |
| Pricer schedule | `terraform/9_pricer` runs `rate(2 hours)` around the clock. Every run queues a full four-agent analysis for every user. | About 75% of runs happen with NSE closed. That is about 360 LLM jobs per user per month, roughly $11–18 per user per month at estimated token counts. It is latent today because `enable_scheduler` defaults to false. | Phase 0 |
| Reporter knowledge base | `reporter/agent.py:134` builds `samruddhi-vectors-{account_id}`, but IAM grants `samruddhi-vectors-dishan-{account_id}` (`6_agents/terraform.tfvars:16`). Errors become "Market insights unavailable". The code reads the wrong allocation keys, and the prompt uses `$`. | Reports are written with no research context, and nothing shows the failure. | Phase 0 |
| Advice language | `reporter/templates.py:21` asks for "Specific Recommendations (5-7 actionable items)". The retirement prompt asks for "action items". The researcher asks for "One clear recommendation". The landing page's sample quote tells the user to move money into a named fund. The Planner agent is named "Financial Planner" and the route is `/advisor-team`. | This crosses into personalised advice under SEBI's definition (section 10). | Phase 0 |
| Price data model | There is one overwritten `current_price`. There is no `prev_close`, `price_as_of`, source, history or OHLC. | There is no day change, range, trend or chart, and no way to tell stale data. | Phase 1 |
| Holdings model | `positions` stores only quantity; the upsert resets `as_of_date`. | There is no cost basis, P&L, XIRR or benchmark comparison. | Phase 3 |
| Market data | There is no index level, valuation, VIX, G-sec yield or holiday calendar. The only market-open check is Polygon's US market. | Nothing to base timing context on. | Phase 2 |
| API and Data API | `GET /api/jobs` returns 100 full rows with all JSONB payloads, which can pass the Data API's 1 MiB limit. `list_positions` has an N+1 query. | This breaks as jobs accumulate and is slow. | Phase 1 |
| Reliability | `planner/lambda_handler.py:138-146` catches every exception and returns a 500 body. | SQS treats the message as done, so the dead-letter queue never fires. | Phase 0 |
| Migrations | `run_migrations.py` hard-codes the 001 SQL. Migration 002 needed its own script, and nothing records what has been applied. | Migration 003 and later would be risky on the live cluster. | Phase 1 |
| Personalisation | Age is hard-coded to 40 and contributions to ₹10,000/yr in the Retirement agent. The frontend keeps the SIP in localStorage. `accounts` has no type, so EPF/PPF cash can't be told apart from demat cash. | Horizon-aware context and "deployable cash" can't be computed. | Phase 3 |
| Evaluation | There are no backtests or golden eval sets. The judge runs only when LangFuse is on (it is off), and it fails open with a score of 80. | Signal claims and AI output can't be checked. | Phases 2 and 4 |

Also note: the seed catalogue has **10** instruments. The "22 ETFs" in `CLAUDE.md` and the guides refers to the old US list.

## 4. What investors will see

### 4.1 "Where is the market right now?": a new Market page

- **Header:** Nifty 50 level, change and "as of 15:30 IST, end of day, source …", or "15 min delayed" once licensed.
- **Valuation temperature:** a 0–100 dial with a descriptive zone. Beside it is the zone's historical table (section 5.2): 1-, 3- and 5-year median returns, the 10th percentile, the share of negative outcomes and the number of distinct years. A band chart shows corrected P/E and P/B over time with 10/25/50/75/90 percentile bands and markers at the methodology breaks.
- **Turbulence panel:** drawdown from the all-time high as an underwater chart, position against the 200-day average, and India VIX with its band (below 13 calm, 13–17 normal, 17–25 nervous, above 25 elevated). Label: "Describes risk right now. Historically it has not predicted the next year's return."
- **Perspective charts:**
  - intra-year fall against calendar-year return, 2000–2025 (median intra-year fall −14.8%; 16 of the 21 years that dipped more than 10% still ended positive)
  - an entry-year × holding-period return triangle
  - a "current vs long-term average vs bottom-cycle" table in the style of DSP Netra.
- **Methodology and limits:** the sources, the chain-linking of breaks, the sample-size caveat, and "past distribution, not a forecast".

### 4.2 "I have idle cash: lump sum or stagger?": a historical explorer

This is user-driven and index-level. It names no fund and offers no default pick.

- **Inputs:** an amount (pre-filled from demat cash, never EPF or PPF), a plan length (all at once, 3, 6 or 12 months), and a yield on waiting cash (default taken from the liquid-fund NAV). An optional question captures loss tolerance: "How would you feel if the market fell 15% the month after you invested?"
- **Output:** for Nifty 50 total returns from 1999, conditioned on today's valuation zone:
  - the share of periods where investing at once did better
  - the median difference
  - the difference in the worst 10% of periods
  - both distributions as a chart.

  All data ends at least 30 days ago, per SEBI's education rule.
- **Copy, descriptive only:** "From zones like today's, investing all at once did better in 65% of historical periods, by a median of 2.8%. In the worst tenth of periods a 6-month plan did better by 6% or more. Many investors who dislike short-term losses choose a 3–6 month plan; others invest at once."

A personalised version ("deploy ₹X over N months") is designed in section 8.5. It stays switched off unless the project registers or partners with a SEBI-registered adviser (section 10).

### 4.3 "How are my holdings doing?"

- **Every price** shows "as of HH:MM IST, source, delayed N min / end of day / NAV of date". Prices older than a trading day show as stale.
- **Holdings and account pages:** previous close and day change (hidden by default in a new *calm mode*), 52-week range, and a sparkline from daily bars.
- **A new Performance view:** portfolio value history, XIRR, absolute return, and a comparison with the Nifty 50 using the same cash flows. It works from recorded transactions, with an opening balance for existing holdings.

### 4.4 Dashboard and Goals additions

- **Dashboard:**
  - a small zone chip ("Valuations: typical") linking to the Market page
  - an idle-cash card linking to the explorer
  - the drift sentence reworded from "move ₹X from equity into fixed income" to "₹X of your portfolio sits above your own 70% equity target"
  - "today's prices" replaced with the real as-of time.
- **Goals:** the SIP is stored in the database instead of localStorage. An optional "use zone-conditioned return ranges" setting uses history from zones like today's for the equity sleeve, shown as ranges.

### 4.5 Alerts

Only two kinds, both neutral and both opt-in:
- "Nifty 50 valuation moved from typical to pricier than usual", debounced to at most once a week.
- "Equity is now 8 points above your own target."

Never "buy the dip" or "extreme fear".

## 5. The market temperature framework

### 5.1 Components

| Dial | Built from | Why |
|---|---|---|
| Valuation temperature (0–100) | The average of walk-forward percentiles of chain-linked Nifty 50 trailing P/E and P/B. Each day is compared only with history up to that day, with at least 3 years of history. | P/B and P/E have the strongest and most stable link to 3–5 year forward returns. P/B's rank correlation with 5-year returns is −0.62 and P/E's −0.48. Dividend yield's is +0.59, so it can be added as a cross-check. |
| Turbulence (shown, not scored) | Drawdown from the all-time high, the index against its 200-day average, India VIX band, 20-day realised volatility | These describe current risk. Below the 200-day average, volatility was 27.7% against 17.8% above it, but the median 1-year return was about the same (12.2% vs 13.1%). |
| Deferred | Earnings yield minus the 10-year G-sec yield; FII/DII flows; sentiment indices | The yield spread needs a licensed daily yield source and a walk-forward test showing it adds information. Flows follow the market rather than lead it. Sentiment gauges are "coincident, not predictive". |

**Methodology breaks must be corrected.** NSE's published series change basis without notice:
- P/E fell 17.9% on 31 Mar 2021 when it switched from standalone to consolidated earnings, while the index moved −1%.
- P/B fell 19.7% on 29 Sep 2023 while the index rose 0.6%; the cause is unconfirmed.

Naive percentiles would call today's P/B the 10th percentile; corrected, it is the 41st. The pipeline keeps a **breaks registry** (series, date, factor: P/E 0.821, P/B 0.803). It also runs an automatic detector that flags any valuation move of more than 6% on a day the price moved less than 1%.

**Zones** use ±3 points of hysteresis so the label doesn't flicker:
- below 20: "Much cheaper than usual"
- 20–40: "Cheaper than usual"
- 40–60: "Typical"
- 60–80: "Pricier than usual"
- above 80: "Much pricier than usual"

**Today:** 52, "Typical", as of 25 Sep 2026. The Nifty is 11.3% below its 2 Jan 2026 high and under its 200-day average.

### 5.2 What history says from each zone

Figures are the research team's own walk-forward computation on Nifty 50 total returns, Jun 1999 to Sep 2026:

| Zone | 1-yr median | 1-yr 10th pct | 1-yr negative | 3-yr median | 5-yr median | Distinct years |
|---|---|---|---|---|---|---|
| Below 20 | 71.8% | 37.8% | 0% | 40.3% | 37.9% | 7 |
| 20–40 | 31.1% | 9.8% | 0% | 18.7% | 14.7% | 12 |
| 40–60 | 19.8% | 0.5% | 10% | 13.5% | 13.6% | 15 |
| 60–80 | 13.0% | −7.6% | 20% | 10.6% | 12.7% | 20 |
| Above 80 | 8.0% | −22.4% | 27% | 12.2% | 10.0% | 15 |

3-year returns were negative in 0–4% of periods. No 5-year window was negative in any zone; the 10th percentile for the richest zone was +3.6%.

### 5.3 Lump sum vs stagger evidence (for the explorer)

- **Vanguard (2023, MSCI World 1976–2022):** investing at once beat a 3-month plan 68% of the time, and 61.6% in emerging markets. Loss-averse investors still prefer short staggering, and Vanguard advises keeping it to about 3 months.
- **Nifty replication:** investing at once beat a 6-month plan (6% earned on waiting cash) 60% of the time, with a median edge of +1.6% and a 10th percentile of −7.9%.
- **Conditioned on the valuation temperature**, 6-month plan:

| Zone third | Lump sum did better | Median edge | Worst-10% edge |
|---|---|---|---|
| Cheapest third | 84% | +6.6% | −3.3% |
| Middle third | 65% | +2.8% | −6.3% |
| Richest third | 56% | +0.9% | −7.3% |

The honest message: staggering has cost little when valuations were high and a lot when they were low. The 200-day trend made no difference: 63% either way.

### 5.4 Limits, to be shown in the product

- There are about 5 independent 5-year windows since 1999. The cheapest-zone results rest on roughly three crises (2003, 2008–09, 2020).
- The relationship varies by period. P/B against 1-year returns was −0.64 in 2009–16 but −0.28 in 2017–25.
- An expanding window drifts "hot" because Indian valuations re-rated upward: 64% of days read 60 or higher. Rolling 10- and 15-year windows must also be tested before choosing.
- 1999–2026 reflects a strongly growing economy. "No negative 5-year window" is history, not a guarantee.

### 5.5 Validation

Port `plans/backtest-reference/` into `backend/market/` as a uv project. It should:
- use walk-forward percentiles only
- compare expanding with rolling 10- and 15-year windows
- run sub-period tests
- compute block-bootstrap or Newey-West intervals for overlapping windows
- report the number of independent episodes per zone.

Each run writes a versioned zone table (`method_version`) that the API and UI read, so every number on screen can be traced to a method version.

## 6. Data sources

| Data | Private demo | Before any public or commercial launch | Cadence |
|---|---|---|---|
| ETF and stock prices | Yahoo via one batched `yfinance` download per run, labelled "demo data" | An NSE-authorised vendor: EOD (about ₹1 lakh/yr per medium) plus optional 15-minute-delayed 1-minute snapshots (about ₹1.2 lakh/yr per medium). Web and mobile are separate media. | Every 15 min in session; EOD bars at 16:15 IST |
| Mutual-fund NAVs | AMFI `NAVAll.txt`. Scheme codes 119091 (HDFC Liquid), 120692 (ICICI Pru Corporate Bond), 120716 (UTI Nifty 50 Index). | AMFI's terms say personal, non-commercial use, so get permission or use a vendor | Daily, about 19:00 IST |
| Index EOD OHLC | NSE UDiFF bhavcopy (free download) | Display rights come with the NSE EOD licence | Daily |
| Nifty P/E, P/B, DY and TRI | Manual CSV download from niftyindices.com into S3. Its terms ban automated collection without consent. | An NSE Indices data subscription (price not published; ask for a quote) | Daily |
| India VIX | Yahoo `^INDIAVIX` or NSE download (not verified) | Vendor | Daily, plus intraday once licensed |
| 10-year G-sec yield | FRED `INDIRLTLT01STM` (monthly, free API) for context | A daily FBIL/CCIL source (terms not verified) | Monthly, then daily |

**Rejected:**
- **Broker APIs.** Zerodha says Kite data can't be displayed on other platforms, and tokens expire at 6 AM every day. Keep broker APIs for a possible later per-user holdings import.
- **Real-time ticks.** ₹25.5 lakh/yr plus ₹875 per user per month.
- **Global vendors' personal tiers.** EODHD's display rights start at $2,499 a month.

Every price row stores `price_source`, `price_as_of` and a delay. The UI shows them.

## 7. Architecture

```
EventBridge Scheduler (Asia/Kolkata, Mon–Fri, holiday-gated in code)
  ├─ every 15 min 09:15–15:30 ─▶ pricer (9_pricer, reworked) ─▶ Aurora instruments (+ DynamoDB market_latest, Phase 5)
  ├─ 16:15 IST ─▶ pricer EOD ─▶ Aurora price_bars_daily, portfolio_snapshots
  ├─ 19:00 IST ─▶ market_eod (10_market) ─▶ AMFI NAVs, market_series, breaks check,
  │                                             market_signals (zones, history stats) ─▶ one shared LLM narrative
  └─ ~19:30 IST ─▶ at most one analysis per user per trading day, only if drift or zone changed

Browser ─▶ CloudFront /api/* ─▶ API Lambda ─▶ /api/market/* reads one Aurora row or DynamoDB, never recomputes
             polls every 60 s only while the tab is visible and NSE is open
```

### 7.1 New and changed infrastructure

- **`terraform/9_pricer` (changed).**
  - Use `schedule_expression_timezone = "Asia/Kolkata"` with cron schedules in place of `rate(2 hours)`.
  - Remove the per-run fan-out of analysis jobs.
  - Raise the timeout if needed for batched downloads.
- **`terraform/10_market` (new, independent state and tfvars).**
  - The `market_eod` Lambda with its schedule.
  - An S3 bucket for raw daily files and the manual valuation CSVs.
  - The optional DynamoDB tables `market_latest` (PK symbol) and `market_intraday` (PK symbol#date, TTL 7 days), used only in Phase 5.
  - Deploy in the same region as Aurora. Consider ap-south-1 later.
- **Rejected:**
  - Timestream for InfluxDB: at least about $87.60/month for a tiny dataset.
  - An always-on Fargate WebSocket consumer: no licensed feed to consume.
  - SSE through Lambda: the project's HTTP API can't stream, and it would cost about $50–210/month at 1,000 users.
  - AppSync Events push is a Phase 5 option, only if the cadence drops to 1 minute or less.

### 7.2 Migration 003 (additive, safe on the live cluster)

`backend/database/migrations/003_market_data.sql`:

```sql
-- statement
ALTER TABLE instruments
  ADD COLUMN IF NOT EXISTS exchange VARCHAR(10) DEFAULT 'NSE',
  ADD COLUMN IF NOT EXISTS yahoo_ticker VARCHAR(40),
  ADD COLUMN IF NOT EXISTS amfi_scheme_code VARCHAR(20),
  ADD COLUMN IF NOT EXISTS isin CHAR(12),
  ADD COLUMN IF NOT EXISTS prev_close DECIMAL(12,4),
  ADD COLUMN IF NOT EXISTS price_as_of TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS price_source VARCHAR(30),
  ADD COLUMN IF NOT EXISTS price_status VARCHAR(10) DEFAULT 'ok';   -- ok | stale | missing
-- statement
CREATE TABLE IF NOT EXISTS price_bars_daily (
  symbol VARCHAR(20) NOT NULL, trade_date DATE NOT NULL,
  open DECIMAL(14,4), high DECIMAL(14,4), low DECIMAL(14,4), close DECIMAL(14,4), adj_close DECIMAL(14,4),
  volume BIGINT, source VARCHAR(30) NOT NULL, ingested_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (symbol, trade_date));
-- statement
CREATE TABLE IF NOT EXISTS market_series (          -- NIFTY50, NIFTY50_TRI, NIFTY50_PE, _PB, _DY, INDIAVIX, GSEC10Y …
  series_id VARCHAR(40) NOT NULL, obs_date DATE NOT NULL, value DECIMAL(16,6) NOT NULL,
  source VARCHAR(60) NOT NULL, PRIMARY KEY (series_id, obs_date));
-- statement
CREATE TABLE IF NOT EXISTS market_series_breaks (
  series_id VARCHAR(40) NOT NULL, break_date DATE NOT NULL, factor DECIMAL(10,6) NOT NULL,
  note TEXT, PRIMARY KEY (series_id, break_date));
-- statement
CREATE TABLE IF NOT EXISTS market_signals (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), as_of DATE NOT NULL, method_version VARCHAR(20) NOT NULL,
  valuation_score DECIMAL(5,2), zone VARCHAR(20), indicators JSONB, history_stats JSONB,
  narrative JSONB, created_at TIMESTAMPTZ DEFAULT NOW(), UNIQUE (as_of, method_version));
-- statement
CREATE TABLE IF NOT EXISTS market_holidays (trade_date DATE PRIMARY KEY, exchange VARCHAR(10), description TEXT);
-- statement
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
  clerk_user_id VARCHAR(255) REFERENCES users ON DELETE CASCADE, snap_date DATE NOT NULL,
  market_value DECIMAL(16,2), invested_value DECIMAL(16,2), cash DECIMAL(16,2),
  PRIMARY KEY (clerk_user_id, snap_date));
-- statement
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS market_payload JSONB;
-- statement
CREATE INDEX IF NOT EXISTS idx_jobs_user_created ON jobs (clerk_user_id, created_at DESC);
```

Migration 004 (Phase 3) adds:
- a `transactions` table: buy, sell, dividend, split, bonus, deposit, withdrawal, fee, interest and opening_balance, with trade date, quantity, price, amount, fees, source and external_ref
- `avg_cost`, `cost_basis` and `first_buy_date` on `positions`
- `accounts.account_type`
- on `users`: `date_of_birth`, `monthly_contribution`, `monthly_expenses`, `emergency_fund_months` and `horizon_years`.

Both migrations run through a new tracked runner: `uv run run_migrations.py`. It reads `migrations/*.sql`, splits on `-- statement` and records each file in `schema_migrations`.

### 7.3 API (FastAPI, `backend/api/main.py`)

| Endpoint | Returns | Notes |
|---|---|---|
| `GET /api/market/context` | `{as_of, session:{state, next_open}, index:{level, change_pct, as_of, source, delay}, valuation:{score, zone, method_version, components:[{id, value, pct, as_of}], history:{zone:{h1,h3,h5:{p10,p50,pct_negative}, distinct_years}}}, turbulence:{drawdown_pct, above_200dma, vix:{value, band}}, narrative, disclaimer}` | Index-level only, no user data. Reads the latest `market_signals` row. |
| `GET /api/market/history?series=&range=1y\|5y\|max` | `{series, adjusted, breaks:[…], points:[{d, v}], source}` | For band and underwater charts |
| `GET /api/market/deployment-history?months=3\|6\|12&cash_yield=` | `{zone, lump_sum_better_pct, median_edge, p10_edge, distributions:{lump:[…], staged:[…]}, data_until, n_periods}` | From a precomputed table. Data ends 30 or more days ago. |
| `GET /api/portfolio/performance?range=` | `{series:[{d, value, invested}], xirr, abs_return_pct, benchmark:{id, xirr_same_cashflows}, coverage}` | Phase 3 |
| `POST/GET/DELETE /api/transactions`, `POST /api/transactions/import` | CRUD plus CSV import | Phase 3 |
| `GET /api/jobs?fields=summary&limit=20` | The job list without JSONB payloads | Stays under the Data API's 1 MiB limit |

**Caching trade-off.** An edge cache for `/api/market/*` would have to drop `Authorization` from the cache key. That makes the data effectively public, which licensing treats as open-website display. Keep these endpoints authenticated and uncached. They read one row, which costs about $1 a month at 1,000 users even with 60-second polling.

### 7.4 Cost

Estimates from AWS price lists; token counts are assumptions to measure in LangFuse.

| Item | Today's design | This plan |
|---|---|---|
| LLM analyses per user per month | about 360 with the scheduler on | about 21 at most (one per trading day, only when something changed), plus user-triggered runs |
| Bedrock per user per month | about $11–18 | about $0.7–1.1, plus one shared daily narrative (cents) |
| New market pipeline (Scheduler, Lambda, S3, optional DynamoDB) | none | under $1/month at 100 users; about $1–3 at 1,000 |
| Aurora | about $43.80/month baseline (0.5 ACU minimum) | Unchanged. For dev, `min_capacity = 0` with auto-pause works on engine 15.12, but a 15-minute pricer and open tabs keep it awake during market hours. |
| Data licences (commercial only) | none | about ₹2.2 lakh/yr plus GST for EOD and 15-minute-delayed data on one website, plus an NSE Indices subscription (unquoted) |

## 8. Agent changes

### 8.1 Stop agents writing prices (Phase 0)

- **Delete the Planner's price step:** `update_instrument_prices` in `planner/lambda_handler.py:50-52`, then `prices.py` and `market.py`, the `polygon` dependency, and `POLYGON_*` from `terraform/6_agents/main.tf:247-248`. In its place, record the `price_as_of` values each job used in `summary_payload`.
- **Remove `current_price` from the Tagger's output** in `tagger/agent.py` and `tagger/templates.py`. It is an LLM guess labelled USD.
- **Add a sanity bound in the pricer.** A new ETF price more than ±20% from `prev_close` is held until the next run confirms it.

### 8.2 Fix the Reporter's grounding (Phase 0)

- Read `VECTOR_BUCKET` from the environment and pass it to the Reporter Lambda in `6_agents/main.tf`. Then find out which bucket actually exists: `samruddhi-vectors-184589966037` or `samruddhi-vectors-dishan-184589966037`.
- Log the failure and add `kb_status` to `report_payload`.
- Fix `allocation_asset_class` and `allocation_regions` in `format_portfolio_for_analysis`, and change `$` to `₹` in the Reporter, Retirement and Charter prompts.

### 8.3 Compliance guardrails (Phase 0 prompts; Phase 2 checker)

- **Prompt rewrites (Phase 0).**
  - Reporter: "Specific Recommendations" becomes "Observations" and "Questions you may want to discuss with a SEBI-registered adviser".
  - Retirement: prescriptions become what-if sensitivities ("with ₹X more a month, the simulated success rate would be Y%").
  - Researcher: drop "One clear recommendation" and point it at Indian primary sources (RBI, SEBI and NSE circulars, AMC factsheets).
  - Rename the Planner agent from "Financial Planner" to "Portfolio Orchestrator".
- **Shared `backend/database/src/guardrails.py` (Phase 0).** `validate_narrative(text, facts)` checks four things:
  - banned phrases in English and common Hinglish (section 10.3)
  - that every ₹ or % figure matches a supplied fact within ±0.5%
  - that the zone label equals the computed zone
  - that no named security appears with an action or a future-price signal.

  On a violation it retries once with feedback, then falls back to a template. The disclaimer is appended in code, never by the LLM.
- **Compliance Checker agent (Phase 2).** It is structured-output only, modelled on the Tagger (no tools, per the LiteLLM/Bedrock rule). Its schema is `{names_security_with_action, personal_instruction, forward_price_or_return_claim, performance_claim, superlative, prohibited_phrases[], verdict: pass|rewrite|block}`. It runs after the Reporter, Retirement and Signals agents and before anything is saved. The judge gets a compliance rubric and fails closed.

### 8.4 New Signals agent (Phases 2 and 4)

- **`backend/signals/indicators.py` and `zones.py`.** Pure, unit-tested functions: walk-forward percentiles of chain-linked P/E and P/B, drawdown, 200-day distance, realised volatility, VIX band and zone hysteresis. The 19:00 IST `market_eod` job computes `market_signals` with no LLM involved.
- **One shared daily narrative.** A single Nova Pro call per day with `output_type=MarketNarrative` (`headline`, `what_the_data_shows`, `what_it_does_not_mean`, `per_indicator_notes`) and no tools. It uses `LitellmModel` with `AWS_REGION_NAME` set and passes through the guardrail.
- **Planner integration.** A new Planner tool, `invoke_market_context(wrapper: RunContextWrapper[PlannerContext])`, follows the existing tools-only Planner pattern. The function body is deterministic: it loads the latest `market_signals` row and writes `jobs.market_payload`. The Reporter receives this as grounded input instead of browsing for numbers.

### 8.5 Personalised deployment framework (built, switched off)

These deterministic rules can be turned on only under a SEBI registration or a registered-adviser partnership (section 10.1):
- **Deployable amount:** emergency buffer = monthly expenses × buffer months. Deployable = min(demat idle cash − buffer, equity gap to the user's own target).
- **Horizon:** under 3 years, none; 3–5 years, at most 50% of the gap; 5 years or more, the full gap.
- **Schedule by zone:** at once when cheaper; 3 tranches when typical; a 6-month STP from a liquid fund when pricier; 12 months when much pricier.

It always shows the backtested comparison and a `rule_trace`. Keep it behind a feature flag in `backend/api` and the frontend. With the flag off, users get the explorer in section 4.2.

### 8.6 Researcher and ingest v2 (Phase 4)

- **Tool signature:** `ingest_financial_document(topic, analysis, source_url, source_name, published_at, symbols, doc_type)`.
- **Ingest Lambda:**
  - Key vectors by `sha256(source_url or normalised text + chunk index)` so re-ingesting overwrites.
  - Chunk to about 200 words (MiniLM truncates longer text).
  - Store text, URL and title as **non-filterable** metadata. This requires recreating the index, because console-created indexes have none, and filterable metadata is capped at 2 KB.
  - Keep `doc_type`, `symbols`, `published_ts`, `source_name` and `expires_ts` filterable.
- **Reporter queries** filter to the last 14 days and the symbols held, and return source and date so reports can cite them.
- **Housekeeping:** a weekly job deletes expired vectors. A code-generated daily "market digest" document is built from `market_series`, with no browsing.
- **Filtering:** tag the source type, and drop sell-side "buy" and target-price language at ingest so it can't be repeated.

### 8.7 Evaluation, observability and audit

- **Backtest harness** (section 5.5).
- **`evals/cases.jsonl`:** about 60 fixtures covering 5 zones × horizons × idle-cash levels, plus adversarial prompts such as "should I buy NIFTYBEES now?". Run with `uv run` against Nova Pro and assert: guardrail pass, number grounding, zone consistency, horizon gating, no named-security action.
- **LangFuse:** enable it in tfvars, record guardrail violations as scores, and replace the 10-second post-flush sleep in `observability.py` with `flush()` alone.
- **Audit log:**
  - Write append-only JSON Lines to an S3 bucket with Object Lock in compliance mode, retained at least 1 year (DPDP) and 5 years if registered.
  - Record per agent run: job id, pseudonymous user id, IST time, agent, model and region, prompt-template hash, input snapshot including data sources and as-of times, tool calls and retrieved document ids, raw output, checker verdict, final text and disclosure version.
  - Keep names and emails out of prompts and traces.
- **Planner handler:** re-raise after marking a job failed so the dead-letter queue works.

## 9. Frontend changes

| Where | Change | Phase |
|---|---|---|
| `pages/index.tsx` | Replace the sample quote that names a fund with an action with a descriptive one. Replace the "Educational tool" footer with the analytics disclosure (section 10.2). | 0 |
| `pages/dashboard.tsx` | Reword the drift sentence (section 4.4). Replace the "today's prices" copy with the as-of time. Later add the zone chip and idle-cash card. | 0, 2 |
| `pages/advisor-team.tsx` | Move to `pages/ai-team.tsx`. Keep `advisor-team` as a client-side redirect, since static export has no server redirects. Update links in Layout, RunCard, CommandPalette, NotificationsMenu and Analysis. | 0 |
| New `pages/market.tsx` | Valuation dial and zone history table, band chart with break markers, turbulence panel, underwater chart, intra-year dips, entry-year triangle, methodology. All in Recharts. | 2 |
| New `pages/explore-deployment.tsx` (or a Market page tab) | The lump sum vs stagger explorer (section 4.2) | 3 |
| Holdings and account pages | As-of, source and delay labels; stale states; previous close and day change with a calm-mode toggle; 52-week range; sparklines | 1–2 |
| New Performance view | Value history, XIRR, benchmark comparison, transactions entry and CSV import | 3 |
| `pages/goals.tsx`, `lib/hooks.ts` | SIP stored through the API. The projection's assumptions are served by the API so the frontend and backend Monte Carlo can't drift apart. Optional zone-conditioned ranges. | 3 |
| New `lib/market-context.tsx` | Shared market data provider. It polls every 60 s only while the tab is visible and NSE is open, and stops after close. | 2 |
| Disclosure UI | A global footer, a one-time modal before the first analysis, and a "How AI is used here" page (agents, what data each sees, limits, evaluation results, how to report a problem) | 0, 4 |
| Charts | Stay on Recharts 3 (supports React 19). Add TradingView lightweight-charts (Apache-2.0, about 62 kB gzipped, visible TradingView attribution required) only after OHLC history exists, loaded client-only. | 5 |

## 10. Compliance and disclosures

### 10.1 Positioning decision (owner to decide with counsel)

- **A. Information and analytics only (recommended now).** Index-level context, statistics, arithmetic on user-set targets and a neutral explorer. This keeps broker and AMC integrations possible: SEBI bars regulated firms from associating with unregistered advisers, and that includes linked IT systems.
- **B. Register a company as an Investment Adviser.** This allows the personalised framework (section 8.5) and research-style output. It brings:
  - risk profiling and suitability checks
  - no free trials
  - a fee cap of ₹1,51,000 per family per year in fixed-fee mode
  - a deposit of ₹1–10 lakh
  - AI-use disclosure and sole responsibility for AI output
  - 5-year records and CSCRF (SEBI's cybersecurity framework) as a small entity
  - possible India-region hosting.
- **C. License the platform to a SEBI-registered adviser**, who owns and signs off the advice.

Consider SEBI's Informal Guidance Scheme on whether the index panel and own-target drift fall within the exemptions in IA Reg 4(a) and RA Reg 2(1)(w).

### 10.2 Disclosure copy (unregistered mode)

> Samruddhi AI is a portfolio analytics and information service. It is not registered with SEBI as an Investment Adviser or Research Analyst, and it does not provide investment advice, research recommendations, buy/sell/hold calls, price targets or model portfolios. Market data is [end-of-day / 15-minute delayed] from [source], as of [HH:MM IST]. Index statistics describe the past and do not predict future returns. Analyses are generated by AI models (Amazon Nova Pro via AWS Bedrock) from the holdings you entered and public market information; they can be incomplete or wrong, and no human reviews them before you see them. Investment in securities market are subject to market risks. Read all the related documents carefully before investing. For advice suited to your situation, consult a SEBI-registered Investment Adviser (you can verify registration on sebi.gov.in).

The sentence beginning "Investment in securities market" must stay word for word. It is SEBI's standard warning. Never use the SEBI logo or any "registered" or "approved" wording.

### 10.3 Never-use phrasing

Keep this list versioned in `backend/database/src/guardrails.py`.

- **Action verbs as an instruction or label on a security:** buy, sell, hold, accumulate, add more, exit, book profit, switch to, avoid.
- **Timing claims:** "good, right or best time to invest", "buying opportunity", "buy the dip", "market has bottomed", "load up".
- **Personal instructions:** "you should invest, deploy, rebalance, buy or sell", "deploy your idle cash now", "stagger over N months" used as an instruction.
- **Forecasts:** target price, stop loss, "upside of X%", "expected return of X%", "will rise, fall or cross", "likely to …".
- **Guarantees and accuracy claims:** guaranteed, assured, risk-free, sure-shot, "X% accurate".
- **Superlatives and advice framing:** best, No. 1, leading, "recommended portfolio for you", model portfolio, "your adviser", "your financial planner".
- **Hedged tips:** "not a tip, but …".

A disclaimer does not rescue advisory substance. In December 2025 SEBI found a trading academy's "not a stock tip" disclaimer "does not seem to be genuine". Block rather than rewrite whenever a named security appears together with an action or a forward-looking signal.

### 10.4 Data licensing gate

Before any public or paid launch:
- Replace Yahoo, AMFI-site and niftyindices sources with licensed ones. Get written quotes from NSE Data & Analytics (marketdata@nse.co.in), NSE Indices, or a vendor with redistribution rights.
- Confirm whether a login-gated app counts as an "open website".
- Confirm whether the valuation temperature counts as a custom index under clause 8.1(a) of NSE's data policy.

### 10.5 DPDP readiness (most duties apply from about 13 May 2027)

- An itemised notice (display name, email, holdings, cash, retirement inputs, analysis output, logs), with consent withdrawal as easy as giving it.
- Account and data erasure with the 1-year log carve-out.
- A grievance contact, and rights requests answered within 90 days.
- A breach runbook: users "without delay", the Data Protection Board within 72 hours.
- Data-processing agreements with AWS, Clerk and LangFuse.
- Minimal personal data in prompts and traces, and a lawful purpose recorded for scheduled analyses.

## 11. Roadmap

Effort key: S = up to 2 days, M = 3–5 days, L = 1–2 weeks, for one developer familiar with the repo.

### Phase 0: make today's data honest and safe (about 1 week)

| Task | Files | Effort | Done when |
|---|---|---|---|
| Remove the Planner price step and Polygon | `backend/planner/{lambda_handler,prices,market}.py`, `pyproject.toml`, `terraform/6_agents/main.tf` | S | No code path writes `instruments.current_price` except the pricer; a test fails if one does |
| Tagger stops writing prices | `backend/tagger/{agent,templates,lambda_handler}.py` | S | The Tagger's output schema has no price field |
| Pricer: IST cron, no per-run analysis fan-out | `terraform/9_pricer/main.tf`, `backend/pricer/lambda_handler.py` | S | The schedule runs only Mon–Fri 09:15–15:30 IST; no jobs are queued from price runs |
| Fix the Reporter bucket, keys and ₹ | `backend/reporter/agent.py`, `terraform/6_agents/main.tf` + tfvars | S | `kb_status` reads "ok" on a live run; the prompt shows allocations and ₹ |
| Rewrite advice prompts; rename the orchestrator | `backend/{reporter,retirement,researcher,planner}/templates.py`, `planner/lambda_handler.py` | S | A regex check across all templates finds no "recommendation" or "actionable" |
| Guardrails module plus post-check on saved reports | `backend/database/src/guardrails.py`, the Reporter and Retirement `lambda_handler.py` | M | Unit tests cover every banned-phrase class and number grounding |
| Planner re-raises so the dead-letter queue works | `backend/planner/lambda_handler.py` | S | A forced failure lands in the DLQ after 3 receives |
| Frontend copy: landing quote and footer, drift wording, `/ai-team` route, disclosure footer | `frontend/pages/*`, `components/Layout.tsx` | S | Copy review passes section 10.3; the old route redirects |

### Phase 1: price foundation (1–2 weeks)

| Task | Files | Effort | Done when |
|---|---|---|---|
| Tracked migration runner plus migration 003 | `backend/database/run_migrations.py`, `migrations/003_market_data.sql` | M | `schema_migrations` lists 001–003, and re-running is a no-op |
| Pricer v2: every held symbol plus the catalogue, one batched download, `prev_close`/`price_as_of`/`price_source`/`price_status`, AMFI NAVs, ±20% sanity bound, stale marking | `backend/pricer/*`, `backend/database/src/models.py` | M | All 10 catalogue instruments have a price with an as-of time; the three NAV funds update daily |
| EOD bars plus `portfolio_snapshots` at 16:15 IST | `backend/pricer/*`, `terraform/9_pricer` | M | Daily rows appear for every symbol and user |
| One-off history backfill (bars and NAVs) | `backend/pricer/backfill.py` (uv) | S | At least 1 year of daily bars per symbol |
| API: `jobs?fields=summary`, remove the N+1 in `list_positions` | `backend/api/main.py`, `models.py` | S | A job list of 100 stays well under 1 MiB; one query per account |
| UI: as-of, source and delay labels, stale states, day change with calm mode | holdings, account, dashboard pages | M | Every ₹ price on screen has a visible as-of time |

### Phase 2: market context MVP (about 2 weeks)

| Task | Files | Effort | Done when |
|---|---|---|---|
| `terraform/10_market` plus the `market_eod` Lambda | new dir, `backend/market/` | M | A 19:00 IST run writes `market_series` and `market_signals` |
| Valuation history backfill (manual CSV into S3), breaks registry and detector | `backend/market/ingest.py` | M | The 2021 and 2023 breaks are registered; a synthetic break triggers the detector |
| Indicators, zones and backtest harness | `backend/market/{indicators,zones,backtest}.py` plus tests | L | The zone table reproduces section 5.2 within rounding; expanding and rolling windows are compared and documented |
| `GET /api/market/context` and `/history` | `backend/api/main.py` | S | Contracts match section 7.3 |
| Market page and dashboard zone chip | `frontend/pages/market.tsx`, `lib/market-context.tsx` | L | The page follows section 4.1, and every section passes the principles in section 2 |
| Compliance Checker agent (structured output) wired after the Reporter and Retirement | `backend/compliance/` (new), `terraform/6_agents` | M | Adversarial fixtures are blocked; clean reports pass |

### Phase 3: explorer, performance and personal inputs (2–3 weeks)

| Task | Files | Effort | Done when |
|---|---|---|---|
| Lump sum vs stagger precompute plus `GET /api/market/deployment-history` | `backend/market/deployment.py`, API | M | Matches section 5.3; data ends 30 or more days ago |
| Explorer UI | `frontend/pages/explore-deployment.tsx` | M | No fund names, no default pick, both distributions shown |
| Migration 004: transactions, cost basis, account type, personal inputs | `migrations/004_*.sql`, models, API | L | Transactions are recorded; existing positions get an opening balance |
| Returns engine (XIRR, absolute return, benchmark on the same cash flows) plus Performance view | `backend/database/src/returns.py`, frontend | L | XIRR matches a spreadsheet on 10 fixtures |
| Goals: SIP and assumptions from the API; the Retirement agent uses stored age and contribution | `frontend/pages/goals.tsx`, `backend/retirement/*` | M | No hard-coded age 40 or ₹10,000 remains |

### Phase 4: AI depth and audit (about 2 weeks)

| Task | Files | Effort | Done when |
|---|---|---|---|
| Daily shared market narrative (Nova Pro, structured output, guardrailed) | `backend/signals/` | M | 30 consecutive days with zero guardrail violations in evals |
| Planner tool `invoke_market_context`; Reporter uses `market_payload` | `backend/planner/agent.py`, `backend/reporter/*` | M | Reports cite the zone and as-of date with no invented numbers |
| Researcher v2 and ingest v2 (dated, sourced, de-duplicated, chunked, filtered) | `backend/researcher/*`, `backend/ingest/*`, recreate the vector index | L | Re-ingesting creates no duplicates; the Reporter shows citations under 14 days old |
| Eval sets plus LangFuse scores; the judge fails closed | `evals/`, `observability.py`, `judge.py` | M | CI-style `uv run` eval reports a pass rate |
| Append-only audit log (S3 Object Lock) | all agent `lambda_handler.py`, `terraform/6_agents` | M | Any report can be replayed from its log entry |
| "How AI is used here" page | frontend | S | Published and linked from the footer |

### Phase 5: near-real-time, after a data licence (optional)

| Task | Effort | Done when |
|---|---|---|
| Licensed 15-minute-delayed snapshots into DynamoDB `market_latest` and `market_intraday` every 5–15 minutes in session | M | The UI shows "15 min delayed, source X", and polling stops after close |
| `GET /api/market/snapshot` served from DynamoDB | S | p95 under 200 ms; Aurora untouched |
| AppSync Events push, only if the cadence reaches 1 minute or less | M | Polling remains as the fallback |
| Candlestick charts (lightweight-charts with attribution) | S | Shown on holding detail only |

## 12. How we'll know it works

- **Truthful data:** 0 prices written by agents, and 100% of displayed prices carry an as-of time. The share of stale prices during market hours stays under 1%.
- **Grounded AI:** 100% number-grounding in evals. The guardrail block rate trends to 0 on real runs, and every block is reviewed.
- **Cost:** 25 or fewer LLM analyses per user per month, and Bedrock spend per user per month tracked in LangFuse.
- **Investor behaviour (the real goal):** the share of users who open the Market page or explorer before a large cash change. Also watch SIP continuity through drawdowns and calm-mode adoption, without a rise in trade frequency.
- **Honest signals:** the backtest report is regenerated on each method change, and the zone table in the UI always matches the current `method_version`.

## 13. Decisions needed from you

1. **Private demo or commercial product?** This decides whether Yahoo, AMFI-site and manual NSE Indices data are acceptable (private demo) or a licence is required (section 10.4).
2. **Registration path A, B or C** (section 10.1), and whether to seek SEBI informal guidance.
3. **Which S3 Vectors bucket exists:** `samruddhi-vectors-184589966037` or `samruddhi-vectors-dishan-184589966037`?
4. **Is `terraform/9_pricer` deployed with the scheduler on?** The repo has no tfvars or state for it.
5. **Percentile window:** expanding since 1999 or rolling 10–15 years? Possibly show both. The backtests in Phase 2 inform this.
6. **Transactions input for v1:** manual entry with an opening balance, or broker tradebook and CAMS/KFintech CAS import?
7. **Catalogue scope:** add mid-cap and small-cap coverage, e.g. a Nifty Midcap 150 temperature, before launch?

## 14. Open research questions

- What caused the 29 Sep 2023 P/B break? Can NSE Indices supply restated history instead of chain-linking?
- Does the earnings-yield-minus-G-sec spread add information beyond P/E and P/B in walk-forward tests?
- Do Clerk's session tokens work with AppSync OIDC, and how does AppSync treat an expired token on an open connection? This matters only for Phase 5 push.
- Do NSE, NSDL or CCIL block AWS us-east-1 egress IPs? This was untested from AWS.
- Has SEBI finalised its June 2025 AI/ML guidelines? None had been found as of Sep 2026.
- Does own-target drift arithmetic count as "financial planning" under IA Reg 2(1)(h)? No SEBI text addresses it directly.

## 15. Sources

**Evidence and presentation**
- NSE Indices historical data (P/E, P/B, DY, TRI): https://www.niftyindices.com/reports/historical-data
- PrimeInvestor on the Nifty P/E basis change: https://primeinvestor.in/nifty-pe-ratio/
- Vanguard, Cost averaging: invest now or temporarily hold your cash? (2023): https://corporate.vanguard.com/content/dam/corp/research/pdf/cost_averaging_invest_now_or_temporarily_hold_your_cash.pdf
- DSP Netra, May 2026: https://www.dspim.com/latest-literature/dspnetra-may26.pdf
- Motilal Oswal AMC, study on India VIX: https://www.motilaloswalmf.com/motilal-oswal-edge/articles/a-study-on-india-volatility-index-vix
- ICRIER WP 109 (FII behaviour): https://www.icrier.org/pdf/wp109.pdf
- freefincal on ICICI Pru BAF: https://freefincal.com/icici-prudential-balanced-advantage-fund/
- Tickertape Market Mood Index: https://www.tickertape.in/market-mood-index
- Koyfin percentile rank: https://www.koyfin.com/help/percentile-rank-snapshot-feature/
- Zerodha Nudges: https://support.zerodha.com/category/trading-and-markets/alerts-and-nudges/nudges/articles/what-is-nudge
- Capitalmind, long-term Nifty returns: https://www.capitalmind.in/insights/decoding-long-term-nifty-returns-the-power-of-time-horizons
- TradingView lightweight-charts: https://github.com/tradingview/lightweight-charts

**Data and architecture**
- NSE price list for domestic clients (effective 1 Apr 2026): https://nsearchives.nseindia.com/web/mediaattachment/2026-03/NSE_Pricing_file_-_Domestic_clients_20260309171343.pdf
- Zerodha, displaying Kite Connect data on other platforms: https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/can-i-use-historical-and-live-data-taken-from-kite-connect-api-on-other-platforms
- Kite Connect WebSocket docs: https://kite.trade/docs/connect/v3/websocket/
- Upstox market data feed V3: https://upstox.com/developer/api-documentation/v3/get-market-data-feed/
- yfinance docs and rate-limit issue: https://ranaroussi.github.io/yfinance/, https://github.com/ranaroussi/yfinance/issues/2422
- AMFI NAV file and terms: https://www.amfiindia.com/spages/NAVAll.txt, https://www.amfiindia.com/terms-of-use
- NSE Indices terms of use: https://www.niftyindices.com/terms-of-use
- EODHD commercial pricing: https://eodhd.com/commercial-pricing
- FRED India 10-year yield: https://fred.stlouisfed.org/series/INDIRLTLT01STM
- AWS pricing: EventBridge https://aws.amazon.com/eventbridge/pricing/, DynamoDB https://aws.amazon.com/dynamodb/pricing/on-demand/, AppSync https://aws.amazon.com/appsync/pricing/, Aurora https://aws.amazon.com/rds/aurora/pricing/
- Timestream LiveAnalytics availability change: https://docs.aws.amazon.com/timestream/latest/developerguide/AmazonTimestreamForLiveAnalytics-availability-change.html
- Aurora Data API limits: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/data-api.limitations.html
- Aurora Serverless v2 auto-pause: https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2-auto-pause.html
- S3 Vectors limits: https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-limitations.html

**Regulation**
- SEBI IA Regulations 2013 (as amended to 25 Nov 2025): https://www.sebi.gov.in/legal/regulations/nov-2025/securities-and-exchange-board-of-india-investment-advisers-regulations-2013-and-securities-last-amended-on-november-25-2025-_98246.html
- SEBI RA Regulations 2014 (as amended to 25 Nov 2025): https://www.sebi.gov.in/legal/regulations/nov-2025/securities-and-exchange-board-of-india-research-analysts-regulations-2014-last-amended-on-november-25-2025-_98248.html
- SEBI IA (Second Amendment) Regulations 2024, AI duties: https://www.sebi.gov.in/legal/regulations/dec-2024/securities-and-exchange-board-of-india-investment-advisers-second-amendment-regulations-2024_89980.html
- SEBI circular on price data for education (8 May 2026): https://www.sebi.gov.in/legal/circulars/may-2026/norms-for-sharing-and-usage-of-price-data-for-educational-purposes_101293.html
- SEBI circular on association with unregistered persons (Jan 2025): https://www.sebi.gov.in/legal/circulars/jan-2025/details-clarifications-on-provisions-related-to-association-of-persons-regulated-by-the-board-miis-and-their-agents-with-persons-engaged-in-prohibited-activities_91356.html
- SEBI RA guidelines (Jan 2025): https://www.sebi.gov.in/sebi_data/attachdocs/jan-2025/1736338732932.pdf
- SEBI IA master circular (Jun 2025): https://www.sebi.gov.in/legal/master-circulars/jun-2025/master-circular-for-investment-advisers_94821.html
- SEBI AI/ML consultation (Jun 2025): https://www.sebi.gov.in/reports-and-statistics/reports/jun-2025/consultation-paper-on-guidelines-for-responsible-usage-of-ai-ml-in-indian-securities-markets_94687.html
- SEBI order, Avadhut Sathe Trading Academy (Dec 2025): https://www.sebi.gov.in/sebi_data/attachdocs/dec-2025/ORDER_1764842991.pdf
- NSE Data Usage and Sharing Policy: https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_DataUsageandSharingPolicy.pdf
- SEBI CSCRF: https://www.sebi.gov.in/legal/circulars/aug-2024/cybersecurity-and-cyber-resilience-framework-cscrf-for-sebi-regulated-entities-res-_85964.html
- DPDP Rules 2025 (unofficial mirror of the Gazette): https://www.dpdpa.com/DPDP_Rules_2025_English_only.pdf; PIB explainer: https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf
