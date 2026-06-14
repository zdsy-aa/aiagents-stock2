# setup_backtest.py —— 起涨打分模型回测: fwd_10_10 GBDT 选股 + 止盈止损 + 净值 vs 上证。
import os, sys, time
import numpy as np

TP, SL, MAXHOLD, COST, TOPN = 0.10, -0.05, 10, 0.002, 10
SLOTS = TOPN * MAXHOLD   # 槽位法满仓上限近似


def _ma(c, n=10):
    c = np.asarray(c, float)
    out = np.full(len(c), np.nan)
    if len(c) >= n:
        cs = np.cumsum(np.insert(c, 0, 0.0))
        out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def simulate_trade(o, h, l, c, entry_idx, mode="fixed", tp=TP, sl=SL, maxhold=MAXHOLD,
                   cost=COST, trail=0.08, ma=None):
    """某股 OHLC(numpy) + 入场行 entry_idx(=t+1) -> (exit_idx, gross, net, reason)。
    entry=open[entry_idx]; mode∈{fixed,trailing,trend}。
    fixed: 逐日先判止损(同日同破取止损)再止盈; 否则持满maxhold收盘卖。
    trailing: 止损优先,否则跟踪最高价回撤trail比例触发移动止盈; 否则持满maxhold收盘卖。
    trend: 止损优先,否则跌破ma触发"破MA"; 否则持满maxhold收盘卖。
    entry非法 -> None。"""
    n = len(c)
    if entry_idx >= n:
        return None
    entry = o[entry_idx]
    if not np.isfinite(entry) or entry <= 0:
        return None
    sl_px = entry * (1 + sl)
    last = min(entry_idx + maxhold - 1, n - 1)
    if mode == "fixed":
        tp_px = entry * (1 + tp)
        for i in range(entry_idx, last + 1):
            if l[i] <= sl_px:
                return (i, sl, sl - cost, "止损")
            if h[i] >= tp_px:
                return (i, tp, tp - cost, "止盈")
        g = c[last] / entry - 1.0
        return (last, g, g - cost, "到期")
    if mode == "trailing":
        peak = h[entry_idx]
        for i in range(entry_idx, last + 1):
            if l[i] <= sl_px:
                return (i, sl, sl - cost, "止损")
            peak = max(peak, h[i])
            if i > entry_idx and l[i] <= peak * (1 - trail):
                g = peak * (1 - trail) / entry - 1.0
                return (i, g, g - cost, "移动止盈")
        g = c[last] / entry - 1.0
        return (last, g, g - cost, "到期")
    if mode == "trend":
        for i in range(entry_idx, last + 1):
            if l[i] <= sl_px:
                return (i, sl, sl - cost, "止损")
            if i > entry_idx and ma is not None and np.isfinite(ma[i]) and c[i] < ma[i]:
                g = c[i] / entry - 1.0
                return (i, g, g - cost, "破MA")
        g = c[last] / entry - 1.0
        return (last, g, g - cost, "到期")
    raise ValueError(mode)


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


import setup_modeling as SM
import setup_features as SF
from mine_commonality import _load_kline

PANEL = "/app/data/profit_mining/setup_panel.npz"


def score_oos(label="fwd_10_10"):
    """载panel,train上重训GBDT(指定标签),返回OOS有效行 (dates[datetime64D], codes, scores)。"""
    d = np.load(PANEL, allow_pickle=True)
    X = d["X"]; Y = d["Y"]; dates = d["dates"].astype("datetime64[D]")
    codes = d["codes"]; names = list(d["label_names"])
    j = names.index(label)
    y = Y[:, j]
    tr, oos = SM.time_split_mask(dates, SM.TRAIN_END, SM.OOS_START, SM.OOS_END)
    valid_tr = tr & ~np.isnan(y); valid_oos = oos & ~np.isnan(y)
    med = SM.col_median(X[valid_tr])
    Xtr = SM.fill_na(X[valid_tr], med); ytr = y[valid_tr]
    Xsub, ysub = SM._subsample_train(Xtr, ytr, ratio=5)
    bst = SM.fit_gbdt(Xsub, ysub)
    Xoos = SM.fill_na(X[valid_oos], med)
    sc = bst.predict(Xoos)
    return dates[valid_oos], codes[valid_oos], sc.astype(float)


