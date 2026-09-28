import { ArrowUpRight, Bot, Coins, Compass, Flag, Globe2, Layers, Play, Plus, Scale, Sparkles, Wallet } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { assetClassColor, CompositionBar, DonutWithLegend, DriftRows, driftStatus, Gauge, HBarList, MoneyFlow, SERIES, toSlices } from "../components/charts";
import Layout from "../components/Layout";
import { WarpBackdrop } from "../components/Shader";
import { showToast } from "../components/Toast";
import { Badge, Button, Card, EmptyState, JobStatusBadge, LinkButton, Meter, Money, PageHeader, Skeleton, tileTone } from "../components/ui";
import { isActive, progressOf, reportTextOf } from "../lib/agents";
import { useAnalysis } from "../lib/analysis-context";
import { formatPct, greeting, labelize, timeAgo } from "../lib/format";
import { useProjectionAssumptions } from "../lib/assumptions";
import { computeDrift, dematCash, investmentHorizon, rankEntries } from "../lib/portfolio";
import { describeAsOf, describeExchangeDelay, freshnessOf, latestExchangeAsOf } from "../lib/pricing";
import { MarketChip } from "../components/market";
import { usePortfolio } from "../lib/portfolio-context";
import { runProjection } from "../lib/projection";
import { useApi } from "../lib/http";
import { excerpt } from "../lib/report";

function DashboardSkeleton() {
  return (
    <div className="mt-7 grid gap-4 lg:grid-cols-12">
      <Skeleton className="h-[260px] lg:col-span-5" />
      <Skeleton className="h-[260px] lg:col-span-4" />
      <Skeleton className="h-[260px] lg:col-span-3" />
      <Skeleton className="h-[220px] lg:col-span-7" />
      <Skeleton className="h-[220px] lg:col-span-5" />
    </div>
  );
}

