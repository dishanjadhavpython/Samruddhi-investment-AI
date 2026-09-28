/**
 * Portfolio domain types and the pure maths the dashboard, holdings, goals and
 * account pages share. Everything here is derived from the user's own accounts,
 * positions and instrument metadata — no invented market data.
 */

import { parseServerDate } from "./format";
import type { LiveQuote } from "./market";

export interface Instrument {
  symbol: string;
  name: string;
  instrument_type: string;
  current_price: number | null;
  /** Previous session's close (or previous NAV), for day change */
  prev_close: number | null;
  /** When current_price was the price; ISO string from the server */
  price_as_of: string | null;
  /** yahoo | amfi | seed */
  price_source: string | null;
  /** ok | stale | missing | held */
  price_status: string | null;
  /** Set when a live snapshot price replaced the stored one */
  price_delay_minutes?: number | null;
  allocation_asset_class: Record<string, number>;
  allocation_regions: Record<string, number>;
  allocation_sectors: Record<string, number>;
}

export interface Position {
  id: string;
  account_id: string;
  symbol: string;
  quantity: number;
  price: number | null;
  instrument: Instrument | null;
  as_of_date?: string;
  /** From the transaction ledger; null while a lot has no known price */
  avg_cost: number | null;
  cost_basis: number | null;
  first_buy_date: string | null;
}

/** demat | mutual_fund | epf | ppf | nps | savings | other */
export type AccountType = "demat" | "mutual_fund" | "epf" | "ppf" | "nps" | "savings" | "other";

export const ACCOUNT_TYPES: { value: AccountType; label: string; hint: string }[] = [
  { value: "demat", label: "Demat / trading", hint: "Shares and ETFs with a broker" },
  { value: "mutual_fund", label: "Mutual funds", hint: "Folios held with an AMC or platform" },
  { value: "epf", label: "EPF", hint: "Employees' Provident Fund" },
  { value: "ppf", label: "PPF", hint: "Public Provident Fund" },
  { value: "nps", label: "NPS", hint: "National Pension System" },
  { value: "savings", label: "Savings account", hint: "Bank savings or deposits" },
  { value: "other", label: "Other", hint: "" },
];

export const accountTypeLabel = (type: string | null | undefined) =>
  ACCOUNT_TYPES.find((t) => t.value === type)?.label ?? "Other";

export interface Account {
  id: string;
  account_name: string;
  account_purpose: string;
  account_type: AccountType;
  cash_balance: number;
  positions: Position[];
  created_at?: string;
}

export interface UserProfile {
  clerk_user_id: string;
  display_name: string;
  years_until_retirement: number;
  target_retirement_income: number;
  asset_class_targets: Record<string, number>;
  region_targets: Record<string, number>;
  /** ISO date, or null when not entered */
  date_of_birth: string | null;
  monthly_contribution: number | null;
  monthly_expenses: number | null;
  emergency_fund_months: number | null;
  /** Horizon for invested money; null means "same as years to retirement" */
  horizon_years: number | null;
}

export interface Holding {
  symbol: string;
  name: string;
  type: string;
  quantity: number;
  price: number | null;
  value: number;
  /** Share of invested (non-cash) value, 0-100 */
  weight: number;
  assetClass: string;
  accounts: { id: string; name: string; quantity: number; value: number }[];
  instrument: Instrument | null;
}

export interface AccountSummary {
  id: string;
  name: string;
  purpose: string;
  cash: number;
  invested: number;
  total: number;
  positionCount: number;
  assetClasses: Record<string, number>;
}

export interface Drift {
  key: string;
  label: string;
  target: number;
  actual: number;
  /** actual - target, percentage points */
  delta: number;
}

export interface PortfolioMetrics {
  totalValue: number;
  cashValue: number;
  investedValue: number;
  holdings: Holding[];
  accounts: AccountSummary[];
  /** Includes a "cash" bucket for uninvested balances */
  assetClasses: Record<string, number>;
  /** Over invested value only */
  regions: Record<string, number>;
  sectors: Record<string, number>;
  top5Share: number;
  /** 1 / Σw² — how many equally-weighted holdings this portfolio behaves like */
  effectiveHoldings: number;
  unpricedCount: number;
}

