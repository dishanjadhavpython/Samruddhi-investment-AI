import { Info, TrendingUp } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { TooltipBox } from "../components/charts";
import Layout from "../components/Layout";
import { Card, EmptyState, LinkButton, Money, PageHeader, Segmented, Skeleton } from "../components/ui";
import { formatINRCompact, formatNumberIN } from "../lib/currency";
import { formatSignedPct } from "../lib/format";
import { useApi } from "../lib/http";
import { usePortfolio } from "../lib/portfolio-context";

type RangeKey = "1m" | "3m" | "6m" | "1y" | "3y" | "all";

const RANGES: { value: RangeKey; label: string }[] = [
  { value: "1m", label: "1M" },
  { value: "3m", label: "3M" },
  { value: "6m", label: "6M" },
  { value: "1y", label: "1Y" },
  { value: "3y", label: "3Y" },
  { value: "all", label: "All" },
];

interface HoldingPerformance {
  symbol: string;
  quantity: number;
  avg_cost: number | null;
  cost_basis: number;
  market_value: number;
  unrealised: number | null;
  realised: number;
  dividends: number;
  abs_return_pct: number | null;
  xirr: number | null;
  since: string;
}

interface Performance {
  available: boolean;
  reason?: string;
  as_of: string;
  since: string;
  period_days: number;
  summary: {
    market_value: number;
    cost_basis: number;
    unrealised: number;
    realised: number;
    dividends: number;
    paid_in: number;
    paid_out: number;
    gain: number;
    abs_return_pct: number | null;
    xirr: number | null;
    xirr_min_days: number;
  };
  benchmark: { id: string; label: string; note: string; as_of: string; value: number; gain: number; abs_return_pct: number | null; xirr: number | null } | null;
  series: { fields: string[]; rows: [string, number | null, number | null, number | null][] };
  holdings: HoldingPerformance[];
  coverage: {
    holdings_total: number;
    holdings_measured: number;
    excluded: { symbol: string; reason: "unknown_cost" | "no_prices" }[];
    opening_estimates: string[];
    chart_from: string | null;
  };
  disclaimer: string;
}

const COLORS = { value: "var(--series-1)", benchmark: "var(--series-2)", invested: "var(--axis)" };

