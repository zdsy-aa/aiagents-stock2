# backtest/combo_engine.py
"""组合规格求值引擎。

ComboSpec = {"name": str, "conds": [{"col": str, "op": ">", "value": float}],
             "join": "AND" | "OR"}

- eval_combo(spec, df) -> pd.Series(bool):
    * unavailable spec(conds 置空 + "unavailable": true)返回全 False Series,
      与对齐测试的跳过逻辑配合(控制器裁决)。
    * 列不存在抛 KeyError 且消息含列名;op 支持 >/>=/</<=/==;
      数值列 to_numeric(errors="coerce").fillna(0)。
    * conds 为空且未标 unavailable 的退化 spec:AND 返回全 True(单位元),
      OR 返回全 False(单位元)。
"""
import operator

import pandas as pd

_OPS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
}


def eval_combo(spec, df):
    """按 spec 在 df 上求值,返回 bool Series(索引与 df 对齐)。"""
    if spec.get("unavailable"):
        return pd.Series(False, index=df.index, dtype=bool)
    conds = spec.get("conds") or []
    join = spec.get("join", "AND")
    if not conds:
        # 退化 spec(非 unavailable):按连接单位元返回
        return pd.Series(join == "AND", index=df.index, dtype=bool)
    masks = []
    for c in conds:
        col = c["col"]
        if col not in df.columns:
            raise KeyError(f"面板缺列: {col}")
        op = c.get("op", ">")
        if op not in _OPS:
            raise ValueError(f"不支持的 op: {op}(spec {spec.get('name')!r})")
        s = pd.to_numeric(df[col], errors="coerce").fillna(0)
        masks.append(_OPS[op](s, c["value"]))
    if join == "AND":
        out = masks[0]
        for m in masks[1:]:
            out = out & m
    elif join == "OR":
        out = masks[0]
        for m in masks[1:]:
            out = out | m
    else:
        raise ValueError(f"不支持的 join: {join}(spec {spec.get('name')!r})")
    return out.astype(bool)


# build_57_specs 定义在 signal_specs.py(简报文件划分:combo_engine 引擎 /
# signal_specs 规格),此处 re-export 供 Task 3.2 对齐测试
# `from backtest.combo_engine import build_57_specs, eval_combo` 的导入路径。
from backtest.signal_specs import build_57_specs  # noqa: E402

__all__ = ["eval_combo", "build_57_specs"]
