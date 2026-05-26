"""引擎分钟分析：freq 时走 get_minute_data，且 fundamental 关闭时不调 get_financial_data。"""
import os

os.environ["LOCAL_DB_DIR"] = "/home/tdxback/aiagents-stock/tdx-data/database/kline"
os.environ.setdefault("LOCAL_DB_ENABLED", "true")

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock
from stock_analysis_engine import StockAnalysisEngine


def test_intraday_uses_minute_data_and_skips_fundamental():
    engine = StockAnalysisEngine()

    # 桩掉 LLM / 网络，保持测试 hermetic
    engine.fetcher.get_stock_info = MagicMock(return_value={"symbol": "600519", "name": "贵州茅台"})
    engine.fetcher.get_financial_data = MagicMock(return_value={})
    engine.agents.run_multi_agent_analysis = MagicMock(return_value={"technical": {}})
    engine.agents.comprehensive_discussion = MagicMock(return_value={})
    engine.agents.deepseek_client = MagicMock()
    engine.agents.deepseek_client.final_decision = MagicMock(return_value={"decision": "观望"})

    # spy 分钟取数（仍调真实实现）
    real_get_minute = engine.fetcher.get_minute_data
    engine.fetcher.get_minute_data = MagicMock(side_effect=real_get_minute)

    result = engine.run_full_analysis(
        "600519", period="30min", freq="30min",
        enabled_analysts={"technical": True, "fundamental": False, "fund_flow": False,
                          "risk": False, "sentiment": False, "news": False},
    )

    engine.fetcher.get_minute_data.assert_called_once()
    engine.fetcher.get_financial_data.assert_not_called()
    assert result["final_decision"] == {"decision": "观望"}


if __name__ == "__main__":
    test_intraday_uses_minute_data_and_skips_fundamental()
    print("PASS: 引擎分钟分析 + 基本面门控")
