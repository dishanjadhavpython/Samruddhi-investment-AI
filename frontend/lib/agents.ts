/**
 * The agent team as the backend actually wires it (backend/planner, tagger,
 * reporter, charter, retirement, researcher) and how a job's database row
 * reveals each agent's progress.
 */
import { parseServerDate } from "./format";

export type AgentId = "planner" | "tagger" | "reporter" | "charter" | "retirement" | "researcher";

export interface AgentInfo {
  id: AgentId;
  name: string;
  job: string;
  runtime: string;
  mode: string;
  writes: string;
  /** Categorical slot for the agent's tile */
  tone: 1 | 2 | 3 | 4 | 5 | 6;
}

export const AGENTS: Record<AgentId, AgentInfo> = {
  planner: {
    id: "planner",
    name: "Planner",
    job: "Reads the queue, checks your holdings and decides which specialists to call.",
    runtime: "Lambda · SQS trigger",
    mode: "Tool calling",
    writes: "Job status",
    tone: 1,
  },
  tagger: {
    id: "tagger",
    name: "Tagger",
    job: "Classifies any instrument it hasn't seen before by asset class, region and sector.",
    runtime: "Lambda",
    mode: "Structured output",
    writes: "Instrument catalogue",
    tone: 6,
  },
  reporter: {
    id: "reporter",
    name: "Reporter",
    job: "Writes the portfolio review, pulling market context from the knowledge base.",
    runtime: "Lambda",
    mode: "Tool calling · RAG",
    writes: "Report",
    tone: 2,
  },
  charter: {
    id: "charter",
    name: "Charter",
    job: "Turns your holdings into 4–6 charts that explain where the money sits.",
    runtime: "Lambda",
    mode: "JSON output",
    writes: "Charts",
    tone: 4,
  },
  retirement: {
    id: "retirement",
    name: "Retirement",
    job: "Runs a Monte Carlo simulation and explains how ready you are to retire.",
    runtime: "Lambda",
    mode: "Simulation + narrative",
    writes: "Retirement projection",
    tone: 5,
  },
  researcher: {
    id: "researcher",
    name: "Researcher",
    job: "Browses the web for market news and files it into the knowledge base.",
    runtime: "Container Lambda · scheduled",
    mode: "Web browsing (MCP)",
    writes: "Knowledge base",
    tone: 3,
  },
};

export const MODEL_LABEL = "Bedrock · Nova Pro";

// ---------------------------------------------------------------------------
// Jobs
// ---------------------------------------------------------------------------

export type JobStatus = "pending" | "running" | "completed" | "failed";

export interface ChartSpec {
  title?: string;
  type?: string;
  description?: string;
  data?: { name: string; value: number; color?: string }[];
  xKey?: string;
}

/** A research note the Reporter cited as [n] (backend/reporter/agent.py) */
export interface ReportCitation {
  n: number;
  title: string;
  source_name: string;
  published: string | null;
  url?: string | null;
  doc_type?: string | null;
}

export interface Job {
  id: string;
  status: JobStatus;
  job_type: string;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  request_payload?: { analysis_type?: string; options?: { trigger?: string } } | null;
  report_payload?: {
    content?: string;
    generated_at?: string;
    agent?: string;
    kb_status?: string;
    citations?: ReportCitation[];
    market?: { available?: boolean; context_allowed?: boolean; reason?: string | null; as_of?: string | null; zone_label?: string | null } | null;
    checks?: { attempts: number; outcome: "passed" | "fallback" };
  } | null;
  charts_payload?: Record<string, ChartSpec> | null;
  retirement_payload?: { analysis?: string; generated_at?: string; agent?: string } | null;
  summary_payload?: Record<string, unknown> | null;
  error_message?: string | null;
  /** Set when the job came from /api/jobs?fields=summary, which leaves the payloads out */
  summary?: JobSummary | null;
}

export interface JobSummary {
  report: boolean;
  chartCount: number;
  retirement: boolean;
  reportExcerpt: string | null;
  kbStatus: string | null;
}

const parseJson = <T,>(value: unknown): T | null => {
  if (value == null) return null;
  if (typeof value === "string") {
    try {
      return JSON.parse(value) as T;
    } catch {
      return null;
    }
  }
  return value as T;
};

