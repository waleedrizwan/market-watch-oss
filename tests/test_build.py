import json

import numpy as np
import pandas as pd
import pytest

import build

CFG = {"horizon_months": 6, "max_lag_months": 12, "fit_years": 20, "min_months": 60, "min_r2": 0.1, "rise_pct": 4, "fall_pct": -4}
GAP = {"upstream_up_pct": 15, "retail_flat_pct": 5, "upstream_down_pct": -15, "min_history_days": 90}


def daily(start, values):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"), dtype=float)


def synthetic_pair(months=240, lag=2, share=0.5, seed=1, shock=0.0):
    """Upstream random walk; retail follows `share` of each upstream move `lag` months later."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2006-01-01", periods=months, freq="MS")
    du = rng.normal(0, 0.05, months)
    du[-1] += shock
    up = 100 * np.exp(np.cumsum(du))
    dr = share * np.concatenate([np.zeros(lag), du[:-lag]]) + rng.normal(0, 0.002, months)
    rt = 50 * np.exp(np.cumsum(dr))
    # Retail is published a month after upstream.
    return pd.Series(up, idx), pd.Series(rt[:-1], idx[:-1])


# --- series helpers --------------------------------------------------------------

def test_pct_change_uses_value_on_or_before_target():
    s = daily("2026-01-01", range(100, 300))
    assert build.pct_change(s, pd.DateOffset(days=30)) == round((299 / 269 - 1) * 100, 1)
    assert build.pct_change(s, pd.DateOffset(days=365)) is None
    assert build.pct_change(pd.Series(dtype=float), pd.DateOffset(days=30)) is None


def test_pct_change_monthly_offsets():
    s = pd.Series([100.0, 110.0, 120.0, 132.0], index=pd.date_range("2026-01-01", periods=4, freq="MS"))
    assert build.pct_change(s, pd.DateOffset(months=1)) == 10.0
    assert build.pct_change(s, pd.DateOffset(months=3)) == 32.0


def test_weekly_dates_each_week_by_its_last_real_observation():
    # Mon 2026-11-02 .. Wed 2026-11-11, with a gap on Fri 11-06.
    s = pd.Series([10, 20, 30, 40, 100, 200, 300],
                  index=pd.to_datetime(["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-09", "2026-11-10", "2026-11-11"]))
    w = build.weekly(s)
    assert list(w.index.strftime("%Y-%m-%d")) == ["2026-11-05", "2026-11-11"]
    assert list(w.values) == [25.0, 200.0]
    assert w.index[-1] <= s.index[-1]


def test_monthly_averages_by_calendar_month():
    s = daily("2026-01-30", [1, 3, 5, 7])  # Jan 30, Jan 31, Feb 1, Feb 2
    m = build.monthly(s)
    assert list(m.values) == [2.0, 6.0]


def test_for_display_only_averages_flagged_series():
    s = daily("2026-11-02", [1, 2, 3, 4, 5])
    assert build.for_display({"weekly_avg": True}, s).iloc[-1] == 3.0
    assert build.for_display({}, s) is s


@pytest.mark.parametrize("values, status, expected", [
    ([], {}, "no data yet"),
    ([], {"x": {"last_error": "HTTP 429"}}, "no data yet (HTTP 429)"),
    ([1, 2], {"x": {"last_error": "blocked"}}, "last fetch failed: blocked"),
    ([1, 2], {}, None),
])
def test_staleness_basic_cases(values, status, expected):
    s = daily("2026-11-10", values) if values else pd.Series(dtype=float)
    assert build.staleness({"id": "x", "stale_after_days": 5}, s, status, pd.Timestamp("2026-11-12")) == expected


def test_staleness_flags_old_data_even_without_errors():
    s = daily("2026-10-01", [1, 2])
    msg = build.staleness({"id": "x", "stale_after_days": 5}, s, {}, pd.Timestamp("2026-11-12"))
    assert msg == "latest value is 41 days old (expected within 5)"


# --- forecast model ---------------------------------------------------------------

def test_fit_recovers_known_lag_weights():
    up, rt = synthetic_pair(lag=2, share=0.5)
    du = np.log(build.monthly(up)).diff().dropna()
    dr = np.log(build.monthly(rt)).diff().dropna()
    model = build.fit(du, dr, 12)
    assert model["b"][2] == pytest.approx(0.5, abs=0.03)
    assert abs(model["b"][0]) < 0.03 and abs(model["b"][5]) < 0.03
    assert model["r2_gain"] > 0.8


def test_fit_refuses_too_little_data():
    idx = pd.date_range("2020-01-01", periods=20, freq="MS")
    s = pd.Series(np.linspace(0, 0.1, 20), idx)
    assert build.fit(s, s, 12) is None


def test_pending_counts_only_moves_not_yet_passed_through():
    idx = pd.date_range("2026-01-01", periods=6, freq="MS")
    du = pd.Series([0, 0, 0, 0, 0, 0.1], idx)  # upstream jumped 10% (log) in June
    b = np.array([0.0, 0.0, 0.5])  # half of it shows up two months later
    # Retail known through June: the whole effect is still ahead (in August).
    assert build.pending(du, b, pd.Timestamp("2026-06-01"), 6) == pytest.approx(0.05)
    # Retail already known through August: nothing left.
    assert build.pending(du, b, pd.Timestamp("2026-08-01"), 6) == pytest.approx(0.0)


def test_forecast_flags_a_pending_rise_and_backtests_well():
    up, rt = synthetic_pair(lag=2, share=0.5, shock=0.3)
    fc = build.forecast(up, rt, CFG)
    assert fc["ok"] is True
    assert fc["passthrough_pct"] == pytest.approx(50, abs=4)
    assert fc["half_lag_months"] == 2
    assert fc["pending_pct"] > 10
    assert fc["track"]["corr"] > 0.3 and fc["track"]["checks"] >= 8
    kind, headline = build.verdict(fc, CFG)
    assert kind == "rise" and headline.startswith("Likely to rise about")


def test_forecast_with_unrelated_series_is_not_trusted():
    up, _ = synthetic_pair(seed=1)
    _, rt = synthetic_pair(seed=2)
    kind, _ = build.verdict(build.forecast(up, rt, CFG), CFG)
    assert kind == "weak"


def test_forecast_needs_enough_overlap():
    up, rt = synthetic_pair(months=40)
    fc = build.forecast(up, rt, CFG)
    assert fc == {"ok": False, "why": "only 38 months of overlapping history"}
    assert build.verdict(fc, CFG) == ("weak", "Can't forecast: only 38 months of overlapping history.")


def fc(**over):
    base = {"ok": True, "pending_pct": 0.0, "passthrough_pct": 50, "r2_gain": 0.3, "half_lag_months": 3,
            "track": {"corr": 0.5, "flags": 3, "hits": 3, "checks": 24}}
    base.update(over)
    return base


@pytest.mark.parametrize("over, kind", [
    ({"pending_pct": 6.2}, "rise"),
    ({"pending_pct": 4.0}, "rise"),
    ({"pending_pct": -5.0}, "fall"),
    ({"pending_pct": 3.9}, "steady"),
    ({"track": {"corr": 0.1, "flags": 0, "hits": 0, "checks": 24}}, "weak"),
    ({"track": None}, "weak"),
    ({"passthrough_pct": -10}, "weak"),
    ({"r2_gain": 0.05}, "weak"),
    ({"track": None, "half_lag_months": 0, "r2_gain": 0.4}, "fast"),
    ({"track": None, "half_lag_months": 1, "r2_gain": 0.25}, "fast"),
    ({"track": None, "half_lag_months": 2, "r2_gain": 0.4}, "weak"),
])
def test_verdict_thresholds(over, kind):
    assert build.verdict(fc(**over), CFG)[0] == kind


def test_verdict_headlines_are_plain_english():
    assert build.verdict(fc(pending_pct=-7.6), CFG)[1] == "Likely to fall about 8% over the next 6 months."
    assert build.verdict(fc(pending_pct=1.24), CFG)[1] == "No big move expected over the next 6 months (+1.2%)."


# --- copy -----------------------------------------------------------------------

def meta(label, m3=None, y1=None, days=400):
    return {"label": label, "changes": {"30d": None, "90d": m3, "1y": y1}, "history_days": days}


def test_describe_move():
    assert build.describe_move(meta("x", m3=-4.4, y1=12.6)) == "up 13% over 12 months, -4% over 3 months"
    assert build.describe_move(meta("x", m3=0.2)) == "flat over 3 months"
    assert build.describe_move(meta("x")) == "too little history for a trend"


def test_reason_mentions_pass_through_and_lag():
    d, r = meta("Crude", 30, 61), meta("Diesel", 16, 63)
    text = build.reason(fc(passthrough_pct=68, half_lag_months=1), "steady", d, r)
    assert text.startswith("Crude: up 61% over 12 months, +30% over 3 months. Diesel:")
    assert text.endswith("about 68% of an upstream move shows up in the store price, half of it about 1 month later.")
    assert "within the same month" in build.reason(fc(half_lag_months=0), "fast", d, r)
    assert "Historically" not in build.reason(fc(), "weak", d, r)


@pytest.mark.parametrize("up, rt, expected", [
    (41, 3, "chips up 41% in 90 days, modules haven't caught up yet."),
    (20, 8, "rising at both ends."),
    (-20, 1, "chips falling; modules may follow down."),
    (4, 1, "no big divergence."),
])
def test_live_gap(up, rt, expected):
    by_id = {"u": meta("DDR5 chip", m3=up), "r": meta("DDR5 module", m3=rt)}
    assert build.live_gap({"upstream": "u", "retail": "r"}, by_id, GAP) == f"Live chip prices: {expected}"


def test_live_gap_says_when_history_is_short():
    by_id = {"u": meta("DDR5 chip", days=16), "r": meta("DDR5 module", m3=1, days=200)}
    assert build.live_gap({"upstream": "u", "retail": "r"}, by_id, GAP) == (
        "Live chip prices: not enough history yet (DDR5 chip has 16 of 90 days)."
    )


# --- end to end -------------------------------------------------------------------

def write_csv(data_dir, sid, series):
    pd.DataFrame({"date": series.index.strftime("%Y-%m-%d"), "value": series.values,
                  "source_timestamp": series.index.strftime("%Y-%m-%d")}).to_csv(data_dir / f"{sid}.csv", index=False)


def test_main_writes_the_contract_the_dashboard_reads(tmp_data):
    up, rt = synthetic_pair(lag=2, share=0.5, shock=0.3)
    write_csv(tmp_data, "up", up)
    write_csv(tmp_data, "rt", rt)
    (tmp_data / "_status.json").write_text(json.dumps({"rt": {"last_error": None}}))
    config = {
        "forecast": CFG, "gap_thresholds": GAP, "groups": ["Food"],
        "series": [
            {"id": "up", "label": "Up", "role": "upstream", "source": "fred", "unit": "index", "frequency": "monthly", "stale_after_days": 100000},
            {"id": "rt", "label": "Rt", "role": "retail", "source": "fred", "unit": "USD", "frequency": "monthly", "stale_after_days": 100000},
            {"id": "unused", "label": "Unused", "role": "upstream", "source": "fred", "unit": "x", "frequency": "monthly", "stale_after_days": 1},
        ],
        "chains": [{"id": "c", "title": "Chain", "group": "Food", "driver": "up", "retail": "rt",
                    "links": [{"label": "L", "url": "https://example.com"}]}],
    }
    (tmp_data.parent / "config.json").write_text(json.dumps(config))
    build.main()
    out = json.loads(build.OUT.read_text())

    assert set(out) == {"generated_at", "horizon_months", "groups", "chains", "series"}
    (chain,) = out["chains"]
    assert set(chain) >= {"id", "title", "group", "kind", "headline", "reason", "forecast", "live_gap", "stale", "series", "links"}
    assert chain["kind"] == "rise" and chain["series"] == ["up", "rt"] and chain["stale"] == []
    assert set(out["series"]) == {"up", "rt"}  # unused series are left out
    s = out["series"]["rt"]
    assert set(s) >= {"label", "role", "unit", "latest", "changes", "change_labels", "stale", "points"}
    assert s["change_labels"] == {"30d": "1m", "90d": "3m", "1y": "12m"}
    assert s["points"][-1][0] == s["latest"]["date"]


# --- the real config ------------------------------------------------------------------

REQUIRED = {"fred": {"fred_id"}, "bls": {"bls_id"}, "yfinance": {"ticker"}, "dramx": {"table", "item", "column"}}


def test_config_is_consistent(real_config):
    ids = [s["id"] for s in real_config["series"]]
    assert len(ids) == len(set(ids)), "duplicate series ids"
    by_id = {s["id"]: s for s in real_config["series"]}
    for s in real_config["series"]:
        assert s["source"] in REQUIRED, s["id"]
        assert REQUIRED[s["source"]] <= set(s), f"{s['id']} is missing {REQUIRED[s['source']] - set(s)}"
        assert s["frequency"] in build.WINDOWS, s["id"]
        assert s["stale_after_days"] > 0
    chain_ids = [c["id"] for c in real_config["chains"]]
    assert len(chain_ids) == len(set(chain_ids)), "duplicate chain ids"
    for c in real_config["chains"]:
        assert c["group"] in real_config["groups"], c["id"]
        for sid in [c["driver"], c["retail"], *c.get("extras", [])]:
            assert sid in by_id, f"chain {c['id']} uses unknown series {sid}"
        if c.get("live_gap"):
            assert {c["live_gap"]["upstream"], c["live_gap"]["retail"]} <= set(by_id)
        for link in c.get("links", []):
            assert link["url"].startswith("https://")
    assert real_config["forecast"]["rise_pct"] > 0 > real_config["forecast"]["fall_pct"]
