import { Activity, ArrowUpRight, Bot, CheckCircle2, Clock, Copy, FileText, History, Play, Radio, Users, XCircle } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import AgentFlow from "../components/AgentFlow";
import { TooltipBox } from "../components/charts";
import Layout from "../components/Layout";
import { WarpBackdrop } from "../components/Shader";
import { showToast } from "../components/Toast";
import { Badge, Card, EmptyState, JobStatusBadge, LinkButton, PageHeader, Segmented, Stat } from "../components/ui";
import { AGENTS, AgentId, FlowNodeId, isActive, isScheduled, Job, jobDurationMs, MODEL_LABEL, outputsOf, progressOf, queueWaitMs, stagesFor } from "../lib/agents";
import { useAnalysis } from "../lib/analysis-context";
import { formatDateTime, formatDuration, formatPct, parseServerDate, timeAgo } from "../lib/format";
import { useNow } from "../lib/hooks";

type View = "live" | "runs" | "team";

const NODE_INFO: Partial<Record<FlowNodeId, { title: string; body: string }>> = {
  trigger: { title: "Trigger", body: "A run starts when you press Run analysis. Price refreshes update prices only; they never start a run." },
  queue: { title: "Job queue", body: "Requests wait in an SQS queue so a burst of runs never overloads the agents. The Planner picks jobs up one at a time." },
  knowledge: { title: "Knowledge base", body: "Market research the Researcher has filed, stored as embeddings in S3 Vectors. The Reporter searches it for context on your holdings." },
  results: { title: "Your report", body: "Each specialist writes its output straight to the job's row in Aurora. This page watches those writes to show progress." },
};

function OutputChips({ job }: { job: Job }) {
  const out = outputsOf(job);
  const chip = (ok: boolean, label: string) => (
    <span className={`inline-flex h-6 items-center gap-1 rounded-md px-1.5 text-[11.5px] font-medium ${ok ? "bg-good-soft text-good" : "bg-sunken text-muted line-through decoration-1"}`}>
      {label}
    </span>
  );
  return (
    <span className="inline-flex gap-1">
      {chip(out.report, "Report")}
      {chip(out.charts, "Charts")}
      {chip(out.retirement, "Retirement")}
    </span>
  );
}

function AgentPanel({ id, job }: { id: FlowNodeId; job: Job | null }) {
  const agent = id in AGENTS ? AGENTS[id as AgentId] : null;
  const info = NODE_INFO[id];
  const out = job ? outputsOf(job) : null;
  const deliverable =
    id === "reporter" ? out?.report : id === "charter" ? out?.charts : id === "retirement" ? out?.retirement : undefined;
  const tab = id === "charter" ? "charts" : id === "retirement" ? "retirement" : "report";

  if (!agent && info) {
    return (
      <div>
        <p className="font-display text-[18px] font-semibold text-ink">{info.title}</p>
        <p className="mt-2 text-[13.5px] leading-6 text-ink-2">{info.body}</p>
      </div>
    );
  }
  if (!agent) return null;
  return (
    <div>
      <p className="font-display text-[18px] font-semibold text-ink">{agent.name}</p>
      <p className="mt-1.5 text-[13.5px] leading-6 text-ink-2">{agent.job}</p>
      <dl className="mt-4 space-y-2.5 text-[13px]">
        {[
          ["Runs on", agent.runtime],
          ["Model", MODEL_LABEL],
          ["Works by", agent.mode],
          ["Produces", agent.writes],
        ].map(([k, v]) => (
          <div key={k} className="flex justify-between gap-4 border-b border-line pb-2.5 last:border-0">
            <dt className="text-muted">{k}</dt>
            <dd className="text-right font-medium text-ink">{v}</dd>
          </div>
        ))}
      </dl>
      {deliverable && job && (
        <LinkButton href={`/analysis?job_id=${job.id}&tab=${tab}`} size="sm" variant="secondary" className="mt-4" icon={<FileText className="h-3.5 w-3.5" strokeWidth={2} />}>
          Open what it produced
        </LinkButton>
      )}
    </div>
  );
}

