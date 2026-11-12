import json
import sys
import types
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

import collect
from fixtures import DRAMX_HTML, FRED_CSV, FakeResponse


def row(d, v, ts=None):
    return {"date": d, "value": str(v), "source_timestamp": ts or d}


# --- CSV storage -------------------------------------------------------------

def test_append_rows_skips_known_timestamps_and_sorts(tmp_data):
    assert collect.append_rows("s", [row("2026-01-02", 2), row("2026-01-01", 1)]) == 2
    assert collect.append_rows("s", [row("2026-01-02", 99), row("2026-01-03", 3)]) == 1
    rows = collect.read_rows("s")
    assert [(r["date"], r["value"]) for r in rows] == [("2026-01-01", "1"), ("2026-01-02", "2"), ("2026-01-03", "3")]


def test_append_rows_keeps_two_updates_on_the_same_day(tmp_data):
    collect.append_rows("s", [row("2026-11-12", 1, "2026-11-12T14:40:00+08:00")])
    collect.append_rows("s", [row("2026-11-12", 2, "2026-11-12T18:10:00+08:00")])
    assert len(collect.read_rows("s")) == 2


def test_append_nothing_does_not_create_a_file(tmp_data):
    assert collect.append_rows("s", []) == 0
    assert not (tmp_data / "s.csv").exists()


def test_replace_since_overwrites_the_revision_window(tmp_data):
    collect.write_rows("s", [row("2026-01-01", 1), row("2026-02-01", 2), row("2026-03-01", 3)])
    collect.replace_since("s", [row("2026-02-01", 20), row("2026-04-01", 4)], "2026-02-01")
    assert [(r["date"], r["value"]) for r in collect.read_rows("s")] == [
        ("2026-01-01", "1"), ("2026-02-01", "20"), ("2026-04-01", "4"),
    ]


def test_with_retries_retries_then_raises(tmp_data):
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("reset")
        return "ok"

    assert collect.with_retries(flaky) == "ok"
    with pytest.raises(ValueError):
        collect.with_retries(lambda: (_ for _ in ()).throw(ValueError("nope")))


# --- FRED --------------------------------------------------------------------

def test_fetch_fred_keyless_csv(tmp_data, monkeypatch):
    seen = {}

    def get(url, params=None, timeout=None, **kw):
        seen.update(url=url, params=params, headers=kw.get("headers"))
        return FakeResponse(FRED_CSV)

    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr(collect.requests, "get", get)
    rows = collect.fetch_fred("X")
    assert seen["url"].endswith("fredgraph.csv") and seen["params"] == {"id": "X"}
    assert seen["headers"] is None  # FRED rejects browser-like UAs on this endpoint
    assert [(r["date"], r["value"]) for r in rows] == [("2026-06-01", "1.0"), ("2026-08-01", "2.5"), ("2026-09-01", "3.0")]
    assert [r["date"] for r in collect.fetch_fred("X", start="2026-08-01")] == ["2026-08-01", "2026-09-01"]


def test_fetch_fred_with_api_key(tmp_data, monkeypatch):
    seen = {}

    def get(url, params=None, timeout=None):
        seen.update(url=url, params=params)
        return FakeResponse(json_data={"observations": [{"date": "2026-09-01", "value": "3.0"}, {"date": "2026-10-01", "value": "."}]})

    monkeypatch.setenv("FRED_API_KEY", "k")
    monkeypatch.setattr(collect.requests, "get", get)
    rows = collect.fetch_fred("X", start="2026-01-01")
    assert "api.stlouisfed.org" in seen["url"]
    assert seen["params"]["observation_start"] == "2026-01-01"
    assert rows == [row("2026-09-01", "3.0")]


