r"""registry 指标 → 回测桥接(Task 4.5)。

把 Phase 2 指标注册表(indicators.registry.load_registry 七键条目:
source/outputs/signals/params/compiled_at/unsupported/partial)接到 Phase 3
回测(backtest.combo_engine 的 ComboSpec 单条件规格)的最小桥。

- registry_to_spec(name) -> ComboSpec | None:
    条目 outputs 中选第一个布尔输出(命名含 买/卖/首发 优先),转单条件
    spec {"name", "join": "AND", "conds": [{"col": 输出名, "op": ">",
    "value": 0}]};条目 partial=true 时附 "partial_warning": True(调用方须
    读 unsupported 判断输出完整性,R3-A);无布尔输出返回 None(纯数值指标
    留 Phase 5)。布尔判定:registry 不存输出类型,故按 entry["source"] 经
    indicators.compute 重求值(合成 df,code_prefix="600000" 与 compile 口径
    一致)——dtype bool 或取值 ⊆ {0,1} 判布尔;求值不可用(源文件缺失等)时
    退回名称启发式(命名含 买/卖/首发 优先,否则第一个输出,与控制器裁决的
    退化语义一致)。
- guard_partial(entry) -> list[str] | None:
    partial=true 且 outputs 空 → RuntimeError(无法产出可回测 spec);
    partial=true 且 outputs 非空 → 打印 stderr 并返回 unsupported 警告清单;
    partial=false → None。

spec 的 col 用 registry 输出名(输出名与确认面板列名的映射核对结论见
task-4.5-report.md:两套命名口径不一致,映射表留 Phase 5 数据层统一时解决)。
"""
import sys

import numpy as np
import pandas as pd

from indicators import compute
from indicators.evaluator import synthetic_df
from indicators.registry import load_registry

__all__ = ["registry_to_spec", "guard_partial"]

_MARKERS = ("买", "卖", "首发")


# ---------------------------------------------------------------------------
# 布尔输出判定
# ---------------------------------------------------------------------------

def _is_bool_value(v):
    """输出值是否布尔:Series dtype bool,或取值 ⊆ {0,1}(如 IF(c,1,0) 型
    0/1 标记列);纯数值线(连续取值)判 False。"""
    if isinstance(v, pd.Series):
        if v.dtype == bool:
            return True
        x = pd.to_numeric(v, errors="coerce").dropna()
        if x.empty:
            return False
        return bool(((x == 0) | (x == 1)).all())
    return isinstance(v, (bool, np.bool_))


def _pick_output(name, entry):
    """选 spec 的列名:第一个布尔输出(命名含 买/卖/首发 优先);
    无布尔输出返回 None(数值指标留 Phase 5)。"""
    outputs = list(entry.get("outputs") or [])
    if not outputs:
        return None
    computed = None
    try:
        computed = compute(name, synthetic_df(), code_prefix="600000")
    except Exception:
        # 源文件缺失/求值异常:类型不可判定,退回名称启发式(不中断调用方)。
        computed = None
    if computed is not None:
        bool_cols = [o for o in outputs if _is_bool_value(computed.get(o))]
        if bool_cols:
            for o in bool_cols:
                if any(m in o for m in _MARKERS):
                    return o
            return bool_cols[0]
        return None
    for o in outputs:
        if any(m in o for m in _MARKERS):
            return o
    return outputs[0]


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------

def registry_to_spec(name):
    """registry 条目 → 单条件回测 spec(ComboSpec);未知名称 / 无输出 /
    无布尔输出 → None。

    布尔输出选取:outputs 中第一个布尔输出,命名含 买/卖/首发 者优先
    (如 六脉神剑V5 → 六脉6红首发;核心_基础V3 → 涨停;MACD 全数值 → None)。
    partial=true 时 spec 附 "partial_warning": True。
    """
    reg = load_registry()
    entry = reg.get(name)
    if not isinstance(entry, dict):
        return None
    col = _pick_output(name, entry)
    if col is None:
        return None
    spec = {
        "name": name,
        "join": "AND",
        "conds": [{"col": col, "op": ">", "value": 0}],
    }
    if entry.get("partial"):
        spec["partial_warning"] = True
    return spec


def guard_partial(entry):
    """partial 注册条目的使用守卫(供调用方在生成回测配置前显式调用)。

    - partial=true 且 outputs 为空 → RuntimeError(无任何成功输出,
      不能产出可回测 spec);
    - partial=true 且 outputs 非空 → 打印 stderr 并返回 unsupported 警告
      清单(每行「行 {line} {name}: [{category}] {reason}」,与 registry
      的错误打印口径一致),调用方可据此判断输出完整性;
    - partial=false → None(无操作)。
    """
    entry = entry if isinstance(entry, dict) else {}
    if not entry.get("partial"):
        return None
    outputs = entry.get("outputs") or []
    unsupported = entry.get("unsupported") or []
    if not outputs:
        raise RuntimeError(
            f"partial 注册条目无任何成功输出(unsupported "
            f"{len(unsupported)} 条),不能产出回测 spec")
    warnings = [
        f"行 {e.get('line', '?')} {e.get('name', '?')}: "
        f"[{e.get('category', '?')}] {e.get('reason', '')}"
        for e in unsupported if isinstance(e, dict)
    ]
    for w in warnings:
        print(f"[bridge] partial 指标警告: {w}", file=sys.stderr)
    return warnings
