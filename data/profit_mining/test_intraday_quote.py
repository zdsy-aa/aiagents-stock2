# test_intraday_quote.py —— 盘中实时bar注入/快照解析 断言测试（无pytest，python3直接跑）
import pandas as pd
import intraday_quote as IQ


def _df(dates, closes):
    idx = pd.to_datetime(dates)
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                         "Close": closes, "Volume": [100.0] * len(closes)}, index=idx)


def test_inject_appends_new_today_row():
    df = _df(["2026-06-08", "2026-06-09"], [10.0, 11.0])
    bar = {"Open": 11.2, "High": 11.9, "Low": 11.1, "Close": 11.5, "Volume": 500.0}
    out = IQ.inject_today_bar(df, bar, pd.Timestamp("2026-06-10"))
    assert len(out) == 3, len(out)
    assert out.index[-1] == pd.Timestamp("2026-06-10")
    assert out["Close"].iloc[-1] == 11.5
    assert len(df) == 2  # 入参不被改


def test_inject_overwrites_existing_today_row():
    df = _df(["2026-06-09", "2026-06-10"], [11.0, 11.3])
    bar = {"Open": 11.2, "High": 12.0, "Low": 11.1, "Close": 11.8, "Volume": 700.0}
    out = IQ.inject_today_bar(df, bar, pd.Timestamp("2026-06-10"))
    assert len(out) == 2, len(out)
    assert out["Close"].iloc[-1] == 11.8
    assert out["High"].iloc[-1] == 12.0


def test_inject_none_bar_passthrough():
    df = _df(["2026-06-09", "2026-06-10"], [11.0, 11.3])
    out = IQ.inject_today_bar(df, None, pd.Timestamp("2026-06-10"))
    assert out["Close"].iloc[-1] == 11.3
    assert len(out) == 2


def test_parse_spot_basic():
    spot = pd.DataFrame({
        "代码": ["600519", "000001", "300750"],
        "今开": [1700.0, 11.0, 200.0],
        "最高": [1720.0, 11.3, 205.0],
        "最低": [1695.0, 10.9, 199.0],
        "最新价": [1710.0, 11.2, 0.0],   # 300750 现价0 → 停牌/无效，应剔除
        "成交量": [3.0e5, 8.0e6, 1.0e5],
    })
    snap = IQ._parse_spot(spot)
    assert "600519" in snap and "000001" in snap
    assert "300750" not in snap, "现价<=0 应剔除"
    assert snap["600519"]["Close"] == 1710.0
    assert snap["000001"]["High"] == 11.3
    assert isinstance(list(snap.keys())[0], str) and len(list(snap.keys())[0]) == 6


def test_parse_spot_empty():
    assert IQ._parse_spot(None) == {}
    assert IQ._parse_spot(pd.DataFrame()) == {}


def test_quote_to_bar():
    q = {"Code": "000001", "TotalHand": 12345,
         "K": {"Open": 10000, "High": 10500, "Low": 9900, "Close": 10200}}
    bar = IQ._quote_to_bar(q)
    assert bar == {"Open": 10.0, "High": 10.5, "Low": 9.9, "Close": 10.2,
                   "Volume": 12345.0}, bar
    assert IQ._quote_to_bar({"K": {"Open": 0, "High": 0, "Low": 0, "Close": 0},
                             "TotalHand": 0}) is None   # 停牌 Close<=0
    assert IQ._quote_to_bar({"foo": 1}) is None          # 缺字段


if __name__ == "__main__":
    test_inject_appends_new_today_row()
    test_inject_overwrites_existing_today_row()
    test_inject_none_bar_passthrough()
    test_parse_spot_basic()
    test_parse_spot_empty()
    test_quote_to_bar()
    print("ALL OK")