export function normalizeJob(raw: unknown): Job {
  const r = raw as Record<string, unknown>;
  const charts = parseJson<Record<string, ChartSpec>>(r.charts_payload);
  return {
    id: String(r.id),
    status: (String(r.status ?? "pending") as JobStatus),
    job_type: String(r.job_type ?? "portfolio_analysis"),
    created_at: String(r.created_at ?? ""),
    started_at: (r.started_at as string) ?? null,
    completed_at: (r.completed_at as string) ?? null,
    request_payload: parseJson(r.request_payload),
    report_payload: parseJson(r.report_payload),
    charts_payload: charts && Object.keys(charts).length ? charts : null,
    retirement_payload: parseJson(r.retirement_payload),
    summary_payload: parseJson(r.summary_payload),
    error_message: (r.error_message as string) ?? null,
    summary:
      r.has_report === undefined
        ? null
        : {
            report: Boolean(r.has_report),
            chartCount: Number(r.chart_count ?? 0),
            retirement: Boolean(r.has_retirement),
            reportExcerpt: (r.report_excerpt as string) ?? null,
            kbStatus: (r.kb_status as string) ?? null,
          },
  };
}

export const isActive = (job: Job | null | undefined) => job?.status === "pending" || job?.status === "running";

export const isScheduled = (job: Job) => job.request_payload?.options?.trigger === "scheduled_refresh";

export function jobDurationMs(job: Job): number | null {
  if (!job.started_at || !job.completed_at) return null;
  return parseServerDate(job.completed_at).getTime() - parseServerDate(job.started_at).getTime();
}

export function queueWaitMs(job: Job): number | null {
  if (!job.started_at || !job.created_at) return null;
  return parseServerDate(job.started_at).getTime() - parseServerDate(job.created_at).getTime();
}

export function outputsOf(job: Job) {
  return {
    report: Boolean(job.report_payload?.content) || Boolean(job.summary?.report),
    charts: Boolean(job.charts_payload) || Boolean(job.summary?.chartCount),
    retirement: Boolean(job.retirement_payload?.analysis) || Boolean(job.summary?.retirement),
  };
}

/** The report text, or the excerpt a summary row carries */
export const reportTextOf = (job: Job | null | undefined): string => job?.report_payload?.content ?? job?.summary?.reportExcerpt ?? "";

// ---------------------------------------------------------------------------
// Agent stages — what a job row tells us about each agent
// ---------------------------------------------------------------------------

export type StageState = "idle" | "queued" | "working" | "done" | "skipped" | "failed";

export type FlowNodeId = "trigger" | "queue" | "planner" | "tagger" | "reporter" | "charter" | "retirement" | "results" | "researcher" | "knowledge";

/**
 * The planner writes `running` when it picks the job up; each specialist
 * writes its own payload column when it finishes. That is the whole signal —
 * everything shown as "working" is inferred from those writes, nothing else.
 */
export function stagesFor(job: Job | null): Record<FlowNodeId, StageState> {
  const idle: Record<FlowNodeId, StageState> = {
    trigger: "idle", queue: "idle", planner: "idle", tagger: "idle", reporter: "idle",
    charter: "idle", retirement: "idle", results: "idle", researcher: "idle", knowledge: "idle",
  };
  if (!job) return idle;

  const out = outputsOf(job);
  const anyOutput = out.report || out.charts || out.retirement;
  const specialist = (done: boolean): StageState => {
    if (done) return "done";
    if (job.status === "running") return "working";
    if (job.status === "pending") return "queued";
    if (job.status === "failed") return "failed";
    return "skipped";
  };

  const stages: Record<FlowNodeId, StageState> = {
    ...idle,
    trigger: "done",
    queue: job.status === "pending" ? "working" : "done",
    planner:
      job.status === "pending" ? "queued" : job.status === "running" ? "working" : job.status === "failed" ? "failed" : "done",
    tagger: job.status === "pending" ? "queued" : anyOutput || job.status === "completed" ? "done" : job.status === "failed" ? "failed" : "working",
    reporter: specialist(out.report),
    charter: specialist(out.charts),
    retirement: specialist(out.retirement),
    results: job.status === "completed" ? "done" : anyOutput ? "working" : job.status === "failed" ? "failed" : "queued",
    knowledge: out.report ? "done" : job.status === "running" ? "working" : "idle",
  };
  return stages;
}

export function progressOf(job: Job | null): { done: number; total: number } {
  if (!job) return { done: 0, total: 3 };
  const out = outputsOf(job);
  return { done: Number(out.report) + Number(out.charts) + Number(out.retirement), total: 3 };
}
