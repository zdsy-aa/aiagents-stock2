"""Task 2.2 内置函数映射与求值器:逐函数对拍单测(简报 Step 1 用例逐字 + 补充对拍)。

补充对拍分两类:
1. 各内置函数与 pandas 直接实现(rolling/ewm/shift)或手算期望对拍;
2. 动态参数形态(语料实际存在:MA(VOL,VL)、REF(CH_,距顶+1) 等窗口/位移为
   Series 的调用)与手算逐 bar 期望对拍。

BARSLAST 与参考实现 tq_confirm_top10._barslast 逐行同算法:注意其语义为
"距最近一次条件为真的 bar 数",首次为真的 bar 处仍为 9999(从未为真),第二次
为真起才是距离(与参考实现一致,见 test_barslast_known 期望值)。
"""
import numpy as np
import pandas as pd
import pytest

from indicators.evaluator import build_env, evaluate_ast
from indicators.tdx_builtins import BUILTINS
from indicators.tdx_parser import parse_formula


def _df(n=120):
    # 注:简报原样 helper 的 Series 未带 index,在 pandas 3.0.6 下
    # pd.DataFrame({...}, index=DatetimeIndex) 会按 index 对齐导致整表 NaN;
    # 此处为保持简报意图(种子随机游走 OHLCV + 交易日索引)给 Series 补上
    # 相同 index(根因见 task-2.2-report.md)。
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2026-01-01", periods=n)
    c = pd.Series(10 + np.cumsum(rng.normal(0, 0.3, n)), index=idx)
    return pd.DataFrame(
        {
            "Open": c.shift(1).fillna(c.iloc[0]),
            "High": c + 0.3,
            "Low": c - 0.3,
            "Close": c,
            "Volume": pd.Series(rng.integers(1000, 2000, n), dtype=float, index=idx),
        },
        index=idx,
    )


# ---------- 简报 Step 1 用例(逐字) ----------

def test_ma_ema_ref():
    df = _df()
    env = build_env(df)
    ma5 = evaluate_ast({"op": "call", "func": "MA", "args": [{"op": "var", "name": "CLOSE"}, {"op": "num", "val": 5}]}, env)
    assert np.allclose(ma5.iloc[-1], df["Close"].iloc[-5:].mean())
    assert np.allclose(ma5.iloc[:4].isna(), [True] * 4)
    ref1 = evaluate_ast({"op": "call", "func": "REF", "args": [{"op": "var", "name": "CLOSE"}, {"op": "num", "val": 1}]}, env)
    assert np.allclose(ref1.iloc[1:], df["Close"].iloc[:-1])


def test_ternary_if_and_cross():
    df = _df()
    env = build_env(df)
    ast = {"op": "ternary", "cond": {"op": "bin", "oper": ">", "left": {"op": "var", "name": "CLOSE"},
           "right": {"op": "var", "name": "OPEN"}},
           "then": {"op": "num", "val": 1}, "else": {"op": "num", "val": 0}}
    r = evaluate_ast(ast, env)
    assert set(r.unique()) <= {0.0, 1.0}
    cross = evaluate_ast({"op": "call", "func": "CROSS", "args": [
        {"op": "call", "func": "MA", "args": [{"op": "var", "name": "CLOSE"}, {"op": "num", "val": 5}]},
        {"op": "call", "func": "MA", "args": [{"op": "var", "name": "CLOSE"}, {"op": "num", "val": 10}]}]}, env)
    assert cross.sum() >= 0


# ---------- 补充:映射表完整性 ----------

def test_builtins_table_complete():
    for fn in ["REF", "MA", "EMA", "SMA", "STD", "HHV", "LLV", "SUM", "COUNT", "ABS",
               "MAX", "MIN", "INTPART", "CROSS", "BARSLAST", "BARSCOUNT", "EVERY", "EXIST"]:
        assert fn in BUILTINS, fn


# ---------- 补充:逐函数与 pandas 直接实现对拍 ----------

