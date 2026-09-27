"""Task 2.2 参考对齐(Phase 2 验收核心):六脉神剑V5 公式经 parse_formula →
evaluate_ast 逐语句求值,与参考实现 /home/tdxback/通达信py脚本/tq_confirm_top10.py
的指标原语(_EMA/_SMA/_MA/_REF/_HHV/_LLV)对拍,atol=1e-6 全绿。

参考口径说明(控制器裁决):
1. tq_confirm_top10 模块顶部 `from tqcenter import tq` + `tq.initialize(__file__)`,
   而 tqcenter 会 ctypes.CDLL('TPythClient.dll') —— Linux 宿主必然 OSError。
   测试在 importlib 加载前向 sys.modules 注入假 tqcenter 模块(测试基础设施,
   非实现 cheat;tq_confirm_top10 模块级只调 tq.initialize,其余 tq.* 均位于
   main() 等函数内,导入期不触发,假模块按需补齐属性)。
2. compute_chanlun_liumai() 返回 {"组合11": bool, "缠论买点4日": bool,
   "六红4日": bool},不返回中间量。按控制器裁决,中间量参考值在测试中用参考
   模块自身原语按六脉神剑V5 公式独立重算 —— 原语即参考口径。
3. 常数口径:语料公式分母保护常数为 +0.0001,参考移植为 +1e-9(移植时改写
   的保护常数)。忠实求值必须复现公式自身的 0.0001,故参考重算按公式常数;
   两者差异量级约 1e-4 相对值(RSI/LWR/MTM 上约 0.01~0.05 绝对值,远超
   atol=1e-6),属"公式与移植版常数差异"而非求值器 bug(根因见报告)。

pairs 为简报逐字清单(九个中间量)+ LM_K/LM_D 补充对拍。
另做端到端对拍:六脉红灯序列与参考重算红灯完全一致(逐位相等),六红 4 日
窗口最新值 == compute_chanlun_liumai(df)["六红4日"]。
"""
import importlib.util
import sys
import types

import numpy as np
import pandas as pd

from indicators.evaluator import build_env, evaluate_ast
from indicators.tdx_parser import parse_formula

TQ_PATH = "/home/tdxback/通达信py脚本/tq_confirm_top10.py"
FORMULA_PATH = ("/home/tdxback/通达信指标/20260424001/tdx_v4_standalone/"
                "03_资金流向体系/六脉神剑V5.txt")

_REF = None


