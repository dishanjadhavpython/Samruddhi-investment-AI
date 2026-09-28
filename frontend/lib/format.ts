/**
 * Display helpers shared across pages (currency lives in ./currency).
 */

const LABEL_OVERRIDES: Record<string, string> = {
  fixed_income: "Fixed income",
  real_estate: "Real estate",
  north_america: "North America",
  latin_america: "Latin America",
  middle_east: "Middle East",
  emerging_markets: "Emerging markets",
  government_related: "Government",
  consumer_discretionary: "Consumer discretionary",
  consumer_staples: "Consumer staples",
  communication_services: "Communication",
  mutual_fund: "Mutual fund",
  bond_fund: "Bond fund",
  etf: "ETF",
  india: "India",
};

/** "fixed_income" → "Fixed income" */
export function labelize(key: string): string {
  if (LABEL_OVERRIDES[key]) return LABEL_OVERRIDES[key];
  const spaced = key.replace(/[_-]+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function formatPct(value: number, decimals = 1): string {
  if (!Number.isFinite(value)) return "—";
  return `${value.toFixed(decimals)}%`;
}

export function formatSignedPct(value: number, decimals = 1): string {
  if (!Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(decimals)}%`;
}

export function timeAgo(input: string | Date | null | undefined): string {
  if (!input) return "never";
  const date = typeof input === "string" ? parseServerDate(input) : input;
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return date.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

/**
 * Aurora returns naive UTC timestamps ("2026-09-26T10:04:11.123") — treat a
 * timestamp without an offset as UTC rather than browser-local time.
 */
export function parseServerDate(value: string): Date {
  const hasZone = /[zZ]|[+-]\d{2}:?\d{2}$/.test(value);
  return new Date(hasZone ? value : `${value.replace(" ", "T")}Z`);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  return parseServerDate(value).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return "—";
  const totalSeconds = Math.round(ms / 1000);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return seconds ? `${minutes}m ${seconds}s` : `${minutes}m`;
}

export function greeting(date = new Date()): string {
  const hour = date.getHours();
  if (hour < 5) return "Good evening";
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}
