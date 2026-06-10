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


if __name__ == "__main__":
    test_inject_appends_new_today_row()
    test_inject_overwrites_existing_today_row()
    test_inject_none_bar_passthrough()
    print("ALL OK")
