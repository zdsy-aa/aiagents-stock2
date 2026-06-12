# tests/test_combo_batch.py
import os, tempfile
import pandas as pd
import combo_batch
from combo_signal_db import ComboSignalDB


def _df(closes, start="2026-04-01"):
    idx = pd.date_range(start, periods=len(closes), freq="D")
    return pd.DataFrame({"Open": closes, "High": [c + 0.5 for c in closes],
                         "Low": [c - 0.5 for c in closes], "Close": closes,
                         "Volume": [1] * len(closes)}, index=idx)


def _bullish_closes():
    closes = [10 + i * 0.5 for i in range(30)]
    for _ in range(5):
        closes.append(closes[-1] - 1.0)
    for _ in range(25):
        closes.append(closes[-1] + 1.0)
    return closes


class _FakeChanDB:
    def __init__(self, rows):
        self._df = pd.DataFrame(rows)

    def get_latest_signals(self):
        return self._df


def _combo_db():
    return ComboSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "cb.db"))


def test_combo_hit_within_window(monkeypatch):
    up = _df(_bullish_closes())                      # 末段强多, 多头数≥5
    hit_date = pd.Timestamp(up.index[-2]).strftime("%Y-%m-%d")   # 末段交易日, ±3窗口内有≥5
    chan = _FakeChanDB([{"code": "600000", "name": "甲", "board": "深主板",
                         "signal_type": "1买", "signal_date": hit_date, "buy_reason": "背驰"}])
    monkeypatch.setattr(combo_batch, "_load", lambda *a, **k: up)
    db = _combo_db()
    n = combo_batch.scan(chan, db, scan_date="2026-05-29")
    assert n == 1
    row = db.get_latest_signals().iloc[0]
    assert row["code"] == "600000" and int(row["liumai_bull_count"]) >= 5


def test_combo_no_hit_when_bearish(monkeypatch):
    down = _df([100 - i for i in range(60)])
    d = pd.Timestamp(down.index[50]).strftime("%Y-%m-%d")
    chan = _FakeChanDB([{"code": "600000", "name": "甲", "board": "深主板",
                         "signal_type": "1买", "signal_date": d, "buy_reason": "背驰"}])
    monkeypatch.setattr(combo_batch, "_load", lambda *a, **k: down)
    n = combo_batch.scan(chan, _combo_db(), scan_date="2026-05-29")
    assert n == 0


def test_combo_empty_chanlun_returns_zero(monkeypatch):
    chan = _FakeChanDB([])
    monkeypatch.setattr(combo_batch, "_load", lambda *a, **k: _df(_bullish_closes()))
    n = combo_batch.scan(chan, _combo_db(), scan_date="2026-05-29")
    assert n == 0


def test_combo_signal_date_not_in_index_skipped(monkeypatch):
    up = _df(_bullish_closes())
    chan = _FakeChanDB([{"code": "600000", "name": "甲", "board": "深主板",
                         "signal_type": "1买", "signal_date": "1999-01-01", "buy_reason": "背驰"}])
    monkeypatch.setattr(combo_batch, "_load", lambda *a, **k: up)
    n = combo_batch.scan(chan, _combo_db(), scan_date="2026-05-29")
    assert n == 0
