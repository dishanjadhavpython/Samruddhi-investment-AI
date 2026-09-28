import { Info, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { FanChart, Gauge } from "../components/charts";
import Layout from "../components/Layout";
import { showToast } from "../components/Toast";
import { Badge, Button, Card, Field, Money, PageHeader, Segmented, Skeleton } from "../components/ui";
import { formatIndianNumberInput, formatNumberIN } from "../lib/currency";
import { useProjectionAssumptions } from "../lib/assumptions";
import { formatPct } from "../lib/format";
import { ageFrom } from "../lib/portfolio";
import { usePortfolio } from "../lib/portfolio-context";
import { runProjection } from "../lib/projection";

interface GoalForm {
  displayName: string;
  years: number;
  income: number;
  equity: number;
  india: number;
  sip: number;
  dob: string;
  horizon: string;
  expenses: string;
  bufferMonths: string;
}

const numberOrNull = (text: string) => {
  const n = parseFloat(text.replace(/,/g, ""));
  return Number.isFinite(n) ? n : null;
};

function Slider({ id, value, min, max, step = 1, onChange, label }: { id: string; value: number; min: number; max: number; step?: number; onChange: (v: number) => void; label: string }) {
  const fill = ((value - min) / (max - min)) * 100;
  return (
    <input
      id={id}
      type="range"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      aria-label={label}
      className="sm-range"
      style={{ "--fill": `${fill}%` } as React.CSSProperties}
    />
  );
}

function SplitBar({ left, leftLabel, rightLabel, leftColor, rightColor }: { left: number; leftLabel: string; rightLabel: string; leftColor: string; rightColor: string }) {
  return (
    <div>
      <div className="flex h-9 gap-[2px] overflow-hidden rounded-[10px] text-[12.5px] font-semibold">
        <div className="flex items-center px-3 transition-[flex-grow] duration-300" style={{ flexGrow: Math.max(left, 0.001), background: leftColor, color: "#17130a" }}>
          {left >= 18 && `${leftLabel} ${left}%`}
        </div>
        <div className="flex items-center justify-end px-3 text-white transition-[flex-grow] duration-300" style={{ flexGrow: Math.max(100 - left, 0.001), background: rightColor }}>
          {100 - left >= 18 && `${rightLabel} ${100 - left}%`}
        </div>
      </div>
    </div>
  );
}

export default function Goals() {
  const { user, metrics, loading, saveUser } = usePortfolio();
  const [form, setForm] = useState<GoalForm | null>(null);
  const [incomeText, setIncomeText] = useState("");
  const [saving, setSaving] = useState(false);
  const [mix, setMix] = useState<"current" | "target">("current");
  const { assumptions, error: assumptionsError } = useProjectionAssumptions();

  const saved: GoalForm | null = useMemo(
    () =>
      user && {
        displayName: user.display_name,
        years: user.years_until_retirement || 20,
        income: user.target_retirement_income,
        equity: Math.round(user.asset_class_targets.equity ?? 70),
        india: Math.round(user.region_targets.india ?? 70),
        sip: user.monthly_contribution ?? 0,
        dob: user.date_of_birth ?? "",
        horizon: user.horizon_years != null ? String(user.horizon_years) : "",
        expenses: user.monthly_expenses != null ? formatNumberIN(user.monthly_expenses) : "",
        bufferMonths: user.emergency_fund_months != null ? String(user.emergency_fund_months) : "",
      },
    [user],
  );

  useEffect(() => {
    if (saved && !form) {
      setForm(saved);
      setIncomeText(formatNumberIN(saved.income));
    }
  }, [saved, form]);

  const dirty = Boolean(form && saved && JSON.stringify(form) !== JSON.stringify(saved));

  const projection = useMemo(() => {
    if (!form || !assumptions) return null;
    const allocation = mix === "target" ? { equity: form.equity, fixed_income: 100 - form.equity } : metrics.assetClasses;
    return runProjection(
      {
        currentValue: metrics.totalValue,
        yearsToRetirement: form.years,
        annualContribution: form.sip * 12,
        targetAnnualIncome: form.income,
        allocation,
      },
      assumptions,
    );
  }, [form, mix, metrics, assumptions]);

  const age = form ? ageFrom(form.dob || null) : null;
  const expenses = form ? numberOrNull(form.expenses) : null;
  const bufferMonths = form ? numberOrNull(form.bufferMonths) : null;

  const set = <K extends keyof GoalForm>(key: K, value: GoalForm[K]) => setForm((f) => (f ? { ...f, [key]: value } : f));

  const save = async () => {
    if (!form) return;
    if (!form.displayName.trim()) {
      showToast("error", "Add a display name before saving.");
      return;
    }
    if (form.dob && (age === null || age < 18 || age > 100)) {
      showToast("error", "Enter a date of birth for someone aged 18 to 100.");
      return;
    }
    setSaving(true);
    try {
      await saveUser({
        display_name: form.displayName.trim(),
        years_until_retirement: form.years,
        target_retirement_income: form.income,
        asset_class_targets: { equity: form.equity, fixed_income: 100 - form.equity },
        region_targets: { india: form.india, international: 100 - form.india },
        monthly_contribution: form.sip,
        date_of_birth: form.dob || null,
        horizon_years: form.horizon.trim() ? Math.round(Number(form.horizon)) : null,
        monthly_expenses: expenses,
        emergency_fund_months: bufferMonths === null ? null : Math.round(bufferMonths),
      });
      showToast("success", "Goals saved. The AI team will use them on the next analysis.");
    } catch (err) {
      showToast("error", err instanceof Error ? err.message : "Couldn't save your goals.");
    } finally {
      setSaving(false);
    }
  };

  const discard = () => {
    if (!saved) return;
    setForm(saved);
    setIncomeText(formatNumberIN(saved.income));
  };

  const success = projection?.successRate ?? 0;
  const outlook = success >= 75 ? { tone: "good" as const, label: "On track" } : success >= 50 ? { tone: "warn" as const, label: "Borderline" } : { tone: "bad" as const, label: "At risk" };
  const gaugeColor = outlook.tone === "good" ? "var(--good)" : outlook.tone === "warn" ? "var(--warn)" : "var(--bad)";

  return (
    <Layout title="Goals">
      <PageHeader
        title="Goals & retirement"
        subtitle="Set what you're aiming for. The projection redraws as you move the sliders; save to hand the goals to the AI team."
      />

      {!form || loading ? (
        <div className="mt-7 grid gap-4 lg:grid-cols-12">
          <Skeleton className="h-[560px] lg:col-span-5" />
          <Skeleton className="h-[560px] lg:col-span-7" />
        </div>
      ) : (
        <div className="mt-7 grid items-start gap-4 lg:grid-cols-12">
          <div className="space-y-4 lg:col-span-5">
            <Card title="Retirement">
              <div className="space-y-6">
                <div>
                  <div className="flex items-baseline justify-between">
                    <label htmlFor="g-years" className="text-[13px] font-medium text-ink">
                      Years until you retire
                    </label>
                    <span className="font-display text-[26px] font-semibold leading-none tracking-[-0.02em] text-ink">
                      {form.years}
                      <span className="ml-1 text-[13px] font-medium text-muted">{age !== null ? `years, at ${age + form.years}` : "years"}</span>
                    </span>
                  </div>
                  <div className="mt-3">
                    <Slider id="g-years" label="Years until retirement" value={form.years} min={0} max={50} onChange={(v) => set("years", v)} />
                  </div>
                </div>

                <Field
                  label="Yearly income you want in retirement"
                  htmlFor="g-income"
                  hint={`In today's rupees. Withdrawals then rise ${assumptions ? formatPct(assumptions.inflation * 100, 0) : "with inflation"} a year for inflation.`}
                >
                  <div className="relative">
                    <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted">₹</span>
                    <input
                      id="g-income"
                      inputMode="numeric"
                      className="sm-field pl-7"
                      value={incomeText}
                      onChange={(e) => {
                        const text = formatIndianNumberInput(e.target.value);
                        setIncomeText(text);
                        set("income", parseFloat(text.replace(/,/g, "")) || 0);
                      }}
                    />
                  </div>
                </Field>

                <div>
                  <div className="flex items-baseline justify-between">
                    <label htmlFor="g-sip" className="text-[13px] font-medium text-ink">
                      Monthly SIP
                    </label>
                    <Money value={form.sip} className="font-display text-[20px] font-semibold text-ink" />
                  </div>
                  <div className="mt-3">
                    <Slider id="g-sip" label="Monthly SIP" value={form.sip} min={0} max={200000} step={1000} onChange={(v) => set("sip", v)} />
                  </div>
                  <p className="mt-2 text-[12.5px] text-muted">What you add each month. Saved with your goals; the Retirement agent uses it too.</p>
                </div>
              </div>
            </Card>

            <Card title="Target mix" subtitle="The AI team measures your portfolio against these">
              <div className="space-y-6">
                <div>
                  <div className="mb-2.5 flex justify-between text-[13px]">
                    <span className="font-medium text-ink">Equity vs fixed income</span>
                  </div>
                  <SplitBar left={form.equity} leftLabel="Equity" rightLabel="Fixed income" leftColor="var(--series-1)" rightColor="var(--series-2)" />
                  <div className="mt-3">
                    <Slider id="g-eq" label="Equity target percentage" value={form.equity} min={0} max={100} onChange={(v) => set("equity", v)} />
                  </div>
                </div>
                <div>
                  <div className="mb-2.5 flex justify-between text-[13px]">
                    <span className="font-medium text-ink">India vs international</span>
                  </div>
                  <SplitBar left={form.india} leftLabel="India" rightLabel="International" leftColor="var(--series-1)" rightColor="var(--series-4)" />
                  <div className="mt-3">
                    <Slider id="g-india" label="India target percentage" value={form.india} min={0} max={100} onChange={(v) => set("india", v)} />
                  </div>
                </div>
              </div>
            </Card>

            <Card title="About you" subtitle="Optional. Saved to your profile and used only in your own projections.">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <Field label="Display name" htmlFor="g-name" hint="Used in greetings and in your reports.">
                    <input id="g-name" className="sm-field" value={form.displayName} onChange={(e) => set("displayName", e.target.value)} />
                  </Field>
                </div>
                <Field label="Date of birth" htmlFor="g-dob" hint={age !== null ? `You're ${age}.` : "Lets reports show ages, not just years."}>
                  <input id="g-dob" type="date" className="sm-field" value={form.dob} max={new Date().toISOString().slice(0, 10)} onChange={(e) => set("dob", e.target.value)} />
                </Field>
                <Field label="Years this money stays invested" htmlFor="g-horizon" hint="Leave empty to use years until retirement. Under 3 years, the app doesn't show market-timing context.">
                  <input
                    id="g-horizon"
                    inputMode="numeric"
                    className="sm-field"
                    placeholder={String(form.years)}
                    value={form.horizon}
                    onChange={(e) => set("horizon", e.target.value.replace(/[^0-9]/g, "").slice(0, 2))}
                  />
                </Field>
                <Field label="Monthly expenses" htmlFor="g-expenses">
                  <div className="relative">
                    <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted">₹</span>
                    <input
                      id="g-expenses"
                      inputMode="numeric"
                      className="sm-field pl-7"
                      value={form.expenses}
                      onChange={(e) => set("expenses", formatIndianNumberInput(e.target.value))}
                    />
                  </div>
                </Field>
                <Field
                  label="Emergency buffer, in months of expenses"
                  htmlFor="g-buffer"
                  hint={expenses && bufferMonths ? <>That&apos;s <Money value={expenses * bufferMonths} className="font-medium text-ink" />.</> : undefined}
                >
                  <input
                    id="g-buffer"
                    inputMode="numeric"
                    className="sm-field"
                    placeholder="6"
                    value={form.bufferMonths}
                    onChange={(e) => set("bufferMonths", e.target.value.replace(/[^0-9]/g, "").slice(0, 2))}
                  />
                </Field>
              </div>
            </Card>

            <div className={`sticky bottom-3 z-10 flex items-center justify-between gap-3 rounded-[16px] border px-4 py-3 transition-all ${dirty ? "border-line bg-surface shadow-[var(--shadow-pop)]" : "border-transparent"}`}>
              <p className="text-[13px] text-muted">{dirty ? "You have unsaved changes" : "All changes saved"}</p>
              <div className="flex gap-2">
                {dirty && (
                  <Button variant="ghost" size="sm" onClick={discard}>
                    Discard
                  </Button>
                )}
                <Button size="sm" onClick={save} loading={saving} disabled={!dirty} icon={<Save className="h-3.5 w-3.5" strokeWidth={2.2} />}>
                  Save goals
                </Button>
              </div>
            </div>
          </div>

          <div className="space-y-4 lg:sticky lg:top-0 lg:col-span-7">
            <Card
              title="Will the money last?"
              subtitle={assumptions ? `${assumptions.simulations} simulated market paths, from today to ${assumptions.retirement_years} years into retirement` : "Simulated market paths"}
              action={
                <Segmented
                  size="sm"
                  ariaLabel="Allocation used for the projection"
                  value={mix}
                  onChange={setMix}
                  items={[
                    { value: "current", label: "Current mix" },
                    { value: "target", label: "Target mix" },
                  ]}
                />
              }
            >
              {metrics.totalValue <= 0 ? (
                <p className="text-[13.5px] text-muted">Add an account with some money in it to project your retirement.</p>
              ) : assumptionsError ? (
                <p className="text-[13.5px] text-bad">Couldn&apos;t load the projection assumptions: {assumptionsError}</p>
              ) : !projection ? (
                <Skeleton className="h-[420px]" />
              ) : projection ? (
                <>
                  <div className="grid gap-5 sm:grid-cols-[auto_1fr] sm:items-center">
                    <div className="flex flex-col items-center">
                      <Gauge value={success} size={150} color={gaugeColor} label="of paths succeed" />
                      <Badge tone={outlook.tone} className="-mt-1">
                        {outlook.label}
                      </Badge>
                    </div>
                    <dl className="grid grid-cols-2 gap-3">
                      <div className="sm-inset p-3.5">
                        <dt className="text-[12px] text-muted">Median pot at retirement</dt>
                        <dd className="mt-1 font-display text-[22px] font-semibold tracking-[-0.02em] text-ink">
                          <Money value={projection.medianAtRetirement} compact />
                        </dd>
                      </div>
                      <div className="sm-inset p-3.5">
                        <dt className="text-[12px] text-muted">Income it supports</dt>
                        <dd className="mt-1 font-display text-[22px] font-semibold tracking-[-0.02em] text-ink">
                          <Money value={projection.sustainableIncome} compact />
                          <span className="text-[12px] font-medium text-muted">/yr</span>
                        </dd>
                      </div>
                      <div className="sm-inset p-3.5">
                        <dt className="text-[12px] text-muted">Poor markets (p10)</dt>
                        <dd className="mt-1 text-[16px] font-semibold text-ink">
                          <Money value={projection.p10AtRetirement} compact />
                        </dd>
                      </div>
                      <div className="sm-inset p-3.5">
                        <dt className="text-[12px] text-muted">Good markets (p90)</dt>
                        <dd className="mt-1 text-[16px] font-semibold text-ink">
                          <Money value={projection.p90AtRetirement} compact />
                        </dd>
                      </div>
                    </dl>
                  </div>

                  <div className="mt-6">
                    <FanChart points={projection.points} retireAt={form.years} />
                    <div className="mt-2 flex flex-wrap gap-4 text-[12px] text-muted">
                      <span className="flex items-center gap-1.5">
                        <span className="h-0.5 w-4 rounded bg-ink" /> Median path
                      </span>
                      <span className="flex items-center gap-1.5">
                        <span className="h-2.5 w-4 rounded-sm bg-accent/40" /> 80% of outcomes
                      </span>
                    </div>
                  </div>

                  <p className="mt-5 rounded-xl bg-sunken px-3.5 py-3 text-[13px] leading-6 text-ink-2">
                    {projection.sustainableIncome >= form.income ? (
                      <>
                        The median outcome supports about <Money value={projection.sustainableIncome} compact className="font-semibold text-ink" /> a year, above your{" "}
                        <Money value={form.income} compact className="font-semibold text-ink" /> goal.
                      </>
                    ) : (
                      <>
                        The median outcome supports about <Money value={projection.sustainableIncome} compact className="font-semibold text-ink" /> a year, short of your{" "}
                        <Money value={form.income} compact className="font-semibold text-ink" /> goal. Try a larger SIP or a later retirement on the sliders to see how the gap changes.
                      </>
                    )}
                  </p>
                </>
              ) : null}
            </Card>

            <details className="sm-card group px-5 py-4">
              <summary className="flex cursor-pointer list-none items-center gap-2 text-[13.5px] font-semibold text-ink">
                <Info className="h-4 w-4 text-muted" strokeWidth={2} />
                How this is calculated
                <span className="ml-auto text-[12.5px] font-normal text-muted group-open:hidden">Show</span>
              </summary>
              {assumptions && (
                <div className="mt-4 grid gap-x-6 gap-y-2 text-[13px] text-ink-2 sm:grid-cols-2">
                  <p>Equity returns {formatPct(assumptions.classes.equity.mean * 100, 0)} a year, ±{formatPct(assumptions.classes.equity.std * 100, 0)}</p>
                  <p>Fixed income {formatPct(assumptions.classes.fixed_income.mean * 100, 0)}, ±{formatPct(assumptions.classes.fixed_income.std * 100, 0)}</p>
                  <p>Commodities {formatPct(assumptions.classes.commodities.mean * 100, 0)}, ±{formatPct(assumptions.classes.commodities.std * 100, 0)}</p>
                  <p>Cash {formatPct(assumptions.classes.cash.mean * 100, 0)}, no volatility</p>
                  <p>Inflation {formatPct(assumptions.inflation * 100, 0)} on withdrawals</p>
                  <p>{assumptions.retirement_years}-year retirement, success = money never runs out</p>
                </div>
              )}
              <p className="mt-4 text-[12.5px] leading-5 text-muted">
                The same model the Retirement agent runs, starting from your current portfolio value. It shows a range of possibilities, not a
                forecast or advice.
              </p>
            </details>
          </div>
        </div>
      )}
    </Layout>
  );
}
