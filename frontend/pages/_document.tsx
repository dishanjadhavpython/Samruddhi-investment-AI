import { Head, Html, Main, NextScript } from "next/document";

// Runs before first paint so the page never flashes the wrong theme or
// shows balances for a moment before privacy mode blurs them.
const bootScript = `
(function () {
  try {
    var root = document.documentElement;
    var stored = localStorage.getItem('samruddhi-theme');
    var theme = stored || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    root.dataset.theme = theme;
    root.dataset.privacy = localStorage.getItem('samruddhi-privacy') === 'on' ? 'on' : 'off';
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', theme === 'dark' ? '#0a0a0b' : '#e6e6ea');
  } catch (e) {}
})();
`;

export default function Document() {
  return (
    <Html lang="en-IN" suppressHydrationWarning>
      <Head>
        <link rel="icon" href="/favicon.ico" />
        <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
        <link rel="apple-touch-icon" href="/favicon.ico" />
        <link rel="manifest" href="/manifest.json" />
        <meta name="description" content="Samruddhi AI — a team of AI agents that reviews your Indian equity portfolio, charts it and stress-tests your retirement." />
        <meta name="theme-color" content="#e6e6ea" />
        <script dangerouslySetInnerHTML={{ __html: bootScript }} />
      </Head>
      <body>
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
