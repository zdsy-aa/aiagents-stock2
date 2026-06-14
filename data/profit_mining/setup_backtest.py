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


def run_backtest(dates, codes, scores, mode="fixed", maxhold=MAXHOLD, riskoff=None):
    """逐日 top-N 选股(在持去重) -> 每笔模拟。mode 透传 simulate_trade;riskoff=不开新仓的日期集合(择时)。"""
    riskoff = riskoff or set()
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
    held = {}
    trades = []
    for dt in uniq_days:
        for cd in [c for c, ed in held.items() if ed <= dt]:
            del held[cd]
        if dt in riskoff:
            continue
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
            ma = _ma(c, 10) if mode == "trend" else None
            r = simulate_trade(o, h, lo, c, t + 1, mode=mode, maxhold=maxhold, ma=ma)
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


def _riskoff_days():
    """上证收盘<MA20 的交易日集合(datetime64[D]) -> 择时不开新仓。"""
    import pandas as pd
    ic = SM._load_index_close()
    ma20 = ic.rolling(20).mean()
    ro = ic.index[(ic < ma20).fillna(False)]
    return set(pd.DatetimeIndex(ro).values.astype("datetime64[D]"))


_CONFIGS = [
    ("C0_fixed",          "fixed",    10, False),
    ("C1_trailing",       "trailing", 30, False),
    ("C2_trend",          "trend",    30, False),
    ("C3_fixed_timing",   "fixed",    10, True),
    ("C4_trailing_timing","trailing", 30, True),
    ("C5_trend_timing",   "trend",    30, True),
]


def _eval_config(name, mode, maxhold, timing, dates, codes, scores, days, bench, riskoff):
    trades = run_backtest(dates, codes, scores, mode=mode, maxhold=maxhold,
                          riskoff=(riskoff if timing else None))
    _, curve = portfolio_curve(trades, days)
    nets = np.array([t["net"] for t in trades]) if trades else np.array([0.0])
    drets = np.diff(np.concatenate([[1.0], curve])) / np.concatenate([[1.0], curve[:-1]])
    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    excess = cum_return(curve) - (bench[-1] / bench[0] - 1)
    return dict(name=name, n=len(trades), win=(nets > 0).mean(), avg=nets.mean(),
                cum=cum_return(curve), ann=annual_return(curve, len(days)),
                sharpe=sharpe(drets), mdd=max_drawdown(curve), excess=excess, reasons=reasons)


def main():
    t0 = time.time()
    dates, codes, scores = score_oos("fwd_10_10")
    print(f"  OOS打分 {len(scores)} bar", flush=True)
    days = np.unique(dates)
    bench = _bench_curve(days)
    riskoff = _riskoff_days()
    rows = []
    for name, mode, maxhold, timing in _CONFIGS:
        r = _eval_config(name, mode, maxhold, timing, dates, codes, scores, days, bench, riskoff)
        rows.append(r)
        print(f"  {name}: 笔{r['n']} 胜率{r['win']:.3f} 累计{r['cum']:.3f} "
              f"年化{r['ann']:.3f} Sharpe{r['sharpe']:.2f} 回撤{r['mdd']:.3f} 超额{r['excess']:.3f}", flush=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    bench_cum = bench[-1] / bench[0] - 1
    L = [f"# 起涨回测v2 执行精细化对比 (fwd_10_10 GBDT, OOS {SM.OOS_START}~{SM.OOS_END})\n",
         f"生成 {ts}；每日top{TOPN}等权·t+1开盘买·扣{COST:.1%}成本；上证同期累计 {bench_cum:.3f}\n",
         "| 配置 | 退出 | 择时 | 笔数 | 胜率 | 平均净 | 累计 | 年化 | Sharpe | 最大回撤 | 超额(vs上证) |",
         "|------|------|------|------|------|--------|------|------|--------|----------|--------------|"]
    cfgmap = {c[0]: c for c in _CONFIGS}
    for r in rows:
        _, mode, mh, timing = cfgmap[r["name"]]
        L.append(f"| {r['name']} | {mode} | {'是' if timing else '否'} | {r['n']} | {r['win']:.3f} | "
                 f"{r['avg']:.4f} | {r['cum']:.3f} | {r['ann']:.3f} | {r['sharpe']:.2f} | {r['mdd']:.3f} | "
                 f"**{r['excess']:+.3f}** |")
    best = max(rows, key=lambda r: r["excess"])
    L.append(f"\n## 结论\n- **最优配置: {best['name']}** 超额 {best['excess']:+.3f}(累计{best['cum']:.3f} vs 上证{bench_cum:.3f})")
    L.append("- 退出占比(各配置): " + " | ".join(
        f"{r['name']}:" + ",".join(f"{k}{v}" for k, v in r["reasons"].items()) for r in rows))
    out = f"/app/data/commonality_reports/起涨回测v2_多配置_{ts}.md"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L), flush=True); print("  写", out, flush=True)
    print(f"  用时{int(time.time()-t0)}s", flush=True)


if __name__ == "__main__":
    main()