def test_ma_ema_sma_std_against_pandas():
    df = _df()
    env = build_env(df)
    c = df["Close"]

    def call(fn, *args):
        return evaluate_ast({"op": "call", "func": fn, "args": [
            {"op": "var", "name": args[0]}, {"op": "num", "val": args[1]},
        ]}, env)

    ma5 = call("MA", "CLOSE", 5)
    assert np.allclose(ma5, c.rolling(5, min_periods=5).mean(), equal_nan=True)
    ema8 = call("EMA", "CLOSE", 8)
    assert np.allclose(ema8, c.ewm(span=8, adjust=False).mean())
    sma5 = call("SMA", "CLOSE", 5)
    assert np.allclose(sma5, c.ewm(alpha=1 / 5, adjust=False).mean())
    std10 = call("STD", "CLOSE", 10)
    assert np.allclose(std10, c.rolling(10, min_periods=10).std(), equal_nan=True)


def test_hhv_llv_sum_count_against_pandas():
    df = _df()
    env = build_env(df)
    c = df["Close"]

    def call(fn, *argvals):
        return evaluate_ast({"op": "call", "func": fn, "args": [
            {"op": "var", "name": argvals[0]}, {"op": "num", "val": argvals[1]},
        ]}, env)

    hhv5 = call("HHV", "HIGH", 5)
    assert np.allclose(hhv5, df["High"].rolling(5, min_periods=1).max())
    llv5 = call("LLV", "LOW", 5)
    assert np.allclose(llv5, df["Low"].rolling(5, min_periods=1).min())
    sum10 = call("SUM", "VOL", 10)
    assert np.allclose(sum10, df["Volume"].rolling(10, min_periods=1).sum())
    # COUNT(条件,10):先算出条件再按 COUNT 语义对拍
    cond_ast = {"op": "bin", "oper": ">", "left": {"op": "var", "name": "CLOSE"},
                "right": {"op": "call", "func": "REF",
                          "args": [{"op": "var", "name": "CLOSE"}, {"op": "num", "val": 1}]}}
    cnt = evaluate_ast({"op": "call", "func": "COUNT", "args": [cond_ast, {"op": "num", "val": 10}]}, env)
    expect = (c > c.shift(1)).astype(float).rolling(10, min_periods=1).sum()
    assert np.allclose(cnt, expect, equal_nan=True)


def test_abs_max_min_intpart():
    x = pd.Series([-3.0, 2.5, -1.5])
    env = {"X": x}
    r = evaluate_ast({"op": "call", "func": "ABS", "args": [{"op": "var", "name": "X"}]}, env)
    assert np.allclose(r, [3.0, 2.5, 1.5])
    r = evaluate_ast({"op": "call", "func": "MAX", "args": [{"op": "var", "name": "X"}, {"op": "num", "val": 1}]}, env)
    assert np.allclose(r, np.maximum(x, 1.0))
    r = evaluate_ast({"op": "call", "func": "MIN", "args": [{"op": "var", "name": "X"}, {"op": "num", "val": 1}]}, env)
    assert np.allclose(r, np.minimum(x, 1.0))
    r = evaluate_ast({"op": "call", "func": "INTPART", "args": [{"op": "var", "name": "X"}]}, env)
    assert np.allclose(r, np.floor(x))
    # 标量形态
    assert evaluate_ast({"op": "call", "func": "INTPART", "args": [{"op": "num", "val": 2.7}]}, env) == 2.0
    assert evaluate_ast({"op": "call", "func": "MAX", "args": [{"op": "num", "val": 3}, {"op": "num", "val": 5}]}, env) == 5.0


def test_cross_known_values():
    a = pd.Series([1.0, 2.0, 1.0, 3.0])
    b = pd.Series([1.5, 1.5, 2.0, 2.0])
    env = {"A": a, "B": b}
    r = evaluate_ast({"op": "call", "func": "CROSS", "args": [
        {"op": "var", "name": "A"}, {"op": "var", "name": "B"}]}, env)
    assert r.tolist() == [False, True, False, True]
    # b 为标量(参考实现口径:b 标量时按同索引 Series 广播)
    r2 = evaluate_ast({"op": "call", "func": "CROSS", "args": [
        {"op": "var", "name": "A"}, {"op": "num", "val": 2}]}, env)
    assert r2.tolist() == [False, False, False, True]


