import { BarChart3, Check, CircleDashed, Clock, Database, Globe, Inbox, Library, LineChart, Minus, Sprout, Tags, User, Workflow, X } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { AGENTS, AgentId, FlowNodeId, StageState } from "../lib/agents";

interface NodeSpec {
  id: FlowNodeId;
  x: number;
  y: number;
  title: string;
  subtitle: string;
  icon: typeof User;
  agent?: AgentId;
}

const NODE_H = 62;

const EDGES: { from: FlowNodeId; to: FlowNodeId; vertical?: boolean; context?: boolean }[] = [
  { from: "trigger", to: "queue" },
  { from: "queue", to: "planner" },
  { from: "planner", to: "tagger", vertical: true },
  { from: "planner", to: "reporter" },
  { from: "planner", to: "charter" },
  { from: "planner", to: "retirement" },
  { from: "reporter", to: "results" },
  { from: "charter", to: "results" },
  { from: "retirement", to: "results" },
  { from: "researcher", to: "knowledge", context: true },
  { from: "knowledge", to: "reporter", context: true },
];

type EdgeState = "idle" | "active" | "done" | "failed";

function edgeState(stages: Record<FlowNodeId, StageState>, to: FlowNodeId, context?: boolean): EdgeState {
  const s = stages[to];
  if (context) return to === "reporter" && s === "working" ? "active" : "idle";
  if (s === "working") return "active";
  if (s === "done") return "done";
  if (s === "failed") return "failed";
  return "idle";
}

/** Orthogonal connector with rounded elbows, like a whiteboard flow chart */
function elbowPath(x1: number, y1: number, x2: number, y2: number, radius = 14) {
  if (Math.abs(y2 - y1) < 1) return `M${x1},${y1} H${x2}`;
  const mid = (x1 + x2) / 2;
  const dir = y2 > y1 ? 1 : -1;
  const r = Math.min(radius, Math.abs(y2 - y1) / 2, Math.abs(mid - x1));
  return `M${x1},${y1} H${mid - r} Q${mid},${y1} ${mid},${y1 + dir * r} V${y2 - dir * r} Q${mid},${y2} ${mid + r},${y2} H${x2}`;
}

const stateStyle: Record<StageState, { ring: string; label: string; Icon: typeof Check | null; tone: string }> = {
  idle: { ring: "border-line", label: "", Icon: null, tone: "text-muted" },
  queued: { ring: "border-line-strong border-dashed", label: "Waiting", Icon: CircleDashed, tone: "text-muted" },
  working: { ring: "border-accent ring-4 ring-accent/25", label: "Working", Icon: null, tone: "text-accent-text" },
  done: { ring: "border-line", label: "Done", Icon: Check, tone: "text-good" },
  skipped: { ring: "border-line border-dashed", label: "No output", Icon: Minus, tone: "text-muted" },
  failed: { ring: "border-bad ring-4 ring-bad/15", label: "Failed", Icon: X, tone: "text-bad" },
};

function useReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const m = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(m.matches);
    const on = (e: MediaQueryListEvent) => setReduced(e.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return reduced;
}

interface AgentFlowProps {
  stages: Record<FlowNodeId, StageState>;
  scheduled?: boolean;
  selected?: FlowNodeId | null;
  onSelect?: (id: FlowNodeId) => void;
}

