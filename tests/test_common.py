"""Phase4 Task4.0:interfaces.common 公共约定测试。

覆盖:ANALYSIS_KEYS 字段完整性、Scenario 构造与校验、api_error 包装、SCREEN_RESULT_COLS。
"""
import pytest

from interfaces.common import ANALYSIS_KEYS, SCREEN_RESULT_COLS, Scenario, api_error


def test_analysis_keys_complete():
    assert "scenarios" in ANALYSIS_KEYS and "degraded" in ANALYSIS_KEYS


def test_analysis_keys_exact_shape():
    # 与 Phase4 计划 Interfaces 一节逐字一致(4.1/4.3 消费方按此结构取值)。
    assert ANALYSIS_KEYS == [
        "symbol", "name", "period", "generated_at", "current_state", "trend",
        "chip", "capital", "industry", "news", "signals", "scenarios",
        "evidence", "degraded", "degraded_reason",
    ]


def test_screen_result_cols_exact_shape():
    assert SCREEN_RESULT_COLS == ["代码", "名称", "信号", "得分", "备注"]


def test_scenario_minimal_fields():
    s = Scenario(name="上涨", trigger="放量突破", confirm="次日站稳", invalidate="回落破位")
    assert s["trigger"] and s["invalidate"]


def test_scenario_returns_declared_field_set():
    # 返回 dict 始终含 R4-B 声明的 8 个字段,未填项为空串(消费方可按列索引渲染)。
    s = Scenario(name="下跌", trigger="跌破支撑", invalidate="收回支撑")
    assert set(s) == {
        "name", "trigger", "confirm", "target", "invalidate", "observe", "risk", "end",
    }
    assert s["name"] == "下跌" and s["confirm"] == ""


def test_scenario_rejects_bad_name():
    with pytest.raises(ValueError):
        Scenario(name="横盘", trigger="t", invalidate="i")


def test_scenario_requires_trigger_and_invalidate():
    with pytest.raises(ValueError):
        Scenario(name="上涨", trigger="", invalidate="i")
    with pytest.raises(ValueError):
        Scenario(name="震荡", trigger="t", invalidate="  ")


def test_api_error_wraps():
    with pytest.raises(RuntimeError, match="analyze_stock"):
        raise api_error("analyze_stock", ValueError("坏输入"))


def test_api_error_keeps_reason_and_cause():
    cause = ValueError("坏输入")
    err = api_error("screen_stocks", cause)
    assert isinstance(err, RuntimeError)
    assert "screen_stocks" in str(err) and "坏输入" in str(err)
    assert err.__cause__ is cause