def test_barslast_known_values():
    # 与 tq_confirm_top10._barslast 同算法:首次为真处仍为 9999(该 bar 之前从未为真)
    cond = pd.Series([False, True, False, False, True, False])
    env = {"C0": cond}
    r = evaluate_ast({"op": "call", "func": "BARSLAST", "args": [{"op": "var", "name": "C0"}]}, env)
    assert r.tolist() == [9999.0, 9999.0, 1.0, 2.0, 3.0, 1.0]
    # NaN 视为 False(参考实现口径)
    cond2 = pd.Series([np.nan, True, False])
    r2 = evaluate_ast({"op": "call", "func": "BARSLAST", "args": [{"op": "var", "name": "C1"}]}, {"C1": cond2})
    assert r2.tolist() == [9999.0, 9999.0, 1.0]


def test_barscount_since_listing():
    # 通达信语义:BARSCOUNT(X) = X 的有效数据周期数(自上市起)。语料 5 处均为
    # BARSCOUNT(C)>250(上市满 250 根K线),与 notna().cumsum() 口径一致。
    x = pd.Series([1.0, np.nan, 2.0])
    r = evaluate_ast({"op": "call", "func": "BARSCOUNT", "args": [{"op": "var", "name": "X"}]}, {"X": x})
    assert r.tolist() == [1, 1, 2]
    env = build_env(_df(10))
    r2 = evaluate_ast({"op": "call", "func": "BARSCOUNT", "args": [{"op": "var", "name": "CLOSE"}]}, env)
    assert r2.tolist() == list(range(1, 11))


def test_every_exist():
    c = pd.Series([True, True, False, True, True])
    env = {"C0": c}
    every = evaluate_ast({"op": "call", "func": "EVERY", "args": [{"op": "var", "name": "C0"}, {"op": "num", "val": 2}]}, env)
    assert every.tolist()[0] != every.tolist()[0]  # 首值 NaN(窗口未满)
    assert every.tolist()[1:] == [1.0, 0.0, 0.0, 1.0]
    exist = evaluate_ast({"op": "call", "func": "EXIST", "args": [{"op": "var", "name": "C0"}, {"op": "num", "val": 3}]}, env)
    assert exist.tolist() == [1.0, 1.0, 1.0, 1.0, 1.0]


# ---------- 补充:动态参数(语料实际形态)对拍 ----------

def test_dynamic_ma_window():
    # 语料:VL:=MAX(INTPART(20*适应系数),10); 量缩显著:=VOL<MA(VOL,VL)*0.8;
    # 逐 bar 窗口语义:bar i 用 x[i-w+1..i](w 为当 bar 的窗口值)
    x = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    n = pd.Series([1, 2, 2, 4, 3], dtype=float)
    r = evaluate_ast({"op": "call", "func": "MA", "args": [
        {"op": "var", "name": "X"}, {"op": "var", "name": "N"}]}, {"X": x, "N": n})
    assert r.tolist() == [1.0, 1.5, 2.5, 2.5, 4.0]
    # 窗口含 NaN 的 bar 结果为 NaN(与 rolling(min_periods=w) 口径一致)
    x2 = pd.Series([np.nan, 2.0, 3.0])
    n2 = pd.Series([2, 2, 2], dtype=float)
    r2 = evaluate_ast({"op": "call", "func": "MA", "args": [
        {"op": "var", "name": "X"}, {"op": "var", "name": "N"}]}, {"X": x2, "N": n2})
    assert np.isnan(r2.iloc[0]) and np.isnan(r2.iloc[1])
    assert r2.iloc[2] == 2.5