def test_fetch_fred_empty_raises(tmp_data, monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr(collect.requests, "get", lambda *a, **k: FakeResponse("observation_date,X\n2026-01-01,.\n"))
    with pytest.raises(RuntimeError, match="no observations"):
        collect.fetch_fred("X")


def test_collect_fred_backfills_then_only_refreshes_recent_months(tmp_data, monkeypatch):
    starts = []

    def fake(fred_id, start=None):
        starts.append(start)
        return [row("2020-01-01", 1), row(date.today().replace(day=1).isoformat(), 5)]

    monkeypatch.setattr(collect, "fetch_fred", fake)
    s = {"id": "s", "fred_id": "X"}
    assert collect.collect_fred(s) == 2
    assert starts == [None]
    collect.collect_fred(s)
    assert starts[1] == (date.today() - timedelta(days=collect.FRED_REVISION_DAYS)).isoformat()
    assert len(collect.read_rows("s")) == 2  # old row kept, recent one replaced, no duplicates


# --- BLS ---------------------------------------------------------------------

def test_bls_request_parses_monthly_values(tmp_data, monkeypatch):
    body = {
        "status": "REQUEST_SUCCEEDED",
        "Results": {"series": [{"seriesID": "A", "data": [
            {"year": "2026", "period": "M09", "value": "1.5"},
            {"year": "2026", "period": "M13", "value": "9"},  # annual average: skipped
            {"year": "2026", "period": "M08", "value": "-"},  # missing: skipped
            {"year": "2026", "period": "S01", "value": "2"},  # semiannual: skipped
        ]}]},
    }
    monkeypatch.setattr(collect.requests, "post", lambda *a, **k: FakeResponse(json_data=body))
    assert collect.bls_request(["A"], 2026, 2026) == {"A": [("2026-09-01", "1.5")]}


def test_bls_request_surfaces_api_errors(tmp_data, monkeypatch):
    body = {"status": "REQUEST_NOT_PROCESSED", "message": ["daily threshold reached"]}
    monkeypatch.setattr(collect.requests, "post", lambda *a, **k: FakeResponse(json_data=body))
    with pytest.raises(RuntimeError, match="REQUEST_NOT_PROCESSED"):
        collect.bls_request(["A"], 2026, 2026)


def test_bls_all_batches_by_decade_and_caches(tmp_data, monkeypatch):
    calls = []

    def fake(ids, start, end):
        calls.append((start, end))
        return {i: [(f"{start}-01-01", "1")] for i in ids}

    monkeypatch.setattr(collect, "bls_request", fake)
    series = [{"id": "a", "bls_id": "A", "source": "bls"}, {"id": "b", "bls_id": "B", "source": "bls"}]
    data = collect.bls_all(series)
    assert len(calls) == 2  # 20-year backfill in 10-year chunks
    assert calls[0][1] - calls[0][0] == 9
    assert collect.bls_all(series) is data and len(calls) == 2


# --- DRAMeXchange --------------------------------------------------------------

def dramx_series(**over):
    s = {"id": "ddr5", "table": "DRAM Spot Price", "item": "DDR5 16Gb (2Gx8) 4800/5600", "column": "Session Average"}
    s.update(over)
    return s


@pytest.fixture
def dramx_page(monkeypatch):
    calls = []

    def get(url, headers=None, timeout=None):
        calls.append(headers)
        return FakeResponse(DRAMX_HTML)

    monkeypatch.setattr(collect.requests, "get", get)
    return calls


def test_dramx_reads_session_average_with_table_timestamp(tmp_data, dramx_page):
    assert collect.collect_dramx(dramx_series()) == 1
    (r,) = collect.read_rows("ddr5")
    assert r == {"date": "2026-11-12", "value": "10.123", "source_timestamp": "2026-11-12T14:40:00+08:00"}
    assert collect.collect_dramx(dramx_series()) == 0  # same update twice: no duplicate


def test_dramx_handles_thousands_separators_and_other_tables(tmp_data, dramx_page):
    collect.collect_dramx(dramx_series(id="ddr4", item="DDR4 16Gb (2Gx8) 3200"))
    collect.collect_dramx(dramx_series(id="nand", table="Wafer Spot Price", item="512Gb TLC"))
    assert collect.read_rows("ddr4")[0]["value"] == "1050.5"
    assert collect.read_rows("nand")[0]["date"] == "2026-11-02"


def test_dramx_fetches_the_homepage_once_per_run(tmp_data, dramx_page):
    collect.collect_dramx(dramx_series())
    collect.collect_dramx(dramx_series(id="ddr4", item="DDR4 16Gb (2Gx8) 3200"))
    assert len(dramx_page) == 1
    assert "Mozilla" in dramx_page[0]["User-Agent"]


@pytest.mark.parametrize("over, match", [
    ({"item": "DDR6 32Gb"}, "item 'DDR6 32Gb' not in table"),
    ({"column": "Weekly Average"}, "column 'Weekly Average' not in"),
    ({"table": "GDDR Spot Price"}, "table 'GDDR Spot Price' not found"),
])
def test_dramx_missing_pieces_raise_clear_errors(tmp_data, dramx_page, over, match):
    with pytest.raises(RuntimeError, match=match):
        collect.collect_dramx(dramx_series(**over))


def test_dramx_layout_change_raises(tmp_data, monkeypatch):
    monkeypatch.setattr(collect.requests, "get", lambda *a, **k: FakeResponse("<html>Maintenance</html>"))
    with pytest.raises(RuntimeError, match="no price tables"):
        collect.dramx_tables()


# --- yfinance ------------------------------------------------------------------

def test_yfinance_backfills_and_skips_todays_unfinished_bar(tmp_data, monkeypatch):
    today = datetime.now(timezone.utc).date()
    idx = pd.to_datetime([today - timedelta(days=2), today - timedelta(days=1), today])
    periods = []

    class Ticker:
        def __init__(self, sym):
            assert sym == "KC=F"

        def history(self, period, interval, auto_adjust):
            periods.append(period)
            return pd.DataFrame({"Close": [270.5, None, 999.0]}, index=idx)

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=Ticker))
    s = {"id": "kc", "ticker": "KC=F"}
    assert collect.collect_yfinance(s) == 1
    assert collect.read_rows("kc")[0]["value"] == "270.5000"
    collect.collect_yfinance(s)
    assert periods == ["5y", "5d"]


