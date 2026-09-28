-- Migration 004: Market page charts (plans/realtime-market-intelligence.md, Phase 2)
-- Additive only. The market_eod job precomputes each chart once a day, so the
-- API reads one row per chart and never recomputes history.

-- One row per chart and method version, overwritten by each market_eod run
-- statement
CREATE TABLE IF NOT EXISTS market_charts (
  chart_id VARCHAR(40) NOT NULL,
  method_version VARCHAR(20) NOT NULL,
  as_of DATE NOT NULL,
  payload JSONB NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (chart_id, method_version)
);

-- The API reads the latest signal row for a method version
-- statement
CREATE INDEX IF NOT EXISTS idx_market_signals_method_asof ON market_signals (method_version, as_of DESC);
