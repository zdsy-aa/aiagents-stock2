# portfolio_backtest_v2.py —— 真实约束组合回测：大盘择时+成交约束(涨停买不进/跌停卖不出/流动性)+滑点。
#   规则=A∪B(极限抄底+量比≥1.3 或 尖刺金叉)；对比 naive(无约束) vs 真实约束。
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/portfolio_backtest_v2.py
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
TP, SL, ND = 30.0, -8.0, 60
COST_NAIVE = 0.003          # 仅佣金印花
COST_REAL = 0.005           # 含滑点
AMT_FLOOR = 2e7             # 流动性下限：进场日成交额≥2000万
POS_AMT_CAP = 0.01          # 单笔≤进场日成交额的1%(防冲击)


def _load(code):
    from akshare_gateway import akshare_gw
    df = akshare_gw.local.get_kline(code, kline_type="day", limit=10000)
    if df is None or df.empty:
        return None
    return df.rename(columns=_RENAME).set_index("日期").sort_index()[["Open", "High", "Low", "Close", "Volume"]]


def _rule_signals():
    f = pd.read_csv(f"{DIR}/signal_features.csv", encoding="utf-8-sig", dtype={"股票代码": str})
    f["股票代码"] = f["股票代码"].str.zfill(6)
    t = pd.read_csv(f"{DIR}/turnover_signal.csv", encoding="utf-8-sig",
                    dtype={"股票代码": str}).drop_duplicates(["股票代码", "信号日期"])
    t["股票代码"] = t["股票代码"].str.zfill(6)
    m = f.merge(t, on=["股票代码", "信号日期"], how="left").drop_duplicates(["股票代码", "信号日期", "买点类型"])
    m["量比_v"] = pd.to_numeric(m["量比"], errors="coerce")
    b = lambda c: pd.to_numeric(m.get(c, 0), errors="coerce").fillna(0).to_numpy() > 0
    A = b("极限抄底") & (m["量比_v"].to_numpy() >= 1.3)
    B = b("尖刺金叉")
    sid_ok = b("SID小于等于2")           # 大盘择时：仅震荡/多头(非空头/危险)
    return m[(A | B)], m[(A | B) & sid_ok]


def simulate(o, h, l, c, v, i, code, idx_state, dates, real):
    """返回 (entry_date, entry_px, exit_date, exit_px, ret%) 或 None(被约束挡掉)。"""
    n = len(c)
    if i + 1 >= n:
        return None
    e = i + 1
    p = 0.2 if str(code)[:3] in ("300", "301") else 0.1
    prev = c[i]
    # 成交约束1：涨停/一字买不进(开盘已近涨停 或 一字板)
    if real:
        if o[e] >= prev * (1 + p) * 0.985:
            return None
        if h[e] == l[e]:
            return None
        if v[e] * 100 * c[e] < AMT_FLOOR:        # 流动性下限(Volume单位=手,×100=元)
            return None
    entry = o[e]
    if entry <= 0:
        return None
    tp_px, sl_px = entry * (1 + TP / 100), entry * (1 + SL / 100)
    end = min(i + ND, n - 1)
    for d in range(e, end + 1):
        # 大盘择时：持仓期间大盘转危险(SID=4) → 当日收盘强制退出
        if real and idx_state is not None:
            sid = idx_state.get(dates[d], 2)
            if sid == 4:
                return e, entry, d, c[d], (c[d] / entry - 1) * 100
        is_down_limit = (h[d] == l[d]) and (c[d] <= c[d - 1] * (1 - p) * 1.02 if d > 0 else False)
        if o[d] >= tp_px:
            return e, entry, d, o[d], (o[d] / entry - 1) * 100
        if o[d] <= sl_px and not is_down_limit:
            return e, entry, d, o[d], (o[d] / entry - 1) * 100
        if l[d] <= sl_px:
            if real and is_down_limit:        # 一字跌停卖不出，顺延
                continue
            return e, entry, d, sl_px, SL
        if h[d] >= tp_px:
            return e, entry, d, tp_px, TP
    return e, entry, end, c[end], (c[end] / entry - 1) * 100


def build_trades(sigs, real, idx_state):
    by_code = defaultdict(list)
    for _, r in sigs.iterrows():
        by_code[str(r["股票代码"]).zfill(6)].append(r["信号日期"])
    trades, closes = [], {}
    blocked = 0
    for code, ds in by_code.items():
        df = _load(code)
        if df is None or len(df) < 70:
            continue
        idxl = list(df.index)
        pos = {dd.strftime("%Y-%m-%d"): k for k, dd in enumerate(idxl)}
        o, h, l, c, v = (df[x].to_numpy() for x in ("Open", "High", "Low", "Close", "Volume"))
        datestr = [dd.strftime("%Y-%m-%d") for dd in idxl]
        for sd in ds:
            if sd not in pos:
                continue
            rr = simulate(o, h, l, c, v, pos[sd], code, idx_state, datestr, real)
            if rr is None:
                blocked += 1
                continue
            e, ep, xi, xp, ret = rr
            tid = len(trades)
            trades.append(dict(tid=tid, code=code, entry_date=datestr[e], entry_px=float(ep),
                               exit_date=datestr[xi], exit_px=float(xp)))
            closes[tid] = {datestr[d]: float(c[d]) for d in range(e, xi + 1)}
    trades.sort(key=lambda x: x["entry_date"])
    return trades, closes, blocked


