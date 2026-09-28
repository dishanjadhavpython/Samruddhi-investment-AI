import { useAuth } from "@clerk/nextjs";
import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import AiDisclosureModal from "../components/AiDisclosureModal";
import { showToast } from "../components/Toast";
import { AgentId, isActive, Job, normalizeJob, outputsOf } from "./agents";
import { AI_DISCLOSURE_VERSION } from "./ai";
import { emitAnalysisCompleted, emitAnalysisFailed, emitAnalysisStarted } from "./events";
import { ApiError, useApi } from "./http";

const ACTIVE_KEY = "samruddhi-active-job";
const POLL_MS = 2500;
const JOBS_REFRESH_MS = 60 * 1000;

export interface RunEvent {
  at: number;
  text: string;
  agent?: AgentId;
  tone: "info" | "good" | "bad";
}

interface AnalysisContextValue {
  jobs: Job[];
  jobsLoaded: boolean;
  /** The run being tracked live — started here, or found pending/running on load */
  activeJob: Job | null;
  /** Timeline of changes observed while tracking the active run in this tab */
  events: RunEvent[];
  starting: boolean;
  startAnalysis: () => Promise<void>;
  refreshJobs: () => Promise<void>;
}

const AnalysisContext = createContext<AnalysisContextValue | null>(null);

function readActiveId(): string | null {
  try {
    return window.localStorage.getItem(ACTIVE_KEY);
  } catch {
    return null;
  }
}

function writeActiveId(id: string | null) {
  try {
    if (id) window.localStorage.setItem(ACTIVE_KEY, id);
    else window.localStorage.removeItem(ACTIVE_KEY);
  } catch {
    // Tracking still works for this tab without storage
  }
}

/** Describe what changed between two polls of the same job */
function diffJob(prev: Job | null, next: Job): RunEvent[] {
  const now = Date.now();
  const events: RunEvent[] = [];
  if (prev?.status !== next.status) {
    if (next.status === "running") events.push({ at: now, text: "Planner picked up the job", agent: "planner", tone: "info" });
    if (next.status === "completed") events.push({ at: now, text: "Run complete — results saved", agent: "planner", tone: "good" });
    if (next.status === "failed") events.push({ at: now, text: next.error_message || "Run failed", agent: "planner", tone: "bad" });
  }
  const before = prev ? outputsOf(prev) : { report: false, charts: false, retirement: false };
  const after = outputsOf(next);
  if (!before.report && after.report) events.push({ at: now, text: "Reporter delivered the portfolio report", agent: "reporter", tone: "good" });
  if (!before.charts && after.charts) {
    const count = Object.keys(next.charts_payload ?? {}).length;
    events.push({ at: now, text: `Charter delivered ${count} chart${count === 1 ? "" : "s"}`, agent: "charter", tone: "good" });
  }
  if (!before.retirement && after.retirement) events.push({ at: now, text: "Retirement delivered the projection", agent: "retirement", tone: "good" });
  return events;
}