def _load_tq():
    """加载参考脚本(先注入假 tqcenter,见模块 docstring 第 1 条)。"""
    global _REF
    if _REF is not None:
        return _REF
    if "tqcenter" not in sys.modules:
        fake = types.ModuleType("tqcenter")
        fake.tq = types.SimpleNamespace(
            initialize=lambda *a, **k: None,
            close=lambda: None,
            get_market_data=lambda *a, **k: None,
            send_message=lambda *a, **k: None,
            get_stock_list=lambda *a, **k: [],
            get_user_sector=lambda *a, **k: "",
            create_sector=lambda *a, **k: None,
            send_user_block=lambda *a, **k: None,
        )
        sys.modules["tqcenter"] = fake
    spec = importlib.util.spec_from_file_location("tq_confirm_top10", TQ_PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    _REF = m
    return m


def _df(n=400):
    # 同 test_tdx_builtins._df:Series 必须带相同 index,否则 pandas 3.0.6 的
    # DataFrame(dict, index=...) 对齐会使整表 NaN(简报原样 helper 的坑)。
    rng = np.random.default_rng(42)
    idx = pd.bdate_range("2024-01-01", periods=n)
    c = pd.Series(20 + np.cumsum(rng.normal(0, 0.25, n)), index=idx)
    return pd.DataFrame(
        {"Open": c - 0.1, "High": c + 0.4, "Low": c - 0.4,
         "Close": c, "Volume": pd.Series(rng.integers(800, 2500, n), dtype=float, index=idx)},
        index=idx)


def _reference_intermediates(tq, df):
    """用参考模块原语按六脉神剑V5 公式重算中间量(参考口径,见模块 docstring)。"""
    c = df["Close"].astype(float)
    h = df["High"].astype(float)
    l = df["Low"].astype(float)
    lc = tq._REF(c, 1)  # 昨收
    LM_DIFF = tq._EMA(c, 8) - tq._EMA(c, 13)
    LM_DEA = tq._EMA(LM_DIFF, 5)
    LM_RSV = (c - tq._LLV(l, 8)) / (tq._HHV(h, 8) - tq._LLV(l, 8) + 0.0001) * 100
    LM_K = tq._SMA(LM_RSV, 3, 1)
    LM_D = tq._SMA(LM_K, 3, 1)
    RSI短 = tq._SMA((c - lc).clip(lower=0), 5, 1) / (tq._SMA((c - lc).abs(), 5, 1) + 0.0001) * 100
    RSI长 = tq._SMA((c - lc).clip(lower=0), 13, 1) / (tq._SMA((c - lc).abs(), 13, 1) + 0.0001) * 100
    LWR原 = (-(tq._HHV(h, 13) - c)) / (tq._HHV(h, 13) - tq._LLV(l, 13) + 0.0001) * 100
    LWR_K = tq._SMA(LWR原, 3, 1)
    LWR_D = tq._SMA(LWR_K, 3, 1)
    BBI = (tq._MA(c, 3) + tq._MA(c, 6) + tq._MA(c, 12) + tq._MA(c, 24)) / 4
    MTM_S = 100 * tq._EMA(tq._EMA(c - lc, 5), 3) / (tq._EMA(tq._EMA((c - lc).abs(), 5), 3) + 0.0001)
    MTM_L = 100 * tq._EMA(tq._EMA(c - lc, 13), 8) / (tq._EMA(tq._EMA((c - lc).abs(), 13), 8) + 0.0001)
    return {"LM_DIFF": LM_DIFF, "LM_DEA": LM_DEA, "LM_K": LM_K, "LM_D": LM_D,
            "RSI短": RSI短, "RSI长": RSI长, "LWR_K": LWR_K, "LWR_D": LWR_D,
            "BBI": BBI, "MTM_S": MTM_S, "MTM_L": MTM_L}


def _evaluate_formula(env):
    src = open(FORMULA_PATH, encoding="utf-8", errors="ignore").read()
    for st in parse_formula(src)["statements"]:
        env[st["name"]] = evaluate_ast(st["expr"], env)
    return env


def test_liumai_v5_formula_aligns_with_reference():
    df = _df()
    env = _evaluate_formula(build_env(df))
    tq = _load_tq()
    ref = _reference_intermediates(tq, df)
    # 简报逐字:九个中间量对拍(LM_DIFF/LM_DEA/LWR_K/LWR_D/BBI/MTM_S/MTM_L/
    # RSI短/RSI长),最近 100 根,atol=1e-6
    pairs = [("LM_DIFF", "LM_DIFF"), ("LM_DEA", "LM_DEA"), ("LWR_K", "LWR_K"),
             ("LWR_D", "LWR_D"), ("BBI", "BBI"), ("MTM_S", "MTM_S"),
             ("MTM_L", "MTM_L"), ("RSI短", "RSI短"), ("RSI长", "RSI长")]
    for ours, theirs in pairs:
        a = env.get(ours)
        b = ref.get(theirs, None)
        assert a is not None and b is not None, ours
        assert np.allclose(a.iloc[-100:].astype(float), b.iloc[-100:].astype(float),
                           atol=1e-6), f"{ours} 与参考实现不一致"
    # 补充对拍:KDJ 中间量(LM_K/LM_D)
    for ours, theirs in [("LM_K", "LM_K"), ("LM_D", "LM_D")]:
        a = env.get(ours)
        b = ref.get(theirs)
        assert np.allclose(a.iloc[-100:].astype(float), b.iloc[-100:].astype(float),
                           atol=1e-6), f"{ours} 与参考实现不一致"


def test_liumai_six_red_aligns_with_reference():
    """端到端:六脉红灯序列与参考重算红灯逐位一致;六红 4 日窗口最新值
    与 compute_chanlun_liumai(df)["六红4日"] 一致。"""
    df = _df()
    env = _evaluate_formula(build_env(df))
    tq = _load_tq()
    ref = _reference_intermediates(tq, df)
    c = df["Close"].astype(float)
    ref红灯 = ((ref["LM_DIFF"] > ref["LM_DEA"]).astype(int)
               + (ref["LM_K"] > ref["LM_D"]).astype(int)
               + (ref["RSI短"] > ref["RSI长"]).astype(int)
               + (ref["LWR_K"] > ref["LWR_D"]).astype(int)
               + (c > ref["BBI"]).astype(int)
               + (ref["MTM_S"] > ref["MTM_L"]).astype(int))
    ours红灯 = env["六脉红灯"]
    assert np.array_equal((ours红灯 >= 6).to_numpy(), (ref红灯 >= 6).to_numpy())
    ref窗六红 = (ref红灯 >= 6).astype(float).rolling(4, min_periods=1).max() >= 1
    c11 = tq.compute_chanlun_liumai(df)
    assert set(c11) == {"组合11", "缠论买点4日", "六红4日"}
    assert all(isinstance(v, (bool, np.bool_)) for v in c11.values())
    assert bool(c11["六红4日"]) == bool(ref窗六红.iloc[-1])
