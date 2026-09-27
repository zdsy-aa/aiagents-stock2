# -*- coding: utf-8 -*-
"""interfaces.analyze 单股分析接口测试(Phase4 Task4.1)。

前两个用例为简报 Step 1 逐字保留;其余用例覆盖:
- 非法输入(ValueError)
- 情景 JSON 解析失败 → []
- 字段从 run_stock_analysis 返回 dict 的提取映射
- with_ai=False 不触发情景 LLM
- 情景 LLM 失败 → degraded 且其余字段保留
- run_stock_analysis 返回 None(Streamlit 上下文不返回值)→ 全字段降级
全部不依赖真实网络(monkeypatch 假 client / 假 run_stock_analysis)。
"""
import pytest

import interfaces.analyze as az
from interfaces.common import ANALYSIS_KEYS


def test_analyze_stock_degraded_on_ai_failure(monkeypatch):
    def fake_run(symbol, period):
        return {"agents_results": {}, "discussion_result": "讨论", "final_decision": "决策"}
    monkeypatch.setattr(az, "run_stock_analysis", fake_run)
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


def test_analyze_stock_extracts_fields_from_result(monkeypatch):
    def fake_run(symbol, period):
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

    monkeypatch.setattr(az, "run_stock_analysis", fake_run)
    monkeypatch.setattr(az, "_call_scenario_llm", fake_client)
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
    def fake_run(symbol, period):
        return {"agents_results": {}, "discussion_result": "讨论", "final_decision": "决策"}

    def boom(*a, **k):
        raise AssertionError("with_ai=False 不应调用情景 LLM")

    monkeypatch.setattr(az, "run_stock_analysis", fake_run)
    monkeypatch.setattr(az, "_call_scenario_llm", boom)
    r = az.analyze_stock("600000", with_ai=False)
    assert r["scenarios"] == []
    assert r["degraded"] is False            # 未请求 AI,不构成降级


def test_analyze_stock_scenario_failure_degrades_but_keeps_fields(monkeypatch):
    def fake_run(symbol, period):
        return {"agents_results": {}, "discussion_result": "讨论", "final_decision": "决策"}

    def boom(*a, **k):
        raise RuntimeError("网络超时")

    monkeypatch.setattr(az, "run_stock_analysis", fake_run)
    monkeypatch.setattr(az, "_call_scenario_llm", boom)
    r = az.analyze_stock("600000")
    assert r["degraded"] is True
    assert "网络超时" in r["degraded_reason"]
    assert r["scenarios"] == []
    assert r["current_state"] == "决策"       # 其余字段保留,不因 AI 失败清空
    assert r["evidence"] == "讨论"


def test_analyze_stock_none_result_degrades(monkeypatch):
    monkeypatch.setattr(az, "run_stock_analysis", lambda s, p: None)
    r = az.analyze_stock("600000")
    assert r["degraded"] is True
    assert "run_stock_analysis" in r["degraded_reason"]
    assert r["current_state"] == "未提供" and r["trend"] == "未提供"
    assert r["scenarios"] == []
    for k in ANALYSIS_KEYS:
        assert k in r, k
