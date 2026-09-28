/**
 * Market page pieces. Index-level only (Nifty 50, India VIX), never a named
 * security. Valuation visuals use the single-hue zone ramp; turbulence
 * visuals use --series-2, so the two dials never blend.
 */
import { motion } from "framer-motion";
import Link from "next/link";
import { ReactNode, useMemo } from "react";
import {
  Area,
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Break,
  ChartRange,
  formatIndex,
  formatMarketDate,
  PerspectiveChart,
  pct,
  TurbulencePoint,
  ValuationPoint,
  ZONES,
  ZoneHistory,
  ZoneId,
  zoneColor,
} from "../lib/market";
import { useMarket } from "../lib/market-context";
import { usePortfolio } from "../lib/portfolio-context";
import { investmentHorizon } from "../lib/portfolio";
import { TooltipBox } from "./charts";

// ---------------------------------------------------------------------------
// Shared bits
// ---------------------------------------------------------------------------

const RANGE_YEARS: Record<ChartRange, number | null> = { "1y": 1, "5y": 5, "10y": 10, max: null };

/** Rows dated within `range` of the last row (dates are ISO strings) */
export function withinRange<T extends { d: string }>(rows: T[], range: ChartRange): T[] {
  const years = RANGE_YEARS[range];
  if (!years || !rows.length) return rows;
  const last = new Date(rows[rows.length - 1].d);
  last.setUTCFullYear(last.getUTCFullYear() - years);
  const cutoff = last.toISOString().slice(0, 10);
  return rows.filter((r) => r.d >= cutoff);
}

const DAY_MS = 86_400_000;

/** Adds a numeric timestamp so the x-axis spaces points by time, not by count
 *  (charts keep daily points for recent years and weekly ones before that). */
function timed<T extends { d: string }>(rows: T[]): (T & { ts: number })[] {
  return rows.map((r) => ({ ...r, ts: Date.parse(r.d) }));
}

/** A time x-axis with ticks on month starts (1Y) or year starts, at most about eight */
function timeAxis(rows: { ts: number }[], range: ChartRange) {
  if (!rows.length) return { dataKey: "ts" };
  const min = rows[0].ts;
  const max = rows[rows.length - 1].ts;
  const ticks: number[] = [];
  const start = new Date(min);
  if (range === "1y") {
    for (let d = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 1)); d.getTime() <= max; d.setUTCMonth(d.getUTCMonth() + 2)) ticks.push(d.getTime());
  } else {
    const years = Math.max(1, Math.round((max - min) / (365 * DAY_MS)));
    const step = Math.max(1, Math.ceil(years / 8));
    for (let y = start.getUTCFullYear() + 1; Date.UTC(y, 0, 1) <= max; y += step) ticks.push(Date.UTC(y, 0, 1));
  }
  return {
    dataKey: "ts",
    type: "number" as const,
    scale: "time" as const,
    domain: [min, max] as [number, number],
    ticks,
    tickFormatter: (ts: number) => {
      const d = new Date(ts);
      if (range !== "1y") return String(d.getUTCFullYear());
      const month = d.toLocaleDateString("en-IN", { month: "short", timeZone: "UTC" });
      return d.getUTCMonth() < 2 ? `${month} ’${String(d.getUTCFullYear()).slice(2)}` : month;
    },
  };
}

const axisProps = {
  tickLine: false,
  tick: { fill: "var(--muted)", fontSize: 12 },
} as const;

// ---------------------------------------------------------------------------
// Valuation dial — a 180° arc split into the five zones
// ---------------------------------------------------------------------------

/** The hero sits on the dark shader in both themes, so it uses the dark ramp */
const DARK_RAMP = ["#4a3b12", "#7a5d0e", "#b38600", "#e3aa12", "#ffd35c"];

function polar(cx: number, cy: number, r: number, score: number) {
  const angle = Math.PI * (1 - score / 100); // 0 → left, 100 → right
  return { x: cx + r * Math.cos(angle), y: cy - r * Math.sin(angle) };
}

