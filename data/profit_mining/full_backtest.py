# full_backtest.py —— 完整买卖策略全市场回测：
#   买=A∪B(极限抄底+量比≥1.3 或 尖刺金叉)+大盘择时；卖=缠论卖点+过热顶(二连板/斐波全多头)，
#   辅以保护止损-8%与时间止损90日；真实约束(涨停买不进/一字跌停卖不出顺延/流动性/滑点)。
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/full_backtest.py
import sys
sys.path.insert(0, "/app"); sys.path.insert(0, "/app/data/profit_mining")
from collections import defaultdict
import numpy as np
import pandas as pd
import features as F

DIR = "/app/data/profit_mining"
IDXCSV = f"{DIR}/index_sh000001.csv"
_RENAME = {"开盘": "Open", "最高": "High", "最低": "Low", "收盘": "Close", "成交量": "Volume"}
INIT = 1_000_000.0
MAXPOS = 10
SL = -8.0
TIME_STOP = 90
COST = 0.005
AMT_FLOOR = 2e7


def _load(code):
    from akshare_gateway import akshare_gw
    df = akshare_gw.local.get_kline(code, kline_type="day", limit=10000)
    if df is None or df.empty:
        return None
    return df.rename(columns=_RENAME).set_index("日期").sort_index()[["Open", "High", "Low", "Close", "Volume"]]


def buy_signals(timed=True):
    f = pd.read_csv(f"{DIR}/signal_features.csv", encoding="utf-8-sig", dtype={"股票代码": str})
    f["股票代码"] = f["股票代码"].str.zfill(6)
    t = pd.read_csv(f"{DIR}/turnover_signal.csv", encoding="utf-8-sig",
                    dtype={"股票代码": str}).drop_duplicates(["股票代码", "信号日期"])
    t["股票代码"] = t["股票代码"].str.zfill(6)
    m = f.merge(t, on=["股票代码", "信号日期"], how="left").drop_duplicates(["股票代码", "信号日期", "买点类型"])
    m["ql"] = pd.to_numeric(m["量比"], errors="coerce")
    b = lambda c: pd.to_numeric(m.get(c, 0), errors="coerce").fillna(0).to_numpy() > 0
    rule = (b("极限抄底") & (m["ql"].to_numpy() >= 1.3)) | b("尖刺金叉")
    if timed:
        rule = rule & b("SID小于等于2")
    bs = defaultdict(set)
    for _, r in m[rule].iterrows():
        bs[r["股票代码"]].add(r["信号日期"])
    return bs


def sell_triggers():
    s = pd.read_csv(f"{DIR}/sell_features.csv", encoding="utf-8-sig", dtype={"股票代码": str})
    s["股票代码"] = s["股票代码"].str.zfill(6)
    b = lambda c: pd.to_numeric(s.get(c, 0), errors="coerce").fillna(0) > 0
    trig = s[b("二连板") | b("斐波全多头")]
    st = defaultdict(list)
    for _, r in trig.iterrows():
        st[r["股票代码"]].append(r["信号日期"])
    return {k: sorted(set(v)) for k, v in st.items()}


_G = {}   # 子进程全局(idx_state)，避免每任务重复pickle


def _init_worker(idx_state):
    _G["idx_state"] = idx_state


