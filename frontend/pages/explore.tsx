/**
 * Lump sum or stagger: an index-level history explorer (plan section 4.2).
 *
 * Describes what happened in the Nifty 50's past; names no fund, picks no
 * plan and recommends nothing. Hidden under a 3-year horizon (principle 7).
 */
import { Info, Split } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { TooltipBox } from "../components/charts";
import Layout from "../components/Layout";
import { Card, EmptyState, Field, LinkButton, PageHeader, Skeleton } from "../components/ui";
import { formatINR, formatIndianNumberInput, formatNumberIN } from "../lib/currency";
import { useApi } from "../lib/http";
import { dematCash, investmentHorizon } from "../lib/portfolio";
import { usePortfolio } from "../lib/portfolio-context";

const PLANS = [3, 6, 12] as const;
type Plan = (typeof PLANS)[number];

interface Dist {
  p10: number | null;
  median: number | null;
  p90: number | null;
  pct_negative: number | null;
}

interface Group {
  id: "all" | "cheapest" | "middle" | "richest";
  label: string;
  n: number;
  distinct_years?: number;
  first_start?: string;
  last_start?: string;
  lump_better_pct?: number;
  median_edge?: number;
  p10_edge?: number;
  p90_edge?: number;
  lump?: Dist;
  staged?: Dist;
  histogram?: { edges: number[]; lump: number[]; staged: number[] };
}

interface Explorer {
  available: boolean;
  as_of: string;
  series: string;
  source: string;
  data_until: string;
  step_trading_days: number;
  has_temperature: boolean;
  default_cash_yield: { value: number; as_of: string | null; basis: string };
  months: Plan;
  cash_yield: number;
  horizon_months: number;
  groups: Group[];
  current: { temperature: number | null; third: Group["id"] | null } | null;
  disclaimer: string;
}

const COLORS = { lump: "var(--series-1)", staged: "var(--series-2)" };

const pct = (v: number | null | undefined, digits = 1) => {
  if (v == null || !Number.isFinite(v)) return "—";
  const value = v * 100;
  const rounded = Number(value.toFixed(digits));
  if (rounded === 0) return `${(0).toFixed(digits)}%`;
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded).toFixed(digits)}%`;
};
const share = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)}%`);
const fmtDate = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
const THIRD_WORDS: Record<string, string> = { cheapest: "the cheapest third", middle: "the middle third", richest: "the richest third" };

/** The group to describe: periods that started in the same valuation third as today, when known */
function focusOf(result: Explorer): Group | undefined {
  const third = result.current?.third;
  return (third && result.groups.find((g) => g.id === third && g.n > 0)) || result.groups.find((g) => g.id === "all");
}