export function AnalysisProvider({ children }: { children: ReactNode }) {
  const { isSignedIn } = useAuth();
  const api = useApi();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobsLoaded, setJobsLoaded] = useState(false);
  const [activeJob, setActiveJob] = useState<Job | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [starting, setStarting] = useState(false);
  // The one-time AI disclosure: the API answers 428 until it's accepted
  const [disclosureOpen, setDisclosureOpen] = useState(false);
  const [accepting, setAccepting] = useState(false);
  const activeRef = useRef<Job | null>(null);

  const refreshJobs = useCallback(async () => {
    try {
      const data = await api<{ jobs?: unknown[] }>("/api/jobs?fields=summary&limit=50");
      const list = (data.jobs ?? []).map(normalizeJob);
      setJobs(list);
      setJobsLoaded(true);

      // Pick up a run started elsewhere, such as another tab
      if (!activeRef.current) {
        const storedId = readActiveId();
        const running = list.find((j) => isActive(j)) ?? (storedId ? list.find((j) => j.id === storedId && isActive(j)) : undefined);
        if (running) {
          activeRef.current = running;
          setActiveJob(running);
          setEvents([{ at: Date.now(), text: "Following a run already in progress", tone: "info" }]);
        } else if (storedId) {
          writeActiveId(null);
        }
      }
    } catch {
      setJobsLoaded(true);
    }
  }, [api]);

  useEffect(() => {
    if (!isSignedIn) return;
    refreshJobs();
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible" && !activeRef.current) refreshJobs();
    }, JOBS_REFRESH_MS);
    return () => window.clearInterval(interval);
  }, [isSignedIn, refreshJobs]);

  // Poll the active job until it settles
  const activeId = activeJob?.id;
  const activeIsLive = isActive(activeJob);
  useEffect(() => {
    if (!activeId || !activeIsLive) return;
    let cancelled = false;

    const tick = async () => {
      try {
        const next = normalizeJob(await api<unknown>(`/api/jobs/${activeId}`));
        if (cancelled) return;
        const prev = activeRef.current;
        const changes = diffJob(prev, next);
        if (changes.length) setEvents((list) => [...list, ...changes]);
        activeRef.current = next;
        setActiveJob(next);
        setJobs((list) => {
          const exists = list.some((j) => j.id === next.id);
          return exists ? list.map((j) => (j.id === next.id ? next : j)) : [next, ...list];
        });

        if (next.status === "completed") {
          writeActiveId(null);
          emitAnalysisCompleted(next.id);
          showToast("success", "Your analysis is ready.", { action: { label: "Open report", href: `/analysis?job_id=${next.id}` } });
        } else if (next.status === "failed") {
          writeActiveId(null);
          emitAnalysisFailed(next.id, next.error_message ?? undefined);
          showToast("error", "The analysis failed. Open the AI team page to see which step stopped.", {
            action: { label: "View run", href: "/ai-team" },
          });
        }
      } catch {
        // Transient — the next tick retries
      }
    };

    tick();
    const interval = window.setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [activeId, activeIsLive, api]);

  const startAnalysis = useCallback(async () => {
    if (starting || isActive(activeRef.current)) return;
    setStarting(true);
    try {
      const data = await api<{ job_id: string }>("/api/analyze", {
        method: "POST",
        body: JSON.stringify({ analysis_type: "portfolio", options: {} }),
      });
      const job: Job = normalizeJob({ id: data.job_id, status: "pending", job_type: "portfolio_analysis", created_at: new Date().toISOString() });
      writeActiveId(job.id);
      activeRef.current = job;
      setActiveJob(job);
      setEvents([{ at: Date.now(), text: "Analysis requested — job queued", tone: "info" }]);
      setJobs((list) => [job, ...list]);
      emitAnalysisStarted(job.id);
      showToast("info", "Analysis started. The team usually needs a couple of minutes.");
    } catch (err) {
      if (err instanceof ApiError && err.status === 428) {
        setDisclosureOpen(true);
      } else {
        showToast("error", err instanceof Error ? `Couldn't start the analysis: ${err.message}` : "Couldn't start the analysis.");
      }
    } finally {
      setStarting(false);
    }
  }, [api, starting]);

  const acceptDisclosure = useCallback(async () => {
    setAccepting(true);
    try {
      await api("/api/user", { method: "PUT", body: JSON.stringify({ ai_disclosure_version: AI_DISCLOSURE_VERSION }) });
      setDisclosureOpen(false);
      setAccepting(false);
      await startAnalysis();
    } catch (err) {
      setAccepting(false);
      showToast("error", err instanceof Error ? `Couldn't save that: ${err.message}` : "Couldn't save that. Try again.");
    }
  }, [api, startAnalysis]);

  const value = useMemo(
    () => ({ jobs, jobsLoaded, activeJob, events, starting, startAnalysis, refreshJobs }),
    [jobs, jobsLoaded, activeJob, events, starting, startAnalysis, refreshJobs],
  );

  return (
    <AnalysisContext.Provider value={value}>
      {children}
      <AiDisclosureModal
        open={disclosureOpen}
        accepting={accepting}
        onAccept={acceptDisclosure}
        onCancel={() => !accepting && setDisclosureOpen(false)}
      />
    </AnalysisContext.Provider>
  );
}

export function useAnalysis(): AnalysisContextValue {
  const ctx = useContext(AnalysisContext);
  if (!ctx) throw new Error("useAnalysis must be used inside AnalysisProvider");
  return ctx;
}