def run_portfolio(trades, closes, cost, calendar):
    cash = INIT; openp = {}
    en, ex = defaultdict(list), defaultdict(list)
    for t in trades:
        en[t["entry_date"]].append(t); ex[t["exit_date"]].append(t)
    tmap = {t["tid"]: t for t in trades}
    curve, taken, skipped = [], 0, 0
    for day in calendar:
        for t in ex.get(day, []):
            if t["tid"] in openp:
                cash += openp[t["tid"]]["sh"] * t["exit_px"] * (1 - cost / 2)
                del openp[t["tid"]]
        for t in en.get(day, []):
            if len(openp) >= MAXPOS:
                skipped += 1; continue
            eq = cash + sum(op["sh"] * closes[tid].get(day, tmap[tid]["entry_px"]) for tid, op in openp.items())
            size = eq / MAXPOS
            if cash < size or size <= 0:
                skipped += 1; continue
            sh = size * (1 - cost / 2) / t["entry_px"]
            cash -= size; openp[t["tid"]] = dict(sh=sh); taken += 1
        eq = cash + sum(op["sh"] * closes[tid].get(day, tmap[tid]["entry_px"]) for tid, op in openp.items())
        curve.append((day, eq))
    return curve, taken, skipped


def metrics(curve):
    eq = np.array([e for _, e in curve], float)
    if len(eq) < 2:
        return 0, 0, 0, 0, 0
    rt = eq[-1] / INIT - 1
    yrs = len(eq) / 244.0
    cagr = (eq[-1] / INIT) ** (1 / yrs) - 1 if yrs > 0 else 0
    peak = np.maximum.accumulate(eq); mdd = ((eq - peak) / peak).min()
    dr = np.diff(eq) / eq[:-1]; sh = (dr.mean() / (dr.std() + 1e-9)) * np.sqrt(244) if dr.std() > 0 else 0
    return rt, cagr, mdd, sh, yrs


def main():
    idx = pd.read_csv(IDXCSV, encoding="utf-8-sig"); idx["日期"] = pd.to_datetime(idx["日期"])
    idx = idx.set_index("日期").sort_index()
    ist = F.index_state(idx[["Open", "High", "Low", "Close", "Volume"]])
    idx_state = {d.strftime("%Y-%m-%d"): int(s) for d, s in ist["大盘状态ID"].items()}
    cal_all = [d.strftime("%Y-%m-%d") for d in idx.index]

    sigs_all, sigs_timed = _rule_signals()
    print(f"[v2] A∪B信号 {len(sigs_all)}；大盘择时后 {len(sigs_timed)}", flush=True)

    rows = []
    # 场景1: naive(无约束, 全部信号)
    tr, cl, bl = build_trades(sigs_all, real=False, idx_state=None)
    lo, hi = min(t["entry_date"] for t in tr), max(t["exit_date"] for t in tr)
    cal = [d for d in cal_all if lo <= d <= hi]
    cv, tk, sk = run_portfolio(tr, cl, COST_NAIVE, cal)
    rt, cg, md, sh, yr = metrics(cv)
    rows.append(("naive(无约束/无择时)", len(tr), bl, tk, sk, rt, cg, md, sh))
    # 场景2: 真实约束(择时信号+成交约束+滑点)
    tr2, cl2, bl2 = build_trades(sigs_timed, real=True, idx_state=idx_state)
    cv2, tk2, sk2 = run_portfolio(tr2, cl2, COST_REAL, cal)
    rt2, cg2, md2, sh2, yr2 = metrics(cv2)
    rows.append(("真实约束(择时+成交约束+滑点)", len(tr2), bl2, tk2, sk2, rt2, cg2, md2, sh2))

    L = ["# 真实约束组合回测 vs naive — A∪B 规则", "",
         f"- 初始 {INIT:,.0f}；并发 {MAXPOS}；出场 TP{TP:.0f}/SL{SL:.0f}/{ND}日；约 {yr:.1f} 年",
         f"- 真实约束：①大盘空头/危险不开仓+持仓遇危险强退 ②次日涨停/一字买不进 ③一字跌停卖不出顺延 "
         f"④流动性≥{AMT_FLOOR/1e7:.0f}千万 ⑤成本含滑点{COST_REAL*100:.1f}%(naive{COST_NAIVE*100:.1f}%)", "",
         "| 场景 | 可成交笔数 | 被约束挡掉 | 进场 | 满仓跳过 | 总收益 | 年化 | 最大回撤 | Sharpe |",
         "|---|---|---|---|---|---|---|---|---|"]
    for name, nt, bl_, tk_, sk_, rt_, cg_, md_, sh_ in rows:
        L.append(f"| {name} | {nt} | {bl_} | {tk_} | {sk_} | {rt_*100:.0f}% | {cg_*100:.1f}% | "
                 f"{md_*100:.1f}% | {sh_:.2f} |")
    L += ["", "## 解读",
          "- naive→真实约束 的收益落差 = 大盘择时+涨停买不进(损失部分gap-up大牛)+流动性过滤+滑点 的综合代价。",
          "- 真实约束下的数字才是接近可执行的预期；仍为样本内，实盘再打折。",
          "- 若真实约束后年化仍显著为正且回撤可控 → 策略具备实战价值；否则需降低预期或优化进场方式(如分批/限价)。"]
    open(f"{DIR}/真实约束组合回测_报告.md", "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))
    print("[v2] 完成", flush=True)


if __name__ == "__main__":
    main()