// ---------------------------------------------------------------------------
// Normalisers — the Data API hands DECIMAL columns back as strings
// ---------------------------------------------------------------------------

const toNum = (value: unknown): number => {
  const n = typeof value === "string" ? parseFloat(value) : typeof value === "number" ? value : NaN;
  return Number.isFinite(n) ? n : 0;
};

const toNumOrNull = (value: unknown): number | null => {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "string" ? parseFloat(value) : typeof value === "number" ? value : NaN;
  return Number.isFinite(n) ? n : null;
};

const toMap = (value: unknown): Record<string, number> => {
  let raw = value;
  if (typeof raw === "string") {
    try {
      raw = JSON.parse(raw);
    } catch {
      return {};
    }
  }
  if (!raw || typeof raw !== "object") return {};
  const out: Record<string, number> = {};
  for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
    const n = toNum(v);
    if (n > 0) out[k] = n;
  }
  return out;
};

export function normalizeInstrument(raw: unknown): Instrument | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  return {
    symbol: String(r.symbol ?? ""),
    name: String(r.name ?? r.symbol ?? ""),
    instrument_type: String(r.instrument_type ?? ""),
    current_price: toNumOrNull(r.current_price),
    prev_close: toNumOrNull(r.prev_close),
    price_as_of: r.price_as_of ? String(r.price_as_of) : null,
    price_source: r.price_source ? String(r.price_source) : null,
    price_status: r.price_status ? String(r.price_status) : null,
    allocation_asset_class: toMap(r.allocation_asset_class ?? r.asset_class_allocation),
    allocation_regions: toMap(r.allocation_regions ?? r.region_allocation),
    allocation_sectors: toMap(r.allocation_sectors ?? r.sector_allocation),
  };
}

export function normalizePosition(raw: unknown): Position {
  const r = raw as Record<string, unknown>;
  const instrument = normalizeInstrument(r.instrument);
  return {
    id: String(r.id),
    account_id: String(r.account_id),
    symbol: String(r.symbol),
    quantity: toNum(r.quantity),
    price: toNumOrNull(r.current_price) ?? instrument?.current_price ?? null,
    instrument,
    as_of_date: r.as_of_date ? String(r.as_of_date) : undefined,
    avg_cost: toNumOrNull(r.avg_cost),
    cost_basis: toNumOrNull(r.cost_basis),
    first_buy_date: r.first_buy_date ? String(r.first_buy_date).slice(0, 10) : null,
  };
}

export function normalizeAccount(raw: unknown, positions: Position[] = []): Account {
  const r = raw as Record<string, unknown>;
  return {
    id: String(r.id),
    account_name: String(r.account_name ?? "Account"),
    account_purpose: String(r.account_purpose ?? ""),
    account_type: (ACCOUNT_TYPES.some((t) => t.value === r.account_type) ? r.account_type : "other") as AccountType,
    cash_balance: toNum(r.cash_balance),
    positions,
    created_at: r.created_at ? String(r.created_at) : undefined,
  };
}

export function normalizeUser(raw: unknown): UserProfile {
  const r = raw as Record<string, unknown>;
  const regions = toMap(r.region_targets);
  // Older rows were created with a north_america/international split
  if (regions.india === undefined && regions.north_america !== undefined) {
    regions.india = regions.north_america;
    delete regions.north_america;
  }
  return {
    clerk_user_id: String(r.clerk_user_id ?? ""),
    display_name: String(r.display_name ?? ""),
    years_until_retirement: toNum(r.years_until_retirement),
    target_retirement_income: toNum(r.target_retirement_income),
    asset_class_targets: toMap(r.asset_class_targets),
    region_targets: regions,
    date_of_birth: r.date_of_birth ? String(r.date_of_birth).slice(0, 10) : null,
    monthly_contribution: toNumOrNull(r.monthly_contribution),
    monthly_expenses: toNumOrNull(r.monthly_expenses),
    emergency_fund_months: toNumOrNull(r.emergency_fund_months),
    horizon_years: toNumOrNull(r.horizon_years),
  };
}