def test_dynamic_ref_shift():
    # 语料:CL_GG1:=REF(CH_,距顶+1); 逐 bar 位移语义:bar i 取 x[i-n[i]]
    x = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])
    n = pd.Series([1, 1, 2, 2, 3], dtype=float)
    r = evaluate_ast({"op": "call", "func": "REF", "args": [
        {"op": "var", "name": "X"}, {"op": "var", "name": "N"}]}, {"X": x, "N": n})
    assert np.isnan(r.iloc[0])
    assert r.iloc[1:].tolist() == [10.0, 10.0, 20.0, 20.0]


# ---------- 补充:build_env / CODELIKE / AST 节点 / 错误路径 ----------

def test_build_env_columns_aliases_amount_tr():
    df = _df(6)
    env = build_env(df)
    assert env["CLOSE"] is env["C"] and env["CLOSE"].equals(df["Close"])
    assert env["OPEN"] is env["O"] and env["HIGH"] is env["H"]
    assert env["LOW"] is env["L"] and env["VOL"] is env["V"]
    assert env["VOL"].equals(df["Volume"])
    assert np.allclose(env["AMOUNT"], df["Volume"] * df["Close"] / 100.0)
    c, h, l = df["Close"], df["High"], df["Low"]
    tr_expect = np.maximum.reduce([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()])
    assert np.allclose(env["TR"], tr_expect, equal_nan=True)


def test_codelike_compile_time():
    src = "涨停幅度:=IF(CODELIKE('3') OR CODELIKE('68'),0.2,0.1);"
    st = parse_formula(src)["statements"][0]
    assert evaluate_ast(st["expr"], {}, code_prefix="300001") == 0.2
    assert evaluate_ast(st["expr"], {}, code_prefix="688001") == 0.2
    assert evaluate_ast(st["expr"], {}, code_prefix="600000") == 0.1
    assert evaluate_ast(st["expr"], {}) == 0.1  # 默认沪深主板


def test_not_neg_str_nodes():
    env = {"X": pd.Series([True, False])}
    r = evaluate_ast({"op": "not", "expr": {"op": "var", "name": "X"}}, env)
    assert r.tolist() == [False, True]
    r = evaluate_ast({"op": "neg", "expr": {"op": "var", "name": "Y"}}, {"Y": pd.Series([1.0, -2.0])})
    assert r.tolist() == [-1.0, 2.0]
    assert evaluate_ast({"op": "str", "val": "abc"}, {}) == "abc"
    assert evaluate_ast({"op": "num", "val": 1.5}, {}) == 1.5
    # 含 NaN 的一元非:NaN 视为 False(TDX 布尔上下文口径)
    r3 = evaluate_ast({"op": "not", "expr": {"op": "var", "name": "Z"}}, {"Z": pd.Series([np.nan, 0.0, 1.0])})
    assert r3.tolist() == [True, True, False]


def test_bin_operators_and_logic():
    env = {"X": pd.Series([1.0, 2.0, 3.0]), "Y": pd.Series([2.0, 2.0, 2.0])}

    def b(op, l, r):
        return evaluate_ast({"op": "bin", "oper": op, "left": l, "right": r}, env)

    assert b("+", {"op": "var", "name": "X"}, {"op": "var", "name": "Y"}).tolist() == [3.0, 4.0, 5.0]
    assert b("-", {"op": "var", "name": "X"}, {"op": "num", "val": 1}).tolist() == [0.0, 1.0, 2.0]
    assert b("*", {"op": "var", "name": "X"}, {"op": "num", "val": 2}).tolist() == [2.0, 4.0, 6.0]
    assert b("/", {"op": "var", "name": "X"}, {"op": "num", "val": 2}).tolist() == [0.5, 1.0, 1.5]
    assert b(">", {"op": "var", "name": "X"}, {"op": "var", "name": "Y"}).tolist() == [False, False, True]
    assert b("=", {"op": "var", "name": "Y"}, {"op": "num", "val": 2}).tolist() == [True, True, True]
    assert b("<>", {"op": "var", "name": "Y"}, {"op": "num", "val": 2}).tolist() == [False, False, False]
    assert b("AND", {"op": "var", "name": "X"}, {"op": "num", "val": 1}).tolist() == [True, True, True]
    assert b("OR", {"op": "num", "val": 0}, {"op": "num", "val": 1}) is True
    assert b("AND", {"op": "num", "val": 0}, {"op": "num", "val": 1}) is False
    # 字符串拼接(防御性;语料求值语句内无字符串运算,仅在绘图语句中)
    assert b("+", {"op": "str", "val": "a"}, {"op": "str", "val": "b"}) == "ab"


