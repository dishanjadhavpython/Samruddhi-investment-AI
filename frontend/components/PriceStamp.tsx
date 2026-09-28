import { usePreferences } from "../lib/preferences";
import { dayChangeOf, freshnessOf, FreshnessTone } from "../lib/pricing";
import { formatINR } from "../lib/currency";
import type { PriceFields } from "../lib/pricing";

const dotClass: Record<FreshnessTone, string> = {
  good: "bg-good",
  muted: "bg-muted",
  warn: "bg-warn",
  bad: "bg-bad",
};

/** "25 Sep, 3:30 pm IST · Yahoo Finance, delayed", with the full explanation on hover. */
export function PriceStamp({ instrument, className = "" }: { instrument: PriceFields | null | undefined; className?: string }) {
  const f = freshnessOf(instrument);
  return (
    <span className={`flex items-center gap-1.5 text-[11.5px] leading-4 text-muted ${className}`} title={f.detail}>
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dotClass[f.tone]}`} aria-hidden />
      <span className={f.tone === "warn" || f.tone === "bad" ? "text-ink-2" : undefined}>{f.label}</span>
      {f.source && <span className="hidden sm:inline">· {f.source}</span>}
    </span>
  );
}

/**
 * Change since the previous close. Hidden in calm mode (the default), so
 * day-to-day noise isn't the first thing people see.
 */
export function DayChange({ instrument, quantity, className = "" }: { instrument: PriceFields | null | undefined; quantity?: number; className?: string }) {
  const { calm } = usePreferences();
  const change = dayChangeOf(instrument);
  if (calm || !change) return null;
  const amount = quantity != null ? change.abs * quantity : change.abs;
  const sign = amount > 0 ? "+" : amount < 0 ? "−" : "";
  const tone = amount > 0 ? "text-good" : amount < 0 ? "text-bad" : "text-muted";
  return (
    <span className={`text-[11.5px] tabular-nums ${tone} ${className}`} title="Change since the previous close">
      <span className="sm-money">
        {sign}
        {formatINR(Math.abs(amount), Math.abs(amount) < 100 ? 2 : 0)}
      </span>{" "}
      ({sign}
      {Math.abs(change.pct).toFixed(2)}%)
    </span>
  );
}

/** Switch between calm mode and showing day change. */
export function CalmToggle({ className = "" }: { className?: string }) {
  const { calm, toggleCalm } = usePreferences();
  return (
    <button
      type="button"
      onClick={toggleCalm}
      aria-pressed={!calm}
      className={`sm-btn sm-btn-sm sm-btn-secondary ${className}`}
      title="Calm mode hides day-to-day price changes"
    >
      {calm ? "Show day change" : "Hide day change"}
    </button>
  );
}
