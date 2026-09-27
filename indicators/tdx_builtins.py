"""通达信内置函数映射表(pandas 实现要点,与简报映射表一致)。

函数清单(对语料 /home/tdxback/通达信指标/20260424001/tdx_v4_standalone 的
32 个公式文件用 Task 2.1 解析器 grep 全量,只计"求值语句"即未被绘图/跳语句
吞掉的调用,39 个不同函数名):

  已实现(简报映射表,实现细节逐条对应):
    REF(x,n)     x.shift(n);n 为 Series 时逐 bar 位移(语料:REF(CH_,距顶+1))
    MA(x,n)      x.rolling(n, min_periods=n).mean();n 为 Series 时逐 bar 窗口
                 (语料:MA(VOL,VL) 等 74 处动态窗口)
    EMA(x,n)     x.ewm(span=n, adjust=False).mean();n 为 Series 时逐 bar 递推
                 alpha=2/(n+1)(语料:EMA(C,MA13周期) 2 处)
    SMA(x,n,m)   x.ewm(alpha=m/n, adjust=False).mean()(TDX SMA(X,N,M))
    STD(x,n)     x.rolling(n, min_periods=n).std();n 为 Series 时逐 bar 样本
                 标准差 ddof=1(w=1 → NaN,与 pandas rolling(1).std() 一致)
    HHV(x,n)/LLV(x,n)  rolling(n, min_periods=1).max()/min();支持 Series n
    SUM(x,n)     rolling(n, min_periods=1).sum();支持 Series n
    COUNT(c,n)   c.astype(float).rolling(n, min_periods=1).sum();支持 Series n
    ABS(x)       x.abs()(标量亦支持)
    MAX(a,b)/MIN(a,b)  np.maximum/np.minimum(标量广播)
    INTPART(x)   np.floor(x)(映射表口径:x>=0 时与 TDX 截断一致;语料全为非负)
    CROSS(a,b)   (a>b)&(a.shift(1)<=b.shift(1));b 标量时按同索引 Series 广播
                 (与 tq_confirm_top10._CROSS 同口径)
    BARSLAST(c)  与 tq_confirm_top10._barslast 逐行同算法(NaN 视为 False,
                 从未为真返回 9999;注意首次为真的 bar 处仍为 9999)
    BARSCOUNT(c) c.notna().cumsum()(TDX 语义:有效数据周期数。简报括号内写
                 c.astype(float).cumsum(),但语料 5 处均为 BARSCOUNT(C)>250
                 即"上市满 250 根K线",cumsum 收盘价口径语义错误,故取有效
                 周期数口径,见 task-2.2-report.md)
    EVERY(c,n)   c.astype(float).rolling(n, min_periods=n).min()
    EXIST(c,n)   c.astype(float).rolling(n, min_periods=1).max()
    TR           列注入(见 evaluator.build_env:max(H-L, |H-昨收|, |L-昨收|))
    IF/AND/OR/NOT 由 AST 层特化(ternary/not 节点 + bin 的 AND/OR),见 evaluator
    CODELIKE     求值器编译期处理:code_prefix.startswith(模式),见 evaluator

  语料出现但映射表缺失 → 求值期抛 NotImplementedError(登记如下):
    WINNER    (28 处,威科夫体系)   筹码分布,依赖分时成交数据,参考实现亦无
    NAMELIKE  (10 处,选股体系)     证券名称匹配,需名称上下文
    FINANCE   (7 处)               财务数据表,需外部数据源
    DYNAINFO  (5 处)               动态行情快照,需实时行情上下文
    HHVBARS   (4 处)/LLVBARS (4 处)  映射表未列,暂未实现
    SUMBARS   (4 处)/DMA     (2 处)  映射表未列,暂未实现
    CON2STR/ISLASTBAR/RGB 仅出现在 DRAW*/STICKLINE 绘图语句内(已被 Task 2.1
    跳过),不进入求值,故不在上述登记之列。

动态参数口径(语料存在窗口/位移为 Series 的调用):
  - bar i 的窗口值 w[i]=int(floor(n[i]));NaN/<=0 → 该 bar 结果为 NaN;
  - MA/STD 窗口内须 w 个值全部有效才出值(与 rolling(min_periods=n) 一致);
    HHV/LLV/SUM/COUNT 与静态口径 min_periods=1 一致,窗口内有多少用多少;
  - REF 位移超出左边界或 n 无效 → NaN;EMA 递推中无效 bar 跳过更新、输出 NaN。
"""
import numpy as np
import pandas as pd

__all__ = ["BUILTINS", "COLUMN_ALIASES"]

# 数据列别名(env 无该名时回退,见 evaluator 变量解析)
COLUMN_ALIASES = {"C": "CLOSE", "H": "HIGH", "L": "LOW", "O": "OPEN", "V": "VOL"}


def _is_series(x):
    return isinstance(x, pd.Series)


def _wint(n):
    """标量窗口 → int(浮点 5.0 → 5;语料窗口均为整数值)。"""
    return int(n)


# ---------------------------------------------------------------------------
# 动态窗口(逐 bar,语料实际形态:MA(VOL,VL)/STD(振幅,N)/REF(CH_,距顶+1) 等)
# ---------------------------------------------------------------------------

