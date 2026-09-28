import { AnimatePresence, motion } from "framer-motion";
import {
  Bot,
  CircleDollarSign,
  CornerDownLeft,
  EyeOff,
  FileText,
  Flag,
  LayoutDashboard,
  LineChart,
  MoonStar,
  Play,
  Plus,
  Search,
  Shapes,
  ShieldCheck,
  Split,
  TrendingUp,
} from "lucide-react";
import { useRouter } from "next/router";
import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { useAnalysis } from "../lib/analysis-context";
import { formatDateTime } from "../lib/format";
import { OPEN_PALETTE_EVENT } from "../lib/hooks";
import { usePortfolio } from "../lib/portfolio-context";
import { usePreferences } from "../lib/preferences";
import { AccountTile } from "./ui";

interface Command {
  id: string;
  group: string;
  label: string;
  hint?: string;
  keywords?: string;
  icon: ReactNode;
  run: () => void;
}

/** ⌘K / Ctrl+K — jump to any page, account, holding or report, or run an action. */
export default function CommandPalette() {
  const router = useRouter();
  const { accounts, metrics } = usePortfolio();
  const { jobs, startAnalysis } = useAnalysis();
  const { toggleTheme, togglePrivacy } = usePreferences();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((o) => !o);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener(OPEN_PALETTE_EVENT, onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener(OPEN_PALETTE_EVENT, onOpen);
    };
  }, []);

  useEffect(() => {
    if (open) {
      setQuery("");
      setCursor(0);
      window.setTimeout(() => inputRef.current?.focus(), 20);
    }
  }, [open]);

  const commands = useMemo<Command[]>(() => {
    const go = (href: string) => () => router.push(href);
    const icon = (Icon: typeof Search) => <Icon className="h-4 w-4" strokeWidth={2} />;
    const list: Command[] = [
      { id: "p-dash", group: "Pages", label: "Dashboard", icon: icon(LayoutDashboard), run: go("/dashboard"), keywords: "home overview net worth" },
      { id: "p-hold", group: "Pages", label: "Holdings", icon: icon(Shapes), run: go("/holdings"), keywords: "positions stocks etf funds" },
      { id: "p-acc", group: "Pages", label: "Accounts", icon: icon(CircleDollarSign), run: go("/accounts"), keywords: "epf ppf nps demat" },
      { id: "p-goals", group: "Pages", label: "Goals & retirement", icon: icon(Flag), run: go("/goals"), keywords: "settings targets retirement projection monte carlo" },
      { id: "p-perf", group: "Pages", label: "Performance", icon: icon(TrendingUp), run: go("/performance"), keywords: "returns xirr gain benchmark transactions" },
      { id: "p-market", group: "Pages", label: "Nifty 50 market context", icon: icon(LineChart), run: go("/market"), keywords: "market index valuation pe pb vix drawdown nifty" },
      { id: "p-explore", group: "Pages", label: "Lump sum or stagger", icon: icon(Split), run: go("/explore"), keywords: "idle cash invest stagger stp lump sum history" },
      { id: "p-team", group: "Pages", label: "AI team", icon: icon(Bot), run: go("/ai-team"), keywords: "agents planner runs history" },
      { id: "p-ai-use", group: "Pages", label: "How AI is used here", icon: icon(ShieldCheck), run: go("/ai-use"), keywords: "ai disclosure checks evals safety report problem audit" },
      { id: "p-rep", group: "Pages", label: "Reports", icon: icon(FileText), run: go("/analysis"), keywords: "analysis charts report" },
      { id: "a-run", group: "Actions", label: "Run a new analysis", icon: icon(Play), run: () => { startAnalysis(); router.push("/ai-team"); }, keywords: "start analyze agents" },
      { id: "a-add", group: "Actions", label: "Add an account", icon: icon(Plus), run: go("/accounts?new=1"), keywords: "create new account" },
      { id: "a-theme", group: "Actions", label: "Switch light / dark theme", icon: icon(MoonStar), run: toggleTheme, keywords: "dark mode light mode appearance" },
      { id: "a-priv", group: "Actions", label: "Hide or show amounts", icon: icon(EyeOff), run: togglePrivacy, keywords: "privacy blur balance" },
    ];
    accounts.forEach((account, index) =>
      list.push({
        id: `acc-${account.id}`,
        group: "Accounts",
        label: account.account_name,
        hint: account.account_purpose,
        icon: <AccountTile name={account.account_name} index={index} size={18} />,
        run: go(`/accounts/${account.id}`),
      }),
    );
    metrics.holdings.forEach((holding) =>
      list.push({
        id: `h-${holding.symbol}`,
        group: "Holdings",
        label: holding.symbol,
        hint: holding.name,
        keywords: holding.name,
        icon: icon(Shapes),
        run: go(`/holdings?q=${encodeURIComponent(holding.symbol)}`),
      }),
    );
    jobs
      .filter((j) => j.status === "completed")
      .slice(0, 5)
      .forEach((job) =>
        list.push({
          id: `j-${job.id}`,
          group: "Reports",
          label: `Report from ${formatDateTime(job.completed_at ?? job.created_at)}`,
          icon: icon(FileText),
          run: go(`/analysis?job_id=${job.id}`),
        }),
      );
    return list;
  }, [accounts, metrics.holdings, jobs, router, startAnalysis, toggleTheme, togglePrivacy]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matches = q
      ? commands.filter((c) => `${c.label} ${c.hint ?? ""} ${c.keywords ?? ""} ${c.group}`.toLowerCase().includes(q))
      : commands.filter((c) => c.group === "Pages" || c.group === "Actions");
    return matches.slice(0, 40);
  }, [commands, query]);

  useEffect(() => setCursor(0), [query]);

  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-index="${cursor}"]`)?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  const execute = (command?: Command) => {
    if (!command) return;
    setOpen(false);
    command.run();
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setCursor((c) => Math.min(filtered.length - 1, c + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setCursor((c) => Math.max(0, c - 1));
    } else if (event.key === "Enter") {
      event.preventDefault();
      execute(filtered[cursor]);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  };

  let lastGroup = "";

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[65] flex items-start justify-center bg-black/35 px-3 pt-[12vh] backdrop-blur-[2px]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onMouseDown={(e) => e.target === e.currentTarget && setOpen(false)}
        >
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label="Command palette"
            initial={{ opacity: 0, y: -8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.98, transition: { duration: 0.1 } }}
            transition={{ type: "spring", stiffness: 500, damping: 36 }}
            className="w-full max-w-[560px] overflow-hidden rounded-[20px] border border-line bg-surface shadow-[var(--shadow-pop)]"
          >
            <div className="flex items-center gap-3 border-b border-line px-4">
              <Search className="h-[18px] w-[18px] text-muted" strokeWidth={2} />
              <input
                ref={inputRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder="Search pages, accounts, holdings…"
                className="h-14 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-muted"
                role="combobox"
                aria-expanded="true"
                aria-controls="palette-list"
                aria-activedescendant={filtered[cursor] ? `cmd-${filtered[cursor].id}` : undefined}
              />
              <kbd className="sm-kbd">Esc</kbd>
            </div>
            <div ref={listRef} id="palette-list" role="listbox" className="sm-scroll-thin max-h-[52vh] overflow-y-auto p-2">
              {filtered.length === 0 && <p className="px-3 py-8 text-center text-[13.5px] text-muted">Nothing matches &ldquo;{query}&rdquo;.</p>}
              {filtered.map((command, index) => {
                const header = command.group !== lastGroup ? command.group : null;
                lastGroup = command.group;
                const active = index === cursor;
                return (
                  <div key={command.id}>
                    {header && <p className="px-3 pb-1 pt-3 text-[11.5px] font-medium text-muted">{header}</p>}
                    <button
                      id={`cmd-${command.id}`}
                      data-index={index}
                      role="option"
                      aria-selected={active}
                      onMouseMove={() => setCursor(index)}
                      onClick={() => execute(command)}
                      className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-[13.5px] ${active ? "bg-sunken text-ink" : "text-ink-2"}`}
                    >
                      <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${active ? "bg-accent text-accent-ink" : "bg-sunken text-muted"}`}>
                        {command.icon}
                      </span>
                      <span className="min-w-0 flex-1 truncate">
                        <span className="font-medium text-ink">{command.label}</span>
                        {command.hint && <span className="ml-2 text-muted">{command.hint}</span>}
                      </span>
                      {active && <CornerDownLeft className="h-4 w-4 text-muted" strokeWidth={2} />}
                    </button>
                  </div>
                );
              })}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
