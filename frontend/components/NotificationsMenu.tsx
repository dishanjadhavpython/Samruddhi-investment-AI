import { AnimatePresence, motion } from "framer-motion";
import { Bell, CheckCircle2, CircleDashed, Loader2, XCircle } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { isScheduled, Job } from "../lib/agents";
import { useAnalysis } from "../lib/analysis-context";
import { parseServerDate, timeAgo } from "../lib/format";

const SEEN_KEY = "samruddhi-notifications-seen";

const eventTime = (job: Job) => parseServerDate(job.completed_at ?? job.started_at ?? job.created_at).getTime();

function describe(job: Job) {
  const who = isScheduled(job) ? "Scheduled review" : "Your analysis";
  switch (job.status) {
    case "completed":
      return { text: `${who} is ready`, Icon: CheckCircle2, tone: "text-good", href: `/analysis?job_id=${job.id}` };
    case "failed":
      return { text: `${who} failed`, Icon: XCircle, tone: "text-bad", href: "/ai-team" };
    case "running":
      return { text: `${who} is running`, Icon: Loader2, tone: "text-accent-text", href: "/ai-team" };
    default:
      return { text: `${who} is queued`, Icon: CircleDashed, tone: "text-muted", href: "/ai-team" };
  }
}

/** Bell menu built from the analysis jobs list — the only events the backend records. */
export default function NotificationsMenu() {
  const { jobs } = useAnalysis();
  const [open, setOpen] = useState(false);
  const [seenAt, setSeenAt] = useState(0);
  // What was unseen when the menu opened, so the "new" dots survive the open itself
  const [seenBeforeOpen, setSeenBeforeOpen] = useState(0);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      setSeenAt(Number(window.localStorage.getItem(SEEN_KEY)) || 0);
    } catch {
      // Unread state resets each visit without storage
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const recent = useMemo(() => jobs.slice(0, 8), [jobs]);
  const unread = recent.filter((j) => (j.status === "completed" || j.status === "failed") && eventTime(j) > seenAt).length;

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next) {
      const now = Date.now();
      setSeenBeforeOpen(seenAt);
      setSeenAt(now);
      try {
        window.localStorage.setItem(SEEN_KEY, String(now));
      } catch {
        // ignore
      }
    }
  };

  return (
    <div className="relative" ref={ref}>
      <button onClick={toggle} className="sm-icon-btn relative" aria-label={unread ? `Notifications, ${unread} new` : "Notifications"} aria-expanded={open}>
        <Bell className="h-[18px] w-[18px]" strokeWidth={2} />
        {unread > 0 && <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-bad ring-2 ring-frame" />}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98, transition: { duration: 0.1 } }}
            transition={{ type: "spring", stiffness: 500, damping: 34 }}
            className="absolute right-0 top-full z-50 mt-2 w-[320px] origin-top-right overflow-hidden rounded-[18px] border border-line bg-surface shadow-[var(--shadow-pop)]"
          >
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <p className="text-[13.5px] font-semibold text-ink">Activity</p>
              <Link href="/ai-team" onClick={() => setOpen(false)} className="text-[12.5px] font-medium text-muted hover:text-ink">
                All runs
              </Link>
            </div>
            {recent.length === 0 ? (
              <p className="px-4 py-8 text-center text-[13px] text-muted">Analyses you run will show up here.</p>
            ) : (
              <ul className="sm-scroll-thin max-h-[360px] overflow-y-auto p-1.5">
                {recent.map((job) => {
                  const d = describe(job);
                  const fresh = (job.status === "completed" || job.status === "failed") && eventTime(job) > seenBeforeOpen;
                  return (
                    <li key={job.id}>
                      <Link href={d.href} onClick={() => setOpen(false)} className="flex items-start gap-3 rounded-xl px-2.5 py-2.5 hover:bg-sunken">
                        <d.Icon className={`mt-0.5 h-4 w-4 shrink-0 ${d.tone} ${job.status === "running" ? "animate-spin" : ""}`} strokeWidth={2.2} />
                        <span className="min-w-0 flex-1">
                          <span className="block text-[13px] font-medium text-ink">{d.text}</span>
                          <span className="block text-[12px] text-muted">{timeAgo(job.completed_at ?? job.created_at)}</span>
                        </span>
                        {fresh && <span className="mt-1.5 h-2 w-2 rounded-full bg-accent" aria-label="New" />}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
