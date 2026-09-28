import { SignedIn, SignedOut, SignInButton, SignUpButton } from "@clerk/nextjs";
import { motion } from "framer-motion";
import { BarChart3, FileText, Globe, LineChart, ShieldCheck, Tags, Workflow } from "lucide-react";
import Head from "next/head";
import Link from "next/link";
import { CompositionBar, Gauge, SERIES } from "../components/charts";
import Disclosure from "../components/Disclosure";
import { LogoMark, Wordmark } from "../components/Logo";
import { WarpBackdrop } from "../components/Shader";
import ThemeToggle from "../components/ThemeToggle";
import { buttonClass } from "../components/ui";

// Illustrative figures for the preview card — clearly labelled as a sample
const SAMPLE_MIX = [
  { key: "equity", label: "Equity", value: 62, color: SERIES[0] },
  { key: "fixed_income", label: "Fixed income", value: 24, color: SERIES[1] },
  { key: "commodities", label: "Gold & silver", value: 9, color: SERIES[2] },
  { key: "cash", label: "Cash", value: 5, color: "var(--series-cash)" },
];

const STEPS = [
  { icon: Workflow, title: "Planner", body: "Checks every holding and decides which specialists to call." },
  { icon: Tags, title: "Tagger", body: "Classifies anything new by asset class, region and sector." },
  { icon: FileText, title: "Reporter", body: "Writes your review, with market context from the Researcher." },
  { icon: BarChart3, title: "Charter", body: "Draws the charts that explain where your money sits." },
  { icon: LineChart, title: "Retirement", body: "Simulates 500 market paths to test whether your savings last." },
];

