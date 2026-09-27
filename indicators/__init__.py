"""指标转换流水线包:parse -> evaluate -> register -> smoke -> docs。

对外接口:
  compute(name, df, code_prefix="") -> {输出名: pd.Series}
      registry.json 查条目 → source 定位公式文本(带 parse 缓存)→ build_env
      逐语句求值;未知名称抛 KeyError;失败语句跳过(与 compile 的部分注册
      口径一致,unsupported 输出不可得)。
  load_registry() / load_alias_rules() / BUILTIN_FORMULAS(内置公式文本)
"""
import pathlib

import numpy as np
import pandas as pd

from .evaluator import build_env, evaluate_ast
from .registry import load_registry
from .tdx_parser import parse_formula

__all__ = ["compute", "load_registry", "load_alias_rules", "BUILTIN_FORMULAS"]


# ---------------------------------------------------------------------------
# 内置标准公式文本(公式库无对应文件时的兜底来源)
# ---------------------------------------------------------------------------

BUILTIN_FORMULAS = {
    # 来源:通达信标准 MACD 定义(常量 12/26/9)。
    # 公式库(/home/tdxback/通达信指标/)无标准 MACD 公式文件(仅 MACD背驰V8
    # 等派生公式),故内置作为 add_new.txt 首例来源(控制器裁决)。
    "MACD": (
        "{通达信标准 MACD 定义(12/26/9),来源:通达信软件 MACD 指标模板}\n"
        "DIFF:EMA(CLOSE,12)-EMA(CLOSE,26);\n"
        "DEA:EMA(DIFF,9);\n"
        "MACD:(DIFF-DEA)*2,COLORSTICK;\n"
    ),
}

# parse 缓存:注册表 source(文件路径或 "builtin:名")+ mtime_ns → parse_formula
# 结果(别每次重解析;文件 mtime 变化自动失效)。
_PARSE_CACHE = {}


def _source_text(entry):
    """registry 条目 → (source_key, 公式文本, mtime_ns|None)。"""
    source = entry.get("source")
    if not source:
        raise KeyError(f"registry 条目缺少 source 字段: {entry}")
    if source.startswith("builtin:"):
        bname = source.split(":", 1)[1]
        if bname not in BUILTIN_FORMULAS:
            raise KeyError(f"内置公式 {bname!r} 不在 BUILTIN_FORMULAS 中")
        return source, BUILTIN_FORMULAS[bname], None
    p = pathlib.Path(source)
    if not p.exists():
        raise FileNotFoundError(f"registry source 文件不存在: {source}")
    return source, p.read_text(encoding="utf-8", errors="ignore"), p.stat().st_mtime_ns


def compute(name, df, code_prefix=""):
    """按已注册指标求值:registry 查 source → parse(带缓存)→ env 求值。

    返回 {输出名: pd.Series}(成功求值的 output 语句;标量输出广播为同索引
    常值 Series;失败语句跳过,口径与 compile_indicator 的部分注册一致——
    partial 指标的 unsupported 输出不在此列);未知名称抛 KeyError。
    """
    reg = load_registry()
    if name not in reg:
        raise KeyError(f"指标 {name!r} 未注册(registry.json 无此名;先运行 "
                       f"scripts/indicator_pipeline.py run {name})")
    source, text, mtime = _source_text(reg[name])
    cache_key = (source, mtime)
    if cache_key not in _PARSE_CACHE:
        _PARSE_CACHE[cache_key] = parse_formula(text)
    env = build_env(df)
    idx = env["CLOSE"].index
    outputs = {}
    for st in _PARSE_CACHE[cache_key]["statements"]:
        try:
            env[st["name"]] = evaluate_ast(st["expr"], env,
                                           code_prefix=code_prefix)
        except Exception:
            # 与 compile 隔离求值口径一致:失败语句(未登记函数/未定义变量)
            # 跳过,不中断其余输出。
            continue
        if st["kind"] == "output":
            v = env[st["name"]]
            if not isinstance(v, pd.Series):
                v = pd.Series(np.full(len(idx), v), index=idx)
            outputs[st["name"]] = v
    return outputs


def load_alias_rules():
    import json
    return json.loads((pathlib.Path(__file__).parent / "alias_rules.json")
                      .read_text(encoding="utf-8"))
