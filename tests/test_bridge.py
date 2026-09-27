"""interfaces.bridge(Task 4.5):registry 指标 → 回测桥接。

覆盖(简报测试 + 计划测试线):
- 六脉神剑V5(partial=false)→ spec 生成(优先命名含 买/卖/首发 的布尔输出)
  + eval_combo 于合成 df;
- 核心_基础V3(partial=true)→ spec 生成(首个布尔输出)+ partial_warning=True;
  guard_partial 返回 unsupported 警告清单;outputs 空 → RuntimeError;
- MACD(纯数值输出 DIFF/DEA/MACD)→ None(数值指标留 Phase 5);
- 未知名称 / outputs 空 → None。

spec 的 col 用 registry 输出名(输出名与确认面板列名的映射核对结论见
task-4.5-report.md,不一致映射留 Phase 5 数据层统一)。
"""
import pandas as pd
import pytest

import backtest.combo_engine as ce
import interfaces.bridge as br
from indicators import compute
from indicators.evaluator import synthetic_df
from indicators.registry import load_registry


# ---------------------------------------------------------------------------
# 六脉神剑V5(partial=false)
# ---------------------------------------------------------------------------

def test_liumai_v5_to_spec_and_eval():
    spec = br.registry_to_spec("六脉神剑V5")
    assert spec is not None
    assert len(spec["conds"]) == 1
    col = spec["conds"][0]["col"]
    assert col in ("六脉红灯", "六脉6红首发", "MACD多")  # 简报口径:布尔输出
    assert spec["conds"][0] == {"col": col, "op": ">", "value": 0}
    assert "partial_warning" not in spec  # partial=false 不带警告字段
    df = pd.DataFrame({col: [1, 0, 1]})
    assert ce.eval_combo(spec, df).sum() == 2


def test_liumai_v5_spec_matches_computed_output():
    """spec 在真实 compute 输出上求值(端到端接线:bridge ↔ combo_engine)。"""
    spec = br.registry_to_spec("六脉神剑V5")
    col = spec["conds"][0]["col"]
    df = pd.DataFrame(compute("六脉神剑V5", synthetic_df(), code_prefix="600000"))
    mask = ce.eval_combo(spec, df)
    assert mask.dtype == bool
    assert len(mask) == len(df)
    assert set(df[col].dropna().unique()) <= {0, 1}  # col 是布尔输出
    assert mask.sum() == (df[col] > 0).sum()


# ---------------------------------------------------------------------------
# 核心_基础V3(partial=true)
# ---------------------------------------------------------------------------

def test_partial_entry_produces_spec_with_warning():
    spec = br.registry_to_spec("核心_基础V3")
    assert spec is not None                      # 部分注册也产出 spec(输出充足)
    assert spec["partial_warning"] is True
    assert spec["conds"][0]["col"] == "涨停"      # 首个布尔输出(涨停幅度为数值)


def test_partial_spec_eval_on_computed_output():
    spec = br.registry_to_spec("核心_基础V3")
    col = spec["conds"][0]["col"]
    df = pd.DataFrame(compute("核心_基础V3", synthetic_df(), code_prefix="600000"))
    mask = ce.eval_combo(spec, df)
    assert set(df[col].dropna().unique()) <= {0, 1}
    assert mask.sum() == (df[col] > 0).sum()


def test_guard_partial_raises_on_empty_outputs():
    with pytest.raises(RuntimeError):
        br.guard_partial({"partial": True, "outputs": [], "unsupported": []})


def test_guard_partial_warns_with_outputs():
    entry = load_registry()["核心_基础V3"]
    warnings = br.guard_partial(entry)
    assert len(warnings) == len(entry["unsupported"]) == 5
    assert all(isinstance(w, str) and w for w in warnings)


def test_guard_partial_noop_when_complete():
    entry = load_registry()["六脉神剑V5"]
    assert br.guard_partial(entry) is None


# ---------------------------------------------------------------------------
# 数值型输出指标 / 异常输入
# ---------------------------------------------------------------------------

def test_numeric_indicator_returns_none():
    # MACD 输出 DIFF/DEA/MACD 全为数值线,无布尔输出 → None(留 Phase 5)
    assert br.registry_to_spec("MACD") is None


def test_unknown_name_returns_none():
    assert br.registry_to_spec("不存在的指标") is None


def test_empty_outputs_returns_none(monkeypatch):
    monkeypatch.setattr(br, "load_registry",
                        lambda: {"X": {"outputs": [], "partial": False,
                                       "unsupported": []}})
    assert br.registry_to_spec("X") is None
