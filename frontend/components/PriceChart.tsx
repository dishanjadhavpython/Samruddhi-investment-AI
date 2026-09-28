import type { IChartApi, ISeriesApi, MouseEventParams, SeriesType, Time } from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import { useApi } from "../lib/http";
import { formatMarketDate } from "../lib/market";
import { Segmented, Skeleton } from "./ui";

// Daily price chart for one holding (plan section 9, Phase 5): candles for
// exchange prices, a line for NAV funds. lightweight-charts is Apache-2.0 and
// asks for visible TradingView attribution, which its logo on the chart gives.

export type BarRange = "6m" | "1y" | "3y" | "max";

export interface BarsResponse {
  symbol: string;
  range: BarRange;
  kind: "ohlc" | "close";
  fields: string[];
  rows: (string | number | null)[][];
  as_of: string | null;
  source: string;
}

interface Bar {
  time: string;
  open?: number;
  high?: number;
  low?: number;
  close: number;
}

const RANGES: { value: BarRange; label: string }[] = [
  { value: "6m", label: "6M" },
  { value: "1y", label: "1Y" },
  { value: "3y", label: "3Y" },
  { value: "max", label: "Max" },
];

function palette() {
  const css = getComputedStyle(document.documentElement);
  const token = (name: string) => css.getPropertyValue(name).trim();
  return {
    ink: token("--ink-2"),
    muted: token("--muted"),
    grid: token("--grid"),
    axis: token("--axis"),
    good: token("--good"),
    bad: token("--bad"),
    line: token("--series-1"),
  };
}

function chartOptions() {
  const c = palette();
  return {
    layout: {
      background: { color: "transparent" },
      textColor: c.muted,
      fontFamily: getComputedStyle(document.body).fontFamily,
      fontSize: 11,
      attributionLogo: true,
    },
    grid: { vertLines: { visible: false }, horzLines: { color: c.grid } },
    rightPriceScale: { borderColor: c.axis },
    timeScale: { borderColor: c.axis },
  };
}

// Up candles are hollow and down candles filled, so direction doesn't rely on colour alone
function seriesOptions(kind: BarsResponse["kind"]) {
  const c = palette();
  return kind === "ohlc"
    ? { upColor: "rgba(0,0,0,0)", borderUpColor: c.good, wickUpColor: c.good, downColor: c.bad, borderDownColor: c.bad, wickDownColor: c.bad }
    : { color: c.line, lineWidth: 2 as const };
}

