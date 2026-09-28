import { Activity, BookOpen, CalendarRange, Gauge as GaugeIcon, History, Scale, Sparkles, TrendingDown } from "lucide-react";
import { useMemo, useState } from "react";
import {
  BandsLegend,
  CycleTable,
  EntryYearGrid,
  IntraYearChart,
  IntraYearLegend,
  intraYearSummary,
  UnderwaterChart,
  ValuationBandsChart,
  ValuationDial,
  VixChart,
  withinRange,
  ZoneHistoryTable,
} from "./market";
import { ReportProblemButton } from "./ReportProblem";
import { WarpBackdrop } from "./Shader";
import { Card, PageHeader, Segmented, Skeleton } from "./ui";
import {
  ChartRange,
  describeSession,
  formatIndex,
  formatMarketDate,
  isClosingPrice,
  istClock,
  MarketContextData,
  MarketNote,
  MarketSnapshot,
  PerspectiveChart,
  pct,
  rowsOf,
  TurbulenceChart,
  TurbulencePoint,
  ValuationChart,
  ValuationPoint,
} from "../lib/market";

const RANGES: { value: ChartRange; label: string }[] = [
  { value: "1y", label: "1Y" },
  { value: "5y", label: "5Y" },
  { value: "10y", label: "10Y" },
  { value: "max", label: "Max" },
];

