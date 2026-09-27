# -*- coding: utf-8 -*-
"""interfaces.analyze 单股分析接口测试(Phase4 Task4.1)。

控制器裁决(2026-09-27):主路径改为 StockAnalysisEngine.run_full_analysis;
run_stock_analysis 仅作引擎不可导入时的回退;interfaces/__init__ 导出 analyze_stock。
相应地:
- 简报原用例的 monkeypatch 目标由 az.run_stock_analysis 调整为引擎主路径
  az._run_engine_analysis(改动处已注明),其余断言逐字保留;
- 新增引擎运行时失败降级、引擎不可导入→回退 run_stock_analysis、双不可用、
  包级导出 等用例。
全部不依赖真实网络(monkeypatch 假 client / 假引擎 / 假 run_stock_analysis)。
"""
import pytest

import interfaces.analyze as az
from interfaces.common import ANALYSIS_KEYS


def _enable_engine(monkeypatch):
    """把 StockAnalysisEngine 置为非 None(venv-data 无重依赖,导入时置 None),
    使 analyze_stock 走引擎主路径。"""
    monkeypatch.setattr(az, "StockAnalysisEngine", type("Engine", (), {}))


# 简报原用例(适配主路径:monkeypatch 目标改为 az._run_engine_analysis,其余不变)
def test_analyze_stock_degraded_on_ai_failure(monkeypatch):
    def fake_engine(symbol, period):
        return {"agents_results": {}, "discussion_result": "讨论", "final_decision": "决策"}
    _enable_engine(monkeypatch)
    monkeypatch.setattr(az, "_run_engine_analysis", fake_engine)
    r = az.analyze_stock("600000")
    assert r["degraded"] is True            # 无 AI(monkeypatch 下 client 不可用)仍返回结构
    for k in ANALYSIS_KEYS:
        assert k in r, k


def test_build_scenarios_parses_json(monkeypatch):
    def fake_client(*a, **k):
        return '{"scenarios": [{"name":"上涨","trigger":"t","invalidate":"i"}]}'
    monkeypatch.setattr(az, "_call_scenario_llm", fake_client)
    scs = az.build_scenarios("任意分析文本")
    assert scs[0]["name"] == "上涨" and scs[0]["trigger"] == "t"


# ---- 补充用例 ----

def test_analyze_stock_invalid_code_raises():
    for bad in ("", "   ", None, 123):
        with pytest.raises(ValueError):
            az.analyze_stock(bad)


def test_build_scenarios_parse_failure_returns_empty(monkeypatch):
    # 非 JSON 文本 → []
    monkeypatch.setattr(az, "_call_scenario_llm", lambda *a, **k: "这不是 JSON")
    assert az.build_scenarios("文本") == []

    # JSON 但缺 scenarios 键 → []
    monkeypatch.setattr(az, "_call_scenario_llm", lambda *a, **k: '{"foo": 1}')
    assert az.build_scenarios("文本") == []

    # 情景缺必填 trigger/invalidate → 解析失败 → []
    monkeypatch.setattr(
        az, "_call_scenario_llm",
        lambda *a, **k: '{"scenarios": [{"name": "上涨", "invalidate": "i"}]}',
    )
    assert az.build_scenarios("文本") == []


