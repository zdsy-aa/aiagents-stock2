# tests/test_combo_selector.py
import os, tempfile
from combo_signal_db import ComboSignalDB
from combo_selector import ComboSelector, KEEP_COLS


def _seed():
    db = ComboSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "cb.db"))
    db.upsert_signals([
        {"code": "600000", "name": "浦发", "board": "深主板", "chanlun_type": "1买",
         "chanlun_date": "2026-05-27", "buy_reason": "背驰", "liumai_date": "2026-05-28",
         "liumai_bull_count": 6, "liumai_score": 100, "scan_date": "2026-05-29"},
    ])
    return db


def test_get_picks():
    ok, df, msg = ComboSelector(db=_seed()).get_picks()
    assert ok and len(df) == 1 and list(df.columns) == KEEP_COLS


def test_get_picks_empty():
    db = ComboSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "cb.db"))
    ok, df, msg = ComboSelector(db=db).get_picks()
    assert ok is False and "暂无" in msg


def test_list_dates():
    assert ComboSelector(db=_seed()).list_dates() == ["2026-05-29"]
