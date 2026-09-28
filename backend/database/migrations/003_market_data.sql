-- Migration 003: price foundation (plans/realtime-market-intelligence.md, section 7.2)
-- Additive only, so it is safe on a live cluster. Statements are separated by
-- "-- statement" lines (see run_migrations.py).

-- Where each price came from and how fresh it is. price_status is
-- ok | stale | missing | held; "held" means the pricer saw a jump of more than
-- 20% from the previous close and is waiting for the next run to confirm it
-- (the candidate is kept in held_price).
-- statement
ALTER TABLE instruments
  ADD COLUMN IF NOT EXISTS exchange VARCHAR(10) DEFAULT 'NSE',
  ADD COLUMN IF NOT EXISTS yahoo_ticker VARCHAR(40),
  ADD COLUMN IF NOT EXISTS amfi_scheme_code VARCHAR(20),
  ADD COLUMN IF NOT EXISTS isin CHAR(12),
  ADD COLUMN IF NOT EXISTS prev_close DECIMAL(12,4),
  ADD COLUMN IF NOT EXISTS price_as_of TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS price_source VARCHAR(30),
  ADD COLUMN IF NOT EXISTS price_status VARCHAR(10) DEFAULT 'ok',
  ADD COLUMN IF NOT EXISTS held_price DECIMAL(12,4);

-- Daily OHLC bars per instrument (ETF bars from Yahoo, NAV funds as close only)
-- statement
CREATE TABLE IF NOT EXISTS price_bars_daily (
  symbol VARCHAR(20) NOT NULL,
  trade_date DATE NOT NULL,
  open DECIMAL(14,4),
  high DECIMAL(14,4),
  low DECIMAL(14,4),
  close DECIMAL(14,4),
  adj_close DECIMAL(14,4),
  volume BIGINT,
  source VARCHAR(30) NOT NULL,
  ingested_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (symbol, trade_date)
);

-- Index-level series for the market context (Phase 2): NIFTY50, NIFTY50_TRI, NIFTY50_PE, ...
-- statement
CREATE TABLE IF NOT EXISTS market_series (
  series_id VARCHAR(40) NOT NULL,
  obs_date DATE NOT NULL,
  value DECIMAL(16,6) NOT NULL,
  source VARCHAR(60) NOT NULL,
  PRIMARY KEY (series_id, obs_date)
);

-- Methodology breaks in published series, with the chain-linking factor
-- statement
CREATE TABLE IF NOT EXISTS market_series_breaks (
  series_id VARCHAR(40) NOT NULL,
  break_date DATE NOT NULL,
  factor DECIMAL(10,6) NOT NULL,
  note TEXT,
  PRIMARY KEY (series_id, break_date)
);

-- statement
CREATE TABLE IF NOT EXISTS market_signals (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  as_of DATE NOT NULL,
  method_version VARCHAR(20) NOT NULL,
  valuation_score DECIMAL(5,2),
  zone VARCHAR(20),
  indicators JSONB,
  history_stats JSONB,
  narrative JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (as_of, method_version)
);

-- statement
CREATE TABLE IF NOT EXISTS market_holidays (
  trade_date DATE PRIMARY KEY,
  exchange VARCHAR(10),
  description TEXT
);

-- One row per user per day, written by the pricer's end-of-day run
-- statement
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
  clerk_user_id VARCHAR(255) REFERENCES users ON DELETE CASCADE,
  snap_date DATE NOT NULL,
  market_value DECIMAL(16,2),
  invested_value DECIMAL(16,2),
  cash DECIMAL(16,2),
  PRIMARY KEY (clerk_user_id, snap_date)
);

-- statement
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS market_payload JSONB;

-- statement
CREATE INDEX IF NOT EXISTS idx_jobs_user_created ON jobs (clerk_user_id, created_at DESC);

-- Price-source identifiers for catalogue rows that already exist. seed_data.py
-- sets the same values on a fresh database. AMFI codes are the Direct Plan -
-- Growth options, checked against AMFI's NAVAll.txt on 27 Sep 2026.
-- statement
UPDATE instruments SET yahoo_ticker = symbol || '.NS'
WHERE yahoo_ticker IS NULL
  AND symbol IN ('NIFTYBEES', 'JUNIORBEES', 'BANKBEES', 'ITBEES', 'GOLDBEES', 'SILVERBEES', 'LIQUIDBEES');

-- statement
UPDATE instruments SET amfi_scheme_code = '119091', isin = 'INF179KB1HP9' WHERE symbol = 'HDFCLIQF' AND amfi_scheme_code IS NULL;

-- statement
UPDATE instruments SET amfi_scheme_code = '120692', isin = 'INF109K016B1' WHERE symbol = 'ICICICORP' AND amfi_scheme_code IS NULL;

-- statement
UPDATE instruments SET amfi_scheme_code = '120716', isin = 'INF789F01XA0' WHERE symbol = 'UTINIFTY' AND amfi_scheme_code IS NULL;