def test_ternary_scalar_cond_and_nan_cond():
    env = {"X": pd.Series([1.0, 2.0, 3.0])}
    ast = {"op": "ternary", "cond": {"op": "num", "val": 1},
           "then": {"op": "num", "val": 7}, "else": {"op": "num", "val": 8}}
    assert evaluate_ast(ast, env) == 7
    # NaN 条件视为 False(pandas astype(bool) 会把 NaN 当 True,必须 fillna 兜底)
    cond = pd.Series([np.nan, 2.0, 0.0])
    ast2 = {"op": "ternary", "cond": {"op": "var", "name": "C0"},
            "then": {"op": "var", "name": "X"}, "else": {"op": "num", "val": 0}}
    r = evaluate_ast(ast2, {"X": env["X"], "C0": cond})
    assert r.tolist() == [0.0, 2.0, 0.0]


def test_ternary_lazy_scalar_cond():
    # 控制器审查修复:标量条件惰性求值(简报「惰性求值由 AST 层处理」)——
    # 未选中的分支完全不求值,引用未定义变量/未登记函数不抛错。
    ast = {"op": "ternary", "cond": {"op": "num", "val": 0},
           "then": {"op": "var", "name": "未定义变量"},
           "else": {"op": "num", "val": 1}}
    assert evaluate_ast(ast, {}) == 1
    ast2 = {"op": "ternary", "cond": {"op": "num", "val": 1},
            "then": {"op": "num", "val": 7},
            "else": {"op": "call", "func": "WINNER",
                     "args": [{"op": "var", "name": "CLOSE"}]}}
    assert evaluate_ast(ast2, {}) == 7
    # 与解析器特化联动:IF(0, 未定义变量, 2) 全链路
    st = parse_formula("X:IF(0,未定义变量,2);")["statements"][0]
    assert evaluate_ast(st["expr"], {}) == 2


def test_ternary_series_cond_evaluates_both_branches():
    # Series 条件:向量化 np.where 语义,两分支均会求值(与通达信向量化语义
    # 一致)——未选中分支的未定义变量同样抛 NameError,行为钉住。
    cond = pd.Series([True, False])
    ast = {"op": "ternary", "cond": {"op": "var", "name": "C0"},
           "then": {"op": "num", "val": 1},
           "else": {"op": "var", "name": "未定义变量"}}
    with pytest.raises(NameError):
        evaluate_ast(ast, {"C0": cond})
    # 两分支均可求值时按 cond 逐位选择(回归)
    r = evaluate_ast({"op": "ternary", "cond": {"op": "var", "name": "C0"},
                      "then": {"op": "num", "val": 1}, "else": {"op": "num", "val": 2}},
                     {"C0": cond})
    assert r.tolist() == [1.0, 2.0]


def test_missing_function_raises_not_implemented():
    with pytest.raises(NotImplementedError, match="WINNER"):
        evaluate_ast({"op": "call", "func": "WINNER", "args": [{"op": "var", "name": "CLOSE"}]}, build_env(_df()))
    with pytest.raises(NotImplementedError, match="DMA"):
        evaluate_ast({"op": "call", "func": "DMA", "args": [{"op": "var", "name": "CLOSE"}, {"op": "num", "val": 1}]}, build_env(_df()))


def test_missing_var_raises_name_error():
    with pytest.raises(NameError):
        evaluate_ast({"op": "var", "name": "不存在的变量"}, {})


def test_alias_fallback_and_drawnull():
    s = pd.Series([1.0, 2.0])
    assert evaluate_ast({"op": "var", "name": "C"}, {"CLOSE": s}) is s
    assert np.isnan(evaluate_ast({"op": "var", "name": "DRAWNULL"}, {}))
