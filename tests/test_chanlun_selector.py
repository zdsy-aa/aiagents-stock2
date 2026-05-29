# tests/test_chanlun_selector.py
import os, tempfile
from chanlun_signal_db import ChanlunSignalDB
from chanlun_selector import ChanlunSelector


def _seed():
    db = ChanlunSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "s.db"))
    db.upsert_signals([
        {"code": "600000", "name": "浦发", "board": "沪主板", "signal_type": "1买",
         "signal_date": "2026-05-26", "buy_price": 10.0, "buy_reason": "下跌段力度背驰",
         "stop_loss": 9.8, "sell_type": "1卖", "sell_date": "2026-05-28",
         "sell_reason": "上涨段力度背驰", "level": "日线", "scan_date": "2026-05-27"},
        {"code": "300750", "name": "宁德", "board": "创业板", "signal_type": "3买",
         "signal_date": "2026-05-27", "buy_price": 200.0, "buy_reason": "上破中枢回踩不破",
         "stop_loss": 196.0, "sell_type": "", "sell_date": "", "sell_reason": "",
         "level": "日线", "scan_date": "2026-05-27"},
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


def test_list_dates():
    sel = ChanlunSelector(db=_seed())
    assert sel.list_dates() == ["2026-05-27"]


def test_get_picks_by_scan_date():
    db = _seed()
    # 追加一个更早批次，确认按日期能取到旧批次而非最新
    db.upsert_signals([
        {"code": "000001", "name": "平安", "board": "深主板", "signal_type": "1买",
         "signal_date": "2026-05-20", "buy_price": 12.0, "buy_reason": "x", "stop_loss": 11.8,
         "sell_type": "", "sell_date": "", "sell_reason": "", "level": "日线",
         "scan_date": "2026-05-22"}])
    sel = ChanlunSelector(db=db)
    ok, df, msg = sel.get_chanlun_picks(scan_date="2026-05-22")
    assert ok and len(df) == 1 and df.iloc[0]["code"] == "000001"
