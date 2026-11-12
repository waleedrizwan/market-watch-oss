# Spec: Personal Market Watch Dashboard

**Status:** Draft v1, ready to build
**Cost:** $0/month
**Owner:** Waleed

---

## 1. What this is (and isn't)

A personal web page that shows, for a few things I care about, **the upstream price** (raw materials / wholesale) **next to the retail price** (what I actually pay), so I can see price waves building before they hit stores.

The motivating example: in 2025–26, memory chip prices exploded because of AI data center demand, and retail RAM/SSD prices followed weeks to months later. The signal was public the whole time; nobody normal was watching it.

**It is:**
- A curiosity tool. Open it whenever, see what's moving.
- Visual first. Charts side by side, with a one-line plain-English summary per category.

**It is not (in v1):**
- An automated buy alarm. No Z-scores, no push notifications. (Can be added later, see §9.)
- A trading tool or a prediction model.

---

## 2. Scope

### v1 categories
| Category | Why it's included |
|---|---|
| **Memory (RAM + SSD)** | Headline section. Chips are ~90% of an SSD's cost, prices swing violently, and it's the case that motivated this. |
| **Coffee** | Clean upstream→retail chain with years of free history on both ends. Good for validating the dashboard works. |

### v2 candidates (not now)
- Dairy / whey protein
- CAD/USD exchange rate overlay (matters since retail is in Canada, upstream is in USD)
- Any other category, added via config

---

## 3. Data sources (all verified Oct 26, 2026)

### 3.1 Memory

| Role | Source | What | Frequency | History |
|---|---|---|---|---|
| Upstream | DRAMeXchange homepage, DRAM Spot table | DDR5 16Gb (2Gx8) 4800/5600, DDR4 16Gb (2Gx8) 3200 | Daily | **Today only, free.** History is paid. |
| Upstream | DRAMeXchange homepage, Wafer Spot table | 512Gb TLC NAND wafer | Weekly-ish | Today only |
| Midstream | DRAMeXchange homepage, Module Spot table | DDR5 UDIMM 16GB 4800/5600 | Daily | Today only |
| Retail | DRAMeXchange homepage, SSD Street Price table | e.g. Samsung 990 Pro 1TB avg price | Weekly-ish | Today only |
| Retail (reference) | PCPartPicker price trends (memory, storage) | Category charts | Daily | Link only, no data download |

**Key constraint:** DRAMeXchange shows current prices free but not history. The collector must save a snapshot every day starting from first run. Memory charts will start empty and fill in over time.

**Open item:** read DRAMeXchange's Terms of Use before relying on daily automated reads.

### 3.2 Coffee

| Role | Source | ID | Frequency | History |
|---|---|---|---|---|
| Upstream (daily) | Yahoo Finance via `yfinance` | `KC=F` (Arabica Coffee "C" front-month futures, US cents/lb) | Daily | Years, free |
| Upstream (monthly) | FRED | `PCOFFOTMUSDM` (Global price of Coffee, Other Mild Arabica) | Monthly | Years, free |
| Wholesale | FRED | `PCU3119203119201` (PPI: Roasted Coffee) | Monthly, ~6 weeks lag | Since 1967 |
| Retail | FRED | `APU0000717311` (Avg price: ground coffee, USD/lb, US city average) | Monthly | Since 1980 |

Note: `KC=F` is being replaced by a metric contract (`AC`) after March 2028. Fine for now; revisit then.

---

## 4. Architecture

```
GitHub Actions (daily cron)
        │
        ▼
collect.py ──► data/*.csv   (append one row per series per day; never overwrite)
        │
        ▼
build.py   ──► site/data.json  (computed % changes + summaries)
        │
        ▼
site/index.html  (static page, reads data.json, draws charts)
        │
        ▼
GitHub Pages (or open locally)
```

### Repository layout
```
market-watch/
├── .github/workflows/daily.yml
├── config.json          # categories, series, labels
├── collect.py           # fetch + append raw data
├── build.py             # compute metrics, write site/data.json
├── data/                # raw history, one CSV per series
├── site/index.html      # the dashboard
├── requirements.txt     # yfinance, requests, pandas, beautifulsoup4
└── SPEC.md              # this file
```

### Hosting decision
- **Default:** public repo + GitHub Pages. Nothing here is personal data; it's all public market prices.
- **Alternative:** private repo, run locally and open `site/index.html`. (GitHub Pages on private repos requires a paid plan.)

---

## 5. Data collection (`collect.py`)