function Distributions({ group, plan }: { group: Group; plan: Plan }) {
  const h = group.histogram;
  const data = useMemo(
    () =>
      h
        ? h.lump.map((count, i) => ({
            bin: `${Math.round(h.edges[i] * 100)}% to ${Math.round(h.edges[i + 1] * 100)}%`,
            from: h.edges[i],
            lump: (count / group.n) * 100,
            staged: (h.staged[i] / group.n) * 100,
          }))
        : [],
    [h, group.n],
  );
  if (!h) return null;
  return (
    <div className="h-[280px]">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barGap={2} barCategoryGap="18%">
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis
            dataKey="from"
            tickLine={false}
            axisLine={{ stroke: "var(--axis)" }}
            tick={{ fill: "var(--muted)", fontSize: 12 }}
            tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
            interval="preserveStartEnd"
            minTickGap={16}
          />
          <YAxis tickLine={false} axisLine={false} width={40} tick={{ fill: "var(--muted)", fontSize: 12 }} tickFormatter={(v: number) => `${Math.round(v)}%`} />
          <Tooltip
            cursor={{ fill: "var(--sunken)" }}
            content={({ active, payload }) => {
              const p = payload?.[0]?.payload as (typeof data)[number] | undefined;
              if (!active || !p) return null;
              return (
                <TooltipBox
                  title={`12-month return ${p.bin}`}
                  rows={[
                    { color: COLORS.lump, label: "All at once", value: `${p.lump.toFixed(1)}% of periods` },
                    { color: COLORS.staged, label: `Over ${plan} months`, value: `${p.staged.toFixed(1)}% of periods` },
                  ]}
                />
              );
            }}
          />
          <Bar dataKey="lump" fill={COLORS.lump} radius={[4, 4, 0, 0]} isAnimationActive={false} />
          <Bar dataKey="staged" fill={COLORS.staged} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function Explore() {
  const api = useApi();
  const { user, accounts, loading: portfolioLoading } = usePortfolio();
  const horizon = investmentHorizon(user);
  const [amountText, setAmountText] = useState("");
  const [yieldText, setYieldText] = useState("");
  const [yieldEdited, setYieldEdited] = useState(false);
  const [results, setResults] = useState<Partial<Record<Plan, Explorer>>>({});
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Pre-fill with demat cash only (never EPF, PPF or other locked-in money)
  const idle = dematCash(accounts);
  useEffect(() => {
    if (!portfolioLoading && !amountText && idle > 0) setAmountText(formatNumberIN(idle));
  }, [portfolioLoading, idle, amountText]);

  // Null until the user changes it, so the API applies its own default (and no second fetch happens)
  const cashYield = !yieldEdited || yieldText.trim() === "" ? null : Math.min(15, Math.max(0, parseFloat(yieldText) || 0)) / 100;

  useEffect(() => {
    let live = true;
    const timer = window.setTimeout(() => {
      setLoading(true);
      const q = cashYield == null ? "" : `&cash_yield=${cashYield}`;
      Promise.all(PLANS.map((m) => api<Explorer>(`/api/market/deployment-history?months=${m}${q}`)))
        .then((list) => {
          if (!live) return;
          setResults(Object.fromEntries(list.map((r, i) => [PLANS[i], r])) as Record<Plan, Explorer>);
          setError(null);
          if (!yieldEdited && list[0]?.available) setYieldText((list[0].default_cash_yield.value * 100).toFixed(1));
        })
        .catch((err) => live && setError(err instanceof Error ? err.message : "Couldn't load the history."))
        .finally(() => live && setLoading(false));
    }, 350);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, cashYield]);

  const amount = parseFloat(amountText.replace(/,/g, "")) || 0;
  const first = results[3];
  const shortHorizon = horizon !== null && horizon < 3;

  const header = (
    <PageHeader
      title="Lump sum or stagger"
      subtitle="How putting a sum into the Nifty 50 all at once compared with spreading it over 3, 6 or 12 monthly instalments, in the index's own history. It describes the past and recommends nothing."
    />
  );

  if (shortHorizon) {
    return (
      <Layout title="Lump sum or stagger">
        {header}
        <div className="sm-card mt-7">
          <EmptyState
            icon={<Split className="h-5 w-5" strokeWidth={2} />}
            title="Not shown for horizons under 3 years"
            body={`Your profile says this money is invested for ${horizon} year${horizon === 1 ? "" : "s"}. Over short horizons, equity market history isn't a useful guide, so the app doesn't show timing context.`}
            action={<LinkButton href="/goals">Change your horizon</LinkButton>}
          />
        </div>
      </Layout>
    );
  }

  return (
    <Layout title="Lump sum or stagger">
      {header}

      {error ? (
        <div className="sm-card mt-7">
          <EmptyState title="The history didn't load" body={error} />
        </div>
      ) : !first && loading ? (
        <div className="mt-7 grid gap-4 lg:grid-cols-12">
          <Skeleton className="h-[260px] lg:col-span-4" />
          <Skeleton className="h-[260px] lg:col-span-8" />
        </div>
      ) : !first?.available ? (
        <div className="sm-card mt-7">
          <EmptyState title="History not computed yet" body="The market job builds this table each evening at 19:00 IST. Check back after the next run." />
        </div>
      ) : (
        <>
          <div className="mt-7 grid items-start gap-4 *:min-w-0 lg:grid-cols-12">
            <Card title="Your numbers" subtitle="Only used to put the percentages in rupees" className="lg:col-span-4">
              <div className="space-y-4">
                <Field label="Amount" htmlFor="x-amount" hint={idle > 0 ? `Filled in from the cash in your demat account${accounts.filter((a) => a.account_type === "demat").length > 1 ? "s" : ""}.` : "Any amount; nothing is saved."}>
                  <div className="relative">
                    <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted">₹</span>
                    <input id="x-amount" inputMode="numeric" className="sm-field pl-7" placeholder="2,00,000" value={amountText} onChange={(e) => setAmountText(formatIndianNumberInput(e.target.value))} />
                  </div>
                </Field>
                <Field label="Yield on the cash waiting to go in" htmlFor="x-yield" hint={`Default: ${first.default_cash_yield.basis}${first.default_cash_yield.as_of ? `, to ${fmtDate(first.default_cash_yield.as_of)}` : ""}.`}>
                  <div className="relative">
                    <input id="x-yield" inputMode="decimal" className="sm-field pr-8" value={yieldText} onChange={(e) => {
                        setYieldEdited(true);
                        setYieldText(e.target.value.replace(/[^0-9.]/g, "").slice(0, 5));
                      }} />
                    <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-muted">%</span>
                  </div>
                </Field>
                {first.has_temperature && first.current?.third && (
                  <p className="rounded-xl bg-sunken px-3.5 py-3 text-[13px] leading-5 text-ink-2">
                    Today the Nifty 50&apos;s valuation temperature is {Math.round(first.current.temperature ?? 0)}, in {THIRD_WORDS[first.current.third]} of its history. The results use periods
                    that started from that third.
                  </p>
                )}
                {!first.has_temperature && (
                  <p className="rounded-xl bg-sunken px-3.5 py-3 text-[13px] leading-5 text-ink-2">
                    Valuation history isn&apos;t loaded yet, so these results cover every start date since {fmtDate(first.groups[0].first_start ?? first.data_until)}, whatever the
                    valuation was.
                  </p>
                )}
              </div>
            </Card>

            <Card
              title="What happened, by plan length"
              subtitle={`Each row compares the two approaches ${first.horizon_months} months after the start. Choose a row to see both distributions.`}
              className="lg:col-span-8"
              bodyClassName="!px-0"
            >
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] text-[13px]">
                  <thead className="border-y border-line bg-sunken text-[12px] text-muted">
                    <tr>
                      <th className="px-5 py-2.5 text-left font-medium">Spread over</th>
                      <th className="px-3 py-2.5 text-right font-medium">All at once did better</th>
                      <th className="px-3 py-2.5 text-right font-medium">Median difference</th>
                      <th className="px-3 py-2.5 text-right font-medium">Worst tenth</th>
                      <th className="px-5 py-2.5 text-right font-medium">Periods</th>
                    </tr>
                  </thead>
                  <tbody>
                    {PLANS.map((m) => {
                      const r = results[m];
                      const g = r?.available ? focusOf(r) : undefined;
                      const selected = plan === m;
                      return (
                        <tr
                          key={m}
                          onClick={() => setPlan(selected ? null : m)}
                          className={`cursor-pointer border-b border-line last:border-0 ${selected ? "bg-accent-soft" : "hover:bg-sunken"}`}
                        >
                          <td className="px-5 py-3">
                            <button
                              type="button"
                              className="font-semibold text-ink underline decoration-line-strong decoration-dotted underline-offset-4"
                              aria-pressed={selected}
                              onClick={(e) => {
                                e.stopPropagation();
                                setPlan(selected ? null : m);
                              }}
                            >
                              {m} months
                            </button>
                          </td>
                          <td className="tabular px-3 py-3 text-right font-semibold text-ink">{g ? share(g.lump_better_pct) : "—"}</td>
                          <td className="tabular px-3 py-3 text-right text-ink-2">{g ? pct(g.median_edge) : "—"}</td>
                          <td className="tabular px-3 py-3 text-right text-ink-2">{g ? pct(g.p10_edge) : "—"}</td>
                          <td className="tabular px-5 py-3 text-right text-muted">
                            {g ? `${formatNumberIN(g.n)} (${g.distinct_years} yrs)` : "—"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p className="px-5 pt-3 text-[12.5px] leading-5 text-muted">
                A positive difference means investing at once ended ahead of the instalments; negative means the instalments did. &ldquo;Worst tenth&rdquo; is the difference in
                the 10% of periods that went worst for investing at once.
              </p>
            </Card>
          </div>

          {plan && results[plan]?.available && (
            <PlanDetail result={results[plan] as Explorer} plan={plan} amount={amount} />
          )}

          <details className="sm-card group mt-4 px-5 py-4">
            <summary className="flex cursor-pointer list-none items-center gap-2 text-[13.5px] font-semibold text-ink">
              <Info className="h-4 w-4 text-muted" strokeWidth={2} />
              How this is worked out, and its limits
              <span className="ml-auto text-[12.5px] font-normal text-muted group-open:hidden">Show</span>
            </summary>
            <div className="mt-4 space-y-2 text-[13px] leading-6 text-ink-2">
              <p>
                Series: {first.series} ({first.source}), with a start date every {first.step_trading_days} trading days from {fmtDate(first.groups[0].first_start ?? "")} to{" "}
                {fmtDate(first.groups[0].last_start ?? "")}. Data ends {fmtDate(first.data_until)}, at least 30 days back, as SEBI requires for price data used in education.
              </p>
              <p>
                &ldquo;All at once&rdquo; invests everything on the start date. &ldquo;Spread over N months&rdquo; invests one Nth on the start date and on each monthly date after it,
                while the rest earns the yield you set. Both are valued {first.horizon_months} months after the start.
              </p>
              {first.series.includes("price index") && (
                <p>The price index leaves out dividends, which slightly understates investing at once. The total return index replaces it once it&apos;s loaded.</p>
              )}
              <p>
                Start dates a few days apart share most of their path, so the periods are not independent. The cheapest valuations come from a few market crises (2003,
                2008–09, 2020), and India&apos;s strong growth since 1999 may not repeat.
              </p>
              <p>Same method and numbers as the research behind this app (plan section 5.3), checked in code against the original script.</p>
            </div>
          </details>

          <p className="mt-6 flex gap-2 text-[12.5px] leading-5 text-muted">
            <Info className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2} />
            <span>{first.disclaimer}</span>
          </p>
        </>
      )}
    </Layout>
  );
}

function PlanDetail({ result, plan, amount }: { result: Explorer; plan: Plan; amount: number }) {
  const g = focusOf(result);
  if (!g || !g.n) return null;
  const staggerBetterBy = g.p10_edge != null && g.p10_edge < 0 ? -g.p10_edge : null;
  const from = result.current?.third && g.id !== "all" ? `From valuations like today's (${THIRD_WORDS[g.id]})` : "Across all periods";
  const thirds = result.groups.filter((x) => x.id !== "all" && x.n > 0);

  return (
    <div className="mt-4 grid items-start gap-4 *:min-w-0 lg:grid-cols-12">
      <Card title={`All at once vs over ${plan} months`} subtitle={`Share of periods by ${result.horizon_months}-month return`} className="lg:col-span-8">
        <p className="mb-4 max-w-[70ch] text-[13.5px] leading-6 text-ink-2">
          {from}, investing all at once did better in {share(g.lump_better_pct)} of periods, by a median of {pct(g.median_edge)}
          {amount > 0 && g.median_edge != null && <> (about {formatINR(Math.abs(g.median_edge) * amount, 0)} on {formatINR(amount, 0)})</>}.
          {staggerBetterBy != null && (
            <>
              {" "}
              In the worst tenth of periods for investing at once, spreading it over {plan} months did better by {pct(staggerBetterBy).replace("+", "")} or more.
            </>
          )}{" "}
          Some people who dislike seeing an early loss choose to spread a sum over a few months; others invest at once.
        </p>
        <Distributions group={g} plan={plan} />
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-[12.5px] text-muted">
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: COLORS.lump }} /> All at once
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: COLORS.staged }} /> Over {plan} months
          </span>
        </div>
      </Card>

      <Card title="The two outcomes" subtitle={`${result.horizon_months}-month returns, ${from.charAt(0).toLowerCase()}${from.slice(1)}`} className="lg:col-span-4" bodyClassName="!px-0">
        <table className="w-full text-[13px]">
          <thead className="border-y border-line bg-sunken text-[12px] text-muted">
            <tr>
              <th className="px-5 py-2 text-left font-medium" />
              <th className="px-3 py-2 text-right font-medium">At once</th>
              <th className="px-5 py-2 text-right font-medium">Over {plan}m</th>
            </tr>
          </thead>
          <tbody>
            {(
              [
                ["Median", "median"],
                ["Worst tenth (p10)", "p10"],
                ["Best tenth (p90)", "p90"],
              ] as const
            ).map(([label, key]) => (
              <tr key={key} className="border-b border-line">
                <td className="px-5 py-2.5 text-ink-2">{label}</td>
                <td className="tabular px-3 py-2.5 text-right text-ink">{pct(g.lump?.[key])}</td>
                <td className="tabular px-5 py-2.5 text-right text-ink">{pct(g.staged?.[key])}</td>
              </tr>
            ))}
            <tr>
              <td className="px-5 py-2.5 text-ink-2">Periods with a loss</td>
              <td className="tabular px-3 py-2.5 text-right text-ink">{share(g.lump?.pct_negative)}</td>
              <td className="tabular px-5 py-2.5 text-right text-ink">{share(g.staged?.pct_negative)}</td>
            </tr>
          </tbody>
        </table>
        {thirds.length > 0 && (
          <div className="mt-4 px-5">
            <p className="text-[12.5px] font-medium text-ink">All at once did better, by valuation third</p>
            <ul className="mt-2 space-y-1.5 text-[12.5px]">
              {thirds.map((t) => (
                <li key={t.id} className={`flex justify-between gap-3 ${t.id === result.current?.third ? "font-semibold text-ink" : "text-ink-2"}`}>
                  <span>{t.label}</span>
                  <span className="tabular">
                    {share(t.lump_better_pct)}, median {pct(t.median_edge)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Card>
    </div>
  );
}