function arcPath(cx: number, cy: number, r: number, from: number, to: number) {
  const a = polar(cx, cy, r, from);
  const b = polar(cx, cy, r, to);
  return `M ${a.x} ${a.y} A ${r} ${r} 0 0 1 ${b.x} ${b.y}`;
}

export function ValuationDial({ score, zone, width = 300 }: { score: number | null | undefined; zone?: ZoneId | null; width?: number }) {
  const stroke = Math.round(width * 0.075);
  const r = width / 2 - stroke;
  const cx = width / 2;
  const cy = width / 2;
  const height = width / 2 + stroke;
  const has = score !== null && score !== undefined && Number.isFinite(score);
  const marker = has ? polar(cx, cy, r, score as number) : null;
  const gap = 1.4; // score units of surface gap between segments

  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={has ? `Valuation temperature ${Math.round(score as number)} of 100` : "Valuation temperature not available"} className="max-w-[340px] overflow-visible">
      {ZONES.map((z, i) => (
        <path
          key={z.id}
          d={arcPath(cx, cy, r, z.lo + (i === 0 ? 0 : gap / 2), z.hi - (i === ZONES.length - 1 ? 0 : gap / 2))}
          fill="none"
          stroke={has ? DARK_RAMP[i] : "rgba(255,255,255,0.14)"}
          strokeWidth={stroke}
          strokeLinecap={i === 0 || i === ZONES.length - 1 ? "round" : "butt"}
          opacity={has && zone && z.id !== zone ? 0.55 : 1}
        />
      ))}
      {marker && (
        <motion.g initial={{ opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.5, delay: 0.2, ease: [0.16, 1, 0.3, 1] }} style={{ transformOrigin: `${marker.x}px ${marker.y}px` }}>
          <circle cx={marker.x} cy={marker.y} r={stroke * 0.62} fill="#121212" stroke="#fff" strokeWidth={3} />
        </motion.g>
      )}
      <text x={cx - r} y={cy + stroke * 1.25} textAnchor="middle" fill="rgba(255,255,255,0.55)" fontSize={11}>
        0
      </text>
      <text x={cx + r} y={cy + stroke * 1.25} textAnchor="middle" fill="rgba(255,255,255,0.55)" fontSize={11}>
        100
      </text>
    </svg>
  );
}

// ---------------------------------------------------------------------------
// What followed from each zone
// ---------------------------------------------------------------------------