def _proc_code(args):
    """处理单只票，返回 [(ed,ep,xd,xp,path_dict), ...]。"""
    code, buy_dates, sell_dates, timed = args
    idx_state = _G.get("idx_state")
    df = _load(code)
    if df is None or len(df) < 70:
        return []
    idxl = [d.strftime("%Y-%m-%d") for d in df.index]
    pos = {d: k for k, d in enumerate(idxl)}
    o, h, l, c, v = (df[x].to_numpy() for x in ("Open", "High", "Low", "Close", "Volume"))
    p_lim = 0.2 if code[:3] in ("300", "301") else 0.1
    sells = [pos[d] for d in sell_dates if d in pos]
    out = []
    for bd in sorted(buy_dates):
        if bd not in pos:
            continue
        i = pos[bd]; e = i + 1; n = len(c)
        if e >= n:
            continue
        if o[e] >= c[i] * (1 + p_lim) * 0.985 or h[e] == l[e] or v[e] * 100 * c[e] < AMT_FLOOR:
            continue
        entry = o[e]; sl_px = entry * (1 + SL / 100)
        nxt_sell = next((sx for sx in sells if sx > i), None)
        end = min(i + TIME_STOP, n - 1)
        exit_i, exit_px = None, None
        for d in range(e, end + 1):
            is_dl = (h[d] == l[d]) and (d > 0 and c[d] <= c[d - 1] * (1 - p_lim) * 1.02)
            if idx_state is not None and idx_state.get(idxl[d], 2) == 4:
                exit_i, exit_px = d, c[d]; break
            if o[d] <= sl_px and not is_dl:
                exit_i, exit_px = d, o[d]; break
            if l[d] <= sl_px and not is_dl:
                exit_i, exit_px = d, sl_px; break
            if nxt_sell is not None and d >= nxt_sell:
                sx = min(d + 1, n - 1); exit_i, exit_px = sx, o[sx]; break
        if exit_i is None:
            exit_i, exit_px = end, c[end]
        path = {idxl[d]: float(c[d]) for d in range(e, exit_i + 1)}
        out.append((idxl[e], float(entry), idxl[exit_i], float(exit_px), path))
    return out


def run(timed, idx_state, nproc=8):
    bs = buy_signals(timed)
    st = sell_triggers()
    codes = sorted(bs)
    args = [(code, sorted(bs[code]), st.get(code, []), timed) for code in codes]
    from multiprocessing import Pool
    with Pool(nproc, initializer=_init_worker, initargs=(idx_state,)) as p:
        results = p.map(_proc_code, args, chunksize=40)
    trades, closes = [], {}
    for partial in results:
        for ed, ep, xd, xp, path in partial:
            tid = len(trades)
            trades.append(dict(tid=tid, ed=ed, ep=ep, xd=xd, xp=xp))
            closes[tid] = path
    trades.sort(key=lambda x: x["ed"])
    return trades, closes


def portfolio(trades, closes, calendar):
    cash = INIT; openp = {}            # tid -> dict(sh, xd, xp)
    en = defaultdict(list)
    for t in trades:
        en[t["ed"]].append(t)
    tmap = {t["tid"]: t for t in trades}
    curve, taken = [], 0

    def close_due(day):
        nonlocal cash
        for tid in list(openp):
            if openp[tid]["xd"] <= day:        # 出场日≤当前日即平(含同日进出场ed==xd)
                cash += openp[tid]["sh"] * openp[tid]["xp"] * (1 - COST / 2)
                del openp[tid]

    for day in calendar:
        close_due(day)
        for t in en.get(day, []):
            if len(openp) >= MAXPOS:
                continue
            eq = cash + sum(op["sh"] * closes[tid].get(day, tmap[tid]["ep"]) for tid, op in openp.items())
            size = eq / MAXPOS
            if cash < size or size <= 0:
                continue
            openp[t["tid"]] = dict(sh=size * (1 - COST / 2) / t["ep"], xd=t["xd"], xp=t["xp"])
            cash -= size; taken += 1
        close_due(day)                          # 同日进出场立即平，避免锁仓
        eq = cash + sum(op["sh"] * closes[tid].get(day, tmap[tid]["ep"]) for tid, op in openp.items())
        curve.append((day, eq))
    return curve, taken


def metrics(curve):
    eq = np.array([e for _, e in curve], float)
    if len(eq) < 2:
        return dict(总收益=0, 年化=0, 回撤=0, sharpe=0, 年=0)
    rt = eq[-1] / INIT - 1; yrs = len(eq) / 244.0
    cagr = (eq[-1] / INIT) ** (1 / yrs) - 1
    peak = np.maximum.accumulate(eq); mdd = ((eq - peak) / peak).min()
    dr = np.diff(eq) / eq[:-1]; sh = (dr.mean() / (dr.std() + 1e-9)) * np.sqrt(244)
    return dict(总收益=rt, 年化=cagr, 回撤=mdd, sharpe=sh, 年=yrs)


