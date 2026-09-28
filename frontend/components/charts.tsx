/**
 * Chart kit. Categorical colours come from the validated --series-* tokens in a
 * fixed order (never cycled past six — the tail folds into "Other"), every chart
 * carries a legend or labels with values, and text always wears ink tokens.
 */
import { motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, CircleAlert } from "lucide-react";
import { ReactNode, useState } from "react";
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Sankey,
  Tooltip,
  Treemap,
  XAxis,
  YAxis,
} from "recharts";
import type { LinkProps, NodeProps } from "recharts/types/chart/Sankey";
import type { TreemapNode } from "recharts/types/chart/Treemap";
import { formatINRCompact } from "../lib/currency";
import { formatPct, labelize } from "../lib/format";
import { Drift } from "../lib/portfolio";
import type { ProjectionPoint } from "../lib/projection";
import { Money } from "./ui";

// ---------------------------------------------------------------------------
// Colour roles
// ---------------------------------------------------------------------------

export const SERIES = [1, 2, 3, 4, 5, 6].map((n) => `var(--series-${n})`);
export const CASH_COLOR = "var(--series-cash)";
export const OTHER_COLOR = "var(--axis)";

// Labels set inside a fill pick ink or white by that fill's luminance
const INK_ON_SLOT = new Set([SERIES[0], CASH_COLOR, OTHER_COLOR]);
export const labelOn = (fill: string) => (INK_ON_SLOT.has(fill) ? "#17130a" : "#ffffff");

/** Asset classes keep one colour everywhere in the app */
const ASSET_CLASS_COLOR: Record<string, string> = {
  equity: SERIES[0],
  fixed_income: SERIES[1],
  commodities: SERIES[2],
  real_estate: SERIES[3],
  alternatives: SERIES[4],
  unclassified: SERIES[5],
  cash: CASH_COLOR,
  other: OTHER_COLOR,
};

export const assetClassColor = (key: string) => ASSET_CLASS_COLOR[key] ?? OTHER_COLOR;

export interface Slice {
  key: string;
  label: string;
  value: number;
  color: string;
}

/** Map [key, value] entries to slices in fixed slot order; "other"/"cash" keep their neutral roles. */
export function toSlices(entries: [string, number][], colorFor?: (key: string, index: number) => string): Slice[] {
  let slot = 0;
  return entries.map(([key, value]) => {
    const color = colorFor
      ? colorFor(key, slot)
      : key === "other"
        ? OTHER_COLOR
        : key === "cash"
          ? CASH_COLOR
          : SERIES[Math.min(slot, SERIES.length - 1)];
    if (key !== "other" && key !== "cash") slot += 1;
    return { key, label: labelize(key), value, color };
  });
}

// ---------------------------------------------------------------------------
// Tooltip shell
// ---------------------------------------------------------------------------

