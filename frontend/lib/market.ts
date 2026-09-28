/**
 * Market context types and helpers. Everything here is index-level (Nifty 50,
 * India VIX); nothing is about the user's holdings. Figures arrive as
 * fractions (0.121 = 12.1%) from /api/market/*.
 */

export type ZoneId = "much_cheaper" | "cheaper" | "typical" | "pricier" | "much_pricier";

export interface ZoneDef {
  id: ZoneId;
  label: string;
  lo: number;
  hi: number;
}

/** Same bands as backend/market/zones.py */
export const ZONES: ZoneDef[] = [
  { id: "much_cheaper", label: "Much cheaper than usual", lo: 0, hi: 20 },
  { id: "cheaper", label: "Cheaper than usual", lo: 20, hi: 40 },
  { id: "typical", label: "Typical", lo: 40, hi: 60 },
  { id: "pricier", label: "Pricier than usual", lo: 60, hi: 80 },
  { id: "much_pricier", label: "Much pricier than usual", lo: 80, hi: 100 },
];

/** One step of the single-hue ramp per zone: magnitude, never good or bad */
export const zoneColor = (id: ZoneId | string | null | undefined) => {
  const index = ZONES.findIndex((z) => z.id === id);
  return index >= 0 ? `var(--zone-${index + 1})` : "var(--axis)";
};

export interface HorizonStats {
  median: number | null;
  p10: number | null;
  p90: number | null;
  pct_negative: number | null;
  n_days: number;
  distinct_years: number;
  episodes: number;
}

export interface ZoneHistory extends ZoneDef {
  share_of_days: number | null;
  h1: HorizonStats;
  h3: HorizonStats;
  h5: HorizonStats;
}

export interface ZoneTable {
  horizons: number[];
  data_from: string;
  data_to: string;
  series: string;
  method_version: string;
  zones: ZoneHistory[];
}

export interface ValuationComponent {
  id: "pe" | "pb";
  label: string;
  value: number | null;
  adjusted: number | null;
  pct: number | null;
  as_of: string | null;
}

export interface Session {
  state: "open" | "closed";
  reason: "weekend" | "holiday" | "before_open" | "after_close" | null;
  closes_at: string | null;
  next_open: string | null;
}

export interface Break {
  series_id: string;
  date: string;
  factor: number;
  note: string;
}

/** The daily shared note written by backend/signals (market_signals.narrative) */
export interface MarketNote {
  status: "ok" | "withheld";
  as_of?: string;
  generated_at?: string;
  headline?: string;
  what_the_data_shows?: string[];
  what_it_does_not_mean?: string;
  per_indicator_notes?: { indicator: string; note: string }[];
  checks?: { attempts: number; outcome: string };
}

export interface MarketContextData {
  available: boolean;
  as_of?: string;
  computed_at?: string;
  method_version?: string;
  session: Session;
  index?: {
    name: string;
    level: number;
    prev_close: number | null;
    change: number | null;
    change_pct: number | null;
    as_of: string;
    source: string;
    delay: string;
  } | null;
  valuation?: {
    available: boolean;
    as_of?: string;
    stale?: boolean;
    score?: number;
    zone?: ZoneId;
    zone_label?: string;
    history_from?: string;
    source?: string;
    components?: ValuationComponent[];
    dividend_yield?: { value: number; as_of: string } | null;
    method?: { version: string; window: string; min_history_years: number; hysteresis_points: number };
    history: ZoneTable | null;
  };
  turbulence?: {
    as_of: string;
    series: string;
    drawdown_pct: number;
    all_time_high: number;
    all_time_high_date: string;
    dma200: number | null;
    dma200_distance_pct: number | null;
    above_200dma: boolean | null;
    realised_vol_20d: number | null;
    source: string;
    vix: { value: number; as_of: string; id: string; label: string } | null;
  } | null;
  breaks?: Break[];
  coverage?: Record<string, [string, string] | null>;
  narrative?: MarketNote | null;
  disclaimer: string;
}

export type ChartRange = "1y" | "5y" | "10y" | "max";

export interface ChartTable {
  fields: string[];
  rows: (string | number | null)[][];
}

/** {fields, rows} from the API, as one object per date */
export function rowsOf<T>(table: ChartTable | null | undefined): T[] {
  if (!table?.rows) return [];
  return table.rows.map((row) => Object.fromEntries(table.fields.map((field, i) => [field, row[i]])) as T);
}

export interface ValuationPoint {
  d: string;
  pe: number | null;
  pb: number | null;
  t: number | null;
  [band: string]: string | number | null;
}

export interface TurbulencePoint {
  d: string;
  level: number | null;
  dd: number | null;
  dma: number | null;
}

export interface ValuationChart extends ChartTable {
  available: boolean;
  breaks: Break[];
  source: string;
}

