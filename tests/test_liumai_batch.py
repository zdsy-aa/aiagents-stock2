# tests/test_liumai_batch.py
import os, tempfile
import pandas as pd
import liumai_batch
from liumai_signal_db import LiumaiSignalDB


def _df(closes):
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    return pd.DataFrame({"Open": closes, "High": [c + 0.5 for c in closes],
                         "Low": [c - 0.5 for c in closes], "Close": closes,
                         "Volume": [1] * len(closes)}, index=idx)


def _bullish_closes():
    """先缓涨后回调再强势反弹, 令六维全多(纯线性序列 K==D 不交叉)。"""
    closes = [10 + i * 0.5 for i in range(30)]
    for _ in range(5):
        closes.append(closes[-1] - 1.0)
    for _ in range(25):
        closes.append(closes[-1] + 1.0)
    return closes


def _db():
    return LiumaiSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "lm.db"))


def test_scan_writes_only_ge5_bull(monkeypatch):
    up = _df(_bullish_closes())                 # 六维全多 → 多头数 6
    down = _df([100 - i for i in range(60)])    # 偏空 → 多头数低

    def fake_load(code, kind, limit):
        return up if code == "600000" else down

    monkeypatch.setattr(liumai_batch, "_load", fake_load)
    db = _db()
    n = liumai_batch.scan_codes(["600000", "000001"], db, scan_date="2026-05-29",
                                name_board={"600000": ("甲", "深主板"),
                                            "000001": ("乙", "深主板")})
    df = db.get_latest_signals()
    assert n == len(df)
    assert list(df["code"]) == ["600000"]        # 只有强多入库
    assert int(df.iloc[0]["bull_count"]) >= 5


def test_scan_skips_short_or_none(monkeypatch):
    monkeypatch.setattr(liumai_batch, "_load", lambda *a, **k: None)
    db = _db()
    n = liumai_batch.scan_codes(["600000"], db, scan_date="2026-05-29")
    assert n == 0 and db.get_latest_signals().empty
