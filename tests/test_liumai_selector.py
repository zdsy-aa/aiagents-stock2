# tests/test_liumai_selector.py
import os, tempfile
from liumai_signal_db import LiumaiSignalDB
from liumai_selector import LiumaiSelector, KEEP_COLS


def _seed():
    db = LiumaiSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "lm.db"))
    db.upsert_signals([
        {"code": "600000", "name": "浦发", "board": "深主板", "signal_date": "2026-05-29",
         "bull_count": 6, "score": 100, "state": "强势", "macd": 1, "kdj": 1, "rsi": 1,
         "lwr": 1, "bbi": 1, "mtm": 1, "scan_date": "2026-05-29"},
        {"code": "000001", "name": "平安", "board": "深主板", "signal_date": "2026-05-29",
         "bull_count": 5, "score": 80, "state": "强势", "macd": 1, "kdj": 1, "rsi": 1,
         "lwr": 0, "bbi": 1, "mtm": 1, "scan_date": "2026-05-29"},
    ])
    return db


def test_get_picks_all_sorted():
    ok, df, msg = LiumaiSelector(db=_seed()).get_picks()
    assert ok and len(df) == 2
    assert list(df.columns) == KEEP_COLS
    assert int(df.iloc[0]["bull_count"]) == 6


def test_get_picks_empty():
    db = LiumaiSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "lm.db"))
    ok, df, msg = LiumaiSelector(db=db).get_picks()
    assert ok is False and "暂无" in msg


def test_list_dates():
    assert LiumaiSelector(db=_seed()).list_dates() == ["2026-05-29"]