export default function Home() {
  return (
    <>
      <Head>
        <title>Samruddhi AI · Your portfolio, reviewed by AI analysts</title>
      </Head>

      <div className="min-h-screen bg-backdrop p-2 sm:p-3">
        {/* Hero */}
        <section className="relative overflow-hidden rounded-[28px] text-white">
          <WarpBackdrop speed={0.8} />
          <div className="absolute inset-0 bg-gradient-to-r from-black/90 via-black/60 to-black/5" aria-hidden="true" />

          <div className="relative mx-auto max-w-[1320px] px-5 sm:px-8">
            <nav className="flex h-20 items-center justify-between">
              <Link href="/" className="flex items-center gap-2.5">
                <LogoMark size={36} />
                <Wordmark className="!text-white" />
              </Link>
              <div className="flex items-center gap-2">
                <ThemeToggle className="!text-white/80 hover:!bg-white/10 hover:!text-white" />
                <SignedOut>
                  <SignInButton mode="modal">
                    <button className="sm-btn hidden !text-white hover:bg-white/10 sm:inline-flex">Sign in</button>
                  </SignInButton>
                  <SignUpButton mode="modal">
                    <button className={buttonClass("primary")}>Get started</button>
                  </SignUpButton>
                </SignedOut>
                <SignedIn>
                  <Link href="/dashboard" className={buttonClass("primary")}>
                    Open dashboard
                  </Link>
                </SignedIn>
              </div>
            </nav>

            <div className="grid items-center gap-12 pb-16 pt-10 lg:grid-cols-[1.1fr_0.9fr] lg:pb-24 lg:pt-16">
              <motion.div initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}>
                <h1 className="max-w-[14ch] font-display text-[clamp(2.6rem,6.2vw,5.2rem)] font-semibold leading-[0.98] tracking-[-0.045em]">
                  Your portfolio, reviewed by a team of AI analysts.
                </h1>
                <p className="mt-6 max-w-[48ch] text-[17px] leading-7 text-white/75">
                  Add your EPF, PPF, NPS and demat holdings. Five agents classify them, write you a plain-English review, chart where the money
                  sits and test whether it lasts through retirement.
                </p>
                <div className="mt-9 flex flex-wrap gap-3">
                  <SignedOut>
                    <SignUpButton mode="modal">
                      <button className={buttonClass("primary", "lg")}>Create a free account</button>
                    </SignUpButton>
                    <SignInButton mode="modal">
                      <button className={buttonClass("secondary", "lg", "!border-white/25 !bg-white/10 !text-white hover:!bg-white/20")}>I have an account</button>
                    </SignInButton>
                  </SignedOut>
                  <SignedIn>
                    <Link href="/dashboard" className={buttonClass("primary", "lg")}>
                      Go to your dashboard
                    </Link>
                  </SignedIn>
                </div>
              </motion.div>

              {/* Product preview */}
              <motion.div
                initial={{ opacity: 0, y: 28, rotate: -1.5 }}
                animate={{ opacity: 1, y: 0, rotate: 0 }}
                transition={{ duration: 0.9, delay: 0.15, ease: [0.16, 1, 0.3, 1] }}
                className="rounded-[22px] border border-white/15 bg-surface p-5 text-ink shadow-[0_40px_100px_-30px_rgba(0,0,0,0.8)]"
              >
                <div className="flex items-center justify-between">
                  <p className="text-[12.5px] font-medium text-muted">Net worth</p>
                  <span className="sm-chip">Sample portfolio</span>
                </div>
                <p className="mt-2 font-display text-[40px] font-semibold leading-none tracking-[-0.035em]">₹48,62,310</p>
                <div className="mt-6">
                  <CompositionBar slices={SAMPLE_MIX} legend={false} height={14} />
                  <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12.5px]">
                    {SAMPLE_MIX.map((s) => (
                      <span key={s.key} className="flex items-center justify-between gap-2 text-ink-2">
                        <span className="flex items-center gap-2">
                          <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: s.color }} />
                          {s.label}
                        </span>
                        <span className="font-semibold text-ink">{s.value}%</span>
                      </span>
                    ))}
                  </div>
                </div>
                <div className="mt-5 grid grid-cols-[auto_1fr] items-center gap-4 rounded-[14px] bg-sunken p-4">
                  <Gauge value={82} size={92} color="var(--good)" />
                  <div>
                    <p className="text-[13.5px] font-semibold">82% of market paths last 30 years</p>
                    <p className="mt-0.5 text-[12.5px] text-muted">at ₹6 lakh a year in retirement</p>
                  </div>
                </div>
                <blockquote className="mt-4 border-l-2 border-accent pl-3 text-[13px] leading-5 text-ink-2">
                  &ldquo;Equity is 8 points above the 70% target you set, mostly because NIFTYBEES has grown. That is about ₹3.9 lakh above your own target.&rdquo;
                </blockquote>
              </motion.div>
            </div>
          </div>
        </section>

        {/* How a review runs */}
        <section className="mx-auto max-w-[1320px] px-3 py-20 sm:px-6">
          <div className="max-w-2xl">
            <h2 className="font-display text-[clamp(1.8rem,3.4vw,2.8rem)] font-semibold leading-[1.05] tracking-[-0.035em] text-ink">
              One tap, five specialists, a few minutes.
            </h2>
            <p className="mt-4 text-[16px] leading-7 text-muted">
              Each agent does one job and hands its work on. You can watch the whole run live, step by step, and every report shows which agent wrote it.
            </p>
          </div>
          <ol className="mt-12 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {STEPS.map((step, i) => (
              <li key={step.title} className="sm-card relative p-5">
                <div className="flex items-center justify-between">
                  <span
                    className="flex h-10 w-10 items-center justify-center rounded-[12px]"
                    style={{
                      background: `linear-gradient(150deg, color-mix(in srgb, var(--series-${[1, 6, 2, 4, 5][i]}) 55%, #fff), var(--series-${[1, 6, 2, 4, 5][i]}))`,
                      color: i === 0 ? "#17130a" : "#fff",
                    }}
                  >
                    <step.icon className="h-5 w-5" strokeWidth={2} />
                  </span>
                  <span className="font-display text-[13px] font-semibold text-muted">Step {i + 1}</span>
                </div>
                <p className="mt-5 text-[15px] font-semibold text-ink">{step.title}</p>
                <p className="mt-1.5 text-[13.5px] leading-6 text-muted">{step.body}</p>
              </li>
            ))}
          </ol>
        </section>

        {/* India-first + trust */}
        <section className="mx-auto grid max-w-[1320px] gap-3 px-3 pb-20 sm:px-6 lg:grid-cols-3">
          <div className="relative overflow-hidden rounded-[22px] bg-[#121212] p-8 text-white lg:col-span-2">
            <div className="pointer-events-none absolute -right-20 -top-24 h-72 w-72 rounded-full opacity-50 blur-3xl" style={{ background: "#ffc62b" }} aria-hidden="true" />
            <div className="relative">
              <h3 className="font-display text-[28px] font-semibold leading-tight tracking-[-0.03em]">Built for how Indians invest</h3>
              <p className="mt-3 max-w-[52ch] text-[15px] leading-7 text-white/70">
                Rupees with lakh and crore grouping, a catalogue of Indian ETFs and funds, and accounts that match yours.
              </p>
              <div className="mt-6 flex flex-wrap gap-2">
                {["EPF", "PPF", "NPS", "Demat", "Mutual funds", "Gold ETFs", "Liquid funds"].map((tag) => (
                  <span key={tag} className="rounded-full border border-white/15 bg-white/5 px-3 py-1.5 text-[13px] font-medium">
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          </div>
          <div className="sm-card flex flex-col gap-5 p-8">
            <div className="flex items-start gap-3">
              <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-good" strokeWidth={2} />
              <div>
                <p className="text-[15px] font-semibold text-ink">Your data stays yours</p>
                <p className="mt-1 text-[13.5px] leading-6 text-muted">Every account and report is tied to your sign-in and kept apart from other users.</p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <Globe className="mt-0.5 h-5 w-5 shrink-0 text-accent-text" strokeWidth={2} />
              <div>
                <p className="text-[15px] font-semibold text-ink">Prices through the trading day</p>
                <p className="mt-1 text-[13.5px] leading-6 text-muted">Prices update every 5 minutes while NSE is open, shown 15 minutes delayed. A new review runs only when you ask for one.</p>
              </div>
            </div>
          </div>
        </section>

        <footer className="mx-auto flex max-w-[1320px] flex-col gap-3 border-t border-line px-3 py-8 text-[12.5px] text-muted sm:px-6">
          <span className="flex items-center gap-2">
            <LogoMark size={22} /> Samruddhi AI
          </span>
          <Disclosure />
        </footer>
      </div>
    </>
  );
}
