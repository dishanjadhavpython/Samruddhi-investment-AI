import "@/styles/globals.css";
import { ClerkProvider } from "@clerk/nextjs";
import type { AppProps } from "next/app";
import { Bricolage_Grotesque, Geist, Geist_Mono } from "next/font/google";
import ErrorBoundary from "@/components/ErrorBoundary";
import { ToastContainer } from "@/components/Toast";
import { AnalysisProvider } from "@/lib/analysis-context";
import { MarketProvider } from "@/lib/market-context";
import { PortfolioProvider } from "@/lib/portfolio-context";
import { PreferencesProvider } from "@/lib/preferences";

const geist = Geist({ subsets: ["latin"], display: "swap" });
const geistMono = Geist_Mono({ subsets: ["latin"], display: "swap" });
const bricolage = Bricolage_Grotesque({ subsets: ["latin"], display: "swap", axes: ["opsz"] });

export default function App({ Component, pageProps }: AppProps) {
  return (
    <ErrorBoundary>
      {/* Font families live on :root so fixed overlays and portals inherit them too */}
      <style jsx global>{`
        :root {
          --font-geist: ${geist.style.fontFamily};
          --font-geist-mono: ${geistMono.style.fontFamily};
          --font-bricolage: ${bricolage.style.fontFamily};
        }
      `}</style>
      <ClerkProvider
        {...pageProps}
        appearance={{
          variables: { colorPrimary: "#121212", borderRadius: "12px", fontFamily: geist.style.fontFamily },
        }}
      >
        <PreferencesProvider>
          <PortfolioProvider>
            <MarketProvider>
              <AnalysisProvider>
                <Component {...pageProps} />
                <ToastContainer />
              </AnalysisProvider>
            </MarketProvider>
          </PortfolioProvider>
        </PreferencesProvider>
      </ClerkProvider>
    </ErrorBoundary>
  );
}