def test_build_scenarios_empty_input_returns_empty(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("空输入不应发起 LLM 调用")
    monkeypatch.setattr(az, "_call_scenario_llm", boom)
    assert az.build_scenarios("") == []
    assert az.build_scenarios(None) == []


# 主路径:引擎返回 dict → 字段提取 + 情景生成;回退函数不应被调用
def test_analyze_stock_extracts_fields_from_engine(monkeypatch):
    def fake_engine(symbol, period):
        return {
            "stock_info": {"name": "浦发银行", "industry": "银行"},
            "agents_results": {
                "technical": {"analysis": "技术分析文本"},
                "fundamental": {"analysis": "基本面分析文本"},
                "fund_flow": {"analysis": "资金分析文本"},
            },
            "discussion_result": "团队讨论结论",
            "final_decision": {"rating": "买入", "logic": "满足放量条件", "decision_text": "综合看多"},
        }

    def fake_client(*a, **k):
        return '{"scenarios": [{"name":"上涨","trigger":"放量","confirm":"站稳","target":"10","invalidate":"破位"}]}'

    def run_boom(*a, **k):
        raise AssertionError("引擎主路径成功时不应回退 run_stock_analysis")

    _enable_engine(monkeypatch)
    monkeypatch.setattr(az, "_run_engine_analysis", fake_engine)
    monkeypatch.setattr(az, "_call_scenario_llm", fake_client)
    monkeypatch.setattr(az, "run_stock_analysis", run_boom)
    r = az.analyze_stock("600000")

    assert r["symbol"] == "600000" and r["name"] == "浦发银行" and r["period"] == "1y"
    assert r["trend"] == "技术分析文本"
    assert r["capital"] == "资金分析文本"
    assert r["industry"] == "基本面分析文本"
    assert r["chip"] == "未提供" and r["news"] == "未提供"
    assert r["current_state"] == "买入" and r["signals"] == "满足放量条件"
    assert r["evidence"] == "团队讨论结论"
    assert r["degraded"] is False and r["degraded_reason"] == ""
    assert len(r["scenarios"]) == 1 and r["scenarios"][0]["name"] == "上涨"


def test_analyze_stock_with_ai_false_skips_scenario_llm(monkeypatch):
    def fake_engine(symbol, period):
        return {"agents_results": {}, "discussion_result": "讨论", "final_decision": "决策"}

    def boom(*a, **k):
        raise AssertionError("with_ai=False 不应调用情景 LLM")

    _enable_engine(monkeypatch)
    monkeypatch.setattr(az, "_run_engine_analysis", fake_engine)
    monkeypatch.setattr(az, "_call_scenario_llm", boom)
    r = az.analyze_stock("600000", with_ai=False)
    assert r["scenarios"] == []
    assert r["degraded"] is False            # 未请求 AI,不构成降级


def test_analyze_stock_scenario_failure_degrades_but_keeps_fields(monkeypatch):
    def fake_engine(symbol, period):
        return {"agents_results": {}, "discussion_result": "讨论", "final_decision": "决策"}

    def boom(*a, **k):
        raise RuntimeError("网络超时")

    _enable_engine(monkeypatch)
    monkeypatch.setattr(az, "_run_engine_analysis", fake_engine)
    monkeypatch.setattr(az, "_call_scenario_llm", boom)
    r = az.analyze_stock("600000")
    assert r["degraded"] is True
    assert "网络超时" in r["degraded_reason"]
    assert r["scenarios"] == []
    assert r["current_state"] == "决策"       # 其余字段保留,不因 AI 失败清空
    assert r["evidence"] == "讨论"


def test_analyze_stock_engine_runtime_failure_degrades(monkeypatch):
    def failing_engine(symbol, period):
        raise ValueError("无法获取股票 600000 的基础信息")

    _enable_engine(monkeypatch)
    monkeypatch.setattr(az, "_run_engine_analysis", failing_engine)
    r = az.analyze_stock("600000")
    assert r["degraded"] is True
    assert "分析引擎调用失败" in r["degraded_reason"]
    assert r["current_state"] == "未提供" and r["scenarios"] == []
    for k in ANALYSIS_KEYS:
        assert k in r, k


# 引擎不可导入 → 回退 run_stock_analysis
def test_analyze_stock_falls_back_to_run_stock_analysis(monkeypatch):
    def fake_run(symbol, period):
        return {
            "agents_results": {"technical": {"analysis": "技术文本"}},
            "discussion_result": "讨论",
            "final_decision": "决策",
        }

    def engine_boom(symbol, period):
        raise AssertionError("引擎不可导入时不应调用引擎")

    def client_boom(*a, **k):
        raise RuntimeError("网络超时")

    monkeypatch.setattr(az, "StockAnalysisEngine", None)
    monkeypatch.setattr(az, "_run_engine_analysis", engine_boom)
    monkeypatch.setattr(az, "run_stock_analysis", fake_run)
    monkeypatch.setattr(az, "_call_scenario_llm", client_boom)
    r = az.analyze_stock("600000")
    assert r["degraded"] is True
    assert "网络超时" in r["degraded_reason"]     # 情景 LLM 失败原因保留
    assert r["trend"] == "技术文本" and r["current_state"] == "决策"


def test_analyze_stock_run_stock_analysis_none_result_degrades(monkeypatch):
    monkeypatch.setattr(az, "StockAnalysisEngine", None)
    monkeypatch.setattr(az, "run_stock_analysis", lambda s, p: None)
    r = az.analyze_stock("600000")
    assert r["degraded"] is True
    assert "run_stock_analysis" in r["degraded_reason"]
    assert r["current_state"] == "未提供" and r["trend"] == "未提供"
    assert r["scenarios"] == []
    for k in ANALYSIS_KEYS:
        assert k in r, k


def test_analyze_stock_both_unavailable_degrades(monkeypatch):
    monkeypatch.setattr(az, "StockAnalysisEngine", None)
    monkeypatch.setattr(az, "run_stock_analysis", None)
    r = az.analyze_stock("600000")
    assert r["degraded"] is True
    assert "分析引擎" in r["degraded_reason"]
    assert "run_stock_analysis" in r["degraded_reason"]
    for k in ANALYSIS_KEYS:
        assert k in r, k


def test_interfaces_package_exports_analyze_stock():
    import interfaces
    assert callable(interfaces.analyze_stock)
