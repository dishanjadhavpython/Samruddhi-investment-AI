import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, CircleDashed, Loader2, X, XCircle } from "lucide-react";
import Link from "next/link";
import { ButtonHTMLAttributes, ComponentProps, ReactNode, useEffect, useId, useRef } from "react";
import { JobStatus } from "../lib/agents";
import { formatINR, formatINRCompact } from "../lib/currency";

// ---------------------------------------------------------------------------
// Buttons
// ---------------------------------------------------------------------------

type ButtonVariant = "primary" | "dark" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md" | "lg";

const variantClass: Record<ButtonVariant, string> = {
  primary: "sm-btn-primary",
  dark: "sm-btn-dark",
  secondary: "sm-btn-secondary",
  ghost: "sm-btn-ghost",
  danger: "sm-btn-danger",
};

const sizeClass: Record<ButtonSize, string> = { sm: "sm-btn-sm", md: "", lg: "sm-btn-lg" };

export function buttonClass(variant: ButtonVariant = "primary", size: ButtonSize = "md", extra = "") {
  return `sm-btn ${variantClass[variant]} ${sizeClass[size]} ${extra}`.replace(/\s+/g, " ").trim();
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
  loading?: boolean;
}

export function Button({ variant = "primary", size = "md", icon, loading, className = "", children, disabled, ...props }: ButtonProps) {
  return (
    <button className={buttonClass(variant, size, className)} disabled={disabled || loading} {...props}>
      {loading ? <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2.2} /> : icon}
      {children}
    </button>
  );
}

interface LinkButtonProps extends ComponentProps<typeof Link> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
}

export function LinkButton({ variant = "secondary", size = "md", icon, className = "", children, ...props }: LinkButtonProps) {
  return (
    <Link className={buttonClass(variant, size, className)} {...props}>
      {icon}
      {children}
    </Link>
  );
}

// ---------------------------------------------------------------------------
// Surfaces
// ---------------------------------------------------------------------------

interface CardProps {
  title?: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
  children?: ReactNode;
  className?: string;
  bodyClassName?: string;
}

/** The standard white panel inside the page well: small title row, then content. */
export function Card({ title, subtitle, action, icon, children, className = "", bodyClassName = "" }: CardProps) {
  return (
    <section className={`sm-card flex flex-col ${className}`}>
      {(title || action) && (
        <header className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4">
          <div className="min-w-0">
            {title && (
              <h2 className="flex items-center gap-2 text-[13.5px] font-semibold text-ink">
                {icon}
                {title}
              </h2>
            )}
            {subtitle && <p className="mt-0.5 text-[12.5px] text-muted">{subtitle}</p>}
          </div>
          {action && <div className="flex shrink-0 items-center gap-1">{action}</div>}
        </header>
      )}
      <div className={`flex-1 px-5 pb-5 pt-4 ${bodyClassName}`}>{children}</div>
    </section>
  );
}

interface PageHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
}

