import Head from "next/head";
import Link from "next/link";
import { LogoMark } from "../components/Logo";
import { buttonClass } from "../components/ui";

export default function Custom500() {
  return (
    <>
      <Head>
        <title>Something went wrong · Samruddhi AI</title>
      </Head>
      <div className="flex min-h-screen items-center justify-center bg-backdrop px-4">
        <div className="sm-card w-full max-w-md px-8 py-10 text-center">
          <LogoMark size={40} className="mx-auto" />
          <p className="mt-6 font-display text-[64px] font-semibold leading-none tracking-[-0.05em] text-ink">500</p>
          <h1 className="mt-3 font-display text-[22px] font-semibold tracking-[-0.02em] text-ink">The server hit a problem</h1>
          <p className="mt-2 text-[14px] leading-6 text-muted">Try again in a moment. If it keeps happening, the API may be down.</p>
          <div className="mt-7 flex flex-col justify-center gap-2 sm:flex-row">
            <button onClick={() => window.location.reload()} className={buttonClass("primary")}>
              Try again
            </button>
            <Link href="/dashboard" className={buttonClass("secondary")}>
              Go to dashboard
            </Link>
          </div>
        </div>
      </div>
    </>
  );
}