export function ZoneHistoryTable({ zones, current }: { zones: ZoneHistory[]; current?: ZoneId | null }) {
  return (
    <div className="-mx-5 overflow-x-auto px-5">
      <table className="w-full min-w-[640px] text-[13px]">
        <thead>
          <tr className="text-left text-[12px] text-muted">
            <th className="pb-2 pr-3 font-medium">Starting zone</th>
            <th className="pb-2 pr-3 text-right font-medium">1 yr, median</th>
            <th className="pb-2 pr-3 text-right font-medium">1 yr, worst 10%</th>
            <th className="pb-2 pr-3 text-right font-medium">1 yr below zero</th>
            <th className="pb-2 pr-3 text-right font-medium">3 yrs, median a year</th>
            <th className="pb-2 pr-3 text-right font-medium">5 yrs, median a year</th>
            <th className="pb-2 text-right font-medium">Years in sample</th>
          </tr>
        </thead>
        <tbody>
          {zones.map((z) => {
            const isNow = z.id === current;
            const empty = z.h1.n_days === 0;
            return (
              <tr key={z.id} className={`border-t border-line ${isNow ? "bg-accent-soft/60" : ""}`}>
                <td className="py-2.5 pr-3">
                  <span className="flex items-center gap-2.5">
                    <span className="h-3 w-3 shrink-0 rounded-[4px] ring-1 ring-black/5" style={{ background: zoneColor(z.id) }} />
                    <span className={isNow ? "font-semibold text-ink" : "text-ink-2"}>{z.label}</span>
                    {isNow && <span className="sm-chip bg-accent text-accent-ink">Today</span>}
                  </span>
                </td>
                {empty ? (
                  <td colSpan={6} className="py-2.5 text-right text-muted">
                    No days in this zone yet
                  </td>
                ) : (
                  <>
                    <td className="tabular py-2.5 pr-3 text-right font-medium text-ink">{pct(z.h1.median)}</td>
                    <td className="tabular py-2.5 pr-3 text-right text-ink-2">{pct(z.h1.p10)}</td>
                    <td className="tabular py-2.5 pr-3 text-right text-ink-2">{pct(z.h1.pct_negative, 0)}</td>
                    <td className="tabular py-2.5 pr-3 text-right text-ink-2">{pct(z.h3.median)}</td>
                    <td className="tabular py-2.5 pr-3 text-right text-ink-2">{pct(z.h5.median)}</td>
                    <td className="tabular py-2.5 text-right text-ink-2">{z.h1.distinct_years}</td>
                  </>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Valuation over time with walk-forward percentile bands
// ---------------------------------------------------------------------------

export function ValuationBandsChart({ points, metric, breaks, range, height = 300 }: { points: ValuationPoint[]; metric: "pe" | "pb"; breaks: Break[]; range: ChartRange; height?: number }) {
  const data = useMemo(
    () =>
      timed(
        points.map((p) => ({
          d: p.d,
          value: p[metric] as number | null,
          median: p[`${metric}_p50`] as number | null,
          outer: p[`${metric}_p10`] !== null && p[`${metric}_p90`] !== null ? [p[`${metric}_p10`], p[`${metric}_p90`]] : null,
          inner: p[`${metric}_p25`] !== null && p[`${metric}_p75`] !== null ? [p[`${metric}_p25`], p[`${metric}_p75`]] : null,
          t: p.t,
        })),
      ),
    [points, metric],
  );
  const seriesId = metric === "pe" ? "NIFTY50_PE" : "NIFTY50_PB";
  const shown = breaks.filter((b) => b.series_id === seriesId && data.length && b.date >= data[0].d);
  const decimals = metric === "pe" ? 1 : 2;

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 16, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis {...timeAxis(data, range)} {...axisProps} axisLine={{ stroke: "var(--axis)" }} />
          <YAxis {...axisProps} axisLine={false} width={44} domain={["auto", "auto"]} tickFormatter={(v: number) => v.toFixed(metric === "pe" ? 0 : 1)} />
          <Tooltip
            cursor={{ stroke: "var(--line-strong)", strokeWidth: 1 }}
            content={({ active, payload }) => {
              const p = payload?.[0]?.payload as (typeof data)[number] | undefined;
              if (!active || !p) return null;
              return (
                <TooltipBox
                  title={formatMarketDate(p.d)}
                  rows={[
                    { color: "var(--ink)", label: metric === "pe" ? "P/E (linked)" : "P/B (linked)", value: p.value?.toFixed(decimals) ?? "—" },
                    { color: "var(--ink-2)", label: "Median so far", value: p.median?.toFixed(decimals) ?? "—" },
                    { label: "Middle half so far", value: p.inner ? `${Number(p.inner[0]).toFixed(decimals)} to ${Number(p.inner[1]).toFixed(decimals)}` : "—" },
                    { label: "Temperature", value: p.t !== null && p.t !== undefined ? `${Math.round(p.t)} of 100` : "—" },
                  ]}
                />
              );
            }}
          />
          <Area dataKey="outer" stroke="none" fill="var(--accent)" fillOpacity={0.14} isAnimationActive={false} connectNulls={false} />
          <Area dataKey="inner" stroke="none" fill="var(--accent)" fillOpacity={0.3} isAnimationActive={false} connectNulls={false} />
          <Line dataKey="median" stroke="var(--ink-2)" strokeWidth={1.5} strokeDasharray="4 4" dot={false} isAnimationActive={false} />
          <Line dataKey="value" stroke="var(--ink)" strokeWidth={2} dot={false} isAnimationActive={false} />
          {shown.map((b) => (
            <ReferenceLine key={b.date} x={Date.parse(b.date)} stroke="var(--muted)" strokeDasharray="2 3" label={{ value: "Basis change", position: "insideTopRight", fill: "var(--muted)", fontSize: 11 }} />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function BandsLegend({ metric }: { metric: "pe" | "pb" }) {
  const items: { swatch: ReactNode; label: string }[] = [
    { swatch: <span className="h-0.5 w-4 rounded bg-ink" />, label: metric === "pe" ? "P/E, linked across basis changes" : "P/B, linked across basis changes" },
    { swatch: <span className="h-0 w-4 border-t-[1.5px] border-dashed border-ink-2" />, label: "Median of all history up to each date" },
    { swatch: <span className="h-2.5 w-4 rounded-[3px] bg-accent/30" />, label: "Middle half (25th to 75th percentile)" },
    { swatch: <span className="h-2.5 w-4 rounded-[3px] bg-accent/15" />, label: "10th to 90th percentile" },
  ];
  return (
    <ul className="flex flex-wrap gap-x-5 gap-y-1.5 text-[12px] text-muted">
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-2">
          {item.swatch}
          {item.label}
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Turbulence: fall from the high, and India VIX
// ---------------------------------------------------------------------------

export function UnderwaterChart({ points, range, height = 240 }: { points: TurbulencePoint[]; range: ChartRange; height?: number }) {
  const data = useMemo(() => timed(points), [points]);
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="underwater" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--series-2)" stopOpacity={0.08} />
              <stop offset="100%" stopColor="var(--series-2)" stopOpacity={0.35} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis {...timeAxis(data, range)} {...axisProps} axisLine={{ stroke: "var(--axis)" }} />
          <YAxis {...axisProps} axisLine={false} width={48} domain={["dataMin", 0]} tickFormatter={(v: number) => pct(v, 0)} />
          <Tooltip
            cursor={{ stroke: "var(--line-strong)", strokeWidth: 1 }}
            content={({ active, payload }) => {
              const p = payload?.[0]?.payload as TurbulencePoint | undefined;
              if (!active || !p) return null;
              return (
                <TooltipBox
                  title={formatMarketDate(p.d)}
                  rows={[
                    { color: "var(--series-2)", label: "Below the high so far", value: pct(p.dd) },
                    { label: "Nifty 50 close", value: formatIndex(p.level) },
                  ]}
                />
              );
            }}
          />
          <Area dataKey="dd" type="monotone" stroke="var(--series-2)" strokeWidth={1.5} fill="url(#underwater)" isAnimationActive={false} baseValue={0} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

// Bands labelled in the right margin, outside the plot, so they never cover the line
const VIX_BANDS = [
  { from: 0, to: 13, label: "Calm" },
  { from: 13, to: 17, label: "Normal" },
  { from: 17, to: 25, label: "Nervous" },
  { from: 25, to: null, label: "Elevated" },
];

export function VixChart({ points, range, height = 240 }: { points: { d: string; v: number | null }[]; range: ChartRange; height?: number }) {
  const data = useMemo(() => timed(points), [points]);
  const top = Math.max(30, ...data.map((p) => p.v ?? 0));
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 64, bottom: 0, left: 0 }}>
          {VIX_BANDS.map((band, i) => (
            <ReferenceArea
              key={band.label}
              y1={band.from}
              y2={band.to ?? top}
              fill={i % 2 ? "var(--sunken)" : "transparent"}
              fillOpacity={1}
              stroke="none"
              ifOverflow="hidden"
              label={{ value: band.label, position: "right", fill: "var(--muted)", fontSize: 11 }}
            />
          ))}
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis {...timeAxis(data, range)} {...axisProps} axisLine={{ stroke: "var(--axis)" }} />
          <YAxis {...axisProps} axisLine={false} width={36} domain={[0, Math.ceil(top / 5) * 5]} ticks={[0, 13, 17, 25, ...(top > 40 ? [Math.ceil(top / 10) * 10] : [])]} />
          <Tooltip
            cursor={{ stroke: "var(--line-strong)", strokeWidth: 1 }}
            content={({ active, payload }) => {
              const p = payload?.[0]?.payload as { d: string; v: number } | undefined;
              if (!active || !p) return null;
              return <TooltipBox title={formatMarketDate(p.d)} rows={[{ color: "var(--series-2)", label: "India VIX", value: p.v?.toFixed(2) ?? "—" }]} />;
            }}
          />
          <Line dataKey="v" stroke="var(--series-2)" strokeWidth={1.5} dot={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Perspective: falls within each year, and returns by starting year
// ---------------------------------------------------------------------------

export function IntraYearChart({ rows, height = 280 }: { rows: PerspectiveChart["intra_year"]; height?: number }) {
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows} margin={{ top: 12, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="year" {...axisProps} axisLine={{ stroke: "var(--axis)" }} tickFormatter={(y: number) => `’${String(y).slice(2)}`} interval="preserveStartEnd" minTickGap={8} />
          <YAxis {...axisProps} axisLine={false} width={48} tickFormatter={(v: number) => pct(v, 0)} />
          <ReferenceLine y={0} stroke="var(--axis)" />
          <Tooltip
            cursor={{ fill: "var(--sunken)" }}
            content={({ active, payload }) => {
              const p = payload?.[0]?.payload as PerspectiveChart["intra_year"][number] | undefined;
              if (!active || !p) return null;
              return (
                <TooltipBox
                  title={String(p.year)}
                  rows={[
                    { color: "var(--series-2)", label: "Calendar-year return", value: pct(p.calendar_return, 1, true) },
                    { color: "var(--series-3)", label: "Deepest fall during the year", value: pct(p.intra_year_fall) },
                  ]}
                />
              );
            }}
          />
          <Bar dataKey="calendar_return" maxBarSize={18} radius={[4, 4, 4, 4]} isAnimationActive={false}>
            {rows.map((r) => (
              <Cell key={r.year} fill="var(--series-2)" fillOpacity={r.calendar_return < 0 ? 0.55 : 0.9} />
            ))}
          </Bar>
          <Scatter dataKey="intra_year_fall" fill="var(--series-3)" stroke="var(--surface)" strokeWidth={2} isAnimationActive={false} shape="circle" />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function IntraYearLegend() {
  return (
    <ul className="flex flex-wrap gap-x-5 gap-y-1.5 text-[12px] text-muted">
      <li className="flex items-center gap-2">
        <span className="h-2.5 w-2.5 rounded-[3px] bg-[var(--series-2)]" />
        Calendar-year return
      </li>
      <li className="flex items-center gap-2">
        <span className="h-2.5 w-2.5 rounded-full bg-[var(--series-3)]" />
        Deepest fall during the year, from the previous high
      </li>
    </ul>
  );
}

export function intraYearSummary(rows: PerspectiveChart["intra_year"]) {
  if (!rows.length) return null;
  const falls = rows.map((r) => r.intra_year_fall).sort((a, b) => a - b);
  const mid = Math.floor(falls.length / 2);
  const median = falls.length % 2 ? falls[mid] : (falls[mid - 1] + falls[mid]) / 2;
  const deep = rows.filter((r) => r.intra_year_fall < -0.1);
  return {
    first: rows[0].year,
    last: rows[rows.length - 1].year,
    years: rows.length,
    medianFall: median,
    deepYears: deep.length,
    deepEndedUp: deep.filter((r) => r.calendar_return > 0).length,
  };
}

const HOLDING_PERIODS = [1, 2, 3, 5, 7, 10, 15, 20];

/** Diverging fill around zero: --series-3 below, --series-2 above, surface at 0 */
function cagrFill(value: number) {
  const strength = Math.min(1, Math.abs(value) / 0.25);
  const mix = Math.round(10 + strength * 45);
  return `color-mix(in srgb, var(${value < 0 ? "--series-3" : "--series-2"}) ${mix}%, var(--surface))`;
}

export function EntryYearGrid({ cells }: { cells: PerspectiveChart["entry_year"] }) {
  const byKey = new Map(cells.map((c) => [`${c.entry}:${c.years}`, c.cagr]));
  const entries = [...new Set(cells.map((c) => c.entry))].sort((a, b) => a - b);
  const periods = HOLDING_PERIODS.filter((p) => cells.some((c) => c.years === p));
  return (
    <div className="-mx-5 overflow-x-auto px-5">
      <table className="w-full min-w-[520px] max-w-[880px] border-separate border-spacing-[2px] text-[12px]">
        <thead>
          <tr className="text-muted">
            <th className="sticky left-0 bg-surface pb-1.5 pr-2 text-left font-medium">Started</th>
            {periods.map((p) => (
              <th key={p} className="pb-1.5 text-center font-medium">
                {p} yr{p > 1 ? "s" : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry}>
              <th scope="row" className="tabular sticky left-0 bg-surface pr-2 text-left font-medium text-ink-2">
                {entry}
              </th>
              {periods.map((p) => {
                const v = byKey.get(`${entry}:${p}`);
                return v === undefined ? (
                  <td key={p} />
                ) : (
                  <td
                    key={p}
                    className="tabular h-7 rounded-[5px] text-center text-ink"
                    style={{ background: cagrFill(v) }}
                    title={`Started at the end of ${entry - 1}, held ${p} year${p > 1 ? "s" : ""}: ${pct(v, 1, true)} a year`}
                  >
                    {pct(v, 0, true)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const CYCLE_LABELS: Record<string, string> = { pe: "P/E (linked)", pb: "P/B (linked)", dy: "Dividend yield" };

export function CycleTable({ cycle }: { cycle: NonNullable<PerspectiveChart["cycle"]> }) {
  const fmt = (id: string, v: number | null) => (v === null ? "—" : id === "dy" ? `${v.toFixed(2)}%` : v.toFixed(id === "pe" ? 1 : 2));
  return (
    <table className="w-full text-[13px]">
      <thead>
        <tr className="text-left text-[12px] text-muted">
          <th className="pb-2 pr-3 font-medium">Measure</th>
          <th className="pb-2 pr-3 text-right font-medium">Latest</th>
          <th className="pb-2 pr-3 text-right font-medium">Long-term median</th>
          <th className="pb-2 text-right font-medium">At the big lows</th>
        </tr>
      </thead>
      <tbody>
        {cycle.rows.map((row) => (
          <tr key={row.id} className="border-t border-line">
            <td className="py-2.5 pr-3 text-ink-2">{CYCLE_LABELS[row.id] ?? row.id}</td>
            <td className="tabular py-2.5 pr-3 text-right font-medium text-ink">{fmt(row.id, row.current)}</td>
            <td className="tabular py-2.5 pr-3 text-right text-ink-2">{fmt(row.id, row.median)}</td>
            <td className="tabular py-2.5 text-right text-ink-2">{fmt(row.id, row.at_lows)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export const zoneLabel = (id: ZoneId | null | undefined) => ZONES.find((z) => z.id === id)?.label ?? "—";

// ---------------------------------------------------------------------------
// Dashboard chip — a link to the Market page, never next to an action
// ---------------------------------------------------------------------------

export function MarketChip() {
  const { market } = useMarket();
  const { user } = usePortfolio();
  if (!market?.available) return null;
  const v = market.valuation;
  // Under a 3-year horizon, no equity-timing context (plan section 2)
  const horizon = investmentHorizon(user);
  const showZone = Boolean(v?.available && v.zone && v.zone_label) && !(horizon !== null && horizon < 3);
  return (
    <Link
      href="/market"
      className="inline-flex h-10 items-center gap-2 rounded-full border border-line bg-surface px-3.5 text-[13px] font-medium text-ink-2 transition-colors hover:border-line-strong hover:text-ink"
    >
      {showZone ? (
        <>
          <span className="h-2.5 w-2.5 rounded-full ring-1 ring-black/10" style={{ background: zoneColor(v?.zone) }} />
          Nifty 50 valuations: {v?.zone_label?.toLowerCase()}
        </>
      ) : (
        <>
          <span className="h-2.5 w-2.5 rounded-full bg-[var(--series-2)]" />
          Nifty 50 at {formatIndex(market.index?.level, 0)}
        </>
      )}
    </Link>
  );
}
