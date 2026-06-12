# tests/test_liumai_signal_db.py
import os, tempfile
from liumai_signal_db import LiumaiSignalDB


def _db():
    return LiumaiSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "lm.db"))


def _row(code="600000", scan="2026-05-29", bull=6):
    return {"code": code, "name": "浦发", "board": "深主板",
            "signal_date": "2026-05-29", "bull_count": bull, "score": 100,
            "state": "强势", "macd": 1, "kdj": 1, "rsi": 1, "lwr": 1,
            "bbi": 1, "mtm": 1, "scan_date": scan}


def test_upsert_and_get_latest():
    db = _db()
    db.upsert_signals([_row(), _row(code="000001", bull=5)])
    df = db.get_latest_signals()
    assert len(df) == 2
    assert set(df["code"]) == {"600000", "000001"}


def test_get_latest_only_newest_batch():
    db = _db()
    db.upsert_signals([_row(scan="2026-05-28")])
    db.upsert_signals([_row(code="000001", scan="2026-05-29")])
    df = db.get_latest_signals()
    assert len(df) == 1 and df.iloc[0]["scan_date"] == "2026-05-29"


def test_upsert_conflict_updates():
    db = _db()
    db.upsert_signals([_row(bull=6)])
    db.upsert_signals([_row(bull=5)])
    df = db.get_latest_signals()
    assert len(df) == 1 and int(df.iloc[0]["bull_count"]) == 5


def test_list_scan_dates_desc():
    db = _db()
    db.upsert_signals([_row(scan="2026-05-28")])
    db.upsert_signals([_row(code="000001", scan="2026-05-29")])
    assert db.list_scan_dates() == ["2026-05-29", "2026-05-28"]


def test_clear_scan():
    db = _db()
    db.upsert_signals([_row(scan="2026-05-29")])
    db.clear_scan("2026-05-29")
    assert db.get_latest_signals().empty
