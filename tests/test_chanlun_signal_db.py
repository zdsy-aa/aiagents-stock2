# tests/test_chanlun_signal_db.py
import os, tempfile
from chanlun_signal_db import ChanlunSignalDB


def _db():
    d = tempfile.mkdtemp()
    return ChanlunSignalDB(db_path=os.path.join(d, "chanlun_signals.db"))


def test_upsert_and_get_latest():
    db = _db()
    rows = [
        {"code": "600000", "name": "浦发银行", "board": "沪主板", "signal_type": "1买",
         "signal_date": "2026-05-26", "buy_price": 10.0, "stop_loss": 9.8,
         "exit_rule": "出现一卖离场", "level": "日线", "scan_date": "2026-05-27"},
        {"code": "300750", "name": "宁德时代", "board": "创业板", "signal_type": "2买",
         "signal_date": "2026-05-27", "buy_price": 200.0, "stop_loss": 196.0,
         "exit_rule": "出现一卖离场", "level": "日线", "scan_date": "2026-05-27"},
    ]
    db.upsert_signals(rows)
    df = db.get_latest_signals()
    assert len(df) == 2
    assert set(df["signal_type"]) == {"1买", "2买"}


def test_upsert_idempotent_on_unique_key():
    db = _db()
    row = {"code": "600000", "name": "浦发", "board": "沪主板", "signal_type": "1买",
           "signal_date": "2026-05-26", "buy_price": 10.0, "stop_loss": 9.8,
           "exit_rule": "x", "level": "日线", "scan_date": "2026-05-27"}
    db.upsert_signals([row, dict(row, buy_price=11.0)])  # 同 code+type+date
    df = db.get_latest_signals()
    assert len(df) == 1
    assert df.iloc[0]["buy_price"] == 11.0   # 后者覆盖


def test_clear_scan():
    db = _db()
    db.upsert_signals([{"code": "600000", "name": "x", "board": "沪主板", "signal_type": "1买",
                        "signal_date": "2026-05-26", "buy_price": 10.0, "stop_loss": 9.8,
                        "exit_rule": "x", "level": "日线", "scan_date": "2026-05-27"}])
    db.clear_scan("2026-05-27")
    assert len(db.get_latest_signals()) == 0