For each series in `config.json`:
1. Fetch the latest value.
2. Append a row `date, value, source_timestamp` to `data/<series_id>.csv`.
3. Skip if a row for that `source_timestamp` already exists (DRAMeXchange doesn't update every day; FRED only monthly).

### Per-source rules
- **yfinance:** on first run, backfill 5 years of daily closes. After that, fetch the last 5 days and append only new dates. Retry 3× with backoff; Yahoo rate-limits cloud IPs.
- **FRED:** use the official API with `FRED_API_KEY` (free). On first run, backfill full history. Afterwards, re-fetch the last 6 months each run, since FRED revises recent values.
- **DRAMeXchange:** one GET of the homepage per day, parse the tables with BeautifulSoup, record the "Session Average" (spot) or "Avg." (SSD street) column plus the table's "Last Update" timestamp. Send a normal User-Agent. No other pages, no high frequency.

### Failure handling
- If any source fails, still write the others.
- Record failures in `data/_status.json` (source, last success, last error).
- The dashboard shows a visible "stale data" badge for any series not updated in longer than its expected frequency. **A broken fetch must never look like "prices are flat."**

---

## 6. Metrics (`build.py`)

Kept deliberately simple. For each series:

| Metric | Definition |
|---|---|
| Latest value | Most recent observation |
| 30-day change | % change vs the value ~30 days earlier |
| 90-day change | % change vs ~90 days earlier |
| 1-year change | % change vs ~365 days earlier (once history allows) |

For monthly series, use 1-, 3- and 12-month changes instead.

### Futures handling
`KC=F` silently switches contract months, which creates fake jumps on roll days. Mitigation for v1: chart the **weekly average** rather than raw daily closes, so a roll-day jump can't dominate the picture. (Proper roll stitching is a v2 nicety.)

### The "gap" summary
Per category, compare the upstream 90-day change to the retail 90-day change and print one plain-English line:

- Upstream up ≥15%, retail up <5% → **"Upstream is up X%, retail hasn't caught up yet."**
- Both up → **"Rising at both ends."**
- Upstream down ≥15%, retail flat → **"Upstream is falling; retail may follow down."**
- Otherwise → **"No big divergence."**

Thresholds live in `config.json` and are expected to be tuned after a few months of watching.

If a series doesn't yet have 90 days of history (memory, early on), say so instead of computing anything.

---

## 7. Dashboard (`site/index.html`)

One page, one section per category, top to bottom.

Each section:
1. **Header + summary line** (from §6), e.g. *"Memory: DDR5 chip spot up 41% in 90 days; retail SSD prices up 6%. Retail hasn't caught up yet."*
2. **Chart:** upstream and retail on the same time axis, each **indexed to 100** at the start of the visible window, so things with different units ($/chip vs $/lb) can share a chart.
3. **Range toggle:** 3M / 1Y / 5Y / All.
4. **Small table:** latest value, 30d / 90d / 1y change for each series.
5. **Links:** source pages, plus PCPartPicker trends for memory.
6. **Stale badge** if any series is overdue.

Tech: plain HTML + Chart.js from a CDN. No build step. Works on phone width.

---

## 8. Schedule & secrets

- **Cron:** daily at 11:17 UTC (odd minute avoids GitHub's top-of-hour congestion). DRAMeXchange updates Asian afternoon; US markets have closed by then.
- **Secret:** `FRED_API_KEY` in repo secrets (free from fredaccount.stlouisfed.org).
- **Persistence:** the workflow commits `data/` and `site/data.json` back to the repo. Add a `concurrency` group so two runs can't race on the commit.
- GitHub Actions free tier easily covers one ~1-minute run per day.

---

## 9. Later (explicitly out of v1)

- Push alerts (Discord/Telegram) when a "retail hasn't caught up" summary first appears, with a cooldown so it doesn't repeat daily.
- Lag measurement: once there's enough memory history, estimate the actual upstream→retail delay instead of guessing.
- Dairy/whey, CAD/USD overlay, other categories.
- Keepa links for specific products I'm eyeing.
- Proper futures roll stitching.

---

## 10. Open items before / during build

1. Read DRAMeXchange Terms of Use re: daily automated reads.
2. Confirm `PCOFFOTMUSDM` returns as expected via the FRED API (seen listed on FRED, not yet pulled).
3. Confirm the DRAMeXchange homepage is reachable from GitHub Actions (some sites block cloud IPs). Fallback: run the collector on my own machine via a local scheduled job.
4. Pick public repo + Pages vs local-only.

---

## 11. Done means

- Daily run completes in GitHub Actions without manual help for 7 days straight.
- Coffee section shows 5 years of history on day one.
- Memory section shows a growing daily series and an honest "not enough history yet" message until it has 90 days.
- A deliberately broken source shows a stale badge rather than a flat line.
