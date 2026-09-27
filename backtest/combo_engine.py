# backtest/combo_engine.py
"""组合规格求值引擎。

ComboSpec = {"name": str, "conds": [条件元素], "join": "AND" | "OR"}
条件元素 = {"col": str, "op": ">", "value": float}
          | {"or_group": [条件元素, ...]}(嵌套 OR 组,可递归嵌套)
顶层 join 决定 conds 各元素(含 or_group)之间的组合方式;or_group 内部恒为 OR。

- eval_combo(spec, df) -> pd.Series(bool):
    * unavailable spec(conds 置空 + "unavailable": true)返回全 False Series,
      与对齐测试的跳过逻辑配合(控制器裁决)。
    * 列不存在抛 KeyError 且消息含列名(嵌套 or_group 内的列同样校验);
      op 支持 >/>=/</<=/==;数值列 to_numeric(errors="coerce").fillna(0)。
    * conds 为空且未标 unavailable 的退化 spec:AND 返回全 True(单位元),
      OR 返回全 False(单位元);空 or_group 返回全 False(OR 单位元)。
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


def _eval_cond(c, df, spec):
    """单个条件元素求值:普通条件或嵌套 or_group(组内 OR,递归)。"""
    if "or_group" in c:
        subs = c["or_group"]
        if not subs:
            return pd.Series(False, index=df.index, dtype=bool)
        m = _eval_cond(subs[0], df, spec)
        for s in subs[1:]:
            m = m | _eval_cond(s, df, spec)
        return m
    col = c["col"]
    if col not in df.columns:
        raise KeyError(f"面板缺列: {col}")
    op = c.get("op", ">")
    if op not in _OPS:
        raise ValueError(f"不支持的 op: {op}(spec {spec.get('name')!r})")
    s = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return _OPS[op](s, c["value"])


def eval_combo(spec, df):
    """按 spec 在 df 上求值,返回 bool Series(索引与 df 对齐)。"""
    if spec.get("unavailable"):
        return pd.Series(False, index=df.index, dtype=bool)
    conds = spec.get("conds") or []
    join = spec.get("join", "AND")
    if not conds:
        # 退化 spec(非 unavailable):按连接单位元返回
        return pd.Series(join == "AND", index=df.index, dtype=bool)
    masks = [_eval_cond(c, df, spec) for c in conds]
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
