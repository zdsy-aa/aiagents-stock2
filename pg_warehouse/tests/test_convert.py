import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import datetime
from zoneinfo import ZoneInfo
from convert import to_ts, to_price, to_amount, to_bool, sqlite_to_pg_type

def test_to_ts():
    # 1715650500 秒 = 2024-05-14 01:35:00 UTC = 2024-05-14 09:35:00 Asia/Shanghai
    out = to_ts(1715650500)
    assert out == datetime.datetime(2024, 5, 14, 9, 35, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert to_ts(None) is None

def test_to_price():
    assert to_price(11390) == 11.39
    assert to_price(0) == 0.0
    assert to_price(None) is None

def test_to_amount():
    assert to_amount(1338932736000) == 1338932736.0
    assert to_amount(None) is None

def test_to_bool():
    assert to_bool(1) is True
    assert to_bool(0) is False
    assert to_bool(None) is None

def test_sqlite_to_pg_type():
    assert sqlite_to_pg_type("INTEGER") == "BIGINT"
    assert sqlite_to_pg_type("REAL") == "DOUBLE PRECISION"
    assert sqlite_to_pg_type("TEXT") == "TEXT"
    assert sqlite_to_pg_type("BOOLEAN") == "BOOLEAN"
    assert sqlite_to_pg_type("TIMESTAMP") == "TIMESTAMPTZ"
    assert sqlite_to_pg_type("VARCHAR(20)") == "TEXT"
    assert sqlite_to_pg_type("SOMETHING_WEIRD") == "TEXT"
