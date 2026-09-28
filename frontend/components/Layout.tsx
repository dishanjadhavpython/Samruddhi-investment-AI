import { Protect, SignInButton, useClerk, UserButton, useUser } from "@clerk/nextjs";
import { AnimatePresence, motion } from "framer-motion";
import {
  Bot,
  CheckCircle2,
  CircleDollarSign,
  FileText,
  Flag,
  LayoutDashboard,
  LineChart,
  LogOut,
  Menu,
  Plus,
  Search,
  Shapes,
  Split,
  TrendingUp,
  X,
  XCircle,
} from "lucide-react";
import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { ReactNode, useEffect, useRef, useState } from "react";
import { isActive } from "../lib/agents";
import { useAnalysis } from "../lib/analysis-context";
import { formatDateTime, timeAgo } from "../lib/format";
import { openCommandPalette } from "../lib/hooks";
import { describeSession, formatMarketDate, isClosingPrice, istClock } from "../lib/market";
import { useMarket } from "../lib/market-context";
import { usePortfolio } from "../lib/portfolio-context";
import CommandPalette from "./CommandPalette";
import Disclosure from "./Disclosure";
import { ReportProblemModal } from "./ReportProblem";
import { LogoMark, Wordmark } from "./Logo";
import NotificationsMenu from "./NotificationsMenu";
import RunCard from "./RunCard";
import { WarpBackdrop } from "./Shader";
import ThemeToggle, { PrivacyToggle } from "./ThemeToggle";
import { AccountTile, buttonClass } from "./ui";

interface LayoutProps {
  children: ReactNode;
  /** Document title, without the product suffix */
  title?: string;
  /** Page-level view switcher, shown in the top bar like the Overview / Board / List tabs */
  tabs?: ReactNode;
}

const portfolioNav = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/holdings", label: "Holdings", icon: Shapes },
  { href: "/accounts", label: "Accounts", icon: CircleDollarSign },
  { href: "/performance", label: "Performance", icon: TrendingUp },
  { href: "/goals", label: "Goals", icon: Flag },
];

// Index-level context lives in its own group, apart from the user's holdings
const marketNav = [
  { href: "/market", label: "Nifty 50", icon: LineChart },
  { href: "/explore", label: "Lump sum or stagger", icon: Split },
];

const aiNav = [
  { href: "/ai-team", label: "AI team", icon: Bot },
  { href: "/analysis", label: "Reports", icon: FileText },
];

function AuthGate() {
  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden p-4">
      <WarpBackdrop speed={0.5} />
      <div className="relative w-full max-w-sm rounded-[24px] border border-line bg-surface p-8 text-center shadow-[var(--shadow-pop)]">
        <LogoMark size={44} className="mx-auto" />
        <h1 className="mt-5 font-display text-[22px] font-semibold tracking-[-0.02em] text-ink">Sign in to see your portfolio</h1>
        <p className="mt-2 text-[13.5px] leading-6 text-muted">Your accounts and reports are private to you.</p>
        <SignInButton mode="modal">
          <button className={buttonClass("primary", "lg", "mt-6 w-full")}>Sign in</button>
        </SignInButton>
        <Link href="/" className="mt-3 inline-block text-[13px] font-medium text-muted hover:text-ink">
          Back to home
        </Link>
      </div>
    </div>
  );
}

function NavLink({ href, label, icon: Icon, active, badge, onNavigate }: { href: string; label: string; icon: typeof Bot; active: boolean; badge?: ReactNode; onNavigate?: () => void }) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={`group flex h-9 items-center gap-2.5 rounded-[10px] px-2.5 text-[13.5px] transition-colors ${
        active ? "bg-sunken font-semibold text-ink shadow-[inset_0_0_0_1px_var(--line)]" : "text-ink-2 hover:bg-sunken hover:text-ink"
      }`}
    >
      <Icon className={`h-[17px] w-[17px] ${active ? "text-ink" : "text-muted group-hover:text-ink"}`} strokeWidth={2} />
      <span className="flex-1 truncate">{label}</span>
      {badge}
    </Link>
  );
}

