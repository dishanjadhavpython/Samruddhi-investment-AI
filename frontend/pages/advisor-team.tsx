import { useEffect } from "react";
import Head from "next/head";
import { useRouter } from "next/router";

// This page moved to /ai-team. The site is a static export, which has no
// server-side redirects, so old links and bookmarks are forwarded in the browser.
export default function AdvisorTeamRedirect() {
  const router = useRouter();

  useEffect(() => {
    if (!router.isReady) return;
    router.replace({ pathname: "/ai-team", query: router.query });
  }, [router]);

  return (
    <Head>
      <meta name="robots" content="noindex" />
    </Head>
  );
}
