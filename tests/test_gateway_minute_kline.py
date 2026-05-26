"""网关分钟K线取数：route B 本地库优先。"""
import os

os.environ["LOCAL_DB_DIR"] = "/home/tdxback/aiagents-stock/tdx-data/database/kline"
os.environ.setdefault("LOCAL_DB_ENABLED", "true")

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from akshare_gateway import akshare_gw


def test_get_minute_kline_local_30min():
    df = akshare_gw.get_minute_kline("600519", "30min", limit=240)
    assert df is not None and not df.empty
    assert list(df.columns)[:5] == ["日期", "开盘", "收盘", "最高", "最低"]
    assert len(df) <= 240
    # 分钟级时间戳应含多个不同的小时（非纯日期）
    assert df["日期"].dt.hour.nunique() > 1


def test_get_minute_kline_5min():
    df = akshare_gw.get_minute_kline("600519", "5min", limit=240)
    assert df is not None and not df.empty
    assert len(df) <= 240


if __name__ == "__main__":
    test_get_minute_kline_local_30min()
    test_get_minute_kline_5min()
    print("PASS: 网关分钟取数")
