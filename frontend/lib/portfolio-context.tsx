import { useAuth } from "@clerk/nextjs";
import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { AnalysisEvents } from "./events";
import { useApi } from "./http";
import type { LiveQuote } from "./market";
import {
  Account,
  computeMetrics,
  normalizeAccount,
  normalizePosition,
  normalizeUser,
  PortfolioMetrics,
  UserProfile,
  withLiveQuotes,
} from "./portfolio";

// Live prices arrive from MarketProvider's snapshot polling (DynamoDB, every
// minute while NSE prices can change), so the portfolio itself is reloaded
// from Aurora only when a tab comes back after a while, or after an analysis.
const REFRESH_ON_RETURN_AFTER_MS = 10 * 60 * 1000;

interface PortfolioContextValue {
  user: UserProfile | null;
  accounts: Account[];
  metrics: PortfolioMetrics;
  loading: boolean;
  error: string | null;
  lastSynced: Date | null;
  refresh: () => Promise<void>;
  saveUser: (patch: Partial<UserProfile>) => Promise<void>;
  /** Delayed prices from GET /api/market/snapshot, applied over the stored ones */
  setLiveQuotes: (quotes: Record<string, LiveQuote>) => void;
}

const PortfolioContext = createContext<PortfolioContextValue | null>(null);

/**
 * One shared copy of the user's profile, accounts and positions for every page.
 * Navigating between pages shows the cached copy instantly and refreshes in the
 * background, instead of each page refetching behind a spinner.
 */
export function PortfolioProvider({ children }: { children: ReactNode }) {
  const { isSignedIn } = useAuth();
  const api = useApi();
  const [user, setUser] = useState<UserProfile | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastSynced, setLastSynced] = useState<Date | null>(null);
  const [liveQuotes, setLiveQuotes] = useState<Record<string, LiveQuote>>({});
  const inflight = useRef<Promise<void> | null>(null);
  const syncedAt = useRef(0);

  const refresh = useCallback(() => {
    if (inflight.current) return inflight.current;
    const run = (async () => {
      try {
        const [userResponse, accountRows] = await Promise.all([
          api<{ user: unknown }>("/api/user"),
          api<unknown[]>("/api/accounts"),
        ]);
        const rows = Array.isArray(accountRows) ? accountRows : [];
        const withPositions = await Promise.all(
          rows.map(async (row) => {
            const id = (row as { id?: string }).id;
            if (!id) return normalizeAccount(row);
            const data = await api<{ positions?: unknown[] }>(`/api/accounts/${id}/positions`).catch(() => ({ positions: [] }));
            return normalizeAccount(row, (data.positions ?? []).map(normalizePosition));
          }),
        );
        setUser(normalizeUser(userResponse.user));
        setAccounts(withPositions);
        setError(null);
        setLastSynced(new Date());
        syncedAt.current = Date.now();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not load your portfolio.");
      } finally {
        setLoading(false);
        inflight.current = null;
      }
    })();
    inflight.current = run;
    return run;
  }, [api]);

  useEffect(() => {
    if (!isSignedIn) return;
    refresh();

    const onVisible = () => {
      if (document.visibilityState === "visible" && Date.now() - syncedAt.current > REFRESH_ON_RETURN_AFTER_MS) refresh();
    };
    const onCompleted = () => refresh();
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener(AnalysisEvents.COMPLETED, onCompleted);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener(AnalysisEvents.COMPLETED, onCompleted);
    };
  }, [isSignedIn, refresh]);

  const saveUser = useCallback(
    async (patch: Partial<UserProfile>) => {
      const updated = await api<unknown>("/api/user", { method: "PUT", body: JSON.stringify(patch) });
      setUser(normalizeUser(updated));
    },
    [api],
  );

  const liveAccounts = useMemo(() => withLiveQuotes(accounts, liveQuotes), [accounts, liveQuotes]);
  const metrics = useMemo(() => computeMetrics(liveAccounts), [liveAccounts]);

  return (
    <PortfolioContext.Provider value={{ user, accounts: liveAccounts, metrics, loading, error, lastSynced, refresh, saveUser, setLiveQuotes }}>
      {children}
    </PortfolioContext.Provider>
  );
}

export function usePortfolio(): PortfolioContextValue {
  const ctx = useContext(PortfolioContext);
  if (!ctx) throw new Error("usePortfolio must be used inside PortfolioProvider");
  return ctx;
}
