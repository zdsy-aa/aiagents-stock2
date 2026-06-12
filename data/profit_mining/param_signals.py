# param_signals.py —— 方案A/B 参数化信号。复用 features.py 的 EMA/MA/HHV/LLV。
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features as F   # MA/EMA/HHV/LLV 纯pandas，本地可import


# ---- MACD ----
def _macd_lines(close, fast, slow, signal):
    dif = F.EMA(close, fast) - F.EMA(close, slow)
    dea = F.EMA(dif, signal)
    return dif, dea


def macd_golden(df, fast=12, slow=26, signal=9):
    dif, dea = _macd_lines(df["Close"], fast, slow, signal)
    return ((dif > dea) & (dif.shift(1) <= dea.shift(1))).fillna(False)


def macd_dead(df, fast=12, slow=26, signal=9):
    dif, dea = _macd_lines(df["Close"], fast, slow, signal)
    return ((dif < dea) & (dif.shift(1) >= dea.shift(1))).fillna(False)


# ---- 斐波回调线 ----
def _fib_levels(df, N, ratio):
    hh = F.HHV(df["High"], N)
    ll = F.LLV(df["Low"], N)
    rng = hh - ll
    return hh - rng * ratio, ll + rng * ratio    # support, resistance


def fib_support_hold(df, N=20, ratio=0.618, band=0.01):
    support, _ = _fib_levels(df, N, ratio)
    return ((df["Low"] <= support * (1 + band)) & (df["Close"] >= support)).fillna(False)


def fib_resist_reject(df, N=20, ratio=0.618, band=0.01):
    _, resistance = _fib_levels(df, N, ratio)
    return ((df["High"] >= resistance * (1 - band)) & (df["Close"] <= resistance)).fillna(False)


# ---- BBI ----
def _bbi(close, periods):
    return sum(F.MA(close, p) for p in periods) / len(periods)


def bbi_cross_up(df, periods=(3, 6, 12, 24)):
    b = _bbi(df["Close"], periods)
    return ((df["Close"] > b) & (df["Close"].shift(1) <= b.shift(1))).fillna(False)


def bbi_cross_down(df, periods=(3, 6, 12, 24)):
    b = _bbi(df["Close"], periods)
    return ((df["Close"] < b) & (df["Close"].shift(1) >= b.shift(1))).fillna(False)


# ---- 方案组合 ----
def plan_a_signal(df, N, ratio, band, fast, slow, signal, side):
    macd = macd_golden(df, fast, slow, signal) if side == "buy" else macd_dead(df, fast, slow, signal)
    fib = (fib_support_hold(df, N, ratio, band) if side == "buy"
           else fib_resist_reject(df, N, ratio, band))
    return (fib & macd).fillna(False)


def plan_b_signal(df, periods, fast, slow, signal, side):
    macd = macd_golden(df, fast, slow, signal) if side == "buy" else macd_dead(df, fast, slow, signal)
    bb = (bbi_cross_up(df, periods) if side == "buy" else bbi_cross_down(df, periods))
    return (bb & macd).fillna(False)


# ---- 参数网格（spec §4 起点，可调）----
_MACD = ((12, 26, 9), (8, 17, 9), (6, 19, 9), (5, 35, 5))
PLAN_A_GRID = [(N, r, b, f, s, sig)
               for N in (10, 20, 30, 60)
               for r in (0.382, 0.5, 0.618)
               for b in (0.005, 0.01, 0.02)
               for (f, s, sig) in _MACD]
PLAN_B_GRID = [(p, f, s, sig)
               for p in ((3, 6, 12, 24), (5, 10, 20, 40), (2, 5, 10, 20))
               for (f, s, sig) in _MACD]
