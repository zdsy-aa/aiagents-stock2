"""AST → pandas Series/标量 求值器(消费 Task 2.1 parse_formula 的 AST)。

AST 节点:num/str/var/call/bin/ternary/not/neg(见 tdx_parser 模块头)。

接口:
  evaluate_ast(ast, env, code_prefix="600000") -> float|str|bool|pd.Series
      env:变量名 → pd.Series|float|str|bool 的字典(语句逐条写回);
      变量查找先 env,后列别名(C→CLOSE 等,见 tdx_builtins.COLUMN_ALIASES);
      DRAWNULL 解析为 NaN(无效值);
      code_prefix:证券代码前缀(CODELIKE 编译期求值用,如 '300001'/'688001'/
      '600000'),默认沪深主板 '600000'(涨停幅度=0.1)。
  build_env(df) -> dict
      注入 CLOSE/OPEN/HIGH/LOW/VOL 与别名 C/O/H/L/V、TR 列、AMOUNT=V*C/100
      (成交额:=V*C/100 的语料口径)。

语义要点:
  - IF(cond,a,b) 由解析器特化为 ternary 节点;cond 为 Series 时 NaN 视为
    False(pandas astype(bool) 会把 NaN 当 True,必须 fillna 兜底),结果按
    cond 索引构造 Series(np.where 会丢失索引);
  - AND/OR:布尔上下文真值(非零即真);Series 侧 fillna(False);
  - NOT:同上(NaN 视为 False);
  - 比较运算:pandas 比较天然把 NaN 一侧判为 False(与 TDX 布尔语境一致);
  - CODELIKE('模式'):编译期求值,code_prefix.startswith('模式');
  - call 命中 BUILTINS(见 tdx_builtins);映射表缺失且语句未被跳过的函数
    (WINNER/NAMELIKE/FINANCE/DYNAINFO/HHVBARS/LLVBARS/SUMBARS/DMA)
    抛 NotImplementedError(登记见 tdx_builtins 模块头);
  - 未知 AST 节点抛 NotImplementedError。
"""
import numpy as np
import pandas as pd

from .tdx_builtins import BUILTINS, COLUMN_ALIASES

__all__ = ["evaluate_ast", "build_env"]

_DEFAULT_CODE_PREFIX = "600000"  # 沪深主板:CODELIKE('3')/('68') 均为假


def _as_bool(x):
    """布尔上下文真值:非零即真;Series 的 NaN 视为 False。"""
    if isinstance(x, pd.Series):
        return x.fillna(False).astype(bool)
    return bool(x)


def _logical(l, r, is_and):
    if isinstance(l, pd.Series) or isinstance(r, pd.Series):
        lb, rb = _as_bool(l), _as_bool(r)
        return (lb & rb) if is_and else (lb | rb)
    return (bool(l) and bool(r)) if is_and else (bool(l) or bool(r))


_BIN_OPS = {
    ">": lambda l, r: l > r,
    "<": lambda l, r: l < r,
    ">=": lambda l, r: l >= r,
    "<=": lambda l, r: l <= r,
    "=": lambda l, r: l == r,
    "!=": lambda l, r: l != r,
    "<>": lambda l, r: l != r,
}


def _bin(oper, l, r):
    if oper in _BIN_OPS:
        return _BIN_OPS[oper](l, r)
    if oper == "+":
        if isinstance(l, str) and isinstance(r, str):  # 防御性:绘图语句内才有拼接
            return l + r
        return l + r
    if oper == "-":
        return l - r
    if oper == "*":
        return l * r
    if oper == "/":
        return l / r
    if oper == "AND":
        return _logical(l, r, True)
    if oper == "OR":
        return _logical(l, r, False)
    raise NotImplementedError(f"未登记的二元运算符 {oper!r}")


def _ternary(cond, a, b):
    if isinstance(cond, pd.Series):
        c = cond.fillna(False).astype(bool)  # NaN 条件视为假(TDX 口径)
        av = a if np.isscalar(a) else a.reindex(c.index).to_numpy()
        bv = b if np.isscalar(b) else b.reindex(c.index).to_numpy()
        return pd.Series(np.where(c.to_numpy(), av, bv), index=c.index)
    return a if bool(cond) else b