const fmtDate = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
const pctOrDash = (v: number | null | undefined, digits = 1) => (v == null ? "—" : formatSignedPct(v * 100, digits));
const listOf = (items: string[]) => (items.length <= 1 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`);

/** Month ticks for up to a year, year ticks beyond; at most about eight */
function timeAxis(min: number, max: number) {
  const DAY = 86_400_000;
  const days = (max - min) / DAY;
  const ticks: number[] = [];
  const start = new Date(min);
  if (days <= 400) {
    const step = Math.max(1, Math.ceil(days / 30 / 7));
    for (let d = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 1)); d.getTime() <= max; d.setUTCMonth(d.getUTCMonth() + step)) ticks.push(d.getTime());
  } else {
    for (let y = start.getUTCFullYear() + 1; Date.UTC(y, 0, 1) <= max; y += 1) ticks.push(Date.UTC(y, 0, 1));
  }
  return {
    dataKey: "ts",
    type: "number" as const,
    scale: "time" as const,
    domain: [min, max] as [number, number],
    ticks,
    tickFormatter: (ts: number) => {
      const d = new Date(ts);
      if (days > 400) return String(d.getUTCFullYear());
      const month = d.toLocaleDateString("en-IN", { month: "short", timeZone: "UTC" });
      return d.getUTCMonth() === 0 ? `${month} ’${String(d.getUTCFullYear()).slice(2)}` : month;
    },
  };
}

function PerformanceChart({ rows, benchmarkLabel }: { rows: Performance["series"]["rows"]; benchmarkLabel: string | null }) {
  const data = useMemo(() => rows.map(([d, value, invested, benchmark]) => ({ d, ts: Date.parse(d), value, invested, benchmark })), [rows]);
  if (data.length < 2) return <p className="text-[13px] text-muted">Not enough price history in this range for a chart yet.</p>;
  const axis = timeAxis(data[0].ts, data[data.length - 1].ts);
  return (
    <div className="h-[300px]">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis {...axis} tickLine={false} tick={{ fill: "var(--muted)", fontSize: 12 }} axisLine={{ stroke: "var(--axis)" }} />
          <YAxis tickLine={false} tick={{ fill: "var(--muted)", fontSize: 12 }} axisLine={false} width={56} domain={["auto", "auto"]} tickFormatter={(v: number) => formatINRCompact(v)} />
          <Tooltip
            cursor={{ stroke: "var(--line-strong)", strokeWidth: 1 }}
            content={({ active, payload }) => {
              const p = payload?.[0]?.payload as (typeof data)[number] | undefined;
              if (!active || !p) return null;
              return (
                <TooltipBox
                  title={fmtDate(p.d)}
                  rows={[
                    { color: COLORS.value, label: "Your holdings", value: p.value != null ? formatINRCompact(p.value) : "—" },
                    ...(benchmarkLabel ? [{ color: COLORS.benchmark, label: "Nifty 50, same cash flows", value: p.benchmark != null ? formatINRCompact(p.benchmark) : "—" }] : []),
                    { color: COLORS.invested, label: "Cost of what you hold", value: p.invested != null ? formatINRCompact(p.invested) : "—" },
                  ]}
                />
              );
            }}
          />
          <Line dataKey="invested" type="stepAfter" stroke={COLORS.invested} strokeWidth={1.5} strokeDasharray="4 4" dot={false} isAnimationActive={false} />
          {benchmarkLabel && <Line dataKey="benchmark" type="monotone" stroke={COLORS.benchmark} strokeWidth={2} dot={false} isAnimationActive={false} />}
          <Line dataKey="value" type="monotone" stroke={COLORS.value} strokeWidth={2} dot={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function Legend({ showBenchmark }: { showBenchmark: boolean }) {
  return (
    <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-[12.5px] text-muted">
      <span className="flex items-center gap-1.5">
        <span className="h-0.5 w-4 rounded" style={{ background: COLORS.value }} /> Your holdings
      </span>
      {showBenchmark && (
        <span className="flex items-center gap-1.5">
          <span className="h-0.5 w-4 rounded" style={{ background: COLORS.benchmark }} /> Nifty 50, same cash flows
        </span>
      )}
      <span className="flex items-center gap-1.5">
        <span className="h-0 w-4 border-t-[1.5px] border-dashed" style={{ borderColor: COLORS.invested }} /> Cost of what you hold
      </span>
    </div>
  );
}

function Figure({ label, value, hint }: { label: string; value: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div className="sm-card p-4">
      <p className="text-[12.5px] font-medium text-muted">{label}</p>
      <p className="mt-2 font-display text-[24px] font-semibold leading-none tracking-[-0.02em] text-ink">{value}</p>
      {hint && <div className="mt-2 text-[12.5px] leading-5 text-muted">{hint}</div>}
    </div>
  );
}

export default function PerformancePage() {
  const api = useApi();
  const { accounts, loading: portfolioLoading } = usePortfolio();
  const [range, setRange] = useState<RangeKey>("1y");
  const [data, setData] = useState<Performance | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    setLoading(true);
    api<Performance>(`/api/portfolio/performance?range=${range}`)
      .then((result) => {
        if (!live) return;
        setData(result);
        setError(null);
      })
      .catch((err) => live && setError(err instanceof Error ? err.message : "Couldn't load performance."))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [api, range]);

  const accountFor = (symbol: string) => accounts.find((a) => a.positions.some((p) => p.symbol === symbol))?.id;
  const s = data?.available ? data.summary : null;
  const b = data?.available ? data.benchmark : null;
  const underAYear = data?.available ? data.period_days < data.summary.xirr_min_days : false;

  return (
    <Layout title="Performance">
      <PageHeader
        title="Performance"
        subtitle="How your holdings have done, worked out from the transactions and opening balances you recorded."
        actions={data?.available ? <Segmented size="sm" ariaLabel="Chart range" value={range} onChange={setRange} items={RANGES} /> : undefined}
      />

      {error ? (
        <div className="sm-card mt-7">
          <EmptyState title="Performance didn't load" body={error} />
        </div>
      ) : (loading && !data) || portfolioLoading ? (
        <div className="mt-7 space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-[112px]" />
            ))}
          </div>
          <Skeleton className="h-[380px]" />
        </div>
      ) : !data?.available || !s ? (
        <div className="sm-card mt-7">
          <EmptyState
            icon={<TrendingUp className="h-5 w-5" strokeWidth={2} />}
            title={data?.reason === "nothing_measurable" ? "Nothing can be measured yet" : "No transactions yet"}
            body={
              data?.reason === "nothing_measurable"
                ? "Your holdings don't have prices or purchase costs the app can use. Add purchase prices on the account pages."
                : "Add holdings or record transactions on the Accounts page, and their returns appear here."
            }
            action={<LinkButton href="/accounts" variant="primary">Go to accounts</LinkButton>}
          />
        </div>
      ) : (
        <>
          <div className="mt-7 grid gap-4 *:min-w-0 sm:grid-cols-2 lg:grid-cols-4">
            <Figure label="Value now" value={<Money value={s.market_value} compact />} hint={<>Cost <Money value={s.cost_basis} compact /></>} />
            <Figure
              label="Total gain"
              value={
                <span className={s.gain >= 0 ? "text-good" : "text-bad"}>
                  {s.gain >= 0 ? "+" : "−"}
                  <Money value={Math.abs(s.gain)} compact />
                </span>
              }
              hint={`${pctOrDash(s.abs_return_pct)} on ${formatINRCompact(s.paid_in)} put in, including sales and dividends`}
            />
            <Figure
              label={underAYear ? "Absolute return" : "XIRR"}
              value={underAYear ? pctOrDash(s.abs_return_pct) : pctOrDash(s.xirr)}
              hint={
                underAYear
                  ? `Since ${fmtDate(data.since)}. XIRR is shown once money has been invested for a year, as mutual funds must show returns.`
                  : `A yearly rate since ${fmtDate(data.since)}, allowing for when each rupee went in`
              }
            />
            <Figure
              label="Nifty 50, same cash flows"
              value={b ? (underAYear ? pctOrDash(b.abs_return_pct) : pctOrDash(b.xirr)) : "—"}
              hint={b ? <>Would be worth <Money value={b.value} compact /> today. {b.note}</> : "No index history covers your first transaction yet."}
            />
          </div>

          <Card
            className="mt-4"
            title="Value over time"
            subtitle={data.coverage.chart_from ? `From ${fmtDate(data.coverage.chart_from)}, the first day with prices for every holding measured` : undefined}
          >
            <PerformanceChart rows={data.series.rows} benchmarkLabel={b ? b.label : null} />
            <Legend showBenchmark={Boolean(b)} />
          </Card>

          <section className="sm-card mt-4 overflow-hidden">
            <header className="px-5 pb-3 pt-4">
              <h2 className="text-[13.5px] font-semibold text-ink">By holding</h2>
              <p className="mt-0.5 text-[12.5px] text-muted">Across all accounts. Gains include sales and dividends.</p>
            </header>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-[13px]">
                <thead className="border-y border-line bg-sunken text-[12px] text-muted">
                  <tr>
                    <th className="px-5 py-2.5 text-left font-medium">Holding</th>
                    <th className="px-3 py-2.5 text-right font-medium">Units</th>
                    <th className="px-3 py-2.5 text-right font-medium">Average cost</th>
                    <th className="px-3 py-2.5 text-right font-medium">Cost</th>
                    <th className="px-3 py-2.5 text-right font-medium">Value</th>
                    <th className="px-3 py-2.5 text-right font-medium">Return</th>
                    <th className="px-3 py-2.5 text-right font-medium">XIRR</th>
                    <th className="px-5 py-2.5 text-right font-medium">Since</th>
                  </tr>
                </thead>
                <tbody>
                  {data.holdings.map((h) => (
                    <tr key={h.symbol} className="border-b border-line last:border-0">
                      <td className="px-5 py-3 font-semibold text-ink">{h.symbol}</td>
                      <td className="tabular px-3 py-3 text-right text-ink-2">{formatNumberIN(h.quantity, h.quantity % 1 ? 2 : 0)}</td>
                      <td className="tabular px-3 py-3 text-right text-ink-2">{h.avg_cost != null ? <Money value={h.avg_cost} decimals={2} /> : "—"}</td>
                      <td className="tabular px-3 py-3 text-right text-ink-2">
                        <Money value={h.cost_basis} />
                      </td>
                      <td className="tabular px-3 py-3 text-right text-ink">
                        <Money value={h.market_value} />
                      </td>
                      <td className={`tabular px-3 py-3 text-right ${(h.abs_return_pct ?? 0) >= 0 ? "text-good" : "text-bad"}`}>{pctOrDash(h.abs_return_pct)}</td>
                      <td className="tabular px-3 py-3 text-right text-ink-2" title={h.xirr == null ? "Shown after a year" : undefined}>
                        {pctOrDash(h.xirr)}
                      </td>
                      <td className="tabular whitespace-nowrap px-5 py-3 text-right text-muted">{fmtDate(h.since)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {(data.coverage.excluded.length > 0 || data.coverage.opening_estimates.length > 0) && (
            <div className="mt-4 space-y-2">
              {data.coverage.opening_estimates.length > 0 && (
                <p className="rounded-xl bg-accent-soft px-4 py-3 text-[13px] leading-6 text-ink">
                  {listOf(data.coverage.opening_estimates)} {data.coverage.opening_estimates.length === 1 ? "is" : "are"} measured from the day you entered{" "}
                  {data.coverage.opening_estimates.length === 1 ? "it" : "them"}, at that day&apos;s close. To measure from when you actually bought, edit the opening
                  balance on the{" "}
                  {data.coverage.opening_estimates.length === 1 && accountFor(data.coverage.opening_estimates[0]) ? (
                    <Link href={`/accounts/${accountFor(data.coverage.opening_estimates[0])}`} className="font-semibold underline decoration-accent decoration-2 underline-offset-4">
                      account page
                    </Link>
                  ) : (
                    <Link href="/accounts" className="font-semibold underline decoration-accent decoration-2 underline-offset-4">
                      account pages
                    </Link>
                  )}
                  .
                </p>
              )}
              {data.coverage.excluded.map((e) => (
                <p key={e.symbol} className="rounded-xl bg-sunken px-4 py-3 text-[13px] leading-6 text-ink-2">
                  <span className="font-semibold text-ink">{e.symbol}</span>{" "}
                  {e.reason === "unknown_cost"
                    ? "is left out: its opening balance has no purchase price. Add one on its account page."
                    : "is left out: the app has no price history for it yet."}
                </p>
              ))}
            </div>
          )}

          <p className="mt-6 flex gap-2 text-[12.5px] leading-5 text-muted">
            <Info className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2} />
            <span>
              {data.disclaimer} Cash balances are left out; this measures the holdings. Returns after charges you recorded; taxes are not deducted.
            </span>
          </p>
        </>
      )}
    </Layout>
  );
}
