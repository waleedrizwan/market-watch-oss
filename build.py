"""Turn data/*.csv into site/data.json: per-chain forecasts, chart points, % changes, stale flags.

The forecast is a distributed-lag model on monthly log changes:
    retail change(t) = seasonal baseline + sum_j b_j * upstream change(t - j),  j = 0..max_lag
Upstream moves that have already happened but haven't fully reached the store yet give the
"pending" change: how much the store price should still move in the next few months if the
upstream price stayed where it is now.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = ROOT / "site" / "data.json"
CHART_YEARS = 20

# (key, label, offset) per frequency. Monthly series use calendar months.
WINDOWS = {
    "daily": [("30d", "30d", pd.DateOffset(days=30)), ("90d", "90d", pd.DateOffset(days=90)), ("1y", "1y", pd.DateOffset(days=365))],
    "monthly": [("30d", "1m", pd.DateOffset(months=1)), ("90d", "3m", pd.DateOffset(months=3)), ("1y", "12m", pd.DateOffset(months=12))],
}
WINDOWS["weekly"] = WINDOWS["daily"]


def load(series):
    path = DATA / f"{series['id']}.csv"
    if not path.exists():
        return pd.Series(dtype=float)
    df = pd.read_csv(path, parse_dates=["date"])
    # Several source timestamps can share a date (e.g. two DRAMeXchange updates); keep the last.
    return df.groupby("date")["value"].last().astype(float).sort_index()


def weekly(s):
    """Weekly mean, each week dated by its last real observation (never ahead of the data)."""
    weeks = s.resample("W-FRI")
    return pd.Series(weeks.mean().values, index=weeks.apply(lambda w: w.index.max()).values).dropna()


def for_display(series, s):
    if series.get("weekly_avg"):
        # Futures roll days create fake jumps; a weekly mean keeps one day from dominating.
        return weekly(s)
    return s


def monthly(s):
    return s.resample("MS").mean().dropna()


def pct_change(s, offset):
    """% change from the last value on/before (latest - offset) to the latest value."""
    if s.empty:
        return None
    target = s.index[-1] - offset
    if s.index[0] > target:
        return None
    base = s[:target].iloc[-1]
    return round(float(s.iloc[-1] / base - 1) * 100, 1) if base else None


def staleness(series, s, status, today):
    st = status.get(series["id"], {})
    if s.empty:
        return "no data yet" + (f" ({st['last_error']})" if st.get("last_error") else "")
    if st.get("last_error"):
        return f"last fetch failed: {st['last_error']}"
    age = (today - s.index[-1]).days
    if age > series["stale_after_days"]:
        return f"latest value is {age} days old (expected within {series['stale_after_days']})"
    return None


# --- forecast model -------------------------------------------------------

def design(du, months, max_lag):
    """Rows: [1, 11 month dummies, du(t), du(t-1), ..., du(t-max_lag)] for each month t."""
    lags = np.column_stack([du.shift(j).reindex(months).values for j in range(max_lag + 1)])
    dummies = np.column_stack([(months.month == m).astype(float) for m in range(2, 13)])
    return np.column_stack([np.ones(len(months)), dummies, lags])


def fit(du, dr, max_lag):
    """OLS of retail log-change on lagged upstream log-changes. Returns lag weights and fit stats."""
    months = dr.index
    X, y = design(du, months, max_lag), dr.values
    ok = ~np.isnan(X).any(axis=1) & ~np.isnan(y)
    X, y = X[ok], y[ok]
    if len(y) < X.shape[1] * 3:
        return None
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    base = X[:, :12]
    base_coef, *_ = np.linalg.lstsq(base, y, rcond=None)
    sst = ((y - y.mean()) ** 2).sum()
    r2 = 1 - ((y - X @ coef) ** 2).sum() / sst if sst else 0.0
    r2_base = 1 - ((y - base @ base_coef) ** 2).sum() / sst if sst else 0.0
    return {"b": coef[12:], "n": int(len(y)), "r2_gain": float(r2 - r2_base)}


def pending(du, b, last_retail_month, horizon):
    """Store-price log change still expected over the next `horizon` months from upstream moves
    already observed. Upstream months after the last known one are assumed flat (change 0)."""
    total = 0.0
    for h in range(1, horizon + 1):
        t = last_retail_month + pd.DateOffset(months=h)
        for j, bj in enumerate(b):
            v = du.get(t - pd.DateOffset(months=j), 0.0)
            total += bj * (0.0 if pd.isna(v) else v)
    return total


def backtest(du, dr, max_lag, horizon, threshold, years=6):
    """Out-of-sample check: each month in the last `years`, fit on data before it only, predict
    the pending move, compare with what the store price actually did (beyond its seasonal norm)."""
    preds, actuals = [], []
    end = dr.index[-1] - pd.DateOffset(months=horizon)
    start = end - pd.DateOffset(years=years)
    for t in dr.index[(dr.index >= start) & (dr.index <= end)]:
        if t.month not in (1, 4, 7, 10):  # quarterly refits keep this fast
            continue
        model = fit(du[:t], dr[:t], max_lag)
        if model is None:
            continue
        du_known = du[:t]
        preds.append(pending(du_known, model["b"], t, horizon))
        future = dr[(dr.index > t) & (dr.index <= t + pd.DateOffset(months=horizon))]
        hist = dr[:t]
        seasonal = sum(hist[hist.index.month == m.month].mean() for m in future.index)
        actuals.append(future.sum() - seasonal)
    if len(preds) < 8:
        return None
    preds, actuals = np.array(preds), np.array(actuals)
    flagged = np.abs(np.expm1(preds) * 100) >= threshold
    hits = int((np.sign(preds[flagged]) == np.sign(actuals[flagged])).sum())
    corr = float(np.corrcoef(preds, actuals)[0, 1]) if preds.std() > 0 and actuals.std() > 0 else 0.0
    return {"corr": round(corr, 2), "flags": int(flagged.sum()), "hits": hits, "checks": int(len(preds))}


def forecast(driver_s, retail_s, cfg):
    up, rt = monthly(driver_s), monthly(retail_s)
    start = rt.index[-1] - pd.DateOffset(years=cfg["fit_years"]) if len(rt) else None
    du = np.log(up).diff().dropna()
    dr = np.log(rt).diff().dropna()
    if start is not None:
        du, dr = du[du.index >= start], dr[dr.index >= start]
    overlap = dr.index.intersection(du.index)
    if len(overlap) < cfg["min_months"]:
        return {"ok": False, "why": f"only {len(overlap)} months of overlapping history"}
    dr = dr[dr.index >= overlap[0]]
    model = fit(du, dr, cfg["max_lag_months"])
    if model is None:
        return {"ok": False, "why": "not enough history to fit"}
    b = model["b"]
    total = float(b.sum())
    cum = np.cumsum(b)
    lag = int(np.argmax(cum >= 0.5 * total)) if total > 0 else None
    pend = pending(du, b, dr.index[-1], cfg["horizon_months"])
    track = backtest(du, dr, cfg["max_lag_months"], cfg["horizon_months"], cfg["rise_pct"])
    return {
        "ok": True,
        "pending_pct": round(float(np.expm1(pend)) * 100, 1),
        "passthrough_pct": round(total * 100),
        "half_lag_months": lag,
        "r2_gain": round(model["r2_gain"], 3),
        "n_months": model["n"],
        "track": track,
        "as_of_retail": dr.index[-1].date().isoformat(),
        "as_of_upstream": du.index[-1].date().isoformat(),
    }


def verdict(fc, cfg):
    if not fc["ok"]:
        return "weak", f"Can't forecast: {fc['why']}."
    track = fc["track"]
    reliable = (
        fc["passthrough_pct"] > 0
        and fc["r2_gain"] >= cfg["min_r2"]
        and track is not None
        and track["corr"] > 0.2
    )
    if not reliable:
        if fc["passthrough_pct"] > 0 and fc["r2_gain"] >= 0.2 and fc["half_lag_months"] in (0, 1):
            return "fast", "Store price follows the upstream price within weeks, so there's no early warning: watch the upstream price itself."
        return "weak", "The upstream price hasn't reliably predicted this store price in the past, so no forecast."
    p = fc["pending_pct"]
    if p >= cfg["rise_pct"]:
        return "rise", f"Likely to rise about {p:.0f}% over the next {cfg['horizon_months']} months."
    if p <= cfg["fall_pct"]:
        return "fall", f"Likely to fall about {abs(p):.0f}% over the next {cfg['horizon_months']} months."
    return "steady", f"No big move expected over the next {cfg['horizon_months']} months ({p:+.1f}%)."


def describe_move(meta):
    c = meta["changes"]
    parts = []
    if c["1y"] is not None:
        parts.append(f"{'up' if c['1y'] >= 0 else 'down'} {abs(c['1y']):.0f}% over 12 months")
    if c["90d"] is not None:
        parts.append("flat over 3 months" if f"{abs(c['90d']):.0f}" == "0" else f"{c['90d']:+.0f}% over 3 months")
    return ", ".join(parts) if parts else "too little history for a trend"


def reason(fc, kind, driver, retail):
    text = f"{driver['label']}: {describe_move(driver)}. {retail['label']}: {describe_move(retail)}."
    if kind != "weak" and fc["passthrough_pct"] > 0 and fc["half_lag_months"] is not None:
        lag = fc["half_lag_months"]
        when = "within the same month" if lag == 0 else f"about {lag} month{'s' if lag != 1 else ''} later"
        text += (
            f" Historically, about {fc['passthrough_pct']}% of an upstream move shows up in the store price,"
            f" half of it {when}."
        )
    return text


def live_gap(gap, by_id, thresholds):
    up_meta, rt_meta = by_id[gap["upstream"]], by_id[gap["retail"]]
    need = thresholds["min_history_days"]
    short = [m for m in (up_meta, rt_meta) if m["changes"]["90d"] is None]
    if short:
        parts = [f"{m['label']} has {m['history_days']} of {need} days" for m in short]
        return "Live chip prices: not enough history yet (" + "; ".join(parts) + ")."
    up, rt = up_meta["changes"]["90d"], rt_meta["changes"]["90d"]
    flat = thresholds["retail_flat_pct"]
    if up >= thresholds["upstream_up_pct"] and rt < flat:
        v = f"chips up {up:.0f}% in 90 days, modules haven't caught up yet."
    elif up >= flat and rt >= flat:
        v = "rising at both ends."
    elif up <= thresholds["upstream_down_pct"] and abs(rt) < flat:
        v = "chips falling; modules may follow down."
    else:
        v = "no big divergence."
    return f"Live chip prices: {v}"


def series_meta(series, status, today):
    raw = load(series)
    s = for_display(series, raw)
    windows = WINDOWS[series["frequency"]]
    chart = s
    if series["frequency"] == "daily" and series["source"] != "dramx" and not series.get("weekly_avg"):
        chart = weekly(s)
    if not chart.empty:
        chart = chart[chart.index >= chart.index[-1] - pd.DateOffset(years=CHART_YEARS)]
    return raw, {
        "id": series["id"],
        "label": series["label"],
        "role": series["role"],
        "unit": series["unit"],
        "frequency": series["frequency"],
        "latest": None if s.empty else {"date": s.index[-1].date().isoformat(), "value": round(float(s.iloc[-1]), 4)},
        "changes": {k: pct_change(s, off) for k, _, off in windows},
        "change_labels": {k: label for k, label, _ in windows},
        "history_days": 0 if s.empty else (s.index[-1] - s.index[0]).days,
        "stale": staleness(series, s, status, today),
        "points": [[d.date().isoformat(), round(float(v), 4)] for d, v in chart.items()],
    }


def main():
    config = json.loads((ROOT / "config.json").read_text())
    status_path = DATA / "_status.json"
    status = json.loads(status_path.read_text()) if status_path.exists() else {}
    today = pd.Timestamp(datetime.now(timezone.utc).date())
    cfg = config["forecast"]

    raw, metas = {}, {}
    for series in config["series"]:
        raw[series["id"]], metas[series["id"]] = series_meta(series, status, today)

    chains = []
    for chain in config["chains"]:
        ids = [chain["driver"], chain["retail"]] + chain.get("extras", [])
        driver, retail = metas[chain["driver"]], metas[chain["retail"]]
        fc = forecast(raw[chain["driver"]], raw[chain["retail"]], cfg)
        kind, headline = verdict(fc, cfg)
        stale = [f"{metas[i]['label']}: {metas[i]['stale']}" for i in ids if metas[i]["stale"]]
        chains.append({
            "id": chain["id"],
            "title": chain["title"],
            "group": chain["group"],
            "kind": kind,
            "headline": headline,
            "reason": reason(fc, kind, driver, retail),
            "forecast": fc,
            "live_gap": live_gap(chain["live_gap"], metas, config["gap_thresholds"]) if chain.get("live_gap") else None,
            "stale": stale,
            "series": ids,
            "links": chain.get("links", []),
        })

    used = {i for c in chains for i in c["series"]}
    out = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "horizon_months": cfg["horizon_months"],
        "groups": config["groups"],
        "chains": chains,
        "series": {i: m for i, m in metas.items() if i in used},
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")) + "\n")

    for c in sorted(chains, key=lambda c: -(c["forecast"].get("pending_pct") or 0)):
        fc = c["forecast"]
        extra = ""
        if fc["ok"]:
            t = fc["track"] or {}
            extra = (f"pend={fc['pending_pct']:+.1f}% pass={fc['passthrough_pct']}% lag={fc['half_lag_months']} "
                     f"r2+={fc['r2_gain']} track={t}")
        print(f"{c['kind']:<6} {c['title']:<32} {extra}{'  STALE' if c['stale'] else ''}")


if __name__ == "__main__":
    main()
