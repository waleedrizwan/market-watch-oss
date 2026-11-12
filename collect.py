"""Fetch the latest value for every series in config.json and append it to data/<id>.csv.

Rows are never rewritten, except FRED rows inside the revision window.
A failing source is recorded in data/_status.json and never stops the others.
"""
import csv
import io
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
STATUS_PATH = DATA / "_status.json"
FIELDS = ["date", "value", "source_timestamp"]
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
FRED_REVISION_DAYS = 183
DRAMX_URL = "https://www.dramexchange.com/"


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_rows(series_id):
    path = DATA / f"{series_id}.csv"
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def write_rows(series_id, rows):
    rows = sorted(rows, key=lambda r: (r["date"], r["source_timestamp"]))
    with (DATA / f"{series_id}.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def append_rows(series_id, new_rows):
    """Append rows whose source_timestamp isn't already stored. Returns count added."""
    rows = read_rows(series_id)
    seen = {r["source_timestamp"] for r in rows}
    added = [r for r in new_rows if r["source_timestamp"] not in seen]
    if added:
        write_rows(series_id, rows + added)
    return len(added)


def replace_since(series_id, new_rows, since):
    """FRED revises recent values: drop stored rows on/after `since`, then merge."""
    rows = [r for r in read_rows(series_id) if r["date"] < since]
    seen = {r["source_timestamp"] for r in rows}
    rows += [r for r in new_rows if r["source_timestamp"] not in seen]
    write_rows(series_id, rows)


def with_retries(fn, attempts=3, base_delay=5):
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(base_delay * 2**i)


# --- yfinance -------------------------------------------------------------

def collect_yfinance(series):
    import yfinance as yf

    first_run = not read_rows(series["id"])

    def fetch():
        df = yf.Ticker(series["ticker"]).history(
            period="5y" if first_run else "5d", interval="1d", auto_adjust=False
        )
        if df.empty:
            raise RuntimeError(f"yfinance returned no rows for {series['ticker']}")
        return df

    df = with_retries(fetch)
    today = datetime.now(timezone.utc).date().isoformat()
    rows = []
    for ts, close in df["Close"].dropna().items():
        d = ts.date().isoformat()
        if d >= today:  # today's bar may still be trading
            continue
        rows.append({"date": d, "value": f"{close:.4f}", "source_timestamp": d})
    if not rows:
        raise RuntimeError("no completed daily bars returned")
    return append_rows(series["id"], rows)


# --- FRED -----------------------------------------------------------------

def fetch_fred(fred_id, start=None):
    key = os.environ.get("FRED_API_KEY")
    if key:
        params = {"series_id": fred_id, "api_key": key, "file_type": "json"}
        if start:
            params["observation_start"] = start
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations", params=params, timeout=30
        )
        r.raise_for_status()
        obs = [(o["date"], o["value"]) for o in r.json()["observations"]]
    else:
        # Keyless fallback: FRED's public CSV download for the same series.
        r = requests.get(
            "https://fred.stlouisfed.org/graph/fredgraph.csv",
            params={"id": fred_id},
            # FRED drops connections with browser or custom UAs; requests' default is accepted.
            timeout=30,
        )
        r.raise_for_status()
        reader = csv.reader(io.StringIO(r.text))
        next(reader)
        obs = [(d, v) for d, v in reader if not start or d >= start]
    rows = [
        {"date": d, "value": v, "source_timestamp": d}
        for d, v in obs
        if v not in (".", "")
    ]
    if not rows:
        raise RuntimeError(f"FRED returned no observations for {fred_id}")
    return rows


def collect_fred(series):
    sid = series["id"]
    before = len(read_rows(sid))
    if before == 0:
        write_rows(sid, with_retries(lambda: fetch_fred(series["fred_id"])))
    else:
        since = (date.today() - timedelta(days=FRED_REVISION_DAYS)).isoformat()
        replace_since(sid, with_retries(lambda: fetch_fred(series["fred_id"], since)), since)
    return len(read_rows(sid)) - before


# --- BLS -----------------------------------------------------------------

BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_BACKFILL_YEARS = 20
BLS_REVISION_YEARS = 2
_bls_cache = {}


def bls_request(ids, start, end):
    payload = {"seriesid": ids, "startyear": str(start), "endyear": str(end)}
    if os.environ.get("BLS_API_KEY"):
        payload["registrationkey"] = os.environ["BLS_API_KEY"]
    r = requests.post(BLS_URL, json=payload, timeout=60)
    r.raise_for_status()
    body = r.json()
    if body.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS: {body.get('status')} {body.get('message')}")
    out = {}
    for s in body["Results"]["series"]:
        out[s["seriesID"]] = [
            (f"{d['year']}-{d['period'][1:]}-01", d["value"])
            for d in s["data"]
            if d["period"].startswith("M") and d["period"] != "M13" and d["value"] not in ("-", "")
        ]
    return out