const inr = (value: number | undefined) =>
  value === undefined ? "—" : `₹${value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function Readout({ bar, previous, kind }: { bar: Bar | null; previous: Bar | null; kind: BarsResponse["kind"] }) {
  if (!bar) return null;
  const change = previous ? bar.close / previous.close - 1 : null;
  const cells: [string, string][] =
    kind === "ohlc"
      ? [["Open", inr(bar.open)], ["High", inr(bar.high)], ["Low", inr(bar.low)], ["Close", inr(bar.close)]]
      : [["NAV", inr(bar.close)]];
  return (
    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-[12.5px]">
      <span className="font-medium text-ink">{formatMarketDate(bar.time, true)}</span>
      {cells.map(([label, value]) => (
        <span key={label} className="text-muted">
          {label} <span className="tabular text-ink">{value}</span>
        </span>
      ))}
      {change !== null && (
        <span className="text-muted">
          Change{" "}
          <span className={`tabular ${change > 0 ? "text-good" : change < 0 ? "text-bad" : "text-ink"}`}>
            {change > 0 ? "+" : change < 0 ? "−" : ""}
            {Math.abs(change * 100).toFixed(2)}%
          </span>
        </span>
      )}
    </div>
  );
}

/** Loads a holding's daily bars and draws them. */
export function PriceChart({ symbol }: { symbol: string }) {
  const api = useApi();
  const [range, setRange] = useState<BarRange>("1y");
  const [data, setData] = useState<BarsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api<BarsResponse>(`/api/instruments/${encodeURIComponent(symbol)}/bars?range=${range}`)
      .then((response) => !cancelled && setData(response))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "Could not load prices."));
    return () => {
      cancelled = true;
    };
  }, [api, symbol, range]);

  return <PriceChartView symbol={symbol} data={data} error={error} range={range} onRangeChange={setRange} />;
}

interface PriceChartViewProps {
  symbol: string;
  data: BarsResponse | null;
  error: string | null;
  range: BarRange;
  onRangeChange: (range: BarRange) => void;
}

/** The chart itself: presentation only, so it renders from fixtures too. */
export function PriceChartView({ symbol, data, error, range, onRangeChange }: PriceChartViewProps) {
  const [hovered, setHovered] = useState<number | null>(null);
  const container = useRef<HTMLDivElement>(null);

  const bars = useMemo<Bar[]>(() => {
    if (!data) return [];
    return data.rows.map((row) =>
      data.kind === "ohlc"
        ? { time: String(row[0]), open: Number(row[1]), high: Number(row[2]), low: Number(row[3]), close: Number(row[4]) }
        : { time: String(row[0]), close: Number(row[1]) },
    );
  }, [data]);

  // The chart library touches window, so it loads only in the browser, when a chart is shown
  useEffect(() => {
    const element = container.current;
    if (!element || !data || bars.length === 0) return;
    let chart: IChartApi | null = null;
    let series: ISeriesApi<SeriesType> | null = null;
    let observer: MutationObserver | null = null;
    let disposed = false;
    const index = new Map(bars.map((b, i) => [b.time, i]));

    import("lightweight-charts").then(({ createChart, CandlestickSeries, LineSeries }) => {
      if (disposed) return;
      chart = createChart(element, {
        ...chartOptions(),
        autoSize: true,
        localization: { locale: "en-IN", priceFormatter: (p: number) => inr(p) },
        handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
        handleScale: { mouseWheel: false, pinch: true, axisPressedMouseMove: false, axisDoubleClickReset: true },
      });
      series =
        data.kind === "ohlc"
          ? chart.addSeries(CandlestickSeries, seriesOptions("ohlc"))
          : chart.addSeries(LineSeries, seriesOptions("close"));
      series.setData(
        data.kind === "ohlc"
          ? bars.map((b) => ({ time: b.time as Time, open: b.open!, high: b.high!, low: b.low!, close: b.close }))
          : bars.map((b) => ({ time: b.time as Time, value: b.close })),
      );
      chart.timeScale().fitContent();
      chart.subscribeCrosshairMove((param: MouseEventParams) => {
        setHovered(param.time !== undefined ? index.get(String(param.time)) ?? null : null);
      });
      // Canvas colours don't follow CSS variables, so re-read them when the theme flips
      observer = new MutationObserver(() => {
        chart?.applyOptions(chartOptions());
        series?.applyOptions(seriesOptions(data.kind));
      });
      observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    });

    return () => {
      disposed = true;
      observer?.disconnect();
      chart?.remove();
      setHovered(null);
    };
  }, [data, bars]);

  const shown = hovered ?? bars.length - 1;
  const lastTen = bars.slice(-10).reverse();

  return (
    <div className="min-w-0">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <p className="text-[12.5px] font-medium text-muted">{data?.kind === "close" ? "Daily NAV" : "Daily price"}</p>
        <Segmented value={range} onChange={onRangeChange} items={RANGES} size="sm" ariaLabel="Chart range" layoutId={`bars-${symbol}`} />
      </div>
      {error ? (
        <p className="text-[13px] text-muted">{error}</p>
      ) : !data ? (
        <Skeleton className="h-[260px]" />
      ) : bars.length === 0 ? (
        <p className="text-[13px] text-muted">No daily prices for {symbol} yet.</p>
      ) : (
        <>
          <Readout bar={bars[shown] ?? null} previous={bars[shown - 1] ?? null} kind={data.kind} />
          <div
            ref={container}
            className="mt-2 h-[260px] w-full"
            role="img"
            aria-label={`${symbol} daily ${data.kind === "ohlc" ? "prices" : "NAVs"} from ${formatMarketDate(bars[0].time)} to ${formatMarketDate(bars[bars.length - 1].time)}; last ${inr(bars[bars.length - 1].close)}.`}
          />
          <p className="mt-2 text-[12px] leading-5 text-muted">
            {data.kind === "ohlc"
              ? "One candle per trading day. Hollow candles closed above their open, filled ones below. "
              : "Mutual funds have one price a day, the NAV, so this is a line rather than candles. "}
            From {data.source}, to {formatMarketDate(data.as_of)}. Chart by{" "}
            <a href="https://www.tradingview.com/lightweight-charts/" target="_blank" rel="noreferrer" className="underline underline-offset-2">
              TradingView Lightweight Charts
            </a>
            .
          </p>
          <details className="mt-2 text-[12.5px]">
            <summary className="cursor-pointer text-muted hover:text-ink">Last 10 sessions as a table</summary>
            <table className="mt-2 w-full max-w-[520px] text-left">
              <thead className="text-muted">
                <tr>
                  <th className="py-1 pr-3 font-medium">Date</th>
                  {data.kind === "ohlc" && (
                    <>
                      <th className="py-1 pr-3 text-right font-medium">Open</th>
                      <th className="py-1 pr-3 text-right font-medium">High</th>
                      <th className="py-1 pr-3 text-right font-medium">Low</th>
                    </>
                  )}
                  <th className="py-1 text-right font-medium">{data.kind === "ohlc" ? "Close" : "NAV"}</th>
                </tr>
              </thead>
              <tbody className="tabular text-ink-2">
                {lastTen.map((b) => (
                  <tr key={b.time} className="border-t border-line">
                    <td className="py-1 pr-3">{formatMarketDate(b.time)}</td>
                    {data.kind === "ohlc" && (
                      <>
                        <td className="py-1 pr-3 text-right">{inr(b.open)}</td>
                        <td className="py-1 pr-3 text-right">{inr(b.high)}</td>
                        <td className="py-1 pr-3 text-right">{inr(b.low)}</td>
                      </>
                    )}
                    <td className="py-1 text-right">{inr(b.close)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}
    </div>
  );
}
