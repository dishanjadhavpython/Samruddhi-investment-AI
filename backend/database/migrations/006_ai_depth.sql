-- Migration 006: AI depth and audit (plans/realtime-market-intelligence.md, Phase 4)
-- Additive only.

-- The market backdrop one analysis used, written by the Planner's
-- invoke_market_context tool and read by the Reporter (plan section 8.4)
-- statement
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS market_payload JSONB;

-- The AI disclosure the user accepted before their first analysis (plan section 9)
-- statement
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS ai_disclosure_version VARCHAR(20),
  ADD COLUMN IF NOT EXISTS ai_disclosure_accepted_at TIMESTAMPTZ;

-- "Report a problem" on AI-written text, reviewed by a person
-- statement
CREATE TABLE IF NOT EXISTS ai_feedback (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  clerk_user_id VARCHAR(255) NOT NULL REFERENCES users(clerk_user_id) ON DELETE CASCADE,
  job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
  surface VARCHAR(30) NOT NULL CHECK (surface IN ('report', 'retirement', 'charts', 'market_narrative', 'other')),
  category VARCHAR(30) NOT NULL CHECK (category IN ('advice', 'wrong_number', 'outdated', 'unclear', 'other')),
  message TEXT CHECK (message IS NULL OR char_length(message) <= 2000),
  status VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'reviewed', 'closed')),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- statement
CREATE INDEX IF NOT EXISTS idx_ai_feedback_user_created ON ai_feedback (clerk_user_id, created_at DESC);

-- statement
CREATE INDEX IF NOT EXISTS idx_ai_feedback_status ON ai_feedback (status, created_at DESC);