def trade_stats(trades):
    r = np.array([(t["xp"] / t["ep"] - 1) * 100 - COST * 100 for t in trades])
    return len(r), (r > 0).mean(), r.mean(), np.median(r)


def main():
    idx = pd.read_csv(IDXCSV, encoding="utf-8-sig"); idx["日期"] = pd.to_datetime(idx["日期"])
    idx = idx.set_index("日期").sort_index()
    ist = F.index_state(idx[["Open", "High", "Low", "Close", "Volume"]])
    idx_state = {d.strftime("%Y-%m-%d"): int(s) for d, s in ist["大盘状态ID"].items()}
    cal_all = [d.strftime("%Y-%m-%d") for d in idx.index]

    L = ["# 完整买卖策略 全市场回测", "",
         "- 买=A∪B(极限抄底+量比≥1.3 或 尖刺金叉)；卖=缠论卖点+过热顶(二连板/斐波全多头)+保护止损-8%+时间止损90日",
         f"- 全A合格池(排除科创/北交/ST)；真实约束(涨停买不进/一字跌停顺延/流动性≥2千万/含滑点{COST*100:.1f}%)；并发{MAXPOS}",
         ""]
    for timed, label in [(True, "含大盘择时(推荐)"), (False, "不择时(全日期)")]:
        trades, closes = run(timed, idx_state if timed else None)
        if not trades:
            continue
        lo, hi = min(t["ed"] for t in trades), max(t["xd"] for t in trades)
        # 日历=指数交易日 ∪ 所有进出场日(确保每笔进出场都能触发,避免槽位锁死)
        cal = sorted(set([d for d in cal_all if lo <= d <= hi])
                     | {t["ed"] for t in trades} | {t["xd"] for t in trades})
        curve, taken = portfolio(trades, closes, cal)
        mk = metrics(curve); n, wr, avg, med = trade_stats(trades)
        L.append(f"## {label}")
        L.append(f"- 候选交易 {n} 笔(成交{taken})；逐笔胜率 {wr*100:.0f}%、平均 {avg:.1f}%、中位 {med:.1f}%")
        L.append(f"- **组合：总收益 {mk['总收益']*100:.0f}%、年化 {mk['年化']*100:.1f}%、最大回撤 {mk['回撤']*100:.1f}%、"
                 f"Sharpe {mk['sharpe']:.2f}**（约{mk['年']:.1f}年）")
        # 分年收益
        eqs = pd.Series({d: e for d, e in curve}); eqs.index = pd.to_datetime(eqs.index)
        yr_ret = eqs.groupby(eqs.index.year).agg(lambda s: s.iloc[-1] / s.iloc[0] - 1)
        L.append("- 分年收益：" + "；".join(f"{y}:{v*100:+.0f}%" for y, v in yr_ret.items()))
        L.append("")
        print(f"[{label}] 成交{taken} 胜率{wr*100:.0f}% 年化{mk['年化']*100:.1f}% 回撤{mk['回撤']*100:.1f}%", flush=True)

    L += ["## 说明",
          "- 出场用验证过的卖点规则(缠论卖点+过热顶,OOS 71-80%)，非固定TP/SL；保护止损与时间止损防极端。",
          "- 仍为样本内：买卖规则均在本数据挖出，真实前瞻按walk-forward经验大幅打折(年化或落15-25%区间)。",
          "- 全A合格池=排除科创/北交/ST的沪深主板+中小+创业；本地K线全历史(~1993-2026)。",
          "- 尖刺金叉(B)换手率经baostock按年下载已覆盖全历史(2001-2026)，为完整A∪B。"]
    open(f"{DIR}/完整买卖策略_全市场回测_报告.md", "w", encoding="utf-8").write("\n".join(L))
    print("[full_backtest] 完成", flush=True)


if __name__ == "__main__":
    main()
