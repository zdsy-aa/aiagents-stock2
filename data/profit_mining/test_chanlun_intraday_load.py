# 验证 chanlun_batch._load 在给定 live_bars 时把今日bar注入日K末尾。
import sys
sys.path.insert(0, "/app")
import pandas as pd
import chanlun_batch as CB


def test_load_injects_live_bar(monkeypatch=None):
    idx = pd.to_datetime(["2026-06-08", "2026-06-09"])
    fake = pd.DataFrame({"日期": idx, "开盘": [10, 11], "最高": [10, 11],
                         "最低": [10, 11], "收盘": [10, 11], "成交量": [100, 100]})

    # 替换本地源 get_kline
    from akshare_gateway import akshare_gw
    orig = akshare_gw.local.get_kline
    akshare_gw.local.get_kline = lambda *a, **k: fake.copy()
    try:
        bars = {"600519": {"Open": 11.2, "High": 11.9, "Low": 11.1,
                           "Close": 11.5, "Volume": 500.0}}
        df = CB._load("600519", "day", 500, live_bars=bars)
        assert df.index[-1] == pd.Timestamp.now().normalize()
        assert df["Close"].iloc[-1] == 11.5
        # 不传 live_bars → 不注入
        df0 = CB._load("600519", "day", 500)
        assert df0.index[-1] == pd.Timestamp("2026-06-09")
    finally:
        akshare_gw.local.get_kline = orig


if __name__ == "__main__":
    test_load_injects_live_bar()
    print("ALL OK")