def evaluate_ast(ast, env, code_prefix=_DEFAULT_CODE_PREFIX):
    """按 AST 求值,返回标量或 pd.Series。"""
    op = ast["op"]
    if op == "num":
        return ast["val"]
    if op == "str":
        return ast["val"]
    if op == "var":
        name = ast["name"]
        if name in env:
            return env[name]
        if name == "DRAWNULL":  # 无效值(TDX 绘图约定)
            return np.nan
        alias = COLUMN_ALIASES.get(name)
        if alias is not None and alias in env:
            return env[alias]
        raise NameError(f"变量 {name!r} 未定义(env 无此名且非列别名)")
    if op == "neg":
        return -evaluate_ast(ast["expr"], env, code_prefix)
    if op == "not":
        x = evaluate_ast(ast["expr"], env, code_prefix)
        if isinstance(x, pd.Series):
            return ~_as_bool(x)
        return not bool(x)
    if op == "bin":
        l = evaluate_ast(ast["left"], env, code_prefix)
        r = evaluate_ast(ast["right"], env, code_prefix)
        return _bin(ast["oper"], l, r)
    if op == "ternary":
        cond = evaluate_ast(ast["cond"], env, code_prefix)
        then = evaluate_ast(ast["then"], env, code_prefix)
        other = evaluate_ast(ast["else"], env, code_prefix)
        return _ternary(cond, then, other)
    if op == "call":
        func = ast["func"]
        args = [evaluate_ast(a, env, code_prefix) for a in ast["args"]]
        if func == "CODELIKE":  # 编译期求值:code_prefix 前 1 位/前 2 位匹配
            if len(args) != 1 or not isinstance(args[0], str):
                raise ValueError("CODELIKE 需要字符串字面量参数(编译期求值)")
            return code_prefix.startswith(args[0])
        impl = BUILTINS.get(func)
        if impl is None:
            raise NotImplementedError(
                f"函数 {func} 未登记:语料出现但映射表缺失(WINNER/NAMELIKE/"
                f"FINANCE/DYNAINFO/HHVBARS/LLVBARS/SUMBARS/DMA),见 tdx_builtins 模块头")
        return impl(*args)
    raise NotImplementedError(f"未知 AST 节点 op={op!r}")


# ---------------------------------------------------------------------------
# 环境构造
# ---------------------------------------------------------------------------

_COL_CANDIDATES = {
    "CLOSE": ("Close", "close", "C", "收盘", "收盘价"),
    "OPEN": ("Open", "open", "O", "开盘", "开盘价"),
    "HIGH": ("High", "high", "H", "最高", "最高价"),
    "LOW": ("Low", "low", "L", "最低", "最低价"),
    "VOL": ("Volume", "volume", "Vol", "vol", "V", "成交量"),
}


def build_env(df):
    """从 OHLCV DataFrame 构造求值环境。

    注入:CLOSE/OPEN/HIGH/LOW/VOL + 别名 C/O/H/L/V、
    TR(=max(H-L, |H-昨收|, |L-昨收|))、AMOUNT(=V*C/100,语料成交额口径)。
    列名按 _COL_CANDIDATES 大小写/中英文兼容匹配,取不到抛 KeyError。
    """
    def _col(key):
        for nm in _COL_CANDIDATES[key]:
            if nm in df.columns:
                return df[nm].astype(float)
        raise KeyError(f"缺少 {key} 行情列,候选列名 {_COL_CANDIDATES[key]}")

    c = _col("CLOSE")
    o = _col("OPEN")
    h = _col("HIGH")
    l = _col("LOW")
    v = _col("VOL")
    prev_c = c.shift(1)
    tr = np.maximum.reduce([h - l, (h - prev_c).abs(), (l - prev_c).abs()])
    env = {
        "CLOSE": c, "OPEN": o, "HIGH": h, "LOW": l, "VOL": v,
        "C": c, "O": o, "H": h, "L": l, "V": v,
        "TR": tr,
        "AMOUNT": v * c / 100.0,  # 语料:成交额:=V*C/100
    }
    return env
