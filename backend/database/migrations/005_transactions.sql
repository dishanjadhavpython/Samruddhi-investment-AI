-- Migration 005: transactions, cost basis, account types and personal inputs
-- (plan section 7.2, where it is called "Migration 004"; renumbered because
-- 004 became market_charts). Additive only, so it is safe on a live cluster.
-- Opening balances for existing positions are written by
-- backfill_opening_balances.py, which uses the same ledger code as the API.

-- One row per event in an account. Quantities and prices are per unit;
-- amount is the rupee value for dividends and cash movements (and the trade
-- value for buys and sells when the broker reports it). cash_effect is what
-- the row added to accounts.cash_balance, so an edit or delete can undo it.
-- source: manual | csv | system (opening balances written by the app)
-- statement
CREATE TABLE IF NOT EXISTS transactions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  txn_type VARCHAR(20) NOT NULL,
  trade_date DATE NOT NULL,
  symbol VARCHAR(20) REFERENCES instruments(symbol),
  quantity DECIMAL(20,8),
  price DECIMAL(14,4),
  amount DECIMAL(16,2),
  fees DECIMAL(12,2) NOT NULL DEFAULT 0,
  cash_effect DECIMAL(16,2) NOT NULL DEFAULT 0,
  source VARCHAR(20) NOT NULL DEFAULT 'manual',
  external_ref VARCHAR(100),
  note TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT transactions_type_check CHECK (txn_type IN (
    'buy', 'sell', 'dividend', 'split', 'bonus', 'deposit', 'withdrawal', 'fee', 'interest', 'opening_balance'
  )),
  CONSTRAINT transactions_external_ref_unique UNIQUE (account_id, source, external_ref)
);

-- statement
CREATE INDEX IF NOT EXISTS idx_transactions_account_date ON transactions (account_id, trade_date);

-- statement
CREATE INDEX IF NOT EXISTS idx_transactions_account_symbol ON transactions (account_id, symbol);

-- statement
CREATE OR REPLACE TRIGGER update_transactions_updated_at BEFORE UPDATE ON transactions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Derived from the ledger by src/returns.py whenever a holding's rows change
-- statement
ALTER TABLE positions
  ADD COLUMN IF NOT EXISTS avg_cost DECIMAL(14,4),
  ADD COLUMN IF NOT EXISTS cost_basis DECIMAL(16,2),
  ADD COLUMN IF NOT EXISTS first_buy_date DATE;

-- demat | mutual_fund | epf | ppf | nps | savings | other. Only demat cash
-- counts as idle cash for the lump sum vs stagger explorer.
-- statement
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS account_type VARCHAR(20) DEFAULT 'other';

-- A first guess from the account name; the user can change it on the Accounts page
-- statement
UPDATE accounts SET account_type = CASE
    WHEN account_name ~* '\mepf\M|provident' THEN 'epf'
    WHEN account_name ~* '\mppf\M' THEN 'ppf'
    WHEN account_name ~* '\mnps\M|pension' THEN 'nps'
    WHEN account_name ~* 'demat|trading|broker|zerodha|groww|upstox|angel' THEN 'demat'
    WHEN account_name ~* 'mutual|\mmf\M|folio|\msip\M' THEN 'mutual_fund'
    WHEN account_name ~* 'saving|bank' THEN 'savings'
    ELSE 'other'
  END
WHERE account_type IS NULL OR account_type = 'other';

-- Personal inputs for the Goals page and the Retirement agent. horizon_years
-- is the horizon for invested money; when empty, years_until_retirement is used.
-- statement
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS date_of_birth DATE,
  ADD COLUMN IF NOT EXISTS monthly_contribution DECIMAL(12,2),
  ADD COLUMN IF NOT EXISTS monthly_expenses DECIMAL(12,2),
  ADD COLUMN IF NOT EXISTS emergency_fund_months INTEGER,
  ADD COLUMN IF NOT EXISTS horizon_years INTEGER;
