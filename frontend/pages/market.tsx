import { LineChart } from "lucide-react";
import { useEffect, useState } from "react";
import Layout from "../components/Layout";
import MarketView from "../components/MarketView";
import { EmptyState, PageHeader, Skeleton } from "../components/ui";
import { useApi } from "../lib/http";
import { PerspectiveChart, TurbulenceChart, ValuationChart } from "../lib/market";
import { useMarket } from "../lib/market-context";
import { usePortfolio } from "../lib/portfolio-context";
import { investmentHorizon } from "../lib/portfolio";

export default function Market() {
  const api = useApi();
  const { market, loading, snapshot } = useMarket();
  const { user } = usePortfolio();
  const [valuation, setValuation] = useState<ValuationChart | null>(null);
  const [turbulence, setTurbulence] = useState<TurbulenceChart | null>(null);
  const [perspective, setPerspective] = useState<PerspectiveChart | null>(null);

  // Each chart is one precomputed row; fetch the full history once and trim in the browser
  useEffect(() => {
    api<ValuationChart>("/api/market/history?chart=valuation").then(setValuation).catch(() => setValuation(null));
    api<TurbulenceChart>("/api/market/history?chart=turbulence").then(setTurbulence).catch(() => setTurbulence(null));
    api<PerspectiveChart>("/api/market/history?chart=perspective").then(setPerspective).catch(() => setPerspective(null));
  }, [api]);

  if (loading && !market) {
    return (
      <Layout title="Market">
        <Skeleton className="h-12 w-1/2" />
        <Skeleton className="mt-7 h-[300px]" />
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <Skeleton className="h-[140px]" />
          <Skeleton className="h-[140px]" />
          <Skeleton className="h-[140px]" />
        </div>
      </Layout>
    );
  }

  if (!market?.available) {
    return (
      <Layout title="Market">
        <PageHeader title="Market" subtitle="Where the Nifty 50 stands against its own history." />
        <div className="sm-card mt-7">
          <EmptyState
            icon={<LineChart className="h-5 w-5" strokeWidth={2} />}
            title="Market data isn't loaded yet"
            body="The daily market job hasn't written its first reading. It runs every weekday at 7 pm IST."
          />
        </div>
      </Layout>
    );
  }

  return (
    <Layout title="Market">
      <MarketView
        market={market}
        snapshot={snapshot}
        valuation={valuation}
        turbulence={turbulence}
        perspective={perspective}
        shortHorizon={(investmentHorizon(user) ?? 99) < 3}
      />
    </Layout>
  );
}
