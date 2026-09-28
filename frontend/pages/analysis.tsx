import { AlertTriangle, BarChart3, CheckCircle2, Clock, Download, FileText, Flag, Loader2, Printer, Receipt, Table2, Target } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/router";
import { Children, isValidElement, ReactNode, useEffect, useMemo, useState } from "react";
import ReactMarkdown, { Components } from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { Columns, DonutWithLegend, HBarList, OTHER_COLOR, SERIES, Slice, SliceTable } from "../components/charts";
import Layout from "../components/Layout";
import { ReportProblemButton } from "../components/ReportProblem";
import { Badge, Button, Card, EmptyState, JobStatusBadge, LinkButton, Money, PageHeader, Segmented, Skeleton } from "../components/ui";
import { AGENTS, ChartSpec, isScheduled, Job, jobDurationMs, normalizeJob, outputsOf, queueWaitMs } from "../lib/agents";
import { useAnalysis } from "../lib/analysis-context";
import { formatDateTime, formatDuration, parseServerDate } from "../lib/format";
import { useApi } from "../lib/http";
import { formatMarketDate } from "../lib/market";
import { usePortfolio } from "../lib/portfolio-context";
import { readingMinutes, slugify, tableOfContents } from "../lib/report";

type Tab = "report" | "charts" | "retirement" | "details";
const TABS: Tab[] = ["report", "charts", "retirement", "details"];

function textOf(node: ReactNode): string {
  return Children.toArray(node)
    .map((child) => (typeof child === "string" || typeof child === "number" ? String(child) : isValidElement(child) ? textOf((child.props as { children?: ReactNode }).children) : ""))
    .join("");
}

/** Markdown renderer whose heading ids match tableOfContents() */
function Markdown({ content }: { content: string }) {
  const seen = new Map<string, number>();
  const headingId = (children: ReactNode) => {
    const base = slugify(textOf(children)) || "section";
    const count = seen.get(base) ?? 0;
    seen.set(base, count + 1);
    return count ? `${base}-${count}` : base;
  };
  const components: Components = {
    h2: ({ children }) => <h2 id={headingId(children)}>{children}</h2>,
    h3: ({ children }) => <h3 id={headingId(children)}>{children}</h3>,
    table: ({ children }) => (
      <div className="sm-table-wrap">
        <table>{children}</table>
      </div>
    ),
  };
  return (
    <div className="sm-prose">
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkBreaks]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}