def bls_all(series_list):
    """All BLS series in as few requests as possible; keyless requests cover 10 years each."""
    if "data" in _bls_cache:
        return _bls_cache["data"]
    ids = [s["bls_id"] for s in series_list]
    this_year = date.today().year
    backfill = any(not read_rows(s["id"]) for s in series_list)
    start = this_year - (BLS_BACKFILL_YEARS if backfill else BLS_REVISION_YEARS) + 1
    data = {i: [] for i in ids}
    for chunk_start in range(start, this_year + 1, 10):
        chunk = with_retries(lambda: bls_request(ids, chunk_start, min(chunk_start + 9, this_year)))
        for i, obs in chunk.items():
            data[i] += obs
    _bls_cache["data"] = data
    return data


def collect_bls(series, all_series):
    obs = bls_all([s for s in all_series if s["source"] == "bls"]).get(series["bls_id"])
    if not obs:
        raise RuntimeError(f"BLS returned no observations for {series['bls_id']}")
    rows = [{"date": d, "value": v, "source_timestamp": d} for d, v in obs]
    sid = series["id"]
    before = len(read_rows(sid))
    since = min(r["date"] for r in rows)
    replace_since(sid, rows, since)
    return len(read_rows(sid)) - before


# --- DRAMeXchange ---------------------------------------------------------

_dramx_cache = {}


def dramx_tables():
    """One GET of the homepage per run; returns {table title: (timestamp, header, rows)}."""
    if "tables" in _dramx_cache:
        return _dramx_cache["tables"]
    r = requests.get(DRAMX_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")
    tables = {}
    for stamp in soup.select("span.tab_time"):
        title_el = stamp.find_previous("font")
        m = re.search(r"([A-Z][a-z]{2})\.?\s*(\d{1,2})\s+(\d{4})\s+(\d{1,2}):(\d{2})", stamp.get_text(" "))
        if not title_el or not m:
            continue
        mon, day, year, hh, mm = m.groups()
        when = datetime.strptime(f"{mon} {day} {year} {hh}:{mm}", "%b %d %Y %H:%M")
        when = when.replace(tzinfo=timezone(timedelta(hours=8)))
        first_header = stamp.find_next("td", class_="tab_title")
        if first_header is None:
            continue
        data_table = first_header.find_parent("table")
        header = [td.get_text(" ", strip=True) for td in data_table.select("td.tab_title")]
        body = []
        for tr in data_table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td", recursive=False)]
            if cells and "tab_title" not in (tr.find("td").get("class") or []):
                body.append(cells)
        tables.setdefault(title_el.get_text(strip=True), (when, header, body))
    if not tables:
        raise RuntimeError("no price tables found on DRAMeXchange homepage (layout changed or blocked?)")
    _dramx_cache["tables"] = tables
    return tables


def collect_dramx(series):
    tables = dramx_tables()
    if series["table"] not in tables:
        raise RuntimeError(f"table '{series['table']}' not found; saw {sorted(tables)}")
    when, header, body = tables[series["table"]]
    if series["column"] not in header:
        raise RuntimeError(f"column '{series['column']}' not in {header}")
    col = header.index(series["column"])
    norm = lambda s: re.sub(r"\s+", " ", s).strip()
    row = next((r for r in body if norm(r[0]) == norm(series["item"])), None)
    if row is None:
        raise RuntimeError(f"item '{series['item']}' not in table '{series['table']}'")
    value = float(row[col].replace(",", ""))
    return append_rows(
        series["id"],
        [{"date": when.date().isoformat(), "value": f"{value}", "source_timestamp": when.isoformat()}],
    )


COLLECTORS = {"yfinance": collect_yfinance, "fred": collect_fred, "dramx": collect_dramx, "bls": collect_bls}


def main():
    DATA.mkdir(exist_ok=True)
    config = json.loads((ROOT / "config.json").read_text())
    status = json.loads(STATUS_PATH.read_text()) if STATUS_PATH.exists() else {}
    failures = 0
    for series in config["series"]:
        sid = series["id"]
        entry = status.setdefault(sid, {})
        entry["source"] = series["source"]
        entry["last_attempt"] = now_iso()
        try:
            if series["source"] == "bls":
                added = collect_bls(series, config["series"])
            else:
                added = COLLECTORS[series["source"]](series)
            entry["last_success"] = entry["last_attempt"]
            entry["last_error"] = None
            print(f"ok    {sid}: +{added} rows", flush=True)
        except Exception as e:
            failures += 1
            entry["last_error"] = f"{type(e).__name__}: {e}"[:500]
            entry["last_error_at"] = entry["last_attempt"]
            print(f"FAIL  {sid}: {entry['last_error']}", file=sys.stderr, flush=True)
    STATUS_PATH.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    print(f"done: {failures} failure(s)")


if __name__ == "__main__":
    main()
