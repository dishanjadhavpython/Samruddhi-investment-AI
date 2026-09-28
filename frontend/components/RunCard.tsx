import { Play, Radio } from "lucide-react";
import Link from "next/link";
import { isActive, progressOf } from "../lib/agents";
import { useAnalysis } from "../lib/analysis-context";
import { formatDuration, parseServerDate, timeAgo } from "../lib/format";
import { useNow } from "../lib/hooks";
import { WarpBackdrop } from "./Shader";

/**
 * Sidebar card that starts an analysis and, while one runs, turns into a live
 * status panel. The shader only animates while agents are actually working —
 * the motion means "something is happening", not decoration.
 */
export default function RunCard() {
  const { activeJob, jobs, startAnalysis, starting } = useAnalysis();
  const running = isActive(activeJob);
  const now = useNow(1000, running);
  const lastDone = jobs.find((j) => j.status === "completed");

  if (running && activeJob) {
    const { done, total } = progressOf(activeJob);
    const elapsed = now - parseServerDate(activeJob.created_at).getTime();
    return (
      <div className="relative overflow-hidden rounded-[18px] p-4 text-white">
        <WarpBackdrop speed={1.4} />
        <div className="absolute inset-0 bg-gradient-to-t from-black/75 via-black/35 to-black/10" aria-hidden="true" />
        <div className="relative">
          <p className="flex items-center gap-2 text-[12px] font-medium text-white/80">
            <Radio className="h-3.5 w-3.5 text-[#ffc62b]" strokeWidth={2.2} />
            {activeJob.status === "pending" ? "Queued" : "Agents working"}
            <span className="tabular ml-auto text-white/70">{formatDuration(elapsed)}</span>
          </p>
          <p className="mt-3 font-display text-[22px] font-semibold leading-none tracking-[-0.02em]">
            {done} of {total}
            <span className="ml-1.5 text-[13px] font-medium text-white/75">delivered</span>
          </p>
          <div className="mt-3 flex gap-1" aria-hidden="true">
            {Array.from({ length: total }).map((_, i) => (
              <span key={i} className={`h-1.5 flex-1 rounded-full ${i < done ? "bg-[#ffc62b]" : "bg-white/25"}`} />
            ))}
          </div>
          <Link
            href="/ai-team"
            className="mt-4 inline-flex h-8 w-full items-center justify-center rounded-[10px] bg-white/15 text-[12.5px] font-semibold backdrop-blur-sm transition-colors hover:bg-white/25"
          >
            Watch the team
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="relative overflow-hidden rounded-[18px] bg-[#121212] p-4 text-white">
      <div
        className="pointer-events-none absolute -right-10 -top-12 h-36 w-36 rounded-full opacity-60 blur-2xl"
        style={{ background: "radial-gradient(circle, #ffc62b 0%, transparent 70%)" }}
        aria-hidden="true"
      />
      <div className="relative">
        <p className="text-[12px] text-white/65">{lastDone ? `Last review ${timeAgo(lastDone.completed_at ?? lastDone.created_at)}` : "No reviews yet"}</p>
        <p className="mt-1.5 text-[14px] font-semibold leading-5">Ask the team for a fresh look at your portfolio</p>
        <button
          onClick={startAnalysis}
          disabled={starting}
          className="mt-4 inline-flex h-9 w-full items-center justify-center gap-2 rounded-[10px] bg-[#ffc62b] text-[13px] font-semibold text-[#1a1400] transition-colors hover:bg-[#ffd35c] disabled:opacity-60"
        >
          <Play className="h-3.5 w-3.5 fill-current" strokeWidth={2.2} />
          {starting ? "Starting…" : "Run analysis"}
        </button>
      </div>
    </div>
  );
}