export default function AgentFlow({ stages, scheduled, selected, onSelect }: AgentFlowProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 960, h: 440 });
  const reducedMotion = useReducedMotion();

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setSize({ w: entry.contentRect.width, h: entry.contentRect.height }));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const nodes: NodeSpec[] = [
    { id: "researcher", x: 0.1, y: 0.16, title: AGENTS.researcher.name, subtitle: "Web research", icon: Globe, agent: "researcher" },
    { id: "knowledge", x: 0.3, y: 0.16, title: "Knowledge base", subtitle: "S3 Vectors", icon: Library },
    { id: "trigger", x: 0.1, y: 0.52, title: scheduled ? "Price refresh" : "You", subtitle: scheduled ? "Scheduled run" : "Run analysis", icon: scheduled ? Clock : User },
    { id: "queue", x: 0.3, y: 0.52, title: "Job queue", subtitle: "SQS", icon: Inbox },
    { id: "planner", x: 0.5, y: 0.52, title: AGENTS.planner.name, subtitle: "Orchestrator", icon: Workflow, agent: "planner" },
    { id: "tagger", x: 0.5, y: 0.86, title: AGENTS.tagger.name, subtitle: "Only for new symbols", icon: Tags, agent: "tagger" },
    { id: "reporter", x: 0.715, y: 0.2, title: AGENTS.reporter.name, subtitle: "Writes the report", icon: Sprout, agent: "reporter" },
    { id: "charter", x: 0.715, y: 0.52, title: AGENTS.charter.name, subtitle: "Designs the charts", icon: BarChart3, agent: "charter" },
    { id: "retirement", x: 0.715, y: 0.84, title: AGENTS.retirement.name, subtitle: "Projects retirement", icon: LineChart, agent: "retirement" },
    { id: "results", x: 0.91, y: 0.52, title: "Your report", subtitle: "Aurora", icon: Database },
  ];
  // Nodes widen with the canvas but never collide: columns sit 20% of the width apart
  const NODE_W = Math.round(Math.max(140, Math.min(184, size.w * 0.2 - 22)));
  const pos = Object.fromEntries(nodes.map((n) => [n.id, { x: n.x * size.w, y: n.y * size.h }])) as Record<FlowNodeId, { x: number; y: number }>;

  return (
    <div className="sm-dot-grid sm-scroll-thin overflow-x-auto rounded-[16px] border border-line">
      <div ref={ref} className="relative h-[440px] min-w-[840px]">
        <svg className="absolute inset-0 h-full w-full" aria-hidden="true">
          {EDGES.map((edge) => {
            const a = pos[edge.from];
            const b = pos[edge.to];
            const d = edge.vertical
              ? `M${a.x},${a.y + NODE_H / 2} V${b.y - NODE_H / 2}`
              : elbowPath(a.x + NODE_W / 2, a.y, b.x - NODE_W / 2, b.y);
            const state = edgeState(stages, edge.to, edge.context);
            const stroke =
              state === "active" ? "var(--accent)" : state === "done" ? "var(--ink-2)" : state === "failed" ? "var(--bad)" : "var(--line-strong)";
            const end = edge.vertical ? { x: b.x, y: b.y - NODE_H / 2 } : { x: b.x - NODE_W / 2, y: b.y };
            return (
              <g key={`${edge.from}-${edge.to}`}>
                <path
                  d={d}
                  fill="none"
                  stroke={stroke}
                  strokeWidth={state === "active" ? 2 : 1.5}
                  strokeDasharray={state === "done" ? undefined : edge.context || state === "idle" ? "4 5" : undefined}
                  className={state === "active" ? "sm-flow-active" : ""}
                  strokeLinecap="round"
                />
                <circle cx={end.x} cy={end.y} r={3.5} fill="var(--sunken)" stroke={stroke} strokeWidth={1.5} />
                {state === "active" && !reducedMotion && (
                  <circle r={4} fill="var(--accent)">
                    <animateMotion dur="1.6s" repeatCount="indefinite" path={d} />
                  </circle>
                )}
              </g>
            );
          })}
        </svg>

        {nodes.map((node) => {
          const state = stages[node.id];
          const style = stateStyle[state];
          const tone = node.agent ? AGENTS[node.agent].tone : null;
          const isSelected = selected === node.id;
          return (
            <button
              key={node.id}
              type="button"
              onClick={() => onSelect?.(node.id)}
              aria-pressed={isSelected}
              aria-label={`${node.title}${style.label ? `, ${style.label.toLowerCase()}` : ""}`}
              className={`absolute flex items-center gap-2.5 rounded-[14px] border bg-surface px-2.5 text-left shadow-[var(--shadow-card)] transition-[box-shadow,transform] hover:-translate-y-0.5 ${style.ring} ${
                isSelected ? "outline outline-2 outline-offset-2 outline-ink" : ""
              }`}
              style={{ left: pos[node.id].x - NODE_W / 2, top: pos[node.id].y - NODE_H / 2, width: NODE_W, height: NODE_H }}
            >
              <span
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px]"
                style={
                  tone
                    ? {
                        background: `linear-gradient(150deg, color-mix(in srgb, var(--series-${tone}) 55%, #fff), var(--series-${tone}))`,
                        color: tone === 1 ? "#17130a" : "#fff",
                        boxShadow: "inset 0 1px 0 rgba(255,255,255,0.4)",
                      }
                    : { background: "var(--sunken)", color: "var(--ink-2)" }
                }
              >
                <node.icon className="h-[18px] w-[18px]" strokeWidth={2} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-semibold text-ink">{node.title}</span>
                <span className={`flex items-center gap-1 truncate text-[11.5px] ${state === "idle" ? "text-muted" : style.tone}`}>
                  {state === "working" && <span className="sm-pulse-dot inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-accent text-accent" />}
                  {style.Icon && <style.Icon className="h-3 w-3 shrink-0" strokeWidth={2.6} />}
                  {style.label || node.subtitle}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