def test_yfinance_empty_raises(tmp_data, monkeypatch):
    class Ticker:
        def __init__(self, sym): pass
        def history(self, **kw): return pd.DataFrame({"Close": []})

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=Ticker))
    with pytest.raises(RuntimeError, match="no rows"):
        collect.collect_yfinance({"id": "kc", "ticker": "KC=F"})


# --- main ----------------------------------------------------------------------

def test_main_isolates_failures_and_records_status(tmp_data, monkeypatch, capsys):
    (tmp_data.parent / "config.json").write_text(json.dumps({"series": [
        {"id": "good", "source": "fred"},
        {"id": "bad", "source": "dramx"},
    ]}))

    def boom(series):
        raise RuntimeError("blocked")

    monkeypatch.setitem(collect.COLLECTORS, "fred", lambda s: 3)
    monkeypatch.setitem(collect.COLLECTORS, "dramx", boom)
    collect.main()
    status = json.loads((tmp_data / "_status.json").read_text())
    assert status["good"]["last_error"] is None and status["good"]["last_success"]
    assert status["bad"]["last_error"] == "RuntimeError: blocked"
    assert "last_success" not in status["bad"]
    assert "done: 1 failure(s)" in capsys.readouterr().out

    # A later success clears the error but keeps the history of when it failed.
    monkeypatch.setitem(collect.COLLECTORS, "dramx", lambda s: 1)
    collect.main()
    status = json.loads((tmp_data / "_status.json").read_text())
    assert status["bad"]["last_error"] is None and status["bad"]["last_error_at"]
