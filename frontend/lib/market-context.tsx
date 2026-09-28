import { useAuth } from "@clerk/nextjs";
import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useApi } from "./http";
import { MarketContextData, MarketSnapshot, nextSnapshotPoll } from "./market";
import { usePortfolio } from "./portfolio-context";

// The index context (Aurora) changes once a day at 19:00 IST, so it is fetched
// once and again when a tab comes back after a while. Delayed intraday prices
// come from the snapshot (DynamoDB): every minute while they can still change,
// and not at all after the close, apart from one wake-up when the next
// session's first delayed price is due (plan section 11, Phase 5).
const REFRESH_ON_RETURN_AFTER_MS = 10 * 60_000;

interface MarketContextValue {
  market: MarketContextData | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  /** Delayed prices for the indices and the user's exchange-traded holdings */
  snapshot: MarketSnapshot | null;
}

const Ctx = createContext<MarketContextValue | null>(null);

/** One shared copy of the index-level market context and the delayed prices for every page. */
export function MarketProvider({ children }: { children: ReactNode }) {
  const { isSignedIn } = useAuth();
  const api = useApi();
  const { accounts, loading: portfolioLoading, setLiveQuotes } = usePortfolio();
  const [market, setMarket] = useState<MarketContextData | null>(null);
  const [snapshot, setSnapshot] = useState<MarketSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fetchedAt = useRef(0);
  const missedWhileHidden = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const data = await api<MarketContextData>("/api/market/context");
      setMarket(data);
      setError(null);
      fetchedAt.current = Date.now();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load market data.");
    } finally {
      setLoading(false);
    }
  }, [api]);

  // Held exchange-traded symbols; NAV funds have one price a day, so they are left out
  const symbols = useMemo(
    () =>
      [...new Set(accounts.flatMap((a) => a.positions.filter((p) => p.instrument?.price_source !== "amfi").map((p) => p.symbol)))]
        .sort()
        .slice(0, 50)
        .join(","),
    [accounts],
  );

  const loadSnapshot = useCallback(async () => {
    const params = new URLSearchParams({ intraday: "NIFTY50" });
    if (symbols) params.set("symbols", symbols);
    try {
      const data = await api<MarketSnapshot>(`/api/market/snapshot?${params}`);
      setSnapshot(data);
      setLiveQuotes(data.quotes ?? {});
    } catch {
      // Keep the stored prices; schedule the next attempt from the last snapshot's timing
      setSnapshot((previous) => (previous ? { ...previous } : previous));
    }
  }, [api, symbols, setLiveQuotes]);

  useEffect(() => {
    if (!isSignedIn) return;
    refresh();
  }, [isSignedIn, refresh]);

  useEffect(() => {
    if (!isSignedIn || portfolioLoading) return;
    loadSnapshot();
  }, [isSignedIn, portfolioLoading, loadSnapshot]);

  // Each snapshot says when the next one is worth asking for
  useEffect(() => {
    if (!isSignedIn || !snapshot) return;
    const wait = nextSnapshotPoll(snapshot);
    if (wait === null) return;
    const timer = window.setTimeout(() => {
      if (document.visibilityState === "visible") loadSnapshot();
      else missedWhileHidden.current = true;
    }, wait);
    return () => window.clearTimeout(timer);
  }, [isSignedIn, snapshot, loadSnapshot]);

  useEffect(() => {
    if (!isSignedIn) return;
    const onVisible = () => {
      if (document.visibilityState !== "visible") return;
      if (missedWhileHidden.current) {
        missedWhileHidden.current = false;
        loadSnapshot();
      }
      if (Date.now() - fetchedAt.current > REFRESH_ON_RETURN_AFTER_MS) refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [isSignedIn, refresh, loadSnapshot]);

  return <Ctx.Provider value={{ market, loading, error, refresh, snapshot }}>{children}</Ctx.Provider>;
}

export function useMarket(): MarketContextValue {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useMarket must be used inside MarketProvider");
  return ctx;
}
