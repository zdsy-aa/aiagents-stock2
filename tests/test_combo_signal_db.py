# tests/test_combo_signal_db.py
import os, tempfile
from combo_signal_db import ComboSignalDB


def _db():
    return ComboSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "cb.db"))


def _row(code="600000", chan_date="2026-05-27", scan="2026-05-29"):
    return {"code": code, "name": "浦发", "board": "深主板",
            "chanlun_type": "1买", "chanlun_date": chan_date, "buy_reason": "背驰",
            "liumai_date": "2026-05-28", "liumai_bull_count": 6, "liumai_score": 100,
            "scan_date": scan}


def test_upsert_and_get_latest():
    db = _db()
    db.upsert_signals([_row(), _row(code="000001")])
    df = db.get_latest_signals()
    assert len(df) == 2


def test_get_latest_only_newest_batch():
    db = _db()
    db.upsert_signals([_row(scan="2026-05-28")])
    db.upsert_signals([_row(code="000001", scan="2026-05-29")])
    df = db.get_latest_signals()
    assert len(df) == 1 and df.iloc[0]["scan_date"] == "2026-05-29"


def test_conflict_updates():
    db = _db()
    db.upsert_signals([_row()])
    r = _row(); r["liumai_bull_count"] = 5
    db.upsert_signals([r])
    df = db.get_latest_signals()
    assert len(df) == 1 and int(df.iloc[0]["liumai_bull_count"]) == 5


def test_list_dates_and_clear():
    db = _db()
    db.upsert_signals([_row(scan="2026-05-29")])
    assert db.list_scan_dates() == ["2026-05-29"]
    db.clear_scan("2026-05-29")
    assert db.get_latest_signals().empty