function EmptyPortfolio() {
  const api = useApi();
  const { refresh } = usePortfolio();
  const [loading, setLoading] = useState(false);

  const loadSample = async () => {
    setLoading(true);
    try {
      await api("/api/populate-test-data", { method: "POST" });
      await refresh();
      showToast("success", "Sample portfolio loaded. Explore, then replace it with your own accounts.");
    } catch (err) {
      showToast("error", err instanceof Error ? err.message : "Couldn't load the sample portfolio.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative mt-7 overflow-hidden rounded-[22px] text-white">
      <WarpBackdrop speed={0.6} />
      <div className="absolute inset-0 bg-gradient-to-r from-black/85 via-black/60 to-black/20" aria-hidden="true" />
      <div className="relative max-w-xl px-7 py-12 sm:px-10 sm:py-16">
        <h2 className="font-display text-[32px] font-semibold leading-[1.1] tracking-[-0.03em] sm:text-[40px]">Add your first account</h2>
        <p className="mt-3 text-[15px] leading-7 text-white/75">
          Add an EPF, PPF, NPS or demat account and the holdings inside it. Your dashboard, charts and the AI team all work from these.
        </p>
        <div className="mt-7 flex flex-wrap gap-2">
          <LinkButton href="/accounts?new=1" variant="primary" size="lg" icon={<Plus className="h-4 w-4" strokeWidth={2.4} />}>
            Add an account
          </LinkButton>
          <Button variant="secondary" size="lg" onClick={loadSample} loading={loading} className="!border-white/25 !bg-white/10 !text-white hover:!bg-white/20">
            Try a sample portfolio
          </Button>
        </div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { user, metrics, loading, accounts } = usePortfolio();
  const { jobs, activeJob, startAnalysis, starting } = useAnalysis();
  const { assumptions } = useProjectionAssumptions();

  const name = user?.display_name?.split(" ")[0];
  const hasData = accounts.length > 0;
  const running = isActive(activeJob);
  const latest = jobs.find((j) => j.status === "completed");

  const assetSlices = useMemo(
    () => toSlices(rankEntries(metrics.assetClasses, 6), (key) => assetClassColor(key)),
    [metrics.assetClasses],
  );

  const holdingSlices = useMemo(() => {
    const top = metrics.holdings.slice(0, 5);
    const rest = metrics.holdings.slice(5).reduce((s, h) => s + h.value, 0);
    const slices = top.map((h, i) => ({ key: h.symbol, label: h.symbol, value: h.value, color: SERIES[i] }));
    if (rest > 0) slices.push({ key: "other", label: `${metrics.holdings.length - 5} others`, value: rest, color: "var(--axis)" });
    return slices;
  }, [metrics.holdings]);

  const drift = useMemo(() => computeDrift(metrics, user), [metrics, user]);
  const equityDrift = drift.assetDrift[0];

  const priceNote = useMemo(() => {
    const asOf = latestExchangeAsOf(metrics.holdings.map((h) => h.instrument));
    const outdated = metrics.holdings.filter((h) => freshnessOf(h.instrument).stale).length;
    const base = asOf
      ? `Worked out from your own accounts, with exchange prices as of ${describeAsOf(asOf)} (${describeExchangeDelay(asOf)}, Yahoo Finance demo data) and fund NAVs from AMFI.`
      : "Worked out from your own accounts and the latest stored prices.";
    return outdated ? `${base} ${outdated} holding${outdated === 1 ? " has an" : "s have"} out-of-date price${outdated === 1 ? "" : "s"}.` : base;
  }, [metrics.holdings]);

  // Same inputs, assumptions and seed as the Goals page, so the two agree
  const projection = useMemo(() => {
    if (!user || !assumptions || metrics.totalValue <= 0) return null;
    return runProjection(
      {
        currentValue: metrics.totalValue,
        yearsToRetirement: user.years_until_retirement,
        annualContribution: (user.monthly_contribution ?? 0) * 12,
        targetAnnualIncome: user.target_retirement_income,
        allocation: metrics.assetClasses,
      },
      assumptions,
    );
  }, [user, metrics, assumptions]);

  // Idle cash: demat cash only, and only for horizons long enough for equity context
  const idleCash = dematCash(accounts);
  const horizon = investmentHorizon(user);
  const showIdleCash = idleCash > 0 && (horizon === null || horizon >= 3);

  const sectorItems = rankEntries(metrics.sectors, 6).map(([key, value], i) => ({ key, label: labelize(key), value, color: key === "other" ? "var(--axis)" : SERIES[i] }));
  const sectorTotal = Object.values(metrics.sectors).reduce((s, v) => s + v, 0);
  const regionItems = rankEntries(metrics.regions, 5).map(([key, value], i) => ({ key, label: labelize(key), value, color: key === "other" ? "var(--axis)" : SERIES[i] }));
  const regionTotal = Object.values(metrics.regions).reduce((s, v) => s + v, 0);

  // Sankey: accounts on the left, asset classes on the right
  const flow = useMemo(() => {
    const classes = rankEntries(metrics.assetClasses, 6).map(([k]) => k);
    const accountNodes = metrics.accounts.filter((a) => a.total > 0);
    const nodes = [
      ...accountNodes.map((a, i) => {
        const index = accounts.findIndex((x) => x.id === a.id);
        return { name: a.name, color: `var(--series-${tileTone(index >= 0 ? index : i)})` };
      }),
      ...classes.map((k) => ({ name: labelize(k), color: assetClassColor(k) })),
    ];
    const links: { source: number; target: number; value: number }[] = [];
    accountNodes.forEach((a, ai) => {
      for (const [cls, value] of Object.entries(a.assetClasses)) {
        let ci = classes.indexOf(cls);
        if (ci < 0) ci = classes.indexOf("other");
        if (ci >= 0 && value > 0) links.push({ source: ai, target: accountNodes.length + ci, value });
      }
    });
    return { nodes, links };
  }, [metrics, accounts]);

  const insight = reportTextOf(latest) ? excerpt(reportTextOf(latest)) : "";
  const equityShare = metrics.totalValue > 0 ? ((metrics.assetClasses.equity ?? 0) / metrics.totalValue) * 100 : 0;
  const investedShare = metrics.totalValue > 0 ? (metrics.investedValue / metrics.totalValue) * 100 : 0;

  return (
    <Layout title="Dashboard">
      <PageHeader
        title={name ? `${greeting()}, ${name}` : greeting()}
        subtitle={priceNote}
        actions={
          hasData && (
            <>
              <MarketChip />
              <LinkButton href="/holdings" variant="secondary" icon={<Layers className="h-4 w-4" strokeWidth={2} />}>
                Holdings
              </LinkButton>
              <Button onClick={startAnalysis} loading={starting} disabled={running} icon={<Play className="h-3.5 w-3.5 fill-current" strokeWidth={2.2} />}>
                {running ? "Analysis running" : "Run analysis"}
              </Button>
            </>
          )
        }
      />

      {loading && !hasData ? (
        <DashboardSkeleton />
      ) : !hasData ? (
        <EmptyPortfolio />
      ) : (
        <div className="mt-7 grid gap-4 lg:grid-cols-12">
          {/* Net worth — the one shader surface on this page */}
          <section className="relative min-h-[260px] overflow-hidden rounded-[18px] text-white lg:col-span-5">
            <WarpBackdrop speed={0.5} />
            <div className="absolute inset-0 bg-gradient-to-br from-black/85 via-black/55 to-black/10" aria-hidden="true" />
            <div className="relative flex h-full flex-col p-6">
              <div className="flex items-center justify-between">
                <p className="flex items-center gap-2 text-[13px] font-medium text-white/75">
                  <Wallet className="h-4 w-4" strokeWidth={2} />
                  Net worth
                </p>
                {metrics.unpricedCount > 0 && (
                  <span className="rounded-full bg-white/15 px-2.5 py-1 text-[11.5px] font-medium backdrop-blur-sm" title="These holdings are counted at zero until the pricer finds a price">
                    {metrics.unpricedCount} unpriced
                  </span>
                )}
              </div>
              <p className="mt-5 font-display text-[44px] font-semibold leading-none tracking-[-0.035em] sm:text-[52px]">
                <Money value={metrics.totalValue} />
              </p>
              <p className="mt-2 text-[13.5px] text-white/70">
                Across {metrics.accounts.length} account{metrics.accounts.length === 1 ? "" : "s"} and {metrics.holdings.length} holding{metrics.holdings.length === 1 ? "" : "s"}
              </p>
              <div className="mt-auto pt-8">
                <div className="flex h-2 w-full gap-[2px] overflow-hidden rounded-full">
                  <span className="h-full rounded-l-full bg-[#ffc62b]" style={{ width: `${investedShare}%` }} />
                  <span className="h-full flex-1 rounded-r-full bg-white/35" />
                </div>
                <div className="mt-2.5 flex justify-between text-[12.5px]">
                  <span className="flex items-center gap-1.5 text-white/80">
                    <span className="h-2 w-2 rounded-full bg-[#ffc62b]" />
                    Invested <Money value={metrics.investedValue} compact className="font-semibold text-white" />
                  </span>
                  <span className="flex items-center gap-1.5 text-white/80">
                    <span className="h-2 w-2 rounded-full bg-white/50" />
                    Cash <Money value={metrics.cashValue} compact className="font-semibold text-white" />
                  </span>
                </div>
              </div>
            </div>
          </section>

          <Card title="Asset mix" subtitle="Share of everything you hold" className="lg:col-span-4">
            <DonutWithLegend
              slices={assetSlices}
              size={140}
              center={
                <>
                  <span className="font-display text-[22px] font-semibold leading-none text-ink">{formatPct(equityShare, 0)}</span>
                  <span className="mt-1 text-[11.5px] text-muted">in equity</span>
                </>
              }
            />
          </Card>

          <div className="grid gap-4 sm:grid-cols-2 lg:col-span-3 lg:grid-cols-1">
            <Card
              title="Retirement outlook"
              icon={<Flag className="h-4 w-4 text-muted" strokeWidth={2} />}
              action={
                <Link href="/goals" className="sm-icon-btn h-7 w-7" aria-label="Open goals">
                  <ArrowUpRight className="h-4 w-4" strokeWidth={2} />
                </Link>
              }
              bodyClassName="flex items-center gap-3 !pt-2"
            >
              {projection ? (
                <>
                  <Gauge
                    value={projection.successRate}
                    size={92}
                    color={projection.successRate >= 75 ? "var(--good)" : projection.successRate >= 50 ? "var(--warn)" : "var(--bad)"}
                  />
                  <div className="min-w-0">
                    <Badge tone={projection.successRate >= 75 ? "good" : projection.successRate >= 50 ? "warn" : "bad"}>
                      {projection.successRate >= 75 ? "On track" : projection.successRate >= 50 ? "Borderline" : "At risk"}
                    </Badge>
                    <p className="mt-1.5 text-[12.5px] leading-5 text-muted">Odds your money lasts a {assumptions?.retirement_years ?? 30}-year retirement</p>
                  </div>
                </>
              ) : (
                <p className="text-[13px] text-muted">Set a retirement goal to see your odds.</p>
              )}
            </Card>

            <Card
              title="AI desk"
              icon={<Bot className="h-4 w-4 text-muted" strokeWidth={2} />}
              action={latest && !running ? <JobStatusBadge status="completed" /> : running && activeJob ? <JobStatusBadge status={activeJob.status} /> : null}
              bodyClassName="!pt-2"
            >
              {running && activeJob ? (
                <>
                  <p className="text-[13px] text-ink-2">
                    {progressOf(activeJob).done} of 3 specialists have delivered.
                  </p>
                  <Meter className="mt-3" value={(progressOf(activeJob).done / 3) * 100} label="Analysis progress" />
                  <Link href="/ai-team" className="mt-3 inline-block text-[13px] font-semibold text-ink underline decoration-accent decoration-2 underline-offset-4">
                    Watch live
                  </Link>
                </>
              ) : latest ? (
                <>
                  <p className="text-[13px] text-ink-2">Latest review {timeAgo(latest.completed_at ?? latest.created_at)}</p>
                  <Link
                    href={`/analysis?job_id=${latest.id}`}
                    className="mt-3 inline-block text-[13px] font-semibold text-ink underline decoration-accent decoration-2 underline-offset-4"
                  >
                    Read the report
                  </Link>
                </>
              ) : (
                <p className="text-[13px] text-muted">No reviews yet. Run one to get a written report and charts.</p>
              )}
            </Card>
          </div>

          <Card title="Where the money sits" subtitle="Your five largest holdings by value" className={showIdleCash ? "lg:col-span-4" : "lg:col-span-7"}>
            <CompositionBar slices={holdingSlices} height={18} />
          </Card>

          {showIdleCash && (
            <Card title="Cash in demat" icon={<Coins className="h-4 w-4 text-muted" strokeWidth={2} />} className="lg:col-span-3" bodyClassName="!pt-2">
              <p className="font-display text-[26px] font-semibold leading-none tracking-[-0.02em] text-ink">
                <Money value={idleCash} compact />
              </p>
              <p className="mt-2 text-[12.5px] leading-5 text-muted">
                Historically, how did investing a sum at once compare with spreading it over a few months?
              </p>
              <Link href="/explore" className="mt-3 inline-block text-[13px] font-semibold text-ink underline decoration-accent decoration-2 underline-offset-4">
                Lump sum or stagger
              </Link>
            </Card>
          )}

          <Card
            title="Against your targets"
            subtitle="Equity vs fixed income, India vs international"
            icon={<Scale className="h-4 w-4 text-muted" strokeWidth={2} />}
            action={
              <Link href="/goals" className="text-[12.5px] font-medium text-muted hover:text-ink">
                Edit targets
              </Link>
            }
            className="lg:col-span-5"
          >
            {drift.assetDrift.length || drift.regionDrift.length ? (
              <>
                <DriftRows rows={[...drift.assetDrift.slice(0, 1), ...drift.regionDrift.slice(0, 1)]} />
                {equityDrift && driftStatus(equityDrift.delta).tone !== "good" && (
                  <p className="mt-4 rounded-xl bg-accent-soft px-3.5 py-3 text-[13px] leading-5 text-ink">
                    {equityDrift.delta > 0 ? (
                      <>
                        <Money value={Math.abs(drift.equityGap)} compact className="font-semibold" /> of your portfolio sits
                        above your own {formatPct(equityDrift.target, 0)} equity target.
                      </>
                    ) : (
                      <>
                        Your equity holdings are <Money value={Math.abs(drift.equityGap)} compact className="font-semibold" />{" "}
                        short of your own {formatPct(equityDrift.target, 0)} equity target.
                      </>
                    )}
                  </p>
                )}
              </>
            ) : (
              <p className="text-[13px] text-muted">Your holdings don&apos;t include equity or fixed income yet.</p>
            )}
          </Card>

          <Card title="Sectors" icon={<Compass className="h-4 w-4 text-muted" strokeWidth={2} />} subtitle="Share of invested value" className="lg:col-span-4">
            {sectorItems.length ? <HBarList items={sectorItems} total={sectorTotal} /> : <p className="text-[13px] text-muted">No sector data for these holdings yet.</p>}
          </Card>

          <Card title="Regions" icon={<Globe2 className="h-4 w-4 text-muted" strokeWidth={2} />} subtitle="Share of invested value" className="lg:col-span-4">
            {regionItems.length ? <HBarList items={regionItems} total={regionTotal} /> : <p className="text-[13px] text-muted">No region data for these holdings yet.</p>}
          </Card>

          <Card title="Diversification" subtitle="How spread out your investments are" className="lg:col-span-4">
            <p className="font-display text-[34px] font-semibold leading-none tracking-[-0.03em] text-ink">
              {metrics.effectiveHoldings.toFixed(1)}
            </p>
            <p className="mt-1.5 text-[13px] text-muted">
              Your {metrics.holdings.length} holdings behave like {metrics.effectiveHoldings.toFixed(1)} equal-sized ones.
            </p>
            <div className="mt-5 space-y-1.5">
              <div className="flex justify-between text-[12.5px]">
                <span className="text-ink-2">Top five holdings</span>
                <span className="tabular font-semibold text-ink">{formatPct(metrics.top5Share, 0)}</span>
              </div>
              <Meter value={metrics.top5Share} label="Share held in top five holdings" />
            </div>
            {metrics.holdings[0] && (
              <p className="mt-4 text-[12.5px] text-muted">
                Largest: <span className="font-semibold text-ink">{metrics.holdings[0].symbol}</span> at {formatPct(metrics.holdings[0].weight, 1)}
                {metrics.holdings[0].weight > 25 && (
                  <Badge tone="warn" className="ml-2 !h-5">
                    Concentrated
                  </Badge>
                )}
              </p>
            )}
          </Card>

          <Card title="Money flow" subtitle="How each account splits across asset classes" className="lg:col-span-8">
            {flow.links.length ? <MoneyFlow nodes={flow.nodes} links={flow.links} height={Math.max(220, flow.nodes.length * 34)} /> : <p className="text-[13px] text-muted">Nothing to show yet.</p>}
          </Card>

          <Card
            title="Latest insight"
            icon={<Sparkles className="h-4 w-4 text-accent-text" strokeWidth={2} />}
            subtitle={latest ? `Written by the Reporter agent ${timeAgo(latest.completed_at ?? latest.created_at)}` : "From the Reporter agent"}
            className="lg:col-span-4"
          >
            {insight ? (
              <>
                <blockquote className="border-l-2 border-accent pl-3.5 text-[14px] leading-6 text-ink-2">{insight}</blockquote>
                <LinkButton href={`/analysis?job_id=${latest?.id}`} variant="secondary" size="sm" className="mt-4">
                  Read the full report
                </LinkButton>
              </>
            ) : (
              <EmptyState
                className="!py-6"
                title="No report yet"
                body="Run an analysis and the Reporter's summary of your portfolio lands here."
                action={
                  <Button size="sm" onClick={startAnalysis} loading={starting} disabled={running}>
                    Run analysis
                  </Button>
                }
              />
            )}
          </Card>
        </div>
      )}
    </Layout>
  );
}