export default function AiTeam() {
  const { jobs, jobsLoaded, activeJob, events, startAnalysis, starting } = useAnalysis();
  const [view, setView] = useState<View>("live");
  const [selected, setSelected] = useState<FlowNodeId | null>("planner");
  const running = isActive(activeJob);
  const now = useNow(1000, running);

  // Show the live run, else the most recent finished one
  const shownJob = activeJob ?? jobs[0] ?? null;
  const stages = stagesFor(shownJob);
  const progress = progressOf(shownJob);

  const finished = jobs.filter((j) => j.status === "completed" || j.status === "failed");
  const succeeded = finished.filter((j) => j.status === "completed");
  const durations = succeeded.map(jobDurationMs).filter((d): d is number => d != null).sort((a, b) => a - b);
  const median = durations.length ? durations[Math.floor(durations.length / 2)] : null;
  const scheduledCount = jobs.filter(isScheduled).length;

  const durationSeries = useMemo(
    () =>
      finished
        .slice(0, 20)
        .reverse()
        .map((j) => ({
          id: j.id,
          label: parseServerDate(j.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" }),
          seconds: Math.max(1, Math.round((jobDurationMs(j) ?? 0) / 1000)),
          status: j.status,
          when: formatDateTime(j.created_at),
        })),
    [finished],
  );

  const elapsed = shownJob && running ? now - parseServerDate(shownJob.created_at).getTime() : shownJob ? jobDurationMs(shownJob) : null;

  return (
    <Layout
      title="AI team"
      tabs={
        <Segmented
          ariaLabel="AI team view"
          value={view}
          onChange={setView}
          layoutId="team-view"
          items={[
            { value: "live", label: "Live", icon: <Radio className="h-3.5 w-3.5" strokeWidth={2} /> },
            { value: "runs", label: "Runs", icon: <History className="h-3.5 w-3.5" strokeWidth={2} /> },
            { value: "team", label: "Team", icon: <Users className="h-3.5 w-3.5" strokeWidth={2} /> },
          ]}
        />
      }
    >
      {/* Run panel — the shader speeds up while agents work */}
      <section className="relative overflow-hidden rounded-[22px] text-white">
        <WarpBackdrop speed={running ? 1.5 : 0.35} />
        <div className="absolute inset-0 bg-gradient-to-r from-black/85 via-black/60 to-black/15" aria-hidden="true" />
        <div className="relative flex flex-col gap-6 px-6 py-7 sm:px-8 md:flex-row md:items-end md:justify-between">
          <div className="max-w-xl">
            <p className="flex items-center gap-2 text-[13px] font-medium text-white/70">
              <Bot className="h-4 w-4" strokeWidth={2} />
              Five agents, one review
            </p>
            <h1 className="mt-2 font-display text-[30px] font-semibold leading-[1.1] tracking-[-0.03em] sm:text-[36px]">
              {running ? (activeJob?.status === "pending" ? "Your review is in the queue" : "The team is working on it") : "Ask your AI team for a review"}
            </h1>
            <p className="mt-2 text-[14px] leading-6 text-white/70">
              {running
                ? `${progress.done} of ${progress.total} specialists have delivered. You can leave this page — you'll get a notification when it's done.`
                : "The Planner prices your holdings, then the Reporter, Charter and Retirement agents work in parallel. Most runs finish in a few minutes."}
            </p>
          </div>
          <div className="flex shrink-0 flex-col items-start gap-3 md:items-end">
            {running ? (
              <>
                <p className="tabular font-display text-[40px] font-semibold leading-none tracking-[-0.03em]">{formatDuration(elapsed)}</p>
                <div className="flex w-48 gap-1" aria-hidden="true">
                  {Array.from({ length: progress.total }).map((_, i) => (
                    <span key={i} className={`h-1.5 flex-1 rounded-full ${i < progress.done ? "bg-[#ffc62b]" : "bg-white/25"}`} />
                  ))}
                </div>
              </>
            ) : (
              <button
                onClick={startAnalysis}
                disabled={starting}
                className="inline-flex h-12 items-center gap-2 rounded-[14px] bg-[#ffc62b] px-6 text-[15px] font-semibold text-[#1a1400] shadow-[0_10px_30px_-10px_rgba(255,198,43,0.8)] transition-colors hover:bg-[#ffd35c] disabled:opacity-60"
              >
                <Play className="h-4 w-4 fill-current" strokeWidth={2.2} />
                {starting ? "Starting…" : "Run analysis"}
              </button>
            )}
          </div>
        </div>
      </section>

      {view === "live" && (
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <Card
            className="lg:col-span-2"
            title={running ? "Live run" : shownJob ? "Last run" : "How a run flows"}
            subtitle={
              shownJob
                ? `${isScheduled(shownJob) ? "Scheduled" : "Started by you"} ${timeAgo(shownJob.created_at)}. Select a step to see what it does.`
                : "Select a step to see what it does."
            }
            action={shownJob && <JobStatusBadge status={shownJob.status} />}
          >
            <AgentFlow stages={stages} scheduled={shownJob ? isScheduled(shownJob) : false} selected={selected} onSelect={setSelected} />
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-[12px] text-muted">
              <span className="flex items-center gap-1.5">
                <span className="h-0.5 w-5 rounded bg-accent" /> Working now
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-0.5 w-5 rounded bg-ink-2" /> Delivered
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-5 border-t-[1.5px] border-dashed border-line-strong" /> Not reached, or background context
              </span>
            </div>
          </Card>

          <Card title="Step details" icon={<Activity className="h-4 w-4 text-muted" strokeWidth={2} />}>
            {selected ? <AgentPanel id={selected} job={shownJob} /> : <p className="text-[13px] text-muted">Select a step in the diagram.</p>}
          </Card>

          <Card title="Run log" subtitle={running ? "What this page has seen so far" : undefined}>
            {events.length && activeJob ? (
              <ol className="relative space-y-3 border-l border-line pl-4">
                {events.map((event, i) => (
                  <li key={i} className="relative">
                    <span
                      className={`absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full ring-4 ring-surface ${
                        event.tone === "good" ? "bg-good" : event.tone === "bad" ? "bg-bad" : "bg-accent"
                      }`}
                    />
                    <p className="text-[13px] text-ink">{event.text}</p>
                    <p className="tabular text-[11.5px] text-muted">
                      {new Date(event.at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                    </p>
                  </li>
                ))}
              </ol>
            ) : shownJob ? (
              <dl className="space-y-2.5 text-[13px]">
                {[
                  ["Waited in queue", formatDuration(queueWaitMs(shownJob))],
                  ["Agents worked for", formatDuration(jobDurationMs(shownJob))],
                  ["Finished", shownJob.completed_at ? formatDateTime(shownJob.completed_at) : "—"],
                ].map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-3">
                    <dt className="text-muted">{k}</dt>
                    <dd className="tabular font-medium text-ink">{v}</dd>
                  </div>
                ))}
                <div className="pt-1">
                  <OutputChips job={shownJob} />
                </div>
                {shownJob.status === "failed" && shownJob.error_message && (
                  <p className="rounded-lg bg-bad-soft px-3 py-2 text-[12.5px] leading-5 text-bad">{shownJob.error_message}</p>
                )}
              </dl>
            ) : (
              <p className="text-[13px] text-muted">Start a run and each agent&apos;s hand-off appears here as it happens.</p>
            )}
          </Card>
        </div>
      )}

      {view === "runs" && (
        <div className="mt-4 space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Runs" value={jobs.length} hint={`${scheduledCount} scheduled, ${jobs.length - scheduledCount} by you`} />
            <Stat label="Success rate" value={finished.length ? formatPct((succeeded.length / finished.length) * 100, 0) : "—"} hint={`${finished.length - succeeded.length} failed`} />
            <Stat label="Typical duration" value={formatDuration(median)} hint="Median of completed runs" />
            <Stat label="Last success" value={succeeded[0] ? timeAgo(succeeded[0].completed_at ?? succeeded[0].created_at) : "—"} />
          </div>

          {durationSeries.length > 1 && (
            <Card title="How long runs take" subtitle="Seconds from pickup to finish, last 20 runs">
              <div className="h-[200px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={durationSeries} margin={{ top: 8, right: 4, left: 0, bottom: 0 }}>
                    <CartesianGrid vertical={false} stroke="var(--grid)" />
                    <XAxis dataKey="label" tickLine={false} axisLine={{ stroke: "var(--axis)" }} tick={{ fill: "var(--muted)", fontSize: 11 }} interval="preserveStartEnd" minTickGap={16} />
                    <YAxis tickLine={false} axisLine={false} width={40} tick={{ fill: "var(--muted)", fontSize: 11 }} tickFormatter={(s: number) => `${s}s`} />
                    <Tooltip
                      cursor={{ fill: "var(--sunken)" }}
                      content={({ active, payload }) => {
                        const d = payload?.[0]?.payload as (typeof durationSeries)[number] | undefined;
                        return active && d ? (
                          <TooltipBox
                            title={d.when}
                            rows={[
                              { label: "Duration", value: formatDuration(d.seconds * 1000) },
                              { label: "Status", value: d.status === "completed" ? "Completed" : "Failed" },
                            ]}
                          />
                        ) : null;
                      }}
                    />
                    <Bar dataKey="seconds" maxBarSize={20} radius={[4, 4, 0, 0]}>
                      {durationSeries.map((d) => (
                        <Cell key={d.id} fill={d.status === "completed" ? "var(--ink-2)" : "var(--bad)"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-2 flex gap-4 text-[12px] text-muted">
                <span className="flex items-center gap-1.5">
                  <CheckCircle2 className="h-3.5 w-3.5 text-good" strokeWidth={2.2} /> Completed
                </span>
                <span className="flex items-center gap-1.5">
                  <XCircle className="h-3.5 w-3.5 text-bad" strokeWidth={2.2} /> Failed, shown in red
                </span>
              </div>
            </Card>
          )}

          <section className="sm-card overflow-hidden">
            {!jobsLoaded ? (
              <p className="px-5 py-10 text-center text-[13px] text-muted">Loading runs…</p>
            ) : jobs.length === 0 ? (
              <EmptyState icon={<Clock className="h-5 w-5" strokeWidth={2} />} title="No runs yet" body="Every analysis you or the scheduler starts is listed here with its timing and outputs." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-[13.5px]">
                  <thead className="border-b border-line bg-sunken text-[12.5px] text-muted">
                    <tr>
                      <th className="px-5 py-2.5 text-left font-medium">Started</th>
                      <th className="px-4 py-2.5 text-left font-medium">By</th>
                      <th className="px-4 py-2.5 text-left font-medium">Status</th>
                      <th className="px-4 py-2.5 text-right font-medium">Duration</th>
                      <th className="px-4 py-2.5 text-left font-medium">Outputs</th>
                      <th className="px-4 py-2.5" aria-label="Actions" />
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.map((job) => (
                      <tr key={job.id} className="border-b border-line last:border-0 hover:bg-sunken/50">
                        <td className="px-5 py-3">
                          <p className="font-medium text-ink">{formatDateTime(job.created_at)}</p>
                          <button
                            onClick={() => {
                              navigator.clipboard?.writeText(job.id);
                              showToast("info", "Job ID copied.");
                            }}
                            className="inline-flex items-center gap-1 font-mono text-[11.5px] text-muted hover:text-ink"
                            title="Copy job ID"
                          >
                            {job.id.slice(0, 8)}
                            <Copy className="h-3 w-3" strokeWidth={2} />
                          </button>
                        </td>
                        <td className="px-4 py-3 text-ink-2">{isScheduled(job) ? "Schedule" : "You"}</td>
                        <td className="px-4 py-3">
                          <JobStatusBadge status={job.status} />
                        </td>
                        <td className="tabular px-4 py-3 text-right text-ink-2">{formatDuration(jobDurationMs(job))}</td>
                        <td className="px-4 py-3">
                          <OutputChips job={job} />
                        </td>
                        <td className="px-4 py-3 text-right">
                          {job.status === "completed" ? (
                            <Link href={`/analysis?job_id=${job.id}`} className="inline-flex items-center gap-1 text-[13px] font-semibold text-ink hover:underline">
                              Open
                              <ArrowUpRight className="h-3.5 w-3.5" strokeWidth={2.2} />
                            </Link>
                          ) : job.status === "failed" && job.error_message ? (
                            <span className="line-clamp-1 max-w-[220px] text-left text-[12px] text-bad" title={job.error_message}>
                              {job.error_message}
                            </span>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      )}

      {view === "team" && (
        <div className="mt-4 space-y-4">
          <PageHeader title="Meet the team" subtitle={`Every agent runs on ${MODEL_LABEL} through the OpenAI Agents SDK. Each one either calls tools or returns structured output, never both.`} />
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {Object.values(AGENTS).map((agent) => (
              <article key={agent.id} className="sm-card p-5">
                <div className="flex items-center gap-3">
                  <span
                    className="flex h-11 w-11 items-center justify-center rounded-[13px] font-display text-[18px] font-semibold"
                    style={{
                      background: `linear-gradient(150deg, color-mix(in srgb, var(--series-${agent.tone}) 55%, #fff), var(--series-${agent.tone}))`,
                      color: agent.tone === 1 ? "#17130a" : "#fff",
                      boxShadow: "inset 0 1px 0 rgba(255,255,255,0.4)",
                    }}
                  >
                    {agent.name.charAt(0)}
                  </span>
                  <div>
                    <h2 className="text-[15px] font-semibold text-ink">{agent.name}</h2>
                    <p className="text-[12.5px] text-muted">{agent.runtime}</p>
                  </div>
                </div>
                <p className="mt-4 text-[13.5px] leading-6 text-ink-2">{agent.job}</p>
                <div className="mt-4 flex flex-wrap gap-1.5">
                  <Badge>{agent.mode}</Badge>
                  <Badge tone="accent">Writes: {agent.writes}</Badge>
                </div>
              </article>
            ))}
          </div>

          <Card title="What happens in a run" subtitle="In order">
            <ol className="grid gap-4 md:grid-cols-4">
              {[
                ["Queue", "Your request lands in SQS, where the Planner picks it up."],
                ["Plan", "The Planner checks every holding and calls the Tagger for any symbol it hasn't seen."],
                ["Specialists", "Reporter, Charter and Retirement run in parallel, each writing its own result."],
                ["Deliver", "Results are saved to your job. This app picks them up and notifies you."],
              ].map(([title, body], i) => (
                <li key={title} className="sm-inset p-4">
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-accent font-display text-[13px] font-semibold text-accent-ink">{i + 1}</span>
                  <p className="mt-3 text-[14px] font-semibold text-ink">{title}</p>
                  <p className="mt-1 text-[13px] leading-5 text-muted">{body}</p>
                </li>
              ))}
            </ol>
          </Card>
        </div>
      )}
    </Layout>
  );
}
