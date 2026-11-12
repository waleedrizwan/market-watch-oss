# Market Watch

What's likely to change price soon, based on what raw materials already did. 27 product chains (electronics, food, energy, vehicles, home, clothing), each pairing an upstream price with a store price. See [SPEC.md](SPEC.md) for the original v1 design.

> This repository is the public source code only. Collected price data isn't included, because DRAMeXchange's terms forbid republishing it. To run your own copy, keep your fork **private** (the daily job refuses to run in a public repository), then follow *Set up the website* below. `site/data.json` appears after your first `python collect.py && python build.py`.

The dashboard runs on a Cloudflare Worker behind Cloudflare Access, so only you can see it. There are no trackers, cookies or third-party requests; see [site/privacy.html](site/privacy.html).

## How the forecast works

For each chain, `build.py` fits a distributed-lag model on up to 20 years of monthly log changes: store-price change = seasonal baseline + Σ b_j × upstream change j months earlier (j = 0..12). Upstream moves already observed but not yet passed through give the expected store-price move over the next 6 months, assuming upstream stays flat from here. Each chain is backtested out of sample (quarterly refits over ~6 years); chains whose backtest fails get "no reliable signal" instead of a number. Tunables live in `config.json` → `forecast`.

Sources: FRED (most series, keyless CSV or `FRED_API_KEY`), BLS public API (item-level CPI FRED doesn't carry; optional `BLS_API_KEY`), Yahoo via yfinance (`KC=F`), DRAMeXchange homepage (daily memory spot prices).

## How it runs

```
GitHub Actions, daily 11:17 UTC (.github/workflows/daily.yml)
  collect.py  ->  data/*.csv          append today's values; failures go to data/_status.json
  build.py    ->  site/data.json      forecasts, % changes, stale flags
  git commit data/ + site/data.json
  wrangler deploy                     Cloudflare Worker serves site/, Access-gated
```

- `src/index.ts` is the Worker. It serves `site/` only to visitors with a valid Cloudflare Access token (it verifies the signed JWT itself, so the data stays private even if Access were misconfigured). `/privacy` and the stylesheet and fonts are public. Without Access configured it fails closed and shows a "private dashboard" page.
- Everything the page loads is self-hosted (`site/vendor`, `site/fonts`), and a strict Content-Security-Policy blocks anything else.
- `.github/workflows/ci.yml` runs every test on pushes and pull requests, and deploys code changes from `main`.
- The data-collecting job only runs in a **private** repository. DRAMeXchange's Terms of Use §6.2 forbid republishing its prices, and the job commits them.

## Set up the website

1. **Deploy once** (needs `npx wrangler login`):
   ```bash
   npm install
   npx wrangler deploy
   ```
2. **Lock it down with Cloudflare Access.** In the Cloudflare dashboard, open *Zero Trust → Access → Applications → Add an application → Self-hosted*. Use the Worker's `*.workers.dev` hostname, and add a policy that allows only your email. Cloudflare also offers a one-click version under *Workers & Pages → market-watch → Settings → Domains & Routes → workers.dev → Cloudflare Access*. Then copy the application's **Audience (AUD) tag** and your **team domain** (`<team>.cloudflareaccess.com`) and save both as Worker secrets:
   ```bash
   npx wrangler secret put ACCESS_TEAM_DOMAIN
   ```
   ```bash
   npx wrangler secret put ACCESS_AUD
   ```
   Optional: add a *Bypass* policy for the path `/privacy` so the privacy policy is readable without signing in.
3. **Let the daily job deploy.** Create an API token from the *Edit Cloudflare Workers* template (*My Profile → API Tokens*), then store it and your account ID as repository secrets:
   ```bash
   gh secret set CLOUDFLARE_API_TOKEN
   ```
   ```bash
   gh secret set CLOUDFLARE_ACCOUNT_ID
   ```
   Without them, the daily job still collects and commits data and just skips the deploy.

## Run locally

```bash
uv venv -p 3.12 .venv && uv pip install -p .venv -r requirements-dev.txt
.venv/bin/python collect.py   # append today's values to data/*.csv
.venv/bin/python build.py     # write site/data.json
npm install
cp .dev.vars.example .dev.vars   # skips the Access check, local only
npm run dev                      # http://localhost:8787
```

`FRED_API_KEY` is optional: with it, FRED series come from the official API; without it, from FRED's public CSV download.

## Tests

```bash
npm run test:all
```

| Suite | Command | Covers |
|---|---|---|
| Python | `.venv/bin/python -m pytest` | Collectors (FRED, BLS, yfinance, DRAMeXchange parsing, retries, dedupe, revision window, failure isolation), the lag model on synthetic data with a known answer, verdict thresholds, stale detection, the `data.json` contract, `config.json` consistency |
| Worker | `npm test` | Access enforcement (missing, forged, expired, wrong-audience tokens), fail-closed default, public paths, security headers, caching, no third-party resources, dashboard helper functions |
| Browser | `npm run test:e2e` | The real page in Chromium on desktop and a phone viewport: buckets, forecasts, stale warnings, filters, charts, keyboard use, error state, dark mode, no console errors or outside requests |

## Changes from the spec (found while building, Oct 26 2026)

- **SSD street price isn't free.** It isn't on the DRAMeXchange homepage; `/Price/SSD_Street` requires a login. Memory "retail" is therefore:
  - the gap summary compares **DDR5 chip spot → DDR5 16GB module spot** (closest free signal to what a RAM stick costs), and
  - **US CPI: computers & peripherals** (FRED `CUSR0000SEEE01`, monthly, back to 2005) is charted as a slow retail reference.
- **DRAMeXchange Terms of Use §6.2** forbid displaying or publishing its materials to third parties without written consent. That's why collected data stays in a private repository and the website is behind Cloudflare Access.
- `PCOFFOTMUSDM` confirmed working (open item 2).
- FRED's CSV endpoint rejects browser-like User-Agents, so the keyless fallback uses requests' default UA.

## License

Code: [MIT](LICENSE). Bundled fonts and libraries: see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Price data belongs to its sources and isn't covered by the license.
