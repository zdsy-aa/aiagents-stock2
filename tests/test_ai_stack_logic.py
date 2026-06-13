# tests/test_ai_stack_logic.py
"""AI 智能体栈业务逻辑单测（纯函数，不联网/不需 DB）。

补 test_ai_stack_smoke(import + 龙虎榜评分基础) 之外的核心算法断言：
- news_flow_sentiment.SentimentAnalyzer：情绪分类边界 / 情绪指数合成 / 流量阶段。
- longhubang_scoring.LonghubangScoring：分项上限、单调性、批量评分契约。
"""
import pandas as pd
import pytest

from news_flow_sentiment import SentimentAnalyzer
from longhubang_scoring import LonghubangScoring


# ───────────────────────── 情绪分析 ─────────────────────────
class TestSentimentClassify:
    @pytest.mark.parametrize("idx,expect", [
        (0, "极度悲观"), (10, "极度悲观"), (19, "极度悲观"),
        (20, "悲观"), (39, "悲观"),
        (40, "中性"), (59, "中性"),
        (60, "乐观"), (79, "乐观"),
        (80, "极度乐观"), (100, "极度乐观"),
    ])
    def test_classify_boundaries(self, idx, expect):
        assert SentimentAnalyzer().classify_sentiment(idx) == expect


class TestSentimentIndex:
    def test_empty_input_is_pessimistic_34(self):
        # 无平台数据：flow=10, finance=50(无样本), keyword=50(中性)
        # index = int(10*.4 + 50*.3 + 50*.3) = 34 → 悲观
        r = SentimentAnalyzer().calculate_sentiment_index([])
        assert r["flow_factor"] == 10
        assert r["finance_factor"] == 50
        assert r["keyword_factor"] == 50
        assert r["sentiment_index"] == 34
        assert r["sentiment_class"] == "悲观"

    def test_high_flow_finance_is_euphoric(self):
        # 600 条财经新闻：flow=90, finance_ratio=1→finance=100, keyword=50
        # index = int(90*.4 + 100*.3 + 50*.3) = 81 → 极度乐观
        platforms = [{"success": True, "count": 600, "category": "finance"}]
        r = SentimentAnalyzer().calculate_sentiment_index(platforms)
        assert r["flow_factor"] == 90
        assert r["finance_factor"] == 100
        assert r["sentiment_index"] == 81
        assert r["sentiment_class"] == "极度乐观"

    def test_index_in_range_and_class_consistent(self):
        sa = SentimentAnalyzer()
        platforms = [{"success": True, "count": 200, "category": "finance"},
                     {"success": True, "count": 100, "category": "tech"},
                     {"success": False, "count": 999, "category": "finance"}]  # 失败的不计
        r = sa.calculate_sentiment_index(platforms)
        assert 0 <= r["sentiment_index"] <= 100
        assert r["sentiment_class"] == sa.classify_sentiment(r["sentiment_index"])
        # total=300(失败的不计) → flow_factor=70
        assert r["flow_factor"] == 70


class TestFlowStage:
    def test_insufficient_history_is_unknown(self):
        r = SentimentAnalyzer().determine_flow_stage([10, 20], current_score=30)
        assert r["stage"] == "unknown"
        assert r["signal"] == "观察"

    def test_sufficient_history_returns_valid_shape(self):
        r = SentimentAnalyzer().determine_flow_stage([10, 20, 30], current_score=40)
        for k in ("stage", "stage_name", "confidence", "signal", "analysis"):
            assert k in r
        assert isinstance(r["confidence"], int)
        assert isinstance(r["signal"], str) and r["signal"]


# ───────────────────────── 龙虎榜评分 ─────────────────────────
class TestLonghubangScoring:
    def test_empty_is_zero(self):
        assert LonghubangScoring().calculate_stock_score([]) == 0.0

    def test_score_bounded_0_100(self):
        s = LonghubangScoring()
        recs = [{"游资名称": "赵老哥", "营业部": "赵老哥",
                 "买入金额": 50_000_000, "净流入金额": 40_000_000}]
        assert 0.0 <= s.calculate_stock_score(recs) <= 100.0

    def test_top_youzi_beats_ordinary(self):
        s = LonghubangScoring()
        top = [{"游资名称": "赵老哥", "营业部": "赵老哥",
                "买入金额": 50_000_000, "净流入金额": 40_000_000}]
        ordinary = [{"游资名称": "某营业部", "营业部": "某营业部",
                     "买入金额": 1_000_000, "净流入金额": 10_000}]
        assert s.calculate_stock_score(top) > s.calculate_stock_score(ordinary)

    def test_capital_quality_capped_30(self):
        # 多个顶级游资买入，资金含金量分项应被 30 上限截断
        s = LonghubangScoring()
        recs = [{"游资名称": n, "营业部": n, "买入金额": 10_000_000, "净流入金额": 0}
                for n in ["赵老哥", "章盟主", "92科比", "瑞鹤仙", "小鳄鱼"]]  # 5×10=50→截到30
        assert s._calculate_capital_quality(recs) == 30.0

    def test_score_all_stocks_contract(self):
        s = LonghubangScoring()
        assert s.score_all_stocks([]).empty
        df = s.score_all_stocks([
            {"股票代码": "600000", "股票名称": "浦发",
             "游资名称": "赵老哥", "营业部": "赵老哥",
             "买入金额": 50_000_000, "净流入金额": 40_000_000},
        ])
        assert isinstance(df, pd.DataFrame)
        assert len(df) >= 1
