import { ChevronDown, Download, LayoutGrid, List, Search, Shapes } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/router";
import { Fragment, useEffect, useMemo, useState } from "react";
import { assetClassColor, HBarList, HoldingsTreemap, LegendList, SERIES, toSlices } from "../components/charts";
import Layout from "../components/Layout";
import { PriceChart } from "../components/PriceChart";
import { CalmToggle, DayChange, PriceStamp } from "../components/PriceStamp";
import { Button, Card, EmptyState, LinkButton, Money, PageHeader, Segmented, Skeleton, Stat } from "../components/ui";
import { formatNumberIN } from "../lib/currency";
import { formatPct, labelize } from "../lib/format";
import { Holding, rankEntries } from "../lib/portfolio";
import { usePortfolio } from "../lib/portfolio-context";

type View = "list" | "map";
type SortKey = "value" | "weight" | "symbol" | "price";

function exportCsv(holdings: Holding[]) {
  const header = ["symbol", "name", "type", "asset_class", "quantity", "price_inr", "value_inr", "weight_pct", "accounts"];
  const escape = (v: string | number) => {
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const rows = holdings.map((h) =>
    [h.symbol, h.name, h.type, h.assetClass, h.quantity, h.price ?? "", h.value.toFixed(2), h.weight.toFixed(2), h.accounts.map((a) => a.name).join("; ")]
      .map(escape)
      .join(","),
  );
  const blob = new Blob([[header.join(","), ...rows].join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `samruddhi-holdings-${new Date().toISOString().slice(0, 10)}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

function HoldingDetail({ holding }: { holding: Holding }) {
  const sectors = rankEntries(holding.instrument?.allocation_sectors ?? {}, 4);
  const regions = rankEntries(holding.instrument?.allocation_regions ?? {}, 4);
  return (
    <div className="bg-sunken px-5 py-5">
      <PriceChart symbol={holding.symbol} />
    <div className="mt-6 grid gap-6 border-t border-line pt-5 md:grid-cols-3">
      <div>
        <p className="mb-3 text-[12.5px] font-medium text-muted">Held in</p>
        <ul className="space-y-2">
          {holding.accounts.map((a) => (
            <li key={a.id} className="flex items-center justify-between gap-3 text-[13px]">
              <Link href={`/accounts/${a.id}`} className="truncate font-medium text-ink hover:underline">
                {a.name}
              </Link>
              <span className="tabular shrink-0 text-muted">
                {formatNumberIN(a.quantity, a.quantity % 1 ? 2 : 0)} units <Money value={a.value} compact className="ml-2 text-ink" />
              </span>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <p className="mb-3 text-[12.5px] font-medium text-muted">Sectors</p>
        {sectors.length ? (
          <HBarList items={sectors.map(([k, v], i) => ({ key: k, label: labelize(k), value: v, color: SERIES[i] }))} total={100} />
        ) : (
          <p className="text-[13px] text-muted">Not classified yet.</p>
        )}
      </div>
      <div>
        <p className="mb-3 text-[12.5px] font-medium text-muted">Regions</p>
        {regions.length ? (
          <HBarList items={regions.map(([k, v], i) => ({ key: k, label: labelize(k), value: v, color: SERIES[i] }))} total={100} />
        ) : (
          <p className="text-[13px] text-muted">Not classified yet.</p>
        )}
      </div>
    </div>
    </div>
  );
}

export default function Holdings() {
  const router = useRouter();
  const { metrics, loading, accounts } = usePortfolio();
  const [view, setView] = useState<View>("list");
  const [query, setQuery] = useState("");
  const [type, setType] = useState<string>("all");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "value", dir: -1 });
  const [expanded, setExpanded] = useState<string | null>(null);

  // Deep links from the command palette land with ?q=SYMBOL
  useEffect(() => {
    if (typeof router.query.q === "string") setQuery(router.query.q);
  }, [router.query.q]);

  const types = useMemo(() => [...new Set(metrics.holdings.map((h) => h.type).filter(Boolean))].sort(), [metrics.holdings]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = metrics.holdings.filter(
      (h) => (type === "all" || h.type === type) && (!q || h.symbol.toLowerCase().includes(q) || h.name.toLowerCase().includes(q)),
    );
    const value = (h: Holding) => (sort.key === "symbol" ? h.symbol : sort.key === "price" ? h.price ?? 0 : sort.key === "weight" ? h.weight : h.value);
    return [...list].sort((a, b) => {
      const av = value(a);
      const bv = value(b);
      return (typeof av === "string" ? av.localeCompare(bv as string) : av - (bv as number)) * sort.dir;
    });
  }, [metrics.holdings, query, type, sort]);

  const classSlices = useMemo(() => {
    const byClass: Record<string, number> = {};
    for (const h of visible) byClass[h.assetClass] = (byClass[h.assetClass] ?? 0) + h.value;
    return toSlices(rankEntries(byClass, 6), (key) => assetClassColor(key));
  }, [visible]);

  const treemap = visible
    .filter((h) => h.value > 0)
    .map((h) => ({ name: h.symbol, size: h.value, color: assetClassColor(h.assetClass), weight: h.weight, label: labelize(h.assetClass) }));

  const toggleSort = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, dir: (s.dir * -1) as 1 | -1 } : { key, dir: key === "symbol" ? 1 : -1 }));

  const SortHeader = ({ k, label, align = "right" }: { k: SortKey; label: string; align?: "left" | "right" }) => (
    <th className={`px-4 py-2.5 font-medium ${align === "right" ? "text-right" : "text-left"}`} aria-sort={sort.key === k ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
      <button onClick={() => toggleSort(k)} className={`inline-flex items-center gap-1 hover:text-ink ${sort.key === k ? "text-ink" : ""}`}>
        {label}
        {sort.key === k && <ChevronDown className={`h-3.5 w-3.5 transition-transform ${sort.dir === 1 ? "rotate-180" : ""}`} strokeWidth={2.2} />}
      </button>
    </th>
  );

  const largest = metrics.holdings[0];

  return (
    <Layout
      title="Holdings"
      tabs={
        <Segmented
          ariaLabel="Holdings view"
          value={view}
          onChange={setView}
          layoutId="holdings-view"
          items={[
            { value: "list", label: "List", icon: <List className="h-3.5 w-3.5" strokeWidth={2} /> },
            { value: "map", label: "Map", icon: <LayoutGrid className="h-3.5 w-3.5" strokeWidth={2} /> },
          ]}
        />
      }
    >
      <PageHeader
        title="Holdings"
        subtitle="Every position across your accounts, combined by instrument. Each price shows when it was the price and where it came from."
        actions={
          metrics.holdings.length > 0 && (
            <>
              <CalmToggle />
              <Button variant="secondary" onClick={() => exportCsv(visible)} icon={<Download className="h-4 w-4" strokeWidth={2} />}>
                Export CSV
              </Button>
            </>
          )
        }
      />

      {loading && !accounts.length ? (
        <div className="mt-7 space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-[92px]" />
            ))}
          </div>
          <Skeleton className="h-[420px]" />
        </div>
      ) : metrics.holdings.length === 0 ? (
        <div className="sm-card mt-7">
          <EmptyState
            icon={<Shapes className="h-5 w-5" strokeWidth={2} />}
            title="No holdings yet"
            body="Open an account and add the ETFs, funds or stocks you own. They all roll up here."
            action={<LinkButton href={accounts.length ? `/accounts/${accounts[0].id}` : "/accounts?new=1"} variant="primary">{accounts.length ? "Add a holding" : "Add an account"}</LinkButton>}
          />
        </div>
      ) : (
        <>
          <div className="mt-7 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Invested" value={<Money value={metrics.investedValue} compact />} hint={<>Plus <Money value={metrics.cashValue} compact /> in cash</>} />
            <Stat label="Holdings" value={metrics.holdings.length} hint={`${types.length} instrument type${types.length === 1 ? "" : "s"}`} />
            <Stat label="Top five" value={formatPct(metrics.top5Share, 0)} hint="Share of invested value" />
            <Stat label="Largest" value={largest?.symbol ?? "—"} hint={largest ? `${formatPct(largest.weight, 1)} of invested value` : undefined} />
          </div>

          <div className="mt-6 flex flex-col gap-3 lg:flex-row lg:items-center">
            <div className="relative lg:w-[300px]">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" strokeWidth={2} />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search symbol or name"
                aria-label="Search holdings"
                className="sm-field !h-10 pl-9"
              />
            </div>
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by instrument type">
              {["all", ...types].map((t) => (
                <button
                  key={t}
                  onClick={() => setType(t)}
                  aria-pressed={type === t}
                  className={`h-8 rounded-full px-3 text-[12.5px] font-medium transition-colors ${
                    type === t ? "bg-ink text-frame" : "bg-surface text-ink-2 ring-1 ring-line hover:ring-line-strong"
                  }`}
                >
                  {t === "all" ? "All" : labelize(t)}
                </button>
              ))}
            </div>
            <p className="text-[12.5px] text-muted lg:ml-auto">
              Showing {visible.length} of {metrics.holdings.length}
            </p>
          </div>

          {view === "map" ? (
            <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_280px]">
              <Card title="Holdings map" subtitle="Each tile is sized by value and coloured by asset class">
                {treemap.length ? <HoldingsTreemap data={treemap} height={440} /> : <p className="text-[13px] text-muted">No priced holdings match.</p>}
              </Card>
              <Card title="Asset classes" subtitle="Of the holdings shown">
                <LegendList slices={classSlices} total={classSlices.reduce((s, x) => s + x.value, 0)} />
              </Card>
            </div>
          ) : (
            <div className="sm-card mt-4 overflow-hidden">
              {/* Desktop table */}
              <div className="hidden overflow-x-auto md:block">
                <table className="w-full text-[13.5px]">
                  <thead className="border-b border-line bg-sunken text-[12.5px] text-muted">
                    <tr>
                      <SortHeader k="symbol" label="Holding" align="left" />
                      <th className="px-4 py-2.5 text-left font-medium">Asset class</th>
                      <th className="px-4 py-2.5 text-right font-medium">Quantity</th>
                      <SortHeader k="price" label="Price" />
                      <SortHeader k="value" label="Value" />
                      <SortHeader k="weight" label="Weight" />
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((h) => {
                      const open = expanded === h.symbol;
                      return (
                        <Fragment key={h.symbol}>
                          <tr
                            className={`cursor-pointer border-b border-line transition-colors hover:bg-sunken/60 ${open ? "bg-sunken/60" : ""}`}
                            onClick={() => setExpanded(open ? null : h.symbol)}
                          >
                            <td className="px-4 py-3">
                              <button
                                className="flex items-center gap-3 text-left"
                                aria-expanded={open}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setExpanded(open ? null : h.symbol);
                                }}
                              >
                                <span
                                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] text-[12px] font-bold"
                                  style={{ background: `color-mix(in srgb, ${assetClassColor(h.assetClass)} 18%, transparent)`, color: "var(--ink)" }}
                                >
                                  {h.symbol.slice(0, 2)}
                                </span>
                                <span className="min-w-0">
                                  <span className="block font-semibold text-ink">{h.symbol}</span>
                                  <span className="block max-w-[280px] truncate text-[12.5px] text-muted">
                                    {h.name}
                                    {h.accounts.length > 1 && `, in ${h.accounts.length} accounts`}
                                  </span>
                                </span>
                              </button>
                            </td>
                            <td className="px-4 py-3">
                              <span className="inline-flex items-center gap-2 text-ink-2">
                                <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: assetClassColor(h.assetClass) }} />
                                {labelize(h.assetClass)}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-right text-ink-2">{formatNumberIN(h.quantity, h.quantity % 1 ? 2 : 0)}</td>
                            <td className="px-4 py-3 text-right text-ink-2">
                              {h.price != null ? <Money value={h.price} decimals={2} /> : <span className="text-warn">No price</span>}
                              <PriceStamp instrument={h.instrument} className="mt-0.5 flex justify-end" />
                            </td>
                            <td className="px-4 py-3 text-right font-semibold text-ink">
                              <Money value={h.value} />
                              <DayChange instrument={h.instrument} quantity={h.quantity} className="mt-0.5 block font-normal" />
                            </td>
                            <td className="px-4 py-3">
                              <div className="ml-auto flex w-[140px] items-center gap-2.5">
                                <div className="h-1.5 flex-1 rounded-full bg-sunken">
                                  <div className="h-full rounded-full bg-accent" style={{ width: `${Math.min(100, (h.weight / (metrics.holdings[0]?.weight || 1)) * 100)}%` }} />
                                </div>
                                <span className="tabular w-12 text-right text-[12.5px] font-semibold text-ink">{formatPct(h.weight, 1)}</span>
                              </div>
                            </td>
                          </tr>
                          {open && (
                            <tr className="border-b border-line">
                              <td colSpan={6} className="p-0">
                                <HoldingDetail holding={h} />
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* Mobile list */}
              <ul className="divide-y divide-line md:hidden">
                {visible.map((h) => (
                  <li key={h.symbol}>
                    <button className="flex w-full items-center gap-3 px-4 py-3 text-left" onClick={() => setExpanded(expanded === h.symbol ? null : h.symbol)} aria-expanded={expanded === h.symbol}>
                      <span className="h-8 w-1.5 shrink-0 rounded-full" style={{ background: assetClassColor(h.assetClass) }} />
                      <span className="min-w-0 flex-1">
                        <span className="block font-semibold text-ink">{h.symbol}</span>
                        <span className="block truncate text-[12.5px] text-muted">{h.name}</span>
                        <PriceStamp instrument={h.instrument} className="mt-0.5" />
                      </span>
                      <span className="text-right">
                        <Money value={h.value} compact className="block font-semibold text-ink" />
                        <span className="block text-[12px] text-muted">{formatPct(h.weight, 1)}</span>
                        <DayChange instrument={h.instrument} quantity={h.quantity} className="block" />
                      </span>
                    </button>
                    {expanded === h.symbol && <HoldingDetail holding={h} />}
                  </li>
                ))}
              </ul>

              {visible.length === 0 && <p className="px-4 py-10 text-center text-[13.5px] text-muted">No holdings match your search.</p>}
            </div>
          )}
        </>
      )}
    </Layout>
  );
}
