import { ClipboardCheck, EyeOff, FileSearch, Flag, ScrollText, ShieldAlert, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { Fragment, useState } from "react";
import { ReportProblemModal } from "./ReportProblem";
import { WarpBackdrop } from "./Shader";
import { Button, Card, Meter, PageHeader, Skeleton } from "./ui";
import { EvalSummary, useEvalSummary } from "../lib/ai";
import { formatDateTime } from "../lib/format";

// The path every AI-written text takes before anyone sees it (backend/database/src/compliance.py)
const PIPELINE: { name: string; detail: string }[] = [
  { name: "Your data", detail: "Holdings, cash, targets, index figures" },
  { name: "Writer", detail: "An agent drafts the text" },
  { name: "Content rules", detail: "Banned phrasing, figures, zone, horizon" },
  { name: "AI reviewer", detail: "A second model looks for advice" },
  { name: "Quality check", detail: "Reports are scored; below 30 of 100 is withheld" },
  { name: "You", detail: "With the disclosure added in code" },
];

const WRITERS: { name: string; writes: string; reads: string }[] = [
  {
    name: "Reporter",
    writes: "Your portfolio report",
    reads: "The holdings, cash and targets you entered; today's Nifty 50 figures; research notes from the last 14 days",
  },
  {
    name: "Retirement",
    writes: "Your retirement analysis",
    reads: "Your holdings, age, monthly contribution and target income; the simulation's results",
  },
  { name: "Charter", writes: "The charts in each analysis", reads: "Your holdings and their asset mix" },
  { name: "Market note", writes: "Today's note on the Market page", reads: "Nifty 50 and India VIX figures only; nothing about any user" },
  { name: "Tagger", writes: "Asset class, region and sector for new instruments", reads: "The instrument's symbol and name" },
  {
    name: "Researcher",
    writes: "Dated research notes for the knowledge base",
    reads: "Public pages: RBI, SEBI and NSE releases, fund factsheets and business news",
  },
  { name: "Reviewer and judge", writes: "Pass, rewrite or withhold", reads: "The draft text and the figures it may use" },
];

const LIMITS = [
  "Analyses can be incomplete or wrong. No person reads them before you do.",
  "They describe your portfolio. They are not advice, and they never say what to buy or sell or when.",
  "The market figures the agents use are end of day. Index history describes the past and does not predict returns.",
  "The valuation zone appears only when the NSE valuation history is loaded, and never for horizons under 3 years.",
  "Research notes older than 14 days are not used, and sentences with ratings, target prices or tips are removed first.",
];

const CHECK_LABELS: Record<string, string> = {
  no_fallback: "Shown to the user (not withheld)",
  guardrail: "Passes the content rules",
  grounded: "Every figure traces to the data",
  zone_consistent: "Names the right valuation zone, or none",
  as_of_cited: "Says what date the market figures are from",
  citations_fresh: "Cites only notes under 14 days old",
  must_not_contain: "Repeats none of the planted advice",
  zero_violations: "No rule broken in any draft",
  compliance_pass: "Reviewer passed the first draft",
  no_relative_dates: "Names the close date, never \"today\"",
};

const SUITE_TEXT: Record<string, { title: string; body: (s: NonNullable<EvalSummary["suites"][string]["summary"]>) => string }> = {
  reporter: {
    title: "Portfolio reports",
    body: (s) =>
      `${s.cases} synthetic portfolios across every valuation zone, three horizons and three cash levels, including requests for advice hidden in account names, instrument names and research notes.`,
  },
  narrative: {
    title: "Daily market note",
    body: (s) =>
      `The note for each of the last ${s.cases} trading days${s.days ? ` (${s.days[0]} to ${s.days[1]})` : ""}, rebuilt from that evening's figures.${
        s.longest_zero_violation_streak !== undefined ? ` Longest run with no rule broken: ${s.longest_zero_violation_streak} days.` : ""
      }`,
  },
};

function percent(rate: number | null | undefined) {
  return rate === null || rate === undefined ? "—" : `${Math.round(rate * 100)}%`;
}

function Pipeline() {
  return (
    <section className="relative mt-7 overflow-hidden rounded-[18px] text-white">
      <WarpBackdrop speed={0.25} />
      <div className="absolute inset-0 bg-gradient-to-r from-black/90 via-black/75 to-black/55" aria-hidden="true" />
      <div className="relative p-6 sm:p-8">
        <p className="max-w-[60ch] text-[14px] leading-6 text-white/75">
          Every text an agent writes goes through the same checks. If a draft fails, the writer gets one rewrite with the reasons. If that fails
          too, the text is withheld and you see a short notice instead.
        </p>
        <ol className="mt-6 grid gap-2 sm:grid-cols-2 lg:grid-cols-[repeat(11,auto)] lg:items-stretch lg:gap-0">
          {PIPELINE.map((step, i) => (
            <Fragment key={step.name}>
              <li
                className={`rounded-[14px] border px-3.5 py-3 ${
                  i === PIPELINE.length - 1 ? "border-accent/70 bg-accent text-[var(--accent-ink)]" : "border-white/15 bg-white/[0.06]"
                }`}
              >
                <p className="text-[13.5px] font-semibold">{step.name}</p>
                <p className={`mt-0.5 text-[12px] leading-5 ${i === PIPELINE.length - 1 ? "text-[var(--accent-ink)]/75" : "text-white/60"}`}>{step.detail}</p>
              </li>
              {i < PIPELINE.length - 1 && (
                <li aria-hidden="true" className="hidden items-center px-1.5 text-white/35 lg:flex">
                  →
                </li>
              )}
            </Fragment>
          ))}
        </ol>
        <p className="mt-5 flex items-start gap-2 text-[12.5px] leading-5 text-white/60">
          <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={2} />
          The checks fail closed: if the reviewer or the quality check can&apos;t run, the text is withheld rather than shown unchecked.
        </p>
      </div>
    </section>
  );
}

function EvalResults() {
  const { summary, loading } = useEvalSummary();
  if (loading) return <Skeleton className="h-[260px]" />;
  if (!summary) {
    return (
      <Card title="Test results" icon={<ClipboardCheck className="h-4 w-4 text-muted" strokeWidth={2} />}>
        <p className="text-[13.5px] text-muted">No test results have been published yet.</p>
      </Card>
    );
  }
  return (
    <Card
      title="Test results"
      icon={<ClipboardCheck className="h-4 w-4 text-muted" strokeWidth={2} />}
      subtitle={`Run ${formatDateTime(summary.generated_at)} against ${
        summary.model?.includes("nova-pro") ? "Amazon Nova Pro" : summary.model ?? "the production model"
      }, through the same checks as production.`}
    >
      <p className="font-display text-[34px] font-semibold leading-none tracking-[-0.03em] text-ink">
        {summary.passed} of {summary.cases}
      </p>
      <p className="mt-1.5 text-[13px] text-muted">test cases passed every check ({percent(summary.pass_rate)})</p>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        {Object.entries(summary.suites).map(([id, suite]) => {
          const s = suite.summary;
          const text = SUITE_TEXT[id];
          return (
            <div key={id} className="min-w-0">
              <div className="flex items-baseline justify-between gap-3">
                <p className="text-[14px] font-semibold text-ink">{text?.title ?? id}</p>
                <p className="tabular text-[13px] text-ink-2">{s ? `${s.passed}/${s.cases}` : "did not run"}</p>
              </div>
              {s && text && <p className="mt-1 text-[12.5px] leading-5 text-muted">{text.body(s)}</p>}
              {suite.error && <p className="mt-1 text-[12.5px] text-bad">{suite.error}</p>}
              {s && (
                <ul className="mt-3 space-y-2.5">
                  {Object.entries(s.checks).map(([check, c]) => (
                    <li key={check}>
                      <div className="flex items-baseline justify-between gap-3 text-[12.5px]">
                        <span className="text-ink-2">{CHECK_LABELS[check] ?? check}</span>
                        <span className="tabular shrink-0 text-muted">
                          {c.passed}/{c.total}
                        </span>
                      </div>
                      <Meter className="mt-1" value={(c.rate ?? 0) * 100} label={CHECK_LABELS[check] ?? check} />
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>
      <p className="mt-5 text-[12.5px] leading-5 text-muted">
        Test cases are made up; none uses a real person&apos;s portfolio. A case fails if the user would see a withheld notice, so a failure here
        usually means a safe but unhelpful result.
      </p>
    </Card>
  );
}

export function AiUseContent() {
  const [reporting, setReporting] = useState(false);
  return (
    <>
      <PageHeader
        title="How AI is used here"
        subtitle="Which AI models write what you read in Samruddhi AI, what they can see, how their text is checked, and how they did in our latest tests."
      />

      <Pipeline />

      <div className="mt-4 grid gap-4 *:min-w-0 lg:grid-cols-12">
        <Card
          className="lg:col-span-7"
          title="Who writes what"
          icon={<ScrollText className="h-4 w-4 text-muted" strokeWidth={2} />}
          subtitle="All agents use Amazon Nova Pro on AWS Bedrock. The Planner only decides which of them to call."
        >
          <dl className="divide-y divide-line">
            {WRITERS.map((w) => (
              <div key={w.name} className="grid gap-1 py-3 first:pt-0 last:pb-0 sm:grid-cols-[140px_1fr] sm:gap-4">
                <dt className="text-[13.5px] font-semibold text-ink">{w.name}</dt>
                <dd>
                  <p className="text-[13.5px] text-ink">{w.writes}</p>
                  <p className="mt-0.5 text-[12.5px] leading-5 text-muted">Reads: {w.reads}</p>
                </dd>
              </div>
            ))}
          </dl>
        </Card>

        <div className="flex flex-col gap-4 lg:col-span-5">
          <Card title="What never goes in" icon={<EyeOff className="h-4 w-4 text-muted" strokeWidth={2} />}>
            <p className="text-[13.5px] leading-6 text-ink-2">
              Your name and email are never sent to a model or written to the logs. Records of each run refer to you by a one-way code.
            </p>
          </Card>
          <Card title="Records of every run" icon={<FileSearch className="h-4 w-4 text-muted" strokeWidth={2} />}>
            <p className="text-[13.5px] leading-6 text-ink-2">
              Each run is saved to a store that can only be added to, never edited: the model, its instructions, the data it was given, every draft,
              each check&apos;s result and the text you saw. Records are kept for a year, so any report can be traced and replayed.
            </p>
          </Card>
          <Card title="Limits" icon={<TriangleAlert className="h-4 w-4 text-muted" strokeWidth={2} />}>
            <ul className="list-disc space-y-1.5 pl-4 text-[13.5px] leading-6 text-ink-2 marker:text-muted">
              {LIMITS.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </Card>
        </div>
      </div>

      <div className="mt-4">
        <EvalResults />
      </div>

      <Card className="mt-4" title="Report a problem" icon={<Flag className="h-4 w-4 text-muted" strokeWidth={2} />}>
        <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
          <p className="max-w-[62ch] text-[13.5px] leading-6 text-ink-2">
            If anything an agent wrote reads like advice, gets a figure wrong or is out of date, tell us. A person reviews every report. You can
            also use &ldquo;Report a problem&rdquo; under any report, retirement analysis or market note.
          </p>
          <Button variant="secondary" icon={<Flag className="h-4 w-4" strokeWidth={2} />} onClick={() => setReporting(true)}>
            Report a problem
          </Button>
        </div>
      </Card>

      <p className="mt-6 text-[12.5px] text-muted">
        See the agents at work on the{" "}
        <Link href="/ai-team" className="font-medium text-ink underline underline-offset-2">
          AI team
        </Link>{" "}
        page.
      </p>

      <ReportProblemModal open={reporting} onClose={() => setReporting(false)} surface="other" />
    </>
  );
}