export function TooltipBox({ title, rows }: { title?: ReactNode; rows: { color?: string; label: ReactNode; value: ReactNode }[] }) {
  return (
    <div className="min-w-[160px] rounded-xl border border-line bg-surface px-3 py-2.5 text-[12.5px] shadow-[var(--shadow-pop)]">
      {title && <p className="mb-1.5 font-semibold text-ink">{title}</p>}
      <div className="space-y-1">
        {rows.map((row, i) => (
          <div key={i} className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-2 text-muted">
              {row.color && <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: row.color }} />}
              {row.label}
            </span>
            <span className="tabular font-semibold text-ink">{row.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Legend with values — the identity channel for every multi-series chart
// ---------------------------------------------------------------------------

interface LegendListProps {
  slices: Slice[];
  total: number;
  active?: string | null;
  onHover?: (key: string | null) => void;
  columns?: 1 | 2;
  money?: boolean;
}

export function LegendList({ slices, total, active, onHover, columns = 1, money = true }: LegendListProps) {
  return (
    <ul className={`@container grid gap-x-5 gap-y-1 ${columns === 2 ? "sm:grid-cols-2" : ""}`}>
      {slices.map((s) => (
        <li
          key={s.key}
          onMouseEnter={() => onHover?.(s.key)}
          onMouseLeave={() => onHover?.(null)}
          className={`flex items-center justify-between gap-3 rounded-lg px-1.5 py-1 text-[13px] transition-opacity ${
            active && active !== s.key ? "opacity-45" : ""
          }`}
        >
          <span className="flex min-w-0 items-center gap-2">
            <span className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: s.color }} />
            <span className="truncate text-ink-2">{s.label}</span>
          </span>
          <span className="flex shrink-0 items-baseline gap-2">
            {money && <Money value={s.value} compact className="tabular hidden text-[12.5px] text-muted @[250px]:inline" />}
            <span className="tabular w-11 text-right font-semibold text-ink">{formatPct(total > 0 ? (s.value / total) * 100 : 0, 0)}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Donut
// ---------------------------------------------------------------------------

interface DonutProps {
  slices: Slice[];
  size?: number;
  thickness?: number;
  center?: ReactNode;
  active?: string | null;
  onHover?: (key: string | null) => void;
}

export function Donut({ slices, size = 168, thickness = 18, center, active, onHover }: DonutProps) {
  const total = slices.reduce((s, x) => s + x.value, 0);
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <PieChart width={size} height={size}>
        <Pie
          data={slices}
          dataKey="value"
          nameKey="label"
          cx="50%"
          cy="50%"
          innerRadius={size / 2 - thickness}
          outerRadius={size / 2}
          startAngle={90}
          endAngle={-270}
          stroke="var(--surface)"
          strokeWidth={2}
          cornerRadius={4}
          animationDuration={700}
          onMouseEnter={(_, index) => onHover?.(slices[index]?.key ?? null)}
          onMouseLeave={() => onHover?.(null)}
        >
          {slices.map((s) => (
            <Cell key={s.key} fill={s.color} fillOpacity={active && active !== s.key ? 0.3 : 1} />
          ))}
        </Pie>
        <Tooltip
          content={({ active: isActive, payload }) =>
            isActive && payload?.[0] ? (
              <TooltipBox
                rows={[
                  {
                    color: (payload[0].payload as Slice).color,
                    label: (payload[0].payload as Slice).label,
                    value: (
                      <>
                        <Money value={Number(payload[0].value)} compact /> · {formatPct(total ? (Number(payload[0].value) / total) * 100 : 0, 0)}
                      </>
                    ),
                  },
                ]}
              />
            ) : null
          }
        />
      </PieChart>
      {center && <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">{center}</div>}
    </div>
  );
}

/** Donut + legend, with hover linked both ways */
export function DonutWithLegend({ slices, size = 160, center }: { slices: Slice[]; size?: number; center?: ReactNode }) {
  const [active, setActive] = useState<string | null>(null);
  const total = slices.reduce((s, x) => s + x.value, 0);
  return (
    <div className="@container w-full">
      <div className="flex flex-col items-center gap-5 @[420px]:flex-row">
        <Donut slices={slices} size={size} center={center} active={active} onHover={setActive} />
        <div className="w-full min-w-0 flex-1">
          <LegendList slices={slices} total={total} active={active} onHover={setActive} />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Composition bar — one stacked bar with 2px surface gaps
// ---------------------------------------------------------------------------

export function CompositionBar({ slices, height = 16, legend = true }: { slices: Slice[]; height?: number; legend?: boolean }) {
  const [active, setActive] = useState<string | null>(null);
  const total = slices.reduce((s, x) => s + x.value, 0);
  const hovered = slices.find((s) => s.key === active);

  return (
    <div>
      <div className="relative">
        <div className="flex w-full gap-[2px] overflow-hidden rounded-[6px]" style={{ height }}>
          {slices.map((s, i) => (
            <motion.button
              type="button"
              key={s.key}
              aria-label={`${s.label}: ${formatPct(total ? (s.value / total) * 100 : 0)}`}
              onMouseEnter={() => setActive(s.key)}
              onMouseLeave={() => setActive(null)}
              onFocus={() => setActive(s.key)}
              onBlur={() => setActive(null)}
              initial={{ flexGrow: 0 }}
              animate={{ flexGrow: s.value, opacity: active && active !== s.key ? 0.35 : 1 }}
              transition={{ duration: 0.8, delay: i * 0.05, ease: [0.16, 1, 0.3, 1] }}
              className="h-full min-w-[3px] basis-0 cursor-default first:rounded-l-[6px] last:rounded-r-[6px]"
              style={{ background: s.color }}
            />
          ))}
        </div>
        {hovered && (
          <div className="pointer-events-none absolute left-0 top-full z-10 mt-2">
            <TooltipBox
              rows={[
                {
                  color: hovered.color,
                  label: hovered.label,
                  value: (
                    <>
                      <Money value={hovered.value} compact /> · {formatPct(total ? (hovered.value / total) * 100 : 0, 1)}
                    </>
                  ),
                },
              ]}
            />
          </div>
        )}
      </div>
      {legend && (
        <div className="mt-4">
          <LegendList slices={slices} total={total} active={active} onHover={setActive} columns={2} />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Horizontal bars with values — sectors, regions, top holdings
// ---------------------------------------------------------------------------

interface HBarItem {
  key: string;
  label: ReactNode;
  value: number;
  color?: string;
  sublabel?: ReactNode;
}

export function HBarList({ items, total, color = SERIES[1], valueFormat = "pct" }: { items: HBarItem[]; total: number; color?: string; valueFormat?: "pct" | "money" }) {
  const max = Math.max(...items.map((i) => i.value), 1);
  return (
    <ul className="space-y-3">
      {items.map((item, i) => {
        const pct = total > 0 ? (item.value / total) * 100 : 0;
        return (
          <li key={item.key}>
            <div className="mb-1.5 flex items-baseline justify-between gap-3 text-[13px]">
              <span className="min-w-0 truncate text-ink-2">
                {item.label}
                {item.sublabel && <span className="ml-1.5 text-muted">{item.sublabel}</span>}
              </span>
              <span className="tabular shrink-0 font-semibold text-ink">
                {valueFormat === "money" ? <Money value={item.value} compact /> : formatPct(pct, pct < 10 ? 1 : 0)}
              </span>
            </div>
            <div className="h-2 w-full rounded-full bg-sunken">
              <motion.div
                className="h-full rounded-full"
                style={{ background: item.color ?? color }}
                initial={{ width: 0 }}
                animate={{ width: `${(item.value / max) * 100}%` }}
                transition={{ duration: 0.7, delay: i * 0.04, ease: [0.16, 1, 0.3, 1] }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Target drift — actual bar, target tick, status with icon + words
// ---------------------------------------------------------------------------

export function driftStatus(delta: number) {
  const abs = Math.abs(delta);
  if (abs <= 5) return { tone: "good" as const, label: "On target", Icon: CheckCircle2 };
  if (abs <= 10) return { tone: "warn" as const, label: "Drifting", Icon: CircleAlert };
  return { tone: "bad" as const, label: "Off target", Icon: AlertTriangle };
}

const toneText = { good: "text-good", warn: "text-warn", bad: "text-bad" };

export function DriftRows({ rows }: { rows: Drift[] }) {
  return (
    <ul className="space-y-4">
      {rows.map((row, i) => {
        const status = driftStatus(row.delta);
        return (
          <li key={row.key}>
            <div className="mb-2 flex items-center justify-between gap-3 text-[13px]">
              <span className="font-medium text-ink">{row.label}</span>
              <span className="flex items-center gap-2">
                <span className="tabular text-muted">
                  {formatPct(row.actual, 0)} <span className="text-[12px]">of {formatPct(row.target, 0)} target</span>
                </span>
                <span className={`inline-flex items-center gap-1 text-[12px] font-semibold ${toneText[status.tone]}`}>
                  <status.Icon className="h-3.5 w-3.5" strokeWidth={2.2} />
                  {row.delta > 0 ? "+" : row.delta < 0 ? "−" : ""}
                  {Math.abs(row.delta).toFixed(0)} pts
                </span>
              </span>
            </div>
            <div className="relative h-2.5 w-full rounded-full bg-sunken">
              <motion.div
                className="h-full rounded-full"
                style={{ background: assetClassColor(row.key === "india" ? "equity" : row.key === "international" ? "fixed_income" : row.key) }}
                initial={{ width: 0 }}
                animate={{ width: `${Math.min(100, row.actual)}%` }}
                transition={{ duration: 0.8, delay: i * 0.06, ease: [0.16, 1, 0.3, 1] }}
              />
              <span
                className="absolute -top-1 h-[18px] w-[3px] -translate-x-1/2 rounded-full bg-ink ring-2 ring-surface"
                style={{ left: `${Math.min(100, row.target)}%` }}
                title={`Target ${formatPct(row.target, 0)}`}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Treemap — holdings sized by value, coloured by asset class
// ---------------------------------------------------------------------------

export interface TreemapDatum {
  name: string;
  size: number;
  color: string;
  weight: number;
  label: string;
  [key: string]: unknown;
}

function TreemapCell(props: TreemapNode) {
  const { x, y, width, height, depth, name, color, weight } = props;
  if (depth !== 1 || width <= 0 || height <= 0) return <g />;
  const ink = labelOn(color as string);
  const showName = width > 56 && height > 30;
  const showWeight = width > 56 && height > 50;
  return (
    <g>
      <rect x={x + 1} y={y + 1} width={Math.max(0, width - 2)} height={Math.max(0, height - 2)} rx={8} fill={color as string} />
      {showName && (
        <text x={x + 10} y={y + 22} fill={ink} fontSize={13} fontWeight={650} style={{ fontFamily: "var(--font-sans)" }}>
          {name}
        </text>
      )}
      {showWeight && (
        <text x={x + 10} y={y + 40} fill={ink} fillOpacity={0.8} fontSize={12} style={{ fontFamily: "var(--font-sans)" }}>
          {formatPct(Number(weight), 1)}
        </text>
      )}
    </g>
  );
}

export function HoldingsTreemap({ data, height = 320 }: { data: TreemapDatum[]; height?: number }) {
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <Treemap data={data} dataKey="size" nameKey="name" content={TreemapCell} animationDuration={600} isAnimationActive>
          <Tooltip
            content={({ active, payload }) => {
              const d = payload?.[0]?.payload as TreemapDatum | undefined;
              return active && d ? (
                <TooltipBox
                  title={d.name}
                  rows={[
                    { color: d.color, label: d.label, value: <Money value={d.size} compact /> },
                    { label: "Weight", value: formatPct(d.weight, 1) },
                  ]}
                />
              ) : null;
            }}
          />
        </Treemap>
      </ResponsiveContainer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sankey — how each account's money splits into asset classes
// ---------------------------------------------------------------------------

export interface FlowNode {
  name: string;
  color: string;
}

export function MoneyFlow({ nodes, links, height = 300 }: { nodes: FlowNode[]; links: { source: number; target: number; value: number }[]; height?: number }) {
  const leftCount = new Set(links.map((l) => l.source)).size;

  const renderNode = (props: NodeProps) => {
    const { x, y, width, height: h, index, payload } = props;
    const node = nodes[index];
    const isLeft = index < leftCount;
    return (
      <g>
        <rect x={x} y={y} width={width} height={Math.max(2, h)} rx={3} fill={node?.color ?? OTHER_COLOR} />
        {h > 12 && (
          <text
            x={isLeft ? x + width + 8 : x - 8}
            y={y + h / 2}
            textAnchor={isLeft ? "start" : "end"}
            dominantBaseline="middle"
            fontSize={12.5}
            fontWeight={550}
            fill="var(--ink)"
            stroke="var(--surface)"
            strokeWidth={4}
            paintOrder="stroke"
            style={{ fontFamily: "var(--font-sans)" }}
          >
            {payload.name as string}
          </text>
        )}
      </g>
    );
  };

  const renderLink = (props: LinkProps) => {
    const { sourceX, targetX, sourceY, targetY, sourceControlX, targetControlX, linkWidth, payload } = props;
    const target = nodes[nodes.findIndex((n) => n.name === (payload.target as { name?: string }).name)];
    return (
      <path
        d={`M${sourceX},${sourceY} C${sourceControlX},${sourceY} ${targetControlX},${targetY} ${targetX},${targetY}`}
        fill="none"
        stroke={target?.color ?? OTHER_COLOR}
        strokeOpacity={0.28}
        strokeWidth={Math.max(1, linkWidth)}
        className="transition-[stroke-opacity] hover:[stroke-opacity:0.55]"
      />
    );
  };

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <Sankey
          data={{ nodes, links }}
          nodeWidth={10}
          nodePadding={18}
          iterations={48}
          margin={{ top: 8, bottom: 8, left: 4, right: 4 }}
          node={renderNode}
          link={renderLink}
        >
          <Tooltip
            content={({ active, payload }) => {
              const p = payload?.[0];
              if (!active || !p) return null;
              const inner = p.payload as { payload?: { source?: { name: string }; target?: { name: string }; value?: number; name?: string } };
              const link = inner?.payload;
              const title = link?.source && link?.target ? `${link.source.name} → ${link.target.name}` : link?.name ?? String(p.name ?? "");
              return <TooltipBox title={title} rows={[{ label: "Value", value: <Money value={Number(p.value)} compact /> }]} />;
            }}
          />
        </Sankey>
      </ResponsiveContainer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Monte Carlo fan — p10–p90 band with the median line
// ---------------------------------------------------------------------------

export function FanChart({ points, retireAt, height = 300 }: { points: ProjectionPoint[]; retireAt: number; height?: number }) {
  return (
    <div style={{ height }} className="sm-money-axis">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={points} margin={{ top: 12, right: 12, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="fan-band" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.35} />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity={0.08} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis
            dataKey="year"
            tickLine={false}
            axisLine={{ stroke: "var(--axis)" }}
            tick={{ fill: "var(--muted)", fontSize: 12 }}
            tickFormatter={(y: number) => (y === 0 ? "Now" : `${y}y`)}
            interval="preserveStartEnd"
            minTickGap={24}
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={64}
            tick={{ fill: "var(--muted)", fontSize: 12 }}
            tickFormatter={(v: number) => formatINRCompact(v)}
          />
          <Tooltip
            cursor={{ stroke: "var(--line-strong)", strokeWidth: 1 }}
            content={({ active, payload }) => {
              const d = payload?.[0]?.payload as ProjectionPoint | undefined;
              if (!active || !d) return null;
              return (
                <TooltipBox
                  title={d.year === 0 ? "Today" : `Year ${d.year} · ${d.phase === "saving" ? "saving" : "in retirement"}`}
                  rows={[
                    { label: "Good markets (p90)", value: <Money value={d.p90} compact /> },
                    { color: "var(--ink)", label: "Median", value: <Money value={d.p50} compact /> },
                    { label: "Poor markets (p10)", value: <Money value={d.p10} compact /> },
                  ]}
                />
              );
            }}
          />
          <Area type="monotone" dataKey="band" stroke="none" fill="url(#fan-band)" isAnimationActive animationDuration={700} />
          <Line type="monotone" dataKey="p50" stroke="var(--ink)" strokeWidth={2} dot={false} strokeLinecap="round" animationDuration={700} />
          <ReferenceLine
            x={retireAt}
            stroke="var(--ink-2)"
            strokeDasharray="4 4"
            label={{ value: "Retire", position: "insideTopRight", fill: "var(--ink-2)", fontSize: 12 }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Radial gauge — a 240° arc
// ---------------------------------------------------------------------------

interface GaugeProps {
  value: number;
  size?: number;
  label?: ReactNode;
  display?: ReactNode;
  color?: string;
}

export function Gauge({ value, size = 150, label, display, color = "var(--accent)" }: GaugeProps) {
  const pct = Math.max(0, Math.min(100, value)) / 100;
  const stroke = Math.max(8, Math.round(size * 0.08));
  const r = (size - stroke) / 2;
  const sweep = 240;
  const circumference = 2 * Math.PI * r;
  const arc = (sweep / 360) * circumference;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size * 0.84 }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="absolute left-0 top-0" style={{ transform: "rotate(150deg)" }} aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--line)" strokeWidth={stroke} strokeLinecap="round" strokeDasharray={`${arc} ${circumference}`} />
        {pct > 0 && (
          <motion.circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${arc} ${circumference}`}
            initial={{ strokeDashoffset: arc }}
            animate={{ strokeDashoffset: arc * (1 - pct) }}
            transition={{ duration: 1, ease: [0.16, 1, 0.3, 1] }}
          />
        )}
      </svg>
      <div className="absolute inset-x-0 flex flex-col items-center text-center" style={{ top: size * 0.3 }}>
        <span className="font-display font-semibold leading-none tracking-[-0.03em] text-ink" style={{ fontSize: Math.round(size * 0.2) }}>
          {display ?? formatPct(value, 0)}
        </span>
        {label && <span className="mt-1 text-[12px] text-muted">{label}</span>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Columns — for agent charts marked "bar" with few categories
// ---------------------------------------------------------------------------

export function Columns({ slices, height = 260 }: { slices: Slice[]; height?: number }) {
  return (
    <div style={{ height }} className="sm-money-axis">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={slices} margin={{ top: 16, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis
            dataKey="label"
            tickLine={false}
            axisLine={{ stroke: "var(--axis)" }}
            tick={{ fill: "var(--muted)", fontSize: 12 }}
            interval={0}
            tickFormatter={(v: string) => (v.length > 12 ? `${v.slice(0, 11)}…` : v)}
          />
          <YAxis tickLine={false} axisLine={false} width={60} tick={{ fill: "var(--muted)", fontSize: 12 }} tickFormatter={(v: number) => formatINRCompact(v)} />
          <Tooltip
            cursor={{ fill: "var(--sunken)" }}
            content={({ active, payload }) => {
              const s = payload?.[0]?.payload as Slice | undefined;
              return active && s ? <TooltipBox rows={[{ color: s.color, label: s.label, value: <Money value={s.value} compact /> }]} /> : null;
            }}
          />
          <Bar dataKey="value" maxBarSize={24} radius={[4, 4, 0, 0]} animationDuration={700}>
            {slices.map((s) => (
              <Cell key={s.key} fill={s.color} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Data table — the accessible twin of any chart
// ---------------------------------------------------------------------------

export function SliceTable({ slices, money = true }: { slices: Slice[]; money?: boolean }) {
  const total = slices.reduce((s, x) => s + x.value, 0);
  return (
    <div className="overflow-hidden rounded-xl border border-line">
      <table className="w-full text-[13px]">
        <thead className="bg-sunken text-left text-muted">
          <tr>
            <th className="px-3 py-2 font-medium">Category</th>
            <th className="px-3 py-2 text-right font-medium">{money ? "Value" : "Amount"}</th>
            <th className="px-3 py-2 text-right font-medium">Share</th>
          </tr>
        </thead>
        <tbody>
          {slices.map((s) => (
            <tr key={s.key} className="border-t border-line">
              <td className="px-3 py-2 text-ink-2">
                <span className="inline-flex items-center gap-2">
                  <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: s.color }} />
                  {s.label}
                </span>
              </td>
              <td className="px-3 py-2 text-right text-ink">{money ? <Money value={s.value} /> : s.value.toLocaleString("en-IN")}</td>
              <td className="px-3 py-2 text-right font-semibold text-ink">{formatPct(total ? (s.value / total) * 100 : 0, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
