# tests/test_current_strategy_live.py
import json
import current_strategy_ui as M


def test_star_read_ok(tmp_path, monkeypatch):
    p = tmp_path / "star.json"
    p.write_text(json.dumps({
        "win_thresh": 4.0, "bigrise_thresh": 10.0,
        "train_end": "2023-12-31", "oos": ["2024-01-01", "2025-10-31"],
        "tiers": {"核心": {"n_stars": 5}, "精选": {"n_stars": 2}},
    }), encoding="utf-8")
    monkeypatch.setattr(M, "STAR_THRESH", str(p))
    out = M._read_star_thresholds()
    assert out["ok"] is True
    assert "4" in out["text"] and "核心" in out["text"]


def test_star_read_missing_is_graceful(monkeypatch):
    monkeypatch.setattr(M, "STAR_THRESH", "/no/such/file.json")
    out = M._read_star_thresholds()
    assert out["ok"] is False
    assert out["text"]  # 有回退文案，不抛异常


def test_watchlist_stat_missing_is_graceful(monkeypatch):
    monkeypatch.setattr(M, "WATCHLIST", "/no/such/file.csv")
    out = M._read_watchlist_stat()
    assert out["ok"] is False and out["text"]


def test_commonality_latest_missing_is_graceful(monkeypatch):
    monkeypatch.setattr(M, "COMMONALITY_DIR", "/no/such/dir")
    out = M._read_commonality_latest()
    assert out["ok"] is False and out["text"]
