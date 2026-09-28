/**
 * How fresh a price is, in words people can check: every price shows when it
 * was the price, where it came from and how delayed it is
 * (plans/realtime-market-intelligence.md, section 4.3). Pure functions over
 * the instrument's price_* fields, which only backend/pricer writes.
 */
import { parseServerDate } from "./format";
/** The price fields any priced thing carries (an Instrument, or a catalogue row from /api/instruments). */
export interface PriceFields {
  current_price: number | null;
  prev_close?: number | null;
  price_as_of?: string | null;
  price_source?: string | null;
  price_status?: string | null;
  /** Minutes the price is held back (15 during the session); set by live snapshot prices */
  price_delay_minutes?: number | null;
}

/** The pricer shows exchange prices at least this late during the session (backend/database/src/market_live.py) */
export const EXCHANGE_DELAY_MINUTES = 15;

export type FreshnessTone = "good" | "muted" | "warn" | "bad";

export interface Freshness {
  /** Short label, e.g. "25 Sep, 3:30 pm IST" or "NAV of 25 Sep" */
  label: string;
  /** Where it came from and how delayed, e.g. "Yahoo Finance, delayed" */
  source: string;
  /** One sentence for a tooltip */
  detail: string;
  tone: FreshnessTone;
  /** True when the number shouldn't be read as current */
  stale: boolean;
}

const IST = "Asia/Kolkata";

function istDate(value: Date, withYear = false): string {
  return value.toLocaleDateString("en-IN", { timeZone: IST, day: "numeric", month: "short", ...(withYear ? { year: "numeric" } : {}) });
}

function istTime(value: Date): string {
  return value.toLocaleTimeString("en-IN", { timeZone: IST, hour: "numeric", minute: "2-digit" }).replace(/\s?(am|pm)$/i, (m) => ` ${m.trim().toLowerCase()}`);
}

function sameIstDay(a: Date, b: Date): boolean {
  return istDate(a, true) === istDate(b, true);
}

export function freshnessOf(inst: PriceFields | null | undefined, now: Date = new Date()): Freshness {
  if (!inst || inst.current_price == null || inst.price_status === "missing") {
    return { label: "No price yet", source: "", detail: "No price has been fetched for this holding yet, so it counts as ₹0.", tone: "bad", stale: true };
  }
  if (inst.price_source === "seed") {
    return {
      label: "Placeholder price",
      source: "not live",
      detail: "A starting value from the catalogue. It is replaced once the price refresh runs.",
      tone: "warn",
      stale: true,
    };
  }

  const asOf = inst.price_as_of ? parseServerDate(inst.price_as_of) : null;
  const when = asOf
    ? inst.price_source === "amfi"
      ? `NAV of ${istDate(asOf)}`
      : sameIstDay(asOf, now)
        ? `Today, ${istTime(asOf)} IST`
        : `${istDate(asOf)}, ${istTime(asOf)} IST`
    : "time unknown";
  const closing = asOf ? istTime(asOf) === "3:30 pm" : false;
  const delay = inst.price_delay_minutes ?? EXCHANGE_DELAY_MINUTES;
  const source =
    inst.price_source === "amfi"
      ? "AMFI"
      : inst.price_source === "yahoo"
        ? `Yahoo Finance (demo), ${closing ? "end of day" : `${delay} min delayed`}`
        : inst.price_source ?? "";

  if (inst.price_status === "held") {
    return {
      label: when,
      source,
      detail: "The latest price moved more than 20% from the previous close, so it is being checked. This is the last confirmed price.",
      tone: "warn",
      stale: false,
    };
  }
  if (inst.price_status === "stale") {
    return {
      label: `Last updated ${asOf ? istDate(asOf) : "a while ago"}`,
      source,
      detail: "This price hasn't been refreshed for more than four days, so it may be out of date.",
      tone: "warn",
      stale: true,
    };
  }
  const detail =
    inst.price_source === "amfi"
      ? "Mutual funds have one official price a day, the NAV, published by AMFI in the evening."
      : closing
        ? "Closing price on NSE from Yahoo Finance (demo data)."
        : `Price on NSE from Yahoo Finance (demo data), shown at least ${delay} minutes after it traded. It is not a live quote.`;
  return { label: when, source, detail, tone: "good", stale: false };
}

export interface DayChange {
  abs: number;
  pct: number;
}

/** Change against the previous close, per unit. Null when there's nothing honest to compare. */
export function dayChangeOf(inst: PriceFields | null | undefined): DayChange | null {
  if (!inst || inst.current_price == null || inst.prev_close == null || inst.prev_close === 0) return null;
  if (inst.price_source === "seed" || inst.price_status === "held" || inst.price_status === "stale") return null;
  const abs = inst.current_price - inst.prev_close;
  return { abs, pct: (abs / inst.prev_close) * 100 };
}

/** The newest exchange-price time across holdings, for "Prices as of …" headers. */
export function latestExchangeAsOf(instruments: (PriceFields | null | undefined)[]): Date | null {
  let latest: Date | null = null;
  for (const inst of instruments) {
    if (!inst?.price_as_of || inst.price_source !== "yahoo") continue;
    const at = parseServerDate(inst.price_as_of);
    if (!latest || at > latest) latest = at;
  }
  return latest;
}

export function describeAsOf(at: Date, now: Date = new Date()): string {
  return sameIstDay(at, now) ? `${istTime(at)} IST today` : `${istTime(at)} IST on ${istDate(at)}`;
}

/** "end of day" for a closing price, otherwise "15 min delayed" */
export function describeExchangeDelay(at: Date): string {
  return istTime(at) === "3:30 pm" ? "end of day" : `${EXCHANGE_DELAY_MINUTES} min delayed`;
}
