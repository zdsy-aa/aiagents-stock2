# tests/test_ai_stack_smoke.py
"""AI 智能体栈冒烟测试。

页面级渲染冒烟已由 test_ui_pages_smoke.py 覆盖（app.py 顶层 import 各栈 UI 入口，
参数化跑 show_* 会连带 import engine/db/pdf 并渲染首屏）。本文件补的是渲染路径
**触达不到**的模块——agents / scoring / pdf / scheduler / sentiment / model / qmt 等，
只在用户点操作时才加载，import 期的语法错/坏 import/副作用崩此前无任何测试兜底。

1) import 冒烟：逐个 import，验证 import 期无异常（不联网、不需 API key）。
2) 纯逻辑冒烟：龙虎榜评分等无副作用纯函数的最小行为断言。
"""
import importlib

import pytest

# 各 AI 栈在 import 期安全（已实测不联网/不需 key）的模块。
AI_STACK_MODULES = [
    # 智瞰龙虎
    "longhubang_agents", "longhubang_data", "longhubang_db", "longhubang_engine",
    "longhubang_pdf", "longhubang_scoring", "longhubang_ui",
    # 宏观分析 / 宏观周期
    "macro_analysis_agents", "macro_analysis_data", "macro_analysis_engine", "macro_analysis_ui",
    "macro_cycle_agents", "macro_cycle_data", "macro_cycle_engine", "macro_cycle_pdf", "macro_cycle_ui",
    # 主力选股
    "main_force_analysis", "main_force_batch_db", "main_force_history_ui",
    "main_force_pdf_generator", "main_force_selector", "main_force_ui",
    # 市场情绪
    "market_sentiment_data",
    # 新闻异动
    "news_flow_agents", "news_flow_alert", "news_flow_data", "news_flow_db",
    "news_flow_engine", "news_flow_model", "news_flow_pdf", "news_flow_scheduler",
    "news_flow_sentiment", "news_flow_ui",
    # 板块策略
    "sector_strategy_agents", "sector_strategy_data", "sector_strategy_db",
    "sector_strategy_engine", "sector_strategy_pdf", "sector_strategy_scheduler", "sector_strategy_ui",
    # 智能监控
    "smart_monitor_data", "smart_monitor_db", "smart_monitor_deepseek", "smart_monitor_engine",
    "smart_monitor_kline", "smart_monitor_qmt", "smart_monitor_tdx_data", "smart_monitor_ui",
]


@pytest.mark.parametrize("modname", AI_STACK_MODULES)
def test_ai_stack_module_imports(modname):
    """每个 AI 栈模块都应能干净 import（catch 语法错/坏 import/import 期副作用崩）。"""
    mod = importlib.import_module(modname)
    assert mod is not None


def test_longhubang_scoring_pure_logic():
    """龙虎榜评分纯逻辑冒烟：空输入=0、顶级游资+大额净流入应高于普通、分值落在 [0,100]。"""
    from longhubang_scoring import LonghubangScoring

    s = LonghubangScoring()

    assert s.calculate_stock_score([]) == 0.0

    top = [{"游资名称": "赵老哥", "营业部": "赵老哥",
            "买入金额": 50_000_000, "净流入金额": 40_000_000}]
    ordinary = [{"游资名称": "某营业部", "营业部": "某营业部",
                 "买入金额": 1_000_000, "净流入金额": 10_000}]
    top_score = s.calculate_stock_score(top)
    ord_score = s.calculate_stock_score(ordinary)

    assert 0.0 <= ord_score <= 100.0
    assert 0.0 <= top_score <= 100.0
    assert top_score > ord_score  # 顶级游资 + 大额净流入应显著高于普通席位

    expl = s.get_score_explanation()
    assert isinstance(expl, str) and len(expl) > 0