function download(filename: string, content: string) {
  const url = URL.createObjectURL(new Blob([content], { type: "text/markdown;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Agent chart data → slices in fixed palette order; the tail past six folds into "Other" */
function chartSlices(spec: ChartSpec): Slice[] {
  const rows = (spec.data ?? []).filter((d) => Number(d.value) > 0).map((d) => ({ name: String(d.name), value: Number(d.value) }));
  rows.sort((a, b) => b.value - a.value);
  const head = rows.length > 6 ? rows.slice(0, 5) : rows;
  const slices: Slice[] = head.map((r, i) => ({ key: `${r.name}-${i}`, label: r.name, value: r.value, color: SERIES[i] }));
  if (rows.length > 6) {
    slices.push({ key: "other", label: `${rows.length - 5} others`, value: rows.slice(5).reduce((s, r) => s + r.value, 0), color: OTHER_COLOR });
  }
  return slices;
}

function AgentChart({ id, spec }: { id: string; spec: ChartSpec }) {
  const [mode, setMode] = useState<"chart" | "table">("chart");
  const slices = chartSlices(spec);
  const total = slices.reduce((s, x) => s + x.value, 0);
  const type = spec.type ?? "bar";
  const title = spec.title || id.split("_").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");

  if (!slices.length) return null;

  return (
    <Card
      title={title}
      subtitle={spec.description}
      action={
        <Segmented
          size="sm"
          ariaLabel={`${title} view`}
          value={mode}
          onChange={setMode}
          items={[
            { value: "chart", label: "Chart", icon: <BarChart3 className="h-3 w-3" strokeWidth={2.2} /> },
            { value: "table", label: "Table", icon: <Table2 className="h-3 w-3" strokeWidth={2.2} /> },
          ]}
        />
      }
    >
      {mode === "table" ? (
        <SliceTable slices={slices} />
      ) : type === "pie" || type === "donut" ? (
        <DonutWithLegend
          slices={slices}
          size={170}
          center={
            <>
              <Money value={total} compact className="font-display text-[18px] font-semibold text-ink" />
              <span className="text-[11px] text-muted">total</span>
            </>
          }
        />
      ) : type === "horizontalBar" || slices.length > 6 ? (
        <HBarList items={slices.map((s) => ({ key: s.key, label: s.label, value: s.value, color: s.color }))} total={total} valueFormat="money" />
      ) : (
        <>
          <Columns slices={slices} />
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink-2">
            {slices.map((s) => (
              <span key={s.key} className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: s.color }} />
                {s.label}
              </span>
            ))}
          </div>
        </>
      )}
    </Card>
  );
}

interface ReadingLayoutProps {
  content: string;
  agent: string;
  generatedAt?: string;
  chips?: ReactNode;
  aside?: ReactNode;
}

/** Where the report's market figures and research came from */
function ReportChips({ payload }: { payload: NonNullable<Job["report_payload"]> }) {
  const market = payload.market;
  const sources = payload.citations?.length ?? 0;
  return (
    <>
      {market?.available && market.context_allowed && market.as_of && (
        <span className="sm-chip">Market figures as of {formatMarketDate(market.as_of)}</span>
      )}
      {sources > 0 && (
        <span className="sm-chip">
          {sources} dated source{sources === 1 ? "" : "s"}
        </span>
      )}
    </>
  );
}

/** Cited notes as links, and the way to flag a problem */
function ReportFooter({ payload, jobId, surface }: { payload?: Job["report_payload"]; jobId: string; surface: "report" | "retirement" }) {
  const citations = payload?.citations ?? [];
  return (
    <div className="mt-8 border-t border-line pt-5">
      {citations.length > 0 && (
        <div className="mb-4">
          <p className="text-[12.5px] font-medium text-muted">Research cited in this report</p>
          <ol className="mt-2 space-y-1.5 text-[13px] leading-5 text-ink-2">
            {citations.map((c) => (
              <li key={c.n} className="flex gap-2">
                <span className="tabular shrink-0 text-muted">[{c.n}]</span>
                <span className="min-w-0">
                  {c.url ? (
                    <a href={c.url} target="_blank" rel="noopener noreferrer" className="font-medium text-ink underline underline-offset-2">
                      {c.title}
                    </a>
                  ) : (
                    <span className="font-medium text-ink">{c.title}</span>
                  )}
                  , {c.source_name}
                  {c.published ? `, ${formatMarketDate(c.published)}` : ""}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[12.5px] leading-5 text-muted">
          Checked by content rules, an AI reviewer and a quality check before it was shown.{" "}
          <Link href="/ai-use" className="underline underline-offset-2 hover:text-ink">
            How AI is used here
          </Link>
        </p>
        <ReportProblemButton surface={surface} jobId={jobId} />
      </div>
    </div>
  );
}

function ReadingLayout({ content, agent, generatedAt, chips, aside }: ReadingLayoutProps) {
  const toc = useMemo(() => tableOfContents(content), [content]);
  const [activeId, setActiveId] = useState<string | null>(null);

  // Highlight the section being read
  useEffect(() => {
    if (!toc.length) return;
    const root = document.getElementById("main");
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActiveId(visible[0].target.id);
      },
      { root, rootMargin: "0px 0px -70% 0px" },
    );
    toc.forEach((t) => {
      const el = document.getElementById(t.id);
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, [toc]);

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_240px]">
      <article className="sm-card px-6 py-7 sm:px-10 sm:py-9">
        <div className="mb-7 flex flex-wrap items-center gap-2 border-b border-line pb-5 text-[12.5px] text-muted">
          <span className="sm-chip bg-accent-soft text-accent-text">Written by the {agent} agent</span>
          <span className="sm-chip">{readingMinutes(content)} min read</span>
          {generatedAt && <span className="sm-chip">{formatDateTime(generatedAt)}</span>}
          {chips}
        </div>
        <Markdown content={content} />
        {aside}
      </article>
      {toc.length > 1 && (
        <nav aria-label="On this page" className="sm-no-print hidden lg:block">
          <div className="sticky top-0 rounded-[18px] border border-line bg-surface p-4">
            <p className="mb-2 text-[12px] font-medium text-muted">On this page</p>
            <ul className="space-y-0.5">
              {toc.map((t) => (
                <li key={t.id}>
                  <button
                    onClick={() => document.getElementById(t.id)?.scrollIntoView({ behavior: "smooth", block: "start" })}
                    className={`block w-full truncate rounded-lg px-2 py-1.5 text-left text-[12.5px] transition-colors ${t.level === 3 ? "pl-5" : ""} ${
                      activeId === t.id ? "bg-accent-soft font-semibold text-ink" : "text-ink-2 hover:bg-sunken hover:text-ink"
                    }`}
                  >
                    {t.text}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </nav>
      )}
    </div>
  );
}

export default function Analysis() {
  const router = useRouter();
  const api = useApi();
  const { jobs, jobsLoaded, startAnalysis, starting, activeJob } = useAnalysis();
  const { metrics, loading: portfolioLoading } = usePortfolio();
  // The Planner skips the Reporter and Charter when there are no positions
  const cashOnly = !portfolioLoading && metrics.holdings.length === 0;
  const addHoldings = (
    <LinkButton href="/accounts" size="sm">
      Add holdings
    </LinkButton>
  );
  const [fetched, setFetched] = useState<Job | null>(null);
  const [notFound, setNotFound] = useState(false);

  const jobId = typeof router.query.job_id === "string" ? router.query.job_id : null;
  const tabParam = typeof router.query.tab === "string" && TABS.includes(router.query.tab as Tab) ? (router.query.tab as Tab) : "report";
  const [tab, setTab] = useState<Tab>(tabParam);
  useEffect(() => setTab(tabParam), [tabParam]);

  const completed = jobs.filter((j) => j.status === "completed");
  const fromList = jobId ? jobs.find((j) => j.id === jobId) : completed[0];
  const job = fromList ?? (fetched?.id === jobId ? fetched : null);

  // Older reports fall outside the jobs list — fetch them directly
  useEffect(() => {
    if (!jobId || !jobsLoaded || jobs.some((j) => j.id === jobId)) return;
    api<unknown>(`/api/jobs/${jobId}`)
      .then((raw) => setFetched(normalizeJob(raw)))
      .catch(() => setNotFound(true));
  }, [jobId, jobsLoaded, jobs, api]);

  const pickReport = (id: string) => router.push({ pathname: "/analysis", query: { job_id: id, tab } }, undefined, { shallow: true });
  const changeTab = (next: Tab) => {
    setTab(next);
    router.replace({ pathname: "/analysis", query: { ...(job ? { job_id: job.id } : {}), tab: next } }, undefined, { shallow: true });
  };

  const out = job ? outputsOf(job) : null;
  const charts = job?.charts_payload ? Object.entries(job.charts_payload) : [];

  const tabs = (
    <Segmented
      ariaLabel="Report sections"
      value={tab}
      onChange={changeTab}
      layoutId="report-tab"
      items={[
        { value: "report", label: "Report", icon: <FileText className="h-3.5 w-3.5" strokeWidth={2} /> },
        { value: "charts", label: `Charts${charts.length ? ` ${charts.length}` : ""}`, icon: <BarChart3 className="h-3.5 w-3.5" strokeWidth={2} /> },
        { value: "retirement", label: "Retirement", icon: <Target className="h-3.5 w-3.5" strokeWidth={2} /> },
        { value: "details", label: "Run details", icon: <Receipt className="h-3.5 w-3.5" strokeWidth={2} /> },
      ]}
    />
  );

  if (!jobsLoaded || (jobId && !job && !notFound)) {
    return (
      <Layout title="Reports">
        <Skeleton className="h-12 w-1/2" />
        <Skeleton className="mt-6 h-[520px]" />
      </Layout>
    );
  }

  if (!job) {
    return (
      <Layout title="Reports">
        <PageHeader title="Reports" subtitle="Every analysis the AI team finishes is kept here." />
        <div className="sm-card mt-7">
          <EmptyState
            icon={<FileText className="h-5 w-5" strokeWidth={2} />}
            title={notFound ? "That report doesn't exist" : "No reports yet"}
            body={notFound ? "It may belong to another account, or the link is incomplete." : "Run an analysis and the team writes a report, draws charts and projects your retirement. It takes a few minutes."}
            action={
              <Button onClick={() => startAnalysis().then(() => router.push("/ai-team"))} loading={starting} disabled={Boolean(activeJob && (activeJob.status === "running" || activeJob.status === "pending"))}>
                Run analysis
              </Button>
            }
          />
        </div>
      </Layout>
    );
  }

  const when = job.completed_at ?? job.created_at;

  return (
    <Layout title="Report" tabs={tabs}>
      <PageHeader
        title="Portfolio review"
        subtitle={
          <>
            {isScheduled(job) ? "Scheduled review" : "Requested by you"}, finished {parseServerDate(when).toLocaleString("en-IN", { dateStyle: "long", timeStyle: "short" })}
          </>
        }
        actions={
          <>
            {completed.length > 1 && (
              <select
                aria-label="Choose a report"
                value={job.id}
                onChange={(e) => pickReport(e.target.value)}
                className="sm-field !h-10 !w-auto pr-8 text-[13px]"
              >
                {completed.map((j) => (
                  <option key={j.id} value={j.id}>
                    {formatDateTime(j.completed_at ?? j.created_at)}
                  </option>
                ))}
              </select>
            )}
            {job.report_payload?.content && (
              <Button
                variant="secondary"
                icon={<Download className="h-4 w-4" strokeWidth={2} />}
                onClick={() => download(`samruddhi-report-${when.slice(0, 10)}.md`, `${job.report_payload?.content ?? ""}\n\n---\n\n${job.retirement_payload?.analysis ?? ""}`)}
              >
                Markdown
              </Button>
            )}
            <Button variant="secondary" icon={<Printer className="h-4 w-4" strokeWidth={2} />} onClick={() => window.print()}>
              Print
            </Button>
          </>
        }
      />

      {job.status !== "completed" && (
        <div className={`mt-6 flex items-start gap-3 rounded-[16px] px-4 py-3.5 text-[13.5px] ${job.status === "failed" ? "bg-bad-soft text-bad" : "bg-accent-soft text-ink"}`}>
          {job.status === "failed" ? <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2} /> : <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin" strokeWidth={2} />}
          <p className="flex-1">
            {job.status === "failed"
              ? `This run failed${job.error_message ? `: ${job.error_message}` : "."} Anything the agents finished before that is shown below.`
              : "This run is still in progress. Sections appear as each agent delivers."}
          </p>
          <Link href="/ai-team" className="shrink-0 font-semibold underline underline-offset-4">
            {job.status === "failed" ? "See where it stopped" : "Watch live"}
          </Link>
        </div>
      )}

      <div className="mt-6">
        {tab === "report" &&
          (job.report_payload?.content ? (
            <ReadingLayout
              content={job.report_payload.content}
              agent={AGENTS.reporter.name}
              generatedAt={job.report_payload.generated_at}
              chips={<ReportChips payload={job.report_payload} />}
              aside={<ReportFooter payload={job.report_payload} jobId={job.id} surface="report" />}
            />
          ) : (
            <div className="sm-card">
              {cashOnly ? (
                <EmptyState
                  title="No written report in this run"
                  body="Your accounts hold only cash, so there were no holdings to review. Add a holding to an account, then run a fresh analysis."
                  action={addHoldings}
                />
              ) : (
                <EmptyState title="No written report in this run" body="The Reporter didn't return a report for this run. Check Run details, or run a fresh analysis." />
              )}
            </div>
          ))}

        {tab === "charts" &&
          (charts.length ? (
            <>
              <p className="mb-4 text-[13px] text-muted">
                Designed by the {AGENTS.charter.name} agent from your holdings. Colours follow this app&apos;s palette; switch any chart to a table for exact figures.
              </p>
              <div className="grid gap-4 lg:grid-cols-2">
                {charts.map(([key, spec]) => (
                  <AgentChart key={key} id={key} spec={spec} />
                ))}
              </div>
            </>
          ) : (
            <div className="sm-card">
              {cashOnly ? (
                <EmptyState title="No charts in this run" body="Charts are drawn from your holdings, and your accounts hold only cash." action={addHoldings} />
              ) : (
                <EmptyState title="No charts in this run" body="The Charter didn't return charts for this run." />
              )}
            </div>
          ))}

        {tab === "retirement" &&
          (job.retirement_payload?.analysis ? (
            <div className="space-y-4">
              <div className="flex flex-col items-start justify-between gap-3 rounded-[18px] border border-line bg-surface px-5 py-4 sm:flex-row sm:items-center">
                <p className="text-[13.5px] text-ink-2">Want to test other numbers? The Goals page runs the same simulation live as you move the sliders.</p>
                <LinkButton href="/goals" variant="secondary" size="sm" icon={<Flag className="h-3.5 w-3.5" strokeWidth={2} />}>
                  Open Goals
                </LinkButton>
              </div>
              <ReadingLayout
                content={job.retirement_payload.analysis}
                agent={AGENTS.retirement.name}
                generatedAt={job.retirement_payload.generated_at}
                aside={<ReportFooter jobId={job.id} surface="retirement" />}
              />
            </div>
          ) : (
            <div className="sm-card">
              <EmptyState title="No retirement projection in this run" body="The Retirement agent didn't deliver for this run." />
            </div>
          ))}

        {tab === "details" && (
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Timeline" icon={<Clock className="h-4 w-4 text-muted" strokeWidth={2} />}>
              <ol className="relative space-y-5 border-l border-line pl-5">
                {[
                  { label: "Requested", at: job.created_at, note: isScheduled(job) ? "By the 2-hourly price refresh" : "By you" },
                  { label: "Picked up by the Planner", at: job.started_at, note: `Waited ${formatDuration(queueWaitMs(job))} in the queue` },
                  { label: job.status === "failed" ? "Failed" : "Finished", at: job.completed_at, note: `Agents worked for ${formatDuration(jobDurationMs(job))}` },
                ].map((step) => (
                  <li key={step.label} className="relative">
                    <span className={`absolute -left-[26px] top-1 h-3 w-3 rounded-full ring-4 ring-surface ${step.at ? "bg-ink" : "bg-line-strong"}`} />
                    <p className="text-[13.5px] font-semibold text-ink">{step.label}</p>
                    <p className="text-[12.5px] text-muted">
                      {step.at ? formatDateTime(step.at) : "Not yet"}
                      {step.at && `, ${step.note.charAt(0).toLowerCase()}${step.note.slice(1)}`}
                    </p>
                  </li>
                ))}
              </ol>
            </Card>
            <Card title="Outputs" subtitle="What each specialist delivered">
              <ul className="space-y-3">
                {[
                  { agent: AGENTS.reporter, ok: out?.report, detail: job.report_payload?.content ? `${readingMinutes(job.report_payload.content)} min report` : null },
                  { agent: AGENTS.charter, ok: out?.charts, detail: charts.length ? `${charts.length} charts` : null },
                  { agent: AGENTS.retirement, ok: out?.retirement, detail: job.retirement_payload?.analysis ? "Projection and narrative" : null },
                ].map(({ agent, ok, detail }) => (
                  <li key={agent.id} className="flex items-center justify-between gap-3 rounded-xl bg-sunken px-3.5 py-3">
                    <span>
                      <span className="block text-[13.5px] font-semibold text-ink">{agent.name}</span>
                      <span className="block text-[12.5px] text-muted">{detail ?? "Nothing delivered"}</span>
                    </span>
                    {ok ? (
                      <Badge tone="good" icon={<CheckCircle2 className="h-3.5 w-3.5" strokeWidth={2.2} />}>
                        Delivered
                      </Badge>
                    ) : job.status === "running" || job.status === "pending" ? (
                      <JobStatusBadge status={job.status} />
                    ) : (
                      <Badge>No output</Badge>
                    )}
                  </li>
                ))}
              </ul>
              <p className="mt-4 font-mono text-[11.5px] text-muted">Job {job.id}</p>
            </Card>
          </div>
        )}
      </div>
    </Layout>
  );
}