function Rail({ onNavigate }: { onNavigate?: () => void }) {
  const router = useRouter();
  const { accounts, metrics } = usePortfolio();
  const { signOut } = useClerk();
  const totals = new Map(metrics.accounts.map((a) => [a.id, a.total]));

  return (
    <div className="flex h-full w-[72px] shrink-0 flex-col items-center gap-3 pb-4 pt-1">
      <div className="sm-scroll-thin flex flex-1 flex-col items-center gap-3 overflow-y-auto px-2 py-1">
        {accounts.map((account, index) => {
          const active = router.pathname === "/accounts/[id]" && router.query.id === account.id;
          return (
            <Link
              key={account.id}
              href={`/accounts/${account.id}`}
              onClick={onNavigate}
              aria-label={`${account.account_name} account`}
              className="group relative flex items-center justify-center"
            >
              {active && <span className="absolute -left-[14px] h-6 w-1 rounded-r-full bg-accent" aria-hidden="true" />}
              <span className={`rounded-[14px] transition-transform group-hover:-translate-y-0.5 ${active ? "ring-2 ring-accent ring-offset-2 ring-offset-frame" : ""}`}>
                <AccountTile name={account.account_name} index={index} size={42} />
              </span>
              <span className="pointer-events-none absolute left-[calc(100%+10px)] top-1/2 z-50 hidden -translate-y-1/2 whitespace-nowrap rounded-lg bg-ink px-2.5 py-1.5 text-[12px] font-medium text-frame shadow-lg group-hover:block">
                {account.account_name}
                {totals.has(account.id) && <span className="sm-money ml-1.5 opacity-70">₹{Math.round(totals.get(account.id) ?? 0).toLocaleString("en-IN")}</span>}
              </span>
            </Link>
          );
        })}
        <Link
          href="/accounts?new=1"
          onClick={onNavigate}
          aria-label="Add an account"
          title="Add an account"
          className="flex h-[42px] w-[42px] items-center justify-center rounded-[13px] border border-dashed border-line-strong text-muted transition-colors hover:border-ink hover:text-ink"
        >
          <Plus className="h-5 w-5" strokeWidth={2} />
        </Link>
      </div>
      <button onClick={() => signOut({ redirectUrl: "/" })} className="sm-icon-btn" aria-label="Sign out" title="Sign out">
        <LogOut className="h-[18px] w-[18px]" strokeWidth={2} />
      </button>
    </div>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const router = useRouter();
  const { user: clerkUser } = useUser();
  const { user, metrics } = usePortfolio();
  const { jobs, activeJob } = useAnalysis();
  const running = isActive(activeJob);
  const completed = jobs.filter((j) => j.status === "completed").length;
  const recent = jobs.filter((j) => j.status === "completed" || j.status === "failed").slice(0, 4);
  const name = user?.display_name || clerkUser?.firstName || "Investor";
  const years = user?.years_until_retirement;

  const isActivePath = (href: string) => router.pathname === href || (href === "/accounts" && router.pathname.startsWith("/accounts"));

  return (
    <div className="flex h-full w-[256px] shrink-0 flex-col border-l border-line px-3 pb-3 pt-1">
      <div className="flex items-center gap-3 px-1.5 py-2">
        {clerkUser?.imageUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={clerkUser.imageUrl} alt="" className="h-10 w-10 rounded-full object-cover ring-2 ring-accent/70 ring-offset-2 ring-offset-frame" />
        ) : (
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-accent font-display font-semibold text-accent-ink">{name.charAt(0)}</span>
        )}
        <div className="min-w-0">
          <p className="truncate text-[14px] font-semibold text-ink">{name}</p>
          <p className="truncate text-[12px] text-muted">{years ? `Retiring in ${years} years` : "Investor"}</p>
        </div>
      </div>

      <button
        onClick={openCommandPalette}
        className="mt-2 flex h-9 w-full items-center gap-2 rounded-[10px] bg-sunken px-2.5 text-[13px] text-muted transition-colors hover:text-ink"
      >
        <Search className="h-4 w-4" strokeWidth={2} />
        <span className="flex-1 text-left">Search</span>
        <kbd className="sm-kbd">⌘K</kbd>
      </button>

      <nav className="sm-scroll-thin mt-4 flex-1 space-y-5 overflow-y-auto pr-0.5" aria-label="Main">
        <div>
          <p className="px-2.5 pb-1.5 text-[12px] text-muted">Portfolio</p>
          <div className="space-y-0.5">
            {portfolioNav.map((item) => (
              <NavLink
                key={item.href}
                {...item}
                active={isActivePath(item.href)}
                onNavigate={onNavigate}
                badge={
                  item.href === "/holdings" && metrics.holdings.length ? (
                    <span className="tabular text-[12px] text-muted">{metrics.holdings.length}</span>
                  ) : item.href === "/accounts" && metrics.accounts.length ? (
                    <span className="tabular text-[12px] text-muted">{metrics.accounts.length}</span>
                  ) : undefined
                }
              />
            ))}
          </div>
        </div>

        <div>
          <p className="px-2.5 pb-1.5 text-[12px] text-muted">Market</p>
          <div className="space-y-0.5">
            {marketNav.map((item) => (
              <NavLink key={item.href} {...item} active={isActivePath(item.href)} onNavigate={onNavigate} />
            ))}
          </div>
        </div>

        <div>
          <p className="px-2.5 pb-1.5 text-[12px] text-muted">AI desk</p>
          <div className="space-y-0.5">
            {aiNav.map((item) => (
              <NavLink
                key={item.href}
                {...item}
                active={isActivePath(item.href)}
                onNavigate={onNavigate}
                badge={
                  item.href === "/ai-team" && running ? (
                    <span className="flex items-center gap-1.5 text-[12px] font-medium text-accent-text">
                      <span className="sm-pulse-dot h-1.5 w-1.5 rounded-full bg-accent text-accent" />
                      Live
                    </span>
                  ) : item.href === "/analysis" && completed ? (
                    <span className="tabular text-[12px] text-muted">{completed}</span>
                  ) : undefined
                }
              />
            ))}
          </div>
        </div>

        {recent.length > 0 && (
          <div>
            <p className="px-2.5 pb-1.5 text-[12px] text-muted">Recent reports</p>
            <ul className="space-y-0.5">
              {recent.map((job) => (
                <li key={job.id}>
                  <Link
                    href={job.status === "completed" ? `/analysis?job_id=${job.id}` : "/ai-team"}
                    onClick={onNavigate}
                    className="flex h-8 items-center gap-2.5 rounded-[10px] px-2.5 text-[13px] text-ink-2 hover:bg-sunken hover:text-ink"
                  >
                    {job.status === "completed" ? (
                      <CheckCircle2 className="h-3.5 w-3.5 text-good" strokeWidth={2.2} aria-label="Completed" />
                    ) : (
                      <XCircle className="h-3.5 w-3.5 text-bad" strokeWidth={2.2} aria-label="Failed" />
                    )}
                    <span className="flex-1 truncate">{formatDateTime(job.completed_at ?? job.created_at)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        )}
      </nav>

      <div className="pt-3">
        <RunCard />
      </div>
    </div>
  );
}

function SyncChip() {
  const { lastSynced, loading } = usePortfolio();
  const { snapshot } = useMarket();
  const [, force] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => force((n) => n + 1), 30_000);
    return () => window.clearInterval(id);
  }, []);
  // How fresh the prices on screen are, from the delayed-price snapshot
  const nifty = snapshot?.indices?.NIFTY50;
  if (snapshot && nifty) {
    const updating = snapshot.updates.active;
    const label = isClosingPrice(nifty.as_of)
      ? `Closing prices, ${formatMarketDate(nifty.as_of).replace(/ \d{4}$/, "")}`
      : `Prices at ${istClock(nifty.as_of)}, ${nifty.delay_minutes} min delayed`;
    const title = `From ${snapshot.source_label ?? "Yahoo Finance"}. ${
      updating ? "New prices every 5 minutes while NSE is open." : `${describeSession(snapshot.session)}.`
    }`;
    return (
      <span className="sm-chip hidden xl:inline-flex" title={title}>
        <span className={`h-1.5 w-1.5 rounded-full ${updating ? "bg-good" : "bg-muted"}`} />
        {label}
      </span>
    );
  }
  return (
    <span className="sm-chip hidden xl:inline-flex" title="Prices refresh on the server every 5 minutes while NSE is open">
      <span className={`h-1.5 w-1.5 rounded-full ${loading ? "bg-muted" : "bg-good"}`} />
      {loading && !lastSynced ? "Syncing…" : `Synced ${timeAgo(lastSynced)}`}
    </span>
  );
}

export default function Layout({ children, title, tabs }: LayoutProps) {
  const router = useRouter();
  const wellRef = useRef<HTMLElement>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // The well is the scroll container; start each page at the top
  useEffect(() => {
    const onDone = () => {
      wellRef.current?.scrollTo({ top: 0 });
      setDrawerOpen(false);
    };
    router.events.on("routeChangeComplete", onDone);
    return () => router.events.off("routeChangeComplete", onDone);
  }, [router.events]);

  return (
    <>
      <Head>
        <title>{title ? `${title} · Samruddhi AI` : "Samruddhi AI"}</title>
      </Head>
      <Protect fallback={<AuthGate />}>
        <div className="h-[100dvh] bg-backdrop lg:p-3">
          <div className="flex h-full flex-col overflow-hidden bg-frame lg:rounded-[28px] lg:border lg:border-line lg:shadow-[0_30px_80px_-40px_rgba(0,0,0,0.35)]">
            {/* Top bar */}
            <header className="sm-no-print flex h-16 shrink-0 items-center gap-3 px-3 lg:px-0">
              <button className="sm-icon-btn lg:hidden" onClick={() => setDrawerOpen(true)} aria-label="Open menu">
                <Menu className="h-5 w-5" strokeWidth={2} />
              </button>
              <Link href="/dashboard" className="flex items-center gap-3 lg:w-[328px] lg:shrink-0">
                <span className="hidden w-[72px] justify-center lg:flex">
                  <LogoMark size={38} />
                </span>
                <LogoMark size={30} className="lg:hidden" />
                <Wordmark />
              </Link>
              <div className="hidden min-w-0 flex-1 md:block">{tabs}</div>
              <div className="ml-auto flex items-center gap-1 lg:pr-4">
                <SyncChip />
                <button onClick={openCommandPalette} className="sm-icon-btn lg:hidden" aria-label="Search">
                  <Search className="h-[18px] w-[18px]" strokeWidth={2} />
                </button>
                <PrivacyToggle />
                <ThemeToggle />
                <NotificationsMenu />
                <div className="ml-1 flex h-9 w-9 items-center justify-center">
                  <UserButton />
                </div>
              </div>
            </header>

            <div className="flex min-h-0 flex-1">
              <aside className="sm-no-print hidden lg:flex">
                <Rail />
                <Sidebar />
              </aside>
              <main
                ref={wellRef}
                id="main"
                className="sm-scroll-thin min-w-0 flex-1 overflow-y-auto bg-well lg:mb-3 lg:mr-3 lg:rounded-[22px] lg:border lg:border-line"
              >
                <div className="mx-auto w-full max-w-[1320px] px-4 pb-10 pt-5 sm:px-6 lg:px-8 lg:pt-7">
                  {tabs && <div className="mb-5 overflow-x-auto md:hidden">{tabs}</div>}
                  {children}
                  <footer className="mt-12 border-t border-line pt-5">
                    <FooterLinks />
                    <Disclosure className="mt-3" />
                  </footer>
                </div>
              </main>
            </div>
          </div>
        </div>

        {/* Mobile drawer */}
        <AnimatePresence>
          {drawerOpen && (
            <motion.div className="fixed inset-0 z-[55] lg:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div className="absolute inset-0 bg-black/40" onClick={() => setDrawerOpen(false)} />
              <motion.div
                className="absolute inset-y-0 left-0 flex max-w-[92vw] bg-frame shadow-2xl"
                initial={{ x: "-100%" }}
                animate={{ x: 0 }}
                exit={{ x: "-100%" }}
                transition={{ type: "spring", stiffness: 420, damping: 40 }}
              >
                <div className="flex flex-col pt-3">
                  <div className="flex h-12 items-center justify-center">
                    <button className="sm-icon-btn" onClick={() => setDrawerOpen(false)} aria-label="Close menu">
                      <X className="h-5 w-5" strokeWidth={2} />
                    </button>
                  </div>
                  <div className="min-h-0 flex-1">
                    <Rail onNavigate={() => setDrawerOpen(false)} />
                  </div>
                </div>
                <div className="pt-3">
                  <Sidebar onNavigate={() => setDrawerOpen(false)} />
                </div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>

        <CommandPalette />
      </Protect>
    </>
  );
}

/** Footer links: how AI is used, and a way to report a problem from any page */
function FooterLinks() {
  const [reporting, setReporting] = useState(false);
  return (
    <nav aria-label="About the AI" className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[12.5px] font-medium">
      <Link href="/ai-use" className="text-ink-2 underline-offset-4 hover:text-ink hover:underline">
        How AI is used here
      </Link>
      <button type="button" onClick={() => setReporting(true)} className="text-ink-2 underline-offset-4 hover:text-ink hover:underline">
        Report a problem
      </button>
      <ReportProblemModal open={reporting} onClose={() => setReporting(false)} surface="other" />
    </nav>
  );
}
