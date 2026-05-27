# tests/test_chanlun_selector.py
import os, tempfile
from chanlun_signal_db import ChanlunSignalDB
from chanlun_selector import ChanlunSelector


def _seed():
    db = ChanlunSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "s.db"))
    db.upsert_signals([
        {"code": "600000", "name": "浦发", "board": "沪主板", "signal_type": "1买",
         "signal_date": "2026-05-26", "buy_price": 10.0, "stop_loss": 9.8,
         "exit_rule": "x", "level": "日线", "scan_date": "2026-05-27"},
        {"code": "300750", "name": "宁德", "board": "创业板", "signal_type": "3买",
         "signal_date": "2026-05-27", "buy_price": 200.0, "stop_loss": 196.0,
         "exit_rule": "x", "level": "日线", "scan_date": "2026-05-27"},
    ])
    return db


def test_get_picks_all():
    ok, df, msg = ChanlunSelector(db=_seed()).get_chanlun_picks()
    assert ok and len(df) == 2


def test_get_picks_filter_type():
    ok, df, msg = ChanlunSelector(db=_seed()).get_chanlun_picks(types=["3买"])
    assert ok and len(df) == 1 and df.iloc[0]["signal_type"] == "3买"


def test_get_picks_empty():
    db = ChanlunSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "s.db"))
    ok, df, msg = ChanlunSelector(db=db).get_chanlun_picks()
    assert ok is False and "暂无" in msg