function Sparkline({ values, baseline, width = 220, height = 48 }: { values: number[]; baseline?: number | null; width?: number; height?: number }) {
  if (values.length < 2) return null;
  const all = baseline != null ? [...values, baseline] : values;
  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = max - min || 1;
  const y = (v: number) => height - ((v - min) / span) * (height - 4) - 2;
  const path = values.map((v, i) => `${i ? "L" : "M"} ${(i / (values.length - 1)) * width} ${y(v)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} preserveAspectRatio="none" aria-hidden="true">
      {baseline != null && (
        <line x1={0} x2={width} y1={y(baseline)} y2={y(baseline)} stroke="rgba(255,255,255,0.35)" strokeWidth={1} strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />
      )}
      <path d={path} fill="none" stroke="rgba(255,255,255,0.8)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/** Today's 5-minute line runs 09:15 to 15:30 IST, so a morning line fills only part of the width */
const SESSION_MINUTES: [number, number] = [9 * 60 + 20, 15 * 60 + 30];

function TodayLine({ points, baseline }: { points: [number, number][]; baseline?: number | null }) {
  const [start, end] = SESSION_MINUTES;
  const done = Math.min(1, Math.max(0, (points[points.length - 1][0] - start) / (end - start)));
  return (
    <div style={{ width: `${Math.max(12, done * 100)}%` }}>
      <Sparkline values={points.map((p) => p[1])} baseline={baseline} />
    </div>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="sm-card p-4">
      <p className="text-[12.5px] text-muted">{label}</p>
      <p className="tabular mt-1.5 font-display text-[26px] font-semibold leading-none tracking-[-0.03em] text-ink">{value}</p>
      <p className="mt-2 text-[12.5px] leading-5 text-muted">{note}</p>
    </div>
  );
}

export interface MarketViewProps {
  market: MarketContextData;
  valuation: ValuationChart | null;
  turbulence: TurbulenceChart | null;
  perspective: PerspectiveChart | null;
  /** The user's retirement is under 3 years away */
  shortHorizon: boolean;
  /** Delayed intraday prices (GET /api/market/snapshot) */
  snapshot?: MarketSnapshot | null;
}

/** The Market page body: presentation only, so it renders from fixtures too. */
/** Today's note: one AI-written description of the figures above, shared by every user */
export function MarketNoteCard({ note }: { note?: MarketNote | null }) {
  if (!note || note.status !== "ok" || !note.headline) return null;
  return (
    <Card
      className="mt-4"
      title="Today's note"
      icon={<Sparkles className="h-4 w-4 text-muted" strokeWidth={2} />}
      subtitle={`Written by an AI model from the figures on this page${note.as_of ? `, as of ${formatMarketDate(note.as_of)}` : ""}, and checked before it was shown.`}
      action={<ReportProblemButton surface="market_narrative" />}
    >
      <p className="max-w-[70ch] font-display text-[18px] font-semibold leading-7 tracking-[-0.01em] text-ink">{note.headline}</p>
      {note.what_the_data_shows?.length ? (
        <p className="mt-2 max-w-[70ch] text-[14px] leading-6 text-ink-2">{note.what_the_data_shows.join(" ")}</p>
      ) : null}
      {note.what_it_does_not_mean && (
        <p className="mt-3 max-w-[70ch] text-[13px] leading-6 text-muted">
          <span className="font-semibold text-ink-2">What this does not mean.</span> {note.what_it_does_not_mean}
        </p>
      )}
    </Card>
  );
}

export default function MarketView({ market, valuation, turbulence, perspective, shortHorizon, snapshot }: MarketViewProps) {
  const [metric, setMetric] = useState<"pe" | "pb">("pb");
  const [bandsRange, setBandsRange] = useState<ChartRange>("max");
  const [turbRange, setTurbRange] = useState<ChartRange>("5y");

  const valuationPoints = useMemo(() => rowsOf<ValuationPoint>(valuation), [valuation]);
  const turbulencePoints = useMemo(() => rowsOf<TurbulencePoint>(turbulence), [turbulence]);
  const vixPoints = useMemo(() => rowsOf<{ d: string; v: number | null }>(turbulence?.vix), [turbulence]);
  const lastYear = useMemo(() => withinRange(turbulencePoints, "1y").map((p) => p.level ?? 0), [turbulencePoints]);
  const summary = useMemo(() => intraYearSummary(perspective?.intra_year ?? []), [perspective]);

  const index = market.index;
  // The delayed level replaces the stored close once it is from the same day or later
  const live = snapshot?.indices?.NIFTY50;
  const useLive = Boolean(live && (!index?.as_of || live.as_of.slice(0, 10) >= index.as_of.slice(0, 10)));
  const level = useLive ? live!.price : index?.level;
  const change = useLive ? live!.change ?? null : index?.change ?? null;
  const changePct = useLive ? live!.change_pct ?? null : index?.change_pct ?? null;
  const today = snapshot?.intraday?.NIFTY50;
  const todayPoints = useLive && today && today.date === live!.as_of.slice(0, 10) && today.points.length > 1 ? today.points : null;
  const v = market.valuation;
  const t = market.turbulence;
  const history = v?.history ?? null;
  const hasValuation = Boolean(v?.available);
  const fiveYearEpisodes = history?.zones.reduce((sum, z) => sum + z.h5.episodes, 0) ?? 0;

  return (
    <>
      <PageHeader
        title="Market"
        subtitle="Where the Nifty 50 stands against its own history. This page describes the index, not your holdings, and says nothing about what comes next."
      />

      {/* Hero: index level and the valuation dial — the one shader surface on this page */}
      <section className="relative mt-7 overflow-hidden rounded-[18px] text-white">
        <WarpBackdrop speed={0.35} />
        <div className="absolute inset-0 bg-gradient-to-r from-black/90 via-black/70 to-black/45" aria-hidden="true" />
        <div className="relative grid gap-8 p-6 *:min-w-0 sm:p-8 lg:grid-cols-[1fr_minmax(0,380px)] lg:items-center">
          <div className="min-w-0">
            <p className="text-[13px] font-medium text-white/70">Nifty 50</p>
            <p className="tabular mt-3 font-display text-[44px] font-semibold leading-none tracking-[-0.035em] sm:text-[56px]">{formatIndex(level)}</p>
            {change !== null && (
              <p className="tabular mt-2 text-[15px] font-medium text-white/85">
                {change > 0 ? "+" : change < 0 ? "−" : ""}
                {formatIndex(Math.abs(change))} ({pct(changePct, 2, true)}) on the day
              </p>
            )}
            <div className={`mt-5 grid max-w-[460px] gap-5 opacity-90 ${todayPoints ? "grid-cols-2" : "grid-cols-1"}`}>
              {todayPoints && (
                <div className="min-w-0">
                  <p className="mb-1.5 text-[11.5px] text-white/55">
                    {today!.date === new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" }) ? "Today" : formatMarketDate(today!.date)}, every 5 minutes
                  </p>
                  <TodayLine points={todayPoints} baseline={live?.prev_close} />
                </div>
              )}
              {lastYear.length > 1 && (
                <div className="min-w-0">
                  {todayPoints && <p className="mb-1.5 text-[11.5px] text-white/55">Past year, daily</p>}
                  <Sparkline values={lastYear} />
                </div>
              )}
            </div>
            <p className="mt-4 max-w-[56ch] text-[13px] leading-6 text-white/65">
              {useLive && live
                ? isClosingPrice(live.as_of)
                  ? `Close on ${formatMarketDate(live.as_of, true)}, from ${snapshot?.source_label ?? "Yahoo Finance"}. `
                  : `As of ${istClock(live.as_of)} IST, ${live.delay_minutes} min delayed, from ${snapshot?.source_label ?? "Yahoo Finance"}. `
                : `Close on ${formatMarketDate(index?.as_of, true)}, end of day, from ${index?.source ?? "Yahoo Finance"}. `}
              {describeSession(snapshot?.session ?? market.session)}.
              {snapshot?.updates.active && snapshot.updates.until ? ` New prices every 5 minutes until ${istClock(new Date(Date.parse(snapshot.updates.until) - 5 * 60_000).toISOString())} IST.` : ""}
              {todayPoints && live?.prev_close ? " The dashed line is the previous close." : ""}
            </p>
          </div>

          <div className="flex flex-col items-center text-center lg:items-stretch">
            <p className="text-[13px] font-medium text-white/70 lg:text-center">Valuation temperature</p>
            <div className="relative mt-3 w-full max-w-[340px] self-center">
              <ValuationDial score={hasValuation ? v?.score : null} zone={v?.zone} />
              <div className="absolute inset-x-0 bottom-[6%] flex flex-col items-center">
                {hasValuation ? (
                  <>
                    <span className="tabular font-display text-[44px] font-semibold leading-none tracking-[-0.03em]">{Math.round(v?.score ?? 0)}</span>
                    <span className="mt-1 text-[12px] text-white/60">of 100</span>
                  </>
                ) : (
                  <span className="text-[13px] text-white/60">Not loaded yet</span>
                )}
              </div>
            </div>
            {hasValuation ? (
              <>
                <p className="mt-4 font-display text-[22px] font-semibold tracking-[-0.02em] lg:text-center">{v?.zone_label}</p>
                <p className="mx-auto mt-1.5 max-w-[40ch] text-[12.5px] leading-5 text-white/65">
                  Nifty 50 P/E and P/B against all history since {formatMarketDate(v?.history_from)}: 0 is the cheapest so far, 100 the priciest. As of {formatMarketDate(v?.as_of)}.
                  {v?.stale ? " This reading is out of date." : ""}
                </p>
              </>
            ) : (
              <p className="mx-auto mt-4 max-w-[40ch] text-[12.5px] leading-5 text-white/65">
                The dial needs the Nifty 50 P/E, P/B and total-return history from NSE Indices, which hasn&apos;t been loaded. Turbulence and history below work without it.
              </p>
            )}
          </div>
        </div>
      </section>

      <MarketNoteCard note={market.narrative} />

      {/* Valuation: what followed from each zone */}
      {hasValuation && history ? (
        <div className="mt-4 grid gap-4 *:min-w-0 lg:grid-cols-12">
          <Card
            className="lg:col-span-8"
            title="What followed from each zone"
            icon={<History className="h-4 w-4 text-muted" strokeWidth={2} />}
            subtitle={`Nifty 50 total returns after every day in each zone, ${formatMarketDate(history.data_from)} to ${formatMarketDate(history.data_to)}. Multi-year figures are a year, compounded.`}
          >
            {shortHorizon && (
              <p className="mb-4 rounded-xl bg-sunken px-3.5 py-2.5 text-[12.5px] leading-5 text-ink-2">
                These figures describe 1 to 5 year periods. Your retirement is under 3 years away, so they say little about your own plan.
              </p>
            )}
            <ZoneHistoryTable zones={history.zones} current={v?.zone} />
            <p className="mt-4 text-[12.5px] leading-5 text-muted">
              Past distributions, not a forecast. Daily periods overlap, so the independent evidence is thin: {fiveYearEpisodes} separate five-year periods across all zones.
            </p>
          </Card>
          <Card className="lg:col-span-4" title="What goes into the dial" icon={<Scale className="h-4 w-4 text-muted" strokeWidth={2} />}>
            <ul className="space-y-4">
              {(v?.components ?? []).map((c) => (
                <li key={c.id}>
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-[13px] text-ink-2">{c.label}</span>
                    <span className="tabular font-display text-[20px] font-semibold tracking-[-0.02em] text-ink">{c.value?.toFixed(c.id === "pe" ? 1 : 2) ?? "—"}</span>
                  </div>
                  <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-line">
                    <div className="h-full rounded-full bg-accent" style={{ width: `${Math.round((c.pct ?? 0) * 100)}%` }} />
                  </div>
                  <p className="mt-1.5 text-[12px] text-muted">
                    Higher than {pct(c.pct, 0)} of days since {formatMarketDate(v?.history_from)}
                  </p>
                </li>
              ))}
              {v?.dividend_yield && (
                <li className="border-t border-line pt-3 text-[12.5px] text-muted">
                  Dividend yield {v.dividend_yield.value.toFixed(2)}%, shown for reference and not part of the dial.
                </li>
              )}
            </ul>
          </Card>

          <Card
            className="lg:col-span-12"
            title="Valuation against its own past"
            icon={<GaugeIcon className="h-4 w-4 text-muted" strokeWidth={2} />}
            subtitle="Bands use only the history available on each date, the same way the dial does."
            action={
              <>
                <Segmented ariaLabel="Measure" size="sm" value={metric} onChange={setMetric} items={[{ value: "pb", label: "P/B" }, { value: "pe", label: "P/E" }]} />
                <Segmented ariaLabel="Range" size="sm" value={bandsRange} onChange={setBandsRange} items={RANGES} />
              </>
            }
          >
            {valuationPoints.length ? (
              <>
                <ValuationBandsChart points={withinRange(valuationPoints, bandsRange)} metric={metric} breaks={valuation?.breaks ?? []} range={bandsRange} />
                <div className="mt-3">
                  <BandsLegend metric={metric} />
                </div>
              </>
            ) : (
              <Skeleton className="h-[300px]" />
            )}
          </Card>
        </div>
      ) : null}

      {/* Turbulence: describes now, predicts nothing */}
      <div className="mt-10 flex flex-col gap-1">
        <h2 className="flex items-center gap-2 font-display text-[20px] font-semibold tracking-[-0.02em] text-ink">
          <Activity className="h-4.5 w-4.5 text-muted" strokeWidth={2} />
          Turbulence
        </h2>
        <p className="max-w-[70ch] text-[13.5px] text-muted">Describes risk right now. Historically it has not predicted the next year&apos;s return.</p>
      </div>

      {t && (
        <div className="mt-4 grid gap-4 *:min-w-0 sm:grid-cols-3">
          <Stat label="Below the all-time high" value={pct(t.drawdown_pct)} note={`High of ${formatIndex(t.all_time_high)} on ${formatMarketDate(t.all_time_high_date)}`} />
          <Stat
            label="Against the 200-day average"
            value={pct(t.dma200_distance_pct, 1, true)}
            note={t.dma200 ? `${t.above_200dma ? "Above" : "Below"} the average of ${formatIndex(t.dma200)}` : "Needs 200 days of closes"}
          />
          <Stat
            label="India VIX"
            value={t.vix ? t.vix.value.toFixed(2) : "—"}
            note={t.vix ? `${t.vix.label} band, as of ${formatMarketDate(t.vix.as_of)}` : "Not available"}
          />
        </div>
      )}

      <div className="mt-4 grid gap-4 *:min-w-0 lg:grid-cols-12">
        <Card
          className="lg:col-span-7"
          title="Fall from the high"
          icon={<TrendingDown className="h-4 w-4 text-muted" strokeWidth={2} />}
          subtitle="How far the Nifty 50 closed below its highest close to date"
          action={<Segmented ariaLabel="Range" size="sm" value={turbRange} onChange={setTurbRange} items={RANGES} />}
        >
          {turbulencePoints.length ? <UnderwaterChart points={withinRange(turbulencePoints, turbRange)} range={turbRange} /> : <Skeleton className="h-[240px]" />}
        </Card>
        <Card className="lg:col-span-5" title="India VIX" icon={<Activity className="h-4 w-4 text-muted" strokeWidth={2} />} subtitle="Expected 30-day swing, from Nifty option prices. Uses the same range as the fall-from-high chart.">
          {vixPoints.length ? <VixChart points={withinRange(vixPoints, turbRange)} range={turbRange} /> : <Skeleton className="h-[240px]" />}
        </Card>
      </div>

      {/* Perspective */}
      {perspective?.available && (
        <>
          <div className="mt-10 flex flex-col gap-1">
            <h2 className="flex items-center gap-2 font-display text-[20px] font-semibold tracking-[-0.02em] text-ink">
              <CalendarRange className="h-4.5 w-4.5 text-muted" strokeWidth={2} />
              Perspective
            </h2>
            <p className="max-w-[70ch] text-[13.5px] text-muted">
              From the {perspective.series.toLowerCase().replace("nifty", "Nifty")}
              {perspective.series.includes("price") ? ", which leaves out dividends" : ""}.
            </p>
          </div>
          <div className="mt-4 grid gap-4 *:min-w-0 lg:grid-cols-12 lg:items-start">
            <Card
              className="lg:col-span-12"
              title="Falls within each year"
              subtitle={
                summary
                  ? `${summary.first} to ${summary.last}: the median fall within a year was ${pct(summary.medianFall)}. In ${summary.deepYears} of ${summary.years} years the index fell more than 10% at some point, and ${summary.deepEndedUp} of those years still ended higher.`
                  : undefined
              }
            >
              <IntraYearChart rows={perspective.intra_year} />
              <div className="mt-3">
                <IntraYearLegend />
              </div>
            </Card>
            <Card
              className={perspective.cycle ? "lg:col-span-7" : "lg:col-span-12"}
              title="Returns by the year you started"
              subtitle="A year, compounded, from the end of the year before the start year. Blue cells rose, red cells fell."
            >
              <EntryYearGrid cells={perspective.entry_year} />
            </Card>
            {perspective.cycle && (
              <Card
                className="lg:col-span-5"
                title="Today against history"
                subtitle={`Big lows: ${perspective.cycle.lows.map((l) => formatMarketDate(l.date)).join(", ")}.`}
              >
                <CycleTable cycle={perspective.cycle} />
              </Card>
            )}
          </div>
        </>
      )}

      {/* Methodology and limits */}
      <Card className="mt-10" title="How this page works, and its limits" icon={<BookOpen className="h-4 w-4 text-muted" strokeWidth={2} />}>
        <div className="grid gap-6 text-[13px] leading-6 text-ink-2 lg:grid-cols-2">
          <div className="space-y-3">
            <p>
              <span className="font-semibold text-ink">The dial.</span> Each day, the Nifty 50&apos;s P/E and P/B are ranked against every earlier day since 1999, with at least three
              years of history. The dial is the average of the two ranks. Zone labels change only when the score moves 3 points past a boundary, so they don&apos;t flicker.
              Method {market.method_version}.
            </p>
            <p>
              <span className="font-semibold text-ink">Basis changes.</span> NSE has changed how it calculates these ratios without restating history. Older values are scaled
              onto today&apos;s basis at each change:
            </p>
            <ul className="list-disc space-y-1 pl-5 text-[12.5px] text-muted">
              {(market.breaks ?? []).map((b) => (
                <li key={`${b.series_id}-${b.date}`}>
                  {b.series_id.replace("NIFTY50_", "")} on {formatMarketDate(b.date)}: {b.note}
                </li>
              ))}
            </ul>
          </div>
          <div className="space-y-3">
            <p>
              <span className="font-semibold text-ink">Limits.</span> Since 1999 there have been only about five separate five-year periods, and the cheapest readings rest
              on roughly three crises (2003, 2008–09 and 2020). The link between valuation and later returns has varied from period to period. These years covered a fast-growing
              economy: that no five-year period has ended below where it started is history, not a promise.
            </p>
            <p>
              <span className="font-semibold text-ink">Sources.</span> {market.disclaimer} Figures were last computed{" "}
              {market.computed_at ? formatMarketDate(market.computed_at.slice(0, 10)) : "—"}.
            </p>
          </div>
        </div>
      </Card>
    </>
  );
}
