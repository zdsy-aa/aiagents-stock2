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
         "signal_date": "2026-05-26", "buy_price": 10.0, "buy_reason": "下跌段力度背驰；30m确认",
         "stop_loss": 9.8, "sell_type": "1卖", "sell_date": "2026-05-28",
         "sell_reason": "上涨段力度背驰", "level": "日线", "scan_date": "2026-05-27"},
        {"code": "300750", "name": "宁德时代", "board": "创业板", "signal_type": "2买",
         "signal_date": "2026-05-27", "buy_price": 200.0, "buy_reason": "回踩不破1买低点",
         "stop_loss": 196.0, "sell_type": "", "sell_date": "", "sell_reason": "",
         "level": "日线", "scan_date": "2026-05-27"},
    ]
    db.upsert_signals(rows)
    df = db.get_latest_signals()
    assert len(df) == 2
    assert set(df["signal_type"]) == {"1买", "2买"}


def test_upsert_idempotent_on_unique_key():
    db = _db()
    row = {"code": "600000", "name": "浦发", "board": "沪主板", "signal_type": "1买",
           "signal_date": "2026-05-26", "buy_price": 10.0, "buy_reason": "x", "stop_loss": 9.8,
           "sell_type": "", "sell_date": "", "sell_reason": "", "level": "日线",
           "scan_date": "2026-05-27"}
    db.upsert_signals([row, dict(row, buy_price=11.0)])  # 同 code+type+date
    df = db.get_latest_signals()
    assert len(df) == 1
    assert df.iloc[0]["buy_price"] == 11.0   # 后者覆盖


def test_clear_scan():
    db = _db()
    db.upsert_signals([{"code": "600000", "name": "x", "board": "沪主板", "signal_type": "1买",
                        "signal_date": "2026-05-26", "buy_price": 10.0, "buy_reason": "x",
                        "stop_loss": 9.8, "sell_type": "", "sell_date": "", "sell_reason": "",
                        "level": "日线", "scan_date": "2026-05-27"}])
    db.clear_scan("2026-05-27")
    assert len(db.get_latest_signals()) == 0


def test_same_signal_different_scan_dates_both_kept():
    db = _db()
    base = {"code": "600000", "name": "浦发", "board": "沪主板", "signal_type": "1买",
            "signal_date": "2026-05-26", "buy_price": 10.0, "buy_reason": "x", "stop_loss": 9.8,
            "sell_type": "", "sell_date": "", "sell_reason": "", "level": "日线"}
    db.upsert_signals([dict(base, scan_date="2026-05-27")])
    db.upsert_signals([dict(base, scan_date="2026-05-28")])
    with db.conn() as conn:
        n = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    assert n == 2  # 两个批次各留一条，互不覆盖


def test_migrates_old_unique_constraint(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    # 手造旧表(3 列唯一键、含遗留 exit_rule、缺新列)并塞一条数据
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL, name TEXT, board TEXT,
        signal_type TEXT NOT NULL, signal_date TEXT NOT NULL,
        buy_price REAL, stop_loss REAL, exit_rule TEXT, level TEXT,
        scan_date TEXT NOT NULL,
        UNIQUE(code, signal_type, signal_date))""")
    conn.execute("INSERT INTO signals (code, signal_type, signal_date, buy_price, scan_date) "
                 "VALUES ('600000','1买','2026-05-26',10.0,'2026-05-27')")
    conn.commit(); conn.close()

    db = ChanlunSignalDB(db_path=path)  # 触发 init_tables → 迁移
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 1
    with db.conn() as c:
        row = c.execute("SELECT buy_price, scan_date FROM signals").fetchone()
        assert row == (10.0, "2026-05-27")
    db.upsert_signals([{"code": "600000", "name": "", "board": "沪主板", "signal_type": "1买",
                        "signal_date": "2026-05-26", "buy_price": 10.0, "buy_reason": "",
                        "stop_loss": 9.8, "sell_type": "", "sell_date": "", "sell_reason": "",
                        "level": "日线", "scan_date": "2026-05-28"}])
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 2


def test_list_scan_dates_distinct_desc():
    db = _db()
    base = {"code": "600000", "name": "", "board": "沪主板", "signal_type": "1买",
            "signal_date": "2026-05-26", "buy_price": 10.0, "buy_reason": "", "stop_loss": 9.8,
            "sell_type": "", "sell_date": "", "sell_reason": "", "level": "日线"}
    for sd in ("2026-05-27", "2026-05-28", "2026-05-27"):
        db.upsert_signals([dict(base, scan_date=sd)])
    assert db.list_scan_dates() == ["2026-05-28", "2026-05-27"]


def test_get_signals_by_scan_date():
    db = _db()
    base = {"code": "600000", "name": "", "board": "沪主板", "signal_type": "1买",
            "signal_date": "2026-05-26", "buy_price": 10.0, "buy_reason": "", "stop_loss": 9.8,
            "sell_type": "", "sell_date": "", "sell_reason": "", "level": "日线"}
    db.upsert_signals([dict(base, scan_date="2026-05-27")])
    db.upsert_signals([dict(base, code="300750", scan_date="2026-05-28")])
    df = db.get_signals_by_scan_date("2026-05-27")
    assert len(df) == 1 and df.iloc[0]["code"] == "600000"
