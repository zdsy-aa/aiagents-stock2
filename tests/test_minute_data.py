"""数据层分钟取数：返回标准 OHLCV（Date 索引），可直接算指标。"""
import os

os.environ["LOCAL_DB_DIR"] = "/home/tdxback/aiagents-stock/tdx-data/database/kline"
os.environ.setdefault("LOCAL_DB_ENABLED", "true")

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from stock_data import StockDataFetcher


def test_get_minute_data_30min():
    f = StockDataFetcher()
    df = f.get_minute_data("600519", "30min", limit=240)
    assert isinstance(df, pd.DataFrame)
    assert df.index.name == "Date"
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        assert col in df.columns
    assert 0 < len(df) <= 240
    # 指标计算不报错
    enriched = f.calculate_technical_indicators(df)
    assert enriched is not None and not enriched.empty


if __name__ == "__main__":
    test_get_minute_data_30min()
    print("PASS: 数据层分钟取数")