def _dyn_roll(x, n, agg, full_window):
    """窗口为 Series 时的逐 bar 滚动聚合。

    full_window=True:窗口内须全部有效(MA/STD,对应 min_periods=n);
    full_window=False:窗口内至少 1 个有效(HHV/LLV/SUM/COUNT,对应 min_periods=1)。
    """
    xv = x.to_numpy(dtype=float)
    w = np.floor(n.to_numpy(dtype=float))
    out = np.full(len(xv), np.nan)
    for i in range(len(xv)):
        wi = w[i]
        if np.isnan(wi) or wi < 1:
            continue
        wi = int(wi)
        seg = xv[max(0, i + 1 - wi):i + 1]
        seg = seg[~np.isnan(seg)]
        need = wi if full_window else 1
        if len(seg) >= need:
            out[i] = agg(seg)
    return pd.Series(out, index=x.index)


def _REF(x, n):
    if _is_series(n):
        w = np.floor(n.to_numpy(dtype=float))
        idx = np.arange(len(x)) - w
        valid = ~np.isnan(w) & (idx >= 0) & (idx <= len(x) - 1)
        out = np.where(valid, x.to_numpy()[np.nan_to_num(idx, nan=0.0).astype(int)], np.nan)
        return pd.Series(out, index=x.index)
    return x.shift(_wint(n))


def _MA(x, n):
    if _is_series(n):
        return _dyn_roll(x, n, np.mean, full_window=True)
    return x.rolling(_wint(n), min_periods=_wint(n)).mean()


def _EMA(x, n):
    if _is_series(n):
        # 逐 bar 递推:alpha[i]=2/(n[i]+1);无效 bar 跳过更新、输出 NaN。
        xv = x.to_numpy(dtype=float)
        w = np.floor(n.to_numpy(dtype=float))
        out = np.full(len(xv), np.nan)
        y = np.nan
        for i in range(len(xv)):
            wi = w[i]
            if np.isnan(wi) or wi < 1 or np.isnan(xv[i]):
                continue
            a = 2.0 / (wi + 1.0)
            y = xv[i] if np.isnan(y) else (1 - a) * y + a * xv[i]
            out[i] = y
        return pd.Series(out, index=x.index)
    return x.ewm(span=_wint(n), adjust=False).mean()


def _SMA(x, n, m=1):
    return x.ewm(alpha=float(m) / float(n), adjust=False).mean()


def _STD(x, n):
    if _is_series(n):
        return _dyn_roll(x, n, lambda s: np.std(s, ddof=1), full_window=True)
    return x.rolling(_wint(n), min_periods=_wint(n)).std()


def _HHV(x, n):
    if _is_series(n):
        return _dyn_roll(x, n, np.max, full_window=False)
    return x.rolling(_wint(n), min_periods=1).max()


def _LLV(x, n):
    if _is_series(n):
        return _dyn_roll(x, n, np.min, full_window=False)
    return x.rolling(_wint(n), min_periods=1).min()


def _SUM(x, n):
    if _is_series(n):
        return _dyn_roll(x, n, np.sum, full_window=False)
    return x.rolling(_wint(n), min_periods=1).sum()


def _COUNT(c, n):
    if _is_series(n):
        return _dyn_roll(c.astype(float), n, np.sum, full_window=False)
    return c.astype(float).rolling(_wint(n), min_periods=1).sum()


def _ABS(x):
    return x.abs() if _is_series(x) else abs(x)


def _MAX(a, b):
    return np.maximum(a, b)


def _MIN(a, b):
    return np.minimum(a, b)


def _INTPART(x):
    return np.floor(x)  # 映射表口径:x>=0 时与 TDX 截断一致(语料全为非负)


def _CROSS(a, b):
    """上穿:今日 a>b 且昨日 a<=b;b 可为标量或同索引 Series(参考实现同口径)。"""
    if np.isscalar(b):
        b = pd.Series(b, index=a.index)
    return (a > b) & (a.shift(1) <= b.shift(1))


def _BARSLAST(cond):
    """距最近一次条件为真的 bar 数;从未为真返回 9999。
    与 tq_confirm_top10._barslast 逐行同算法(NaN 视为 False)。"""
    arr = cond.fillna(False).to_numpy().astype(bool)
    out = np.full(len(arr), 9999.0)
    last = None
    for i, v in enumerate(arr):
        if last is not None:
            out[i] = i - last
        if v:
            last = i
    return pd.Series(out, index=cond.index)


def _BARSCOUNT(x):
    """TDX 语义:有效数据周期数(自上市起,NaN 不计)。
    见模块头注释:与简报括号内的 cumsum 写法不同,以语料语义为准。"""
    return x.notna().cumsum()


def _EVERY(c, n):
    return c.astype(float).rolling(_wint(n), min_periods=_wint(n)).min()


def _EXIST(c, n):
    return c.astype(float).rolling(_wint(n), min_periods=1).max()


BUILTINS = {
    "REF": _REF,
    "MA": _MA,
    "EMA": _EMA,
    "SMA": _SMA,
    "STD": _STD,
    "HHV": _HHV,
    "LLV": _LLV,
    "SUM": _SUM,
    "COUNT": _COUNT,
    "ABS": _ABS,
    "MAX": _MAX,
    "MIN": _MIN,
    "INTPART": _INTPART,
    "CROSS": _CROSS,
    "BARSLAST": _BARSLAST,
    "BARSCOUNT": _BARSCOUNT,
    "EVERY": _EVERY,
    "EXIST": _EXIST,
}