/** Whole years of age today, or null */
export function ageFrom(dateOfBirth: string | null, today = new Date()): number | null {
  if (!dateOfBirth) return null;
  const [y, m, d] = dateOfBirth.split("-").map(Number);
  if (!y || !m || !d) return null;
  const before = today.getMonth() + 1 < m || (today.getMonth() + 1 === m && today.getDate() < d);
  return today.getFullYear() - y - (before ? 1 : 0);
}

/** The horizon that gates market-timing context (plan principle 7) */
export function investmentHorizon(user: UserProfile | null): number | null {
  if (!user) return null;
  return user.horizon_years ?? (user.years_until_retirement || null);
}

/** Cash sitting in demat accounts: the only cash the explorer treats as idle */
export function dematCash(accounts: Account[]): number {
  return accounts.filter((a) => a.account_type === "demat").reduce((sum, a) => sum + a.cash_balance, 0);
}

// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

const add = (bucket: Record<string, number>, key: string, amount: number) => {
  if (amount <= 0) return;
  bucket[key] = (bucket[key] ?? 0) + amount;
};

const dominantKey = (map: Record<string, number>, fallback: string) => {
  let best = fallback;
  let bestValue = -1;
  for (const [k, v] of Object.entries(map)) {
    if (v > bestValue) {
      best = k;
      bestValue = v;
    }
  }
  return best;
};

/**
 * Holdings with newer delayed prices from GET /api/market/snapshot applied, so
 * an open tab stays current without reloading the portfolio from Aurora. A
 * stored price that is as new or newer (or held for checking) is kept.
 */
export function withLiveQuotes(accounts: Account[], quotes: Record<string, LiveQuote>): Account[] {
  if (!Object.keys(quotes).length) return accounts;
  return accounts.map((account) => ({
    ...account,
    positions: account.positions.map((position) => {
      const quote = quotes[position.symbol];
      const inst = position.instrument;
      if (!quote || !inst || inst.price_status === "held") return position;
      const stored = inst.price_as_of ? parseServerDate(inst.price_as_of).getTime() : 0;
      if (Date.parse(quote.as_of) < stored) return position;
      return {
        ...position,
        price: quote.price,
        instrument: {
          ...inst,
          current_price: quote.price,
          prev_close: quote.prev_close ?? inst.prev_close,
          price_as_of: quote.as_of,
          price_source: quote.source,
          price_status: "ok",
          price_delay_minutes: quote.delay_minutes,
        },
      };
    }),
  }));
}

export function positionValue(position: Position): number {
  return position.price != null ? position.quantity * position.price : 0;
}

export function computeMetrics(accounts: Account[]): PortfolioMetrics {
  const holdingsBySymbol = new Map<string, Holding>();
  const assetClasses: Record<string, number> = {};
  const regions: Record<string, number> = {};
  const sectors: Record<string, number> = {};
  let cashValue = 0;
  let unpricedCount = 0;

  const accountSummaries: AccountSummary[] = accounts.map((account) => {
    const summary: AccountSummary = {
      id: account.id,
      name: account.account_name,
      purpose: account.account_purpose,
      cash: account.cash_balance,
      invested: 0,
      total: 0,
      positionCount: account.positions.length,
      assetClasses: {},
    };
    cashValue += account.cash_balance;
    add(assetClasses, "cash", account.cash_balance);
    add(summary.assetClasses, "cash", account.cash_balance);

    for (const position of account.positions) {
      if (position.price == null) unpricedCount += 1;
      const value = positionValue(position);
      summary.invested += value;

      const inst = position.instrument;
      const classMap = inst && Object.keys(inst.allocation_asset_class).length
        ? inst.allocation_asset_class
        : { unclassified: 100 };

      for (const [cls, pct] of Object.entries(classMap)) {
        add(assetClasses, cls, (value * pct) / 100);
        add(summary.assetClasses, cls, (value * pct) / 100);
      }
      for (const [region, pct] of Object.entries(inst?.allocation_regions ?? {})) {
        add(regions, region, (value * pct) / 100);
      }
      for (const [sector, pct] of Object.entries(inst?.allocation_sectors ?? {})) {
        add(sectors, sector, (value * pct) / 100);
      }

      const existing = holdingsBySymbol.get(position.symbol);
      if (existing) {
        existing.quantity += position.quantity;
        existing.value += value;
        existing.accounts.push({ id: account.id, name: account.account_name, quantity: position.quantity, value });
      } else {
        holdingsBySymbol.set(position.symbol, {
          symbol: position.symbol,
          name: inst?.name || position.symbol,
          type: inst?.instrument_type || "",
          quantity: position.quantity,
          price: position.price,
          value,
          weight: 0,
          assetClass: dominantKey(classMap, "unclassified"),
          accounts: [{ id: account.id, name: account.account_name, quantity: position.quantity, value }],
          instrument: inst,
        });
      }
    }
    summary.total = summary.cash + summary.invested;
    return summary;
  });

  const holdings = [...holdingsBySymbol.values()].sort((a, b) => b.value - a.value);
  const investedValue = holdings.reduce((sum, h) => sum + h.value, 0);
  for (const h of holdings) {
    h.weight = investedValue > 0 ? (h.value / investedValue) * 100 : 0;
  }

  const top5Share = holdings.slice(0, 5).reduce((sum, h) => sum + h.weight, 0);
  const hhi = holdings.reduce((sum, h) => sum + (h.weight / 100) ** 2, 0);

  return {
    totalValue: cashValue + investedValue,
    cashValue,
    investedValue,
    holdings,
    accounts: accountSummaries,
    assetClasses,
    regions,
    sectors,
    top5Share,
    effectiveHoldings: hhi > 0 ? 1 / hhi : 0,
    unpricedCount,
  };
}

