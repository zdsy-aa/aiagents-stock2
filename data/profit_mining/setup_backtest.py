# setup_backtest.py —— 起涨打分模型回测: fwd_10_10 GBDT 选股 + 止盈止损 + 净值 vs 上证。
import os, sys, time
import numpy as np

TP, SL, MAXHOLD, COST, TOPN = 0.10, -0.05, 10, 0.002, 10
SLOTS = TOPN * MAXHOLD   # 槽位法满仓上限近似


def simulate_trade(o, h, l, c, entry_idx, tp=TP, sl=SL, maxhold=MAXHOLD, cost=COST):
    """某股 OHLC(numpy) + 入场行 entry_idx(=t+1) -> (exit_idx, gross, net, reason)。
    entry=open[entry_idx]; 逐日先判止损(同日同破取止损)再止盈; 否则持满maxhold收盘卖。
    entry非法 -> None。"""
    n = len(c)
    if entry_idx >= n:
        return None
    entry = o[entry_idx]
    if not np.isfinite(entry) or entry <= 0:
        return None
    tp_px, sl_px = entry * (1 + tp), entry * (1 + sl)
    last = min(entry_idx + maxhold - 1, n - 1)
    for i in range(entry_idx, last + 1):
        if l[i] <= sl_px:
            return (i, sl, sl - cost, "止损")
        if h[i] >= tp_px:
            return (i, tp, tp - cost, "止盈")
    gross = c[last] / entry - 1.0
    return (last, gross, gross - cost, "到期")


def select_topn(day_codes, day_scores, held, topn=TOPN):
    """当日 codes/scores -> 按分降序取不在 held 的前 topn 个 code。"""
    order = np.argsort(day_scores)[::-1]
    out = []
    for j in order:
        cd = day_codes[j]
        if cd in held:
            continue
        out.append(cd)
        if len(out) >= topn:
            break
    return out


def cum_return(curve):
    return float(curve[-1] / curve[0] - 1.0)


def annual_return(curve, n_days):
    return float((curve[-1] / curve[0]) ** (252.0 / max(n_days, 1)) - 1.0)


def max_drawdown(curve):
    peak = -1e18; mdd = 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return float(mdd)


def sharpe(daily_rets):
    r = np.asarray(daily_rets, float)
    sd = r.std()
    return 0.0 if sd == 0 else float(r.mean() / sd * np.sqrt(252))
