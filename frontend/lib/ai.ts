import { useEffect, useState } from "react";

// Bump together with AI_DISCLOSURE_VERSION in backend/api/main.py whenever the
// disclosure copy changes; users accept again before their next analysis.
export const AI_DISCLOSURE_VERSION = "2026-09-28";

export type FeedbackSurface = "report" | "retirement" | "charts" | "market_narrative" | "other";
export type FeedbackCategory = "advice" | "wrong_number" | "outdated" | "unclear" | "other";

export const FEEDBACK_CATEGORIES: { value: FeedbackCategory; label: string; hint: string }[] = [
  { value: "advice", label: "It reads like advice", hint: "It tells me what to buy, sell or do, or predicts prices" },
  { value: "wrong_number", label: "A figure is wrong", hint: "A number doesn't match my holdings or the market data" },
  { value: "outdated", label: "It's out of date", hint: "Old prices, old news or an old date" },
  { value: "unclear", label: "It's hard to follow", hint: "Confusing, repetitive or missing something" },
  { value: "other", label: "Something else", hint: "Anything the other options don't cover" },
];

/** Summary written by backend/evals/run_evals.py; never contains generated text */
export interface EvalSummary {
  generated_at: string;
  model: string | null;
  cases: number;
  passed: number;
  pass_rate: number | null;
  suites: Record<
    string,
    {
      error?: string | null;
      summary: {
        cases: number;
        passed: number;
        pass_rate: number | null;
        checks: Record<string, { passed: number; total: number; rate: number | null }>;
        longest_zero_violation_streak?: number;
        first_draft_clean_rate?: number | null;
        days?: [string, string] | null;
      } | null;
      results: { id: string; passed: boolean; failed: string[] }[];
    }
  >;
}

/** The latest eval results, published with the site at /evals/latest.json */
export function useEvalSummary(): { summary: EvalSummary | null; loading: boolean } {
  const [summary, setSummary] = useState<EvalSummary | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let live = true;
    fetch("/evals/latest.json", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => live && setSummary(data))
      .catch(() => live && setSummary(null))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, []);
  return { summary, loading };
}