def run_backtest(dates, codes, scores):
    """逐日 top-N 选股(在持去重) -> 每笔 _load_kline 定位 t+1 模拟 -> trades list。"""
    uniq_days = np.unique(dates)
    by_day = {}
    for dt, cd, s in zip(dates, codes, scores):
        by_day.setdefault(dt, ([], []))
        by_day[dt][0].append(cd); by_day[dt][1].append(s)
    kl_cache = {}
    def kl(code):
        if code not in kl_cache:
            kl_cache[code] = _load_kline(code)
        return kl_cache[code]
    held = {}   # code -> exit_date; 持仓中不重复买
    trades = []
    for dt in uniq_days:
        for cd in [c for c, ed in held.items() if ed <= dt]:
            del held[cd]
        cs, ss = by_day[dt]
        for cd in select_topn(cs, np.array(ss), set(held.keys()), TOPN):
            df = kl(cd)
            if df is None:
                continue
            t = df.index.get_indexer([np.datetime64(dt)])[0]
            if t < 0 or t + 1 >= len(df):
                continue
            o = df["Open"].to_numpy(float); h = df["High"].to_numpy(float)
            lo = df["Low"].to_numpy(float); c = df["Close"].to_numpy(float)
            r = simulate_trade(o, h, lo, c, t + 1)
            if r is None:
                continue
            exit_idx, gross, net, reason = r
            exit_dt = df.index[exit_idx].to_numpy().astype("datetime64[D]")
            held[cd] = exit_dt
            trades.append(dict(code=cd, entry=np.datetime64(dt), exit=exit_dt,
                               gross=gross, net=net, reason=reason))
    return trades


def portfolio_curve(trades, oos_days):
    """槽位法日净值(简化:净收益记在exit日): 日收益 = 当日所有exit笔 net 之和 / SLOTS。"""
    days = np.unique(oos_days)
    ret_by_day = {d: 0.0 for d in days}
    for tr in trades:
        ed = tr["exit"]
        if ed in ret_by_day:
            ret_by_day[ed] += tr["net"] / SLOTS
    curve = [1.0]
    for d in days:
        curve.append(curve[-1] * (1 + ret_by_day[d]))
    return days, np.array(curve[1:])


def _bench_curve(days):
    import pandas as pd
    ic = SM._load_index_close()
    s = ic.reindex(pd.to_datetime(days)).ffill()
    v = s.to_numpy(float)
    return v / v[0]


def main():
    t0 = time.time()
    dates, codes, scores = score_oos("fwd_10_10")
    print(f"  OOS打分 {len(scores)} bar", flush=True)
    trades = run_backtest(dates, codes, scores)
    oos_days = np.unique(dates)
    days, curve = portfolio_curve(trades, oos_days)
    bench = _bench_curve(days)
    nets = np.array([t["net"] for t in trades]) if trades else np.array([0.0])
    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    drets = np.diff(np.concatenate([[1.0], curve])) / np.concatenate([[1.0], curve[:-1]])
    ts = time.strftime("%Y%m%d_%H%M%S")
    L = [f"# 起涨打分模型回测 (fwd_10_10 GBDT, OOS {SM.OOS_START}~{SM.OOS_END})\n",
         f"生成 {ts}；策略: 每日top{TOPN}等权·t+1开盘买·止盈+{TP:.0%}/止损{SL:.0%}/持{MAXHOLD}日·扣{COST:.1%}成本\n",
         f"## 笔级\n- 总笔数 {len(trades)};胜率(净>0) {(nets>0).mean():.3f};平均净收益 {nets.mean():.4f}",
         f"- 退出占比: " + ", ".join(f"{k} {v}({v/max(len(trades),1):.0%})" for k, v in reasons.items()),
         f"## 组合(槽位法 SLOTS={SLOTS})\n- 累计 {cum_return(curve):.3f};年化 {annual_return(curve,len(days)):.3f};"
         f"Sharpe {sharpe(drets):.2f};最大回撤 {max_drawdown(curve):.3f}",
         f"- 上证同期: 累计 {bench[-1]/bench[0]-1:.3f};**策略超额 {cum_return(curve)-(bench[-1]/bench[0]-1):.3f}**",
         f"\n用时 {int(time.time()-t0)}s"]
    out = f"/app/data/commonality_reports/起涨回测_{ts}.md"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    import csv as _csv
    with open(f"/app/data/commonality_reports/起涨回测_净值_{ts}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.writer(f); w.writerow(["date", "strategy", "bench"])
        for dd, sv, bv in zip(days, curve, bench):
            w.writerow([str(dd), f"{sv:.6f}", f"{bv:.6f}"])
    print("\n".join(L), flush=True); print("  写", out, flush=True)


if __name__ == "__main__":
    main()