/** Sorted [key, value] pairs, largest first, with the tail folded into "other". */
export function rankEntries(map: Record<string, number>, limit = 6): [string, number][] {
  const entries = Object.entries(map).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  if (entries.length <= limit) return entries;
  const head = entries.slice(0, limit - 1);
  const rest = entries.slice(limit - 1).reduce((sum, [, v]) => sum + v, 0);
  return [...head, ["other", rest]];
}

/**
 * Drift inside the sleeves the user set targets for. Asset-class targets cover
 * equity + fixed income only, so cash and commodities sit outside the comparison
 * rather than being flagged as "0% target, sell everything".
 */
export function computeDrift(metrics: PortfolioMetrics, user: UserProfile | null) {
  const eq = metrics.assetClasses.equity ?? 0;
  const fi = metrics.assetClasses.fixed_income ?? 0;
  const sleeve = eq + fi;
  const eqTarget = user?.asset_class_targets.equity ?? 70;
  const fiTarget = user?.asset_class_targets.fixed_income ?? 100 - eqTarget;

  const india = metrics.regions.india ?? 0;
  const regionTotal = Object.values(metrics.regions).reduce((s, v) => s + v, 0);
  const intl = regionTotal - india;
  const indiaTarget = user?.region_targets.india ?? 70;
  const intlTarget = user?.region_targets.international ?? 100 - indiaTarget;

  const assetDrift: Drift[] = sleeve > 0
    ? [
        { key: "equity", label: "Equity", target: eqTarget, actual: (eq / sleeve) * 100, delta: (eq / sleeve) * 100 - eqTarget },
        { key: "fixed_income", label: "Fixed income", target: fiTarget, actual: (fi / sleeve) * 100, delta: (fi / sleeve) * 100 - fiTarget },
      ]
    : [];

  const regionDrift: Drift[] = regionTotal > 0
    ? [
        { key: "india", label: "India", target: indiaTarget, actual: (india / regionTotal) * 100, delta: (india / regionTotal) * 100 - indiaTarget },
        { key: "international", label: "International", target: intlTarget, actual: (intl / regionTotal) * 100, delta: (intl / regionTotal) * 100 - intlTarget },
      ]
    : [];

  // Rupee amount to move from the overweight to the underweight asset class
  const equityGap = assetDrift[0] ? (assetDrift[0].delta / 100) * sleeve : 0;

  return { assetDrift, regionDrift, equityGap, sleeveValue: sleeve, outsideSleeve: metrics.totalValue - sleeve };
}

/** Largest absolute drift across both target sets, in percentage points */
export function maxDrift(drift: ReturnType<typeof computeDrift>): number {
  return Math.max(0, ...drift.assetDrift.map((d) => Math.abs(d.delta)), ...drift.regionDrift.map((d) => Math.abs(d.delta)));
}