export interface TurbulenceChart extends ChartTable {
  available: boolean;
  source: string;
  series: string;
  vix: ChartTable | null;
}

export interface PerspectiveChart {
  available: boolean;
  series: string;
  source: string;
  intra_year: { year: number; calendar_return: number; intra_year_fall: number }[];
  entry_year: { entry: number; years: number; cagr: number }[];
  cycle: {
    lows: { name: string; date: string }[];
    rows: { id: "pe" | "pb" | "dy"; current: number; as_of: string; median: number; at_lows: number | null; since: string }[];
  } | null;
}

const IST = "Asia/Kolkata";

/** "25 Sept 2026" for an ISO date (dates are exchange dates, so no time zone shift) */
export function formatMarketDate(iso: string | null | undefined, withWeekday = false): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-IN", {
    timeZone: "UTC",
    day: "numeric",
    month: "short",
    year: "numeric",
    ...(withWeekday ? { weekday: "short" } : {}),
  });
}

/** "NSE open until 3:30 pm" / "NSE closed, opens Mon 9:15 am" */
export function describeSession(session: Session | null | undefined, now: Date = new Date()): string {
  if (!session) return "";
  if (session.state === "open" && session.closes_at) {
    return `NSE open until ${new Date(session.closes_at).toLocaleTimeString("en-IN", { timeZone: IST, hour: "numeric", minute: "2-digit" })}`;
  }
  if (!session.next_open) return "NSE closed";
  const next = new Date(session.next_open);
  const sameDay = next.toLocaleDateString("en-CA", { timeZone: IST }) === now.toLocaleDateString("en-CA", { timeZone: IST });
  const when = next.toLocaleString("en-IN", {
    timeZone: IST,
    ...(sameDay ? {} : { weekday: "short" }),
    hour: "numeric",
    minute: "2-digit",
  });
  const why = session.reason === "holiday" ? " for a holiday" : "";
  return `NSE closed${why}, opens ${sameDay ? "today at " : ""}${when}`;
}

/** Fractions to "12.1%" / "−3.4%" (signed) */
export function pct(value: number | null | undefined, decimals = 1, signed = false): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const shown = Math.abs(value * 100).toFixed(decimals);
  if (Number(shown) === 0) return `${shown}%`; // never "−0%" or "+0%"
  const sign = value < 0 ? "−" : signed ? "+" : "";
  return `${sign}${shown}%`;
}

export function formatIndex(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toLocaleString("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

// ---------------------------------------------------------------------------
// Delayed intraday prices (Phase 5): GET /api/market/snapshot, from DynamoDB
// ---------------------------------------------------------------------------

/** One delayed price (backend/database/src/market_live.py). change_pct is a fraction. */
export interface LiveQuote {
  symbol: string;
  kind: "index" | "instrument";
  name?: string;
  price: number;
  prev_close?: number;
  change?: number;
  change_pct?: number;
  day_open?: number;
  day_high?: number;
  day_low?: number;
  /** End of the 5-minute bar the price comes from (IST, ISO) */
  as_of: string;
  source: string;
  delay_minutes: number;
  updated_at: string;
}

export interface MarketSnapshot {
  available: boolean;
  session: Session;
  /** Whether delayed prices can still change today (until 15:50 IST), else when they next will */
  updates: { active: boolean; until: string | null; next: string | null };
  source: string | null;
  source_label: string | null;
  delay_minutes: number;
  updated_at: string | null;
  indices: Record<string, LiveQuote>;
  quotes: Record<string, LiveQuote>;
  /** Today's 5-minute points: [minutes after midnight IST, level] */
  intraday: Record<string, { date: string; points: [number, number][] }>;
  disclaimer: string;
}

export const SNAPSHOT_POLL_MS = 60_000;

/**
 * Milliseconds until the snapshot should be fetched again, or null to stop.
 * Every minute while delayed prices can still change; after that, one wake-up
 * when the next session's first delayed price is due. Nothing polls overnight.
 */
export function nextSnapshotPoll(snapshot: MarketSnapshot | null, now: number = Date.now()): number | null {
  if (!snapshot) return null;
  const { active, until, next } = snapshot.updates;
  if (active && until) return Math.max(1_000, Math.min(SNAPSHOT_POLL_MS, Date.parse(until) - now));
  if (next) return Math.min(Math.max(1_000, Date.parse(next) - now), 2_147_000_000); // setTimeout's limit
  return null;
}

/** "2:35 pm" in IST */
export function istClock(iso: string): string {
  return new Date(iso)
    .toLocaleTimeString("en-IN", { timeZone: IST, hour: "numeric", minute: "2-digit" })
    .replace(/\s?(am|pm)$/i, (m) => ` ${m.trim().toLowerCase()}`);
}

/** True when a delayed price is the session's close rather than a mid-session price */
export function isClosingPrice(iso: string): boolean {
  return istClock(iso) === "3:30 pm";
}