export function PageHeader({ title, subtitle, actions }: PageHeaderProps) {
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="font-display text-[28px] font-semibold leading-[1.1] tracking-[-0.03em] text-ink sm:text-[32px]">{title}</h1>
        {subtitle && <p className="mt-1.5 max-w-[62ch] text-[14px] text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

interface StatProps {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon?: ReactNode;
  className?: string;
}

export function Stat({ label, value, hint, icon, className = "" }: StatProps) {
  return (
    <div className={`sm-card p-4 ${className}`}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-[12.5px] font-medium text-muted">{label}</p>
        {icon && <span className="text-muted">{icon}</span>}
      </div>
      <p className="mt-2 font-display text-[24px] font-semibold leading-none tracking-[-0.02em] text-ink">{value}</p>
      {hint && <p className="mt-2 text-[12.5px] text-muted">{hint}</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Money — every rupee figure goes through here so privacy mode can blur it
// ---------------------------------------------------------------------------

interface MoneyProps {
  value: number;
  compact?: boolean;
  decimals?: number;
  className?: string;
}

export function Money({ value, compact, decimals = 0, className = "" }: MoneyProps) {
  return (
    <span className={`sm-money ${className}`} title={compact ? formatINR(value) : undefined}>
      {compact ? formatINRCompact(value) : formatINR(value, decimals)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Badges
// ---------------------------------------------------------------------------

type Tone = "neutral" | "good" | "bad" | "warn" | "accent";

const toneClass: Record<Tone, string> = {
  neutral: "bg-sunken text-ink-2",
  good: "bg-good-soft text-good",
  bad: "bg-bad-soft text-bad",
  warn: "bg-warn-soft text-warn",
  accent: "bg-accent-soft text-accent-text",
};

export function Badge({ tone = "neutral", icon, children, className = "" }: { tone?: Tone; icon?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <span className={`sm-chip ${toneClass[tone]} ${className}`}>
      {icon}
      {children}
    </span>
  );
}

const statusMeta: Record<JobStatus, { tone: Tone; label: string; Icon: typeof CheckCircle2 }> = {
  completed: { tone: "good", label: "Completed", Icon: CheckCircle2 },
  failed: { tone: "bad", label: "Failed", Icon: XCircle },
  running: { tone: "accent", label: "Running", Icon: Loader2 },
  pending: { tone: "neutral", label: "Queued", Icon: CircleDashed },
};

export function JobStatusBadge({ status }: { status: JobStatus }) {
  const meta = statusMeta[status] ?? statusMeta.pending;
  return (
    <Badge tone={meta.tone} icon={<meta.Icon className={`h-3.5 w-3.5 ${status === "running" ? "animate-spin" : ""}`} strokeWidth={2.2} />}>
      {meta.label}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Segmented control / tabs
// ---------------------------------------------------------------------------

interface SegmentedProps<T extends string> {
  value: T;
  onChange: (value: T) => void;
  items: { value: T; label: string; icon?: ReactNode }[];
  size?: "sm" | "md";
  ariaLabel: string;
  layoutId?: string;
}

export function Segmented<T extends string>({ value, onChange, items, size = "md", ariaLabel, layoutId }: SegmentedProps<T>) {
  const autoId = useId();
  const pillId = layoutId ?? `seg-${autoId}`;
  return (
    <div role="tablist" aria-label={ariaLabel} className="inline-flex items-center gap-0.5 rounded-xl bg-sunken p-1">
      {items.map((item) => {
        const active = item.value === value;
        return (
          <button
            key={item.value}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(item.value)}
            className={`relative inline-flex items-center gap-1.5 rounded-[9px] font-medium transition-colors ${
              size === "sm" ? "h-7 px-2.5 text-[12px]" : "h-8 px-3 text-[13px]"
            } ${active ? "text-ink" : "text-muted hover:text-ink"}`}
          >
            {active && (
              <motion.span
                layoutId={pillId}
                className="absolute inset-0 rounded-[9px] bg-pill shadow-[0_1px_3px_rgba(0,0,0,0.1)]"
                transition={{ type: "spring", stiffness: 500, damping: 38 }}
              />
            )}
            <span className="relative z-10 inline-flex items-center gap-1.5">
              {item.icon}
              {item.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  width?: string;
}

export function Modal({ open, onClose, title, description, children, footer, width = "max-w-md" }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  // Callers pass inline closures; keep the latest without re-running the focus effect
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCloseRef.current();
    };
    window.addEventListener("keydown", onKey);
    // Focus the first field (or the panel) so keyboard users land inside
    const timer = window.setTimeout(() => {
      const first = panelRef.current?.querySelector<HTMLElement>("input, select, textarea, button[data-autofocus]");
      (first ?? panelRef.current)?.focus();
    }, 30);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.clearTimeout(timer);
      previouslyFocused?.focus?.();
    };
  }, [open]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[60] flex items-end justify-center bg-black/40 p-3 backdrop-blur-[2px] sm:items-center sm:p-6"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) onClose();
          }}
        >
          <motion.div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            tabIndex={-1}
            initial={{ opacity: 0, y: 24, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.98, transition: { duration: 0.12 } }}
            transition={{ type: "spring", stiffness: 420, damping: 34 }}
            className={`w-full ${width} rounded-[22px] border border-line bg-surface shadow-[var(--shadow-pop)] outline-none`}
          >
            <div className="flex items-start justify-between gap-4 px-6 pb-2 pt-5">
              <div>
                <h2 id={titleId} className="font-display text-[20px] font-semibold tracking-[-0.02em] text-ink">
                  {title}
                </h2>
                {description && <div className="mt-1 text-[13.5px] leading-6 text-muted">{description}</div>}
              </div>
              <button onClick={onClose} className="sm-icon-btn -mr-2 shrink-0" aria-label="Close">
                <X className="h-[18px] w-[18px]" strokeWidth={2} />
              </button>
            </div>
            {children && <div className="px-6 py-4">{children}</div>}
            {footer && <div className="flex flex-col-reverse gap-2 border-t border-line px-6 py-4 sm:flex-row sm:justify-end">{footer}</div>}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// ---------------------------------------------------------------------------
// Forms
// ---------------------------------------------------------------------------

interface FieldProps {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  children: ReactNode;
  htmlFor?: string;
}

export function Field({ label, hint, error, children, htmlFor }: FieldProps) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-[13px] font-medium text-ink">
        {label}
      </label>
      {children}
      {error ? <p className="text-[12.5px] text-bad">{error}</p> : hint ? <p className="text-[12.5px] text-muted">{hint}</p> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty & loading
// ---------------------------------------------------------------------------

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  body: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({ icon, title, body, action, className = "" }: EmptyStateProps) {
  return (
    <div className={`flex flex-col items-center justify-center px-6 py-12 text-center ${className}`}>
      {icon && <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-accent-soft text-accent-text">{icon}</div>}
      <p className="font-display text-[18px] font-semibold tracking-[-0.02em] text-ink">{title}</p>
      <div className="mt-1.5 max-w-[46ch] text-[13.5px] leading-6 text-muted">{body}</div>
      {action && <div className="mt-5 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`sm-skeleton ${className}`} aria-hidden="true" />;
}

// ---------------------------------------------------------------------------
// Identity tile for an account — the "workspace" tiles in the rail
// ---------------------------------------------------------------------------

export function tileTone(index: number): number {
  return (index % 6) + 1;
}

export function AccountTile({ name, index, size = 40, className = "" }: { name: string; index: number; size?: number; className?: string }) {
  const tone = tileTone(index);
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center font-display font-semibold text-white ${className}`}
      style={{
        width: size,
        height: size,
        borderRadius: size * 0.3,
        fontSize: size * 0.4,
        background: `linear-gradient(150deg, color-mix(in srgb, var(--series-${tone}) 62%, #fff) 0%, var(--series-${tone}) 58%, color-mix(in srgb, var(--series-${tone}) 80%, #000) 100%)`,
        boxShadow: `inset 0 1px 0 rgba(255,255,255,0.45), inset 0 -2px 0 rgba(0,0,0,0.12), 0 6px 14px -8px var(--series-${tone})`,
        textShadow: "0 1px 1px rgba(0,0,0,0.25)",
      }}
      aria-hidden="true"
    >
      {name.trim().charAt(0).toUpperCase() || "·"}
    </span>
  );
}

/** Thin progress meter: yellow fill on a hairline track */
export function Meter({ value, className = "", label }: { value: number; className?: string; label: string }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className={`h-1.5 w-full overflow-hidden rounded-full bg-line ${className}`} role="meter" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
      <motion.div className="h-full rounded-full bg-accent" initial={{ width: 0 }} animate={{ width: `${pct}%` }} transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }} />
    </div>
  );
}
