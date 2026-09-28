import Head from "next/head";
import Link from "next/link";
import { LogoMark } from "../components/Logo";
import { buttonClass } from "../components/ui";

export default function Custom404() {
  return (
    <>
      <Head>
        <title>Page not found · Samruddhi AI</title>
      </Head>
      <div className="flex min-h-screen items-center justify-center bg-backdrop px-4">
        <div className="sm-card w-full max-w-md px-8 py-10 text-center">
          <LogoMark size={40} className="mx-auto" />
          <p className="mt-6 font-display text-[64px] font-semibold leading-none tracking-[-0.05em] text-ink">404</p>
          <h1 className="mt-3 font-display text-[22px] font-semibold tracking-[-0.02em] text-ink">This page doesn&apos;t exist</h1>
          <p className="mt-2 text-[14px] leading-6 text-muted">The link may be old, or the page has moved.</p>
          <div className="mt-7 flex flex-col justify-center gap-2 sm:flex-row">
            <Link href="/dashboard" className={buttonClass("primary")}>
              Go to dashboard
            </Link>
            <Link href="/" className={buttonClass("secondary")}>
              Home
            </Link>
          </div>
        </div>
      </div>
    </>
  );
}
