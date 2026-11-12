const escapeHtml = (s: string) =>
  s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

/** Shown instead of the dashboard when the visitor isn't signed in via Cloudflare Access. */
export function lockedPage(reason: string, setupNeeded: boolean): string {
  const body = setupNeeded
    ? `<p class="lede">This dashboard is private, and its sign-in isn't switched on yet.</p>
        <p>If you own it: turn on Cloudflare Access for this Worker, then save <code>ACCESS_TEAM_DOMAIN</code> and
        <code>ACCESS_AUD</code> with <code>wrangler secret put</code>. The README walks through it.</p>`
    : `<p class="lede">This dashboard is private to its owner.</p>
        <p>${escapeHtml(reason)} If it's yours, reload the page to sign in through Cloudflare Access.</p>`;
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="robots" content="noindex, nofollow" />
    <meta name="color-scheme" content="light dark" />
    <title>Private · Market Watch</title>
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
    <link rel="stylesheet" href="/styles.css" />
  </head>
  <body>
    <div class="wrap">
      <main class="prose">
        <h1>Private dashboard</h1>
        ${body}
      </main>
      <footer class="footer">
        <nav aria-label="Footer">
          <a href="/privacy">Privacy policy</a>
          <a href="https://github.com/waleedrizwan/market-watch-oss" rel="noopener">Source code (MIT)</a>
        </nav>
      </footer>
    </div>
  </body>
</html>`;
}
