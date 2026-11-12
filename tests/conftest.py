import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import build  # noqa: E402
import collect  # noqa: E402


@pytest.fixture
def tmp_data(tmp_path, monkeypatch):
    """Point collect.py and build.py at an empty temporary data/ folder."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(collect, "ROOT", tmp_path)
    monkeypatch.setattr(collect, "DATA", data)
    monkeypatch.setattr(collect, "STATUS_PATH", data / "_status.json")
    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.setattr(build, "DATA", data)
    monkeypatch.setattr(build, "OUT", tmp_path / "site" / "data.json")
    monkeypatch.setattr(collect.time, "sleep", lambda s: None)
    collect._dramx_cache.clear()
    collect._bls_cache.clear()
    return data


@pytest.fixture
def real_config():
    return json.loads((ROOT / "config.json").read_text())
