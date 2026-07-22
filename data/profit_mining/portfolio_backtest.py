# portfolio_backtest.py —— 组合级回测：并发持仓上限+仓位管理+逐日盯市，出资金曲线/年化/最大回撤。
#   规则=极限抄底+量比≥1.3；进场次日开盘；出场TP/SL/时间止损；扣0.3%成本。
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/portfolio_backtest.py
import sys, time
sys.path.insert(0, "/app")
from collections import defaultdict
import numpy as np
import pandas as pd

FEAT = "/app/data/profit_mining/signal_features.csv"
IDXCSV = "/app/data/profit_mining/index_sh000001.csv"
OUTDIR = "/app/data/profit_mining"
_RENAME = {"开盘": "Open", "最高": "High", "最低": "Low", "收盘": "Close", "成交量": "Volume"}
COST = 0.003
INIT = 1_000_000.0
TP, SL, ND = 30.0, -8.0, 60          # 验证过较稳健的出场
CONFIGS = [5, 10, 20]                 # 最大并发持仓数敏感性


def _load(symbol):
    from akshare_gateway import akshare_gw
    df = akshare_gw.local.get_kline(symbol, kline_type="day", limit=1200)
    if df is None or df.empty:
        return None
    df = df.rename(columns=_RENAME).set_index("日期").sort_index()
    return df[["Open", "High", "Low", "Close"]]


def sim_exit(o, h, l, c, i):
    """进场i+1开盘，返回 (entry_date_idx, entry_px, exit_idx, exit_px)。"""
    n = len(c)
    if i + 1 >= n:
        return None
    e = i + 1
    entry = o[e]
    if entry <= 0:
        return None
    tp_px, sl_px = entry * (1 + TP / 100), entry * (1 + SL / 100)
    end = min(i + ND, n - 1)
    for d in range(e, end + 1):
        if o[d] >= tp_px:
            return e, entry, d, o[d]
        if o[d] <= sl_px:
            return e, entry, d, o[d]
        if l[d] <= sl_px:
            return e, entry, d, sl_px
        if h[d] >= tp_px:
            return e, entry, d, tp_px
    return e, entry, end, c[end]


def build_trades(rule_mask, feat):
    sigs = feat[rule_mask]
    by_code = defaultdict(list)
    for _, r in sigs.iterrows():
        by_code[str(r["股票代码"]).zfill(6)].append(r["信号日期"])
    trades = []
    closes = {}   # idx -> {date:close} 持仓期收盘路径(盯市用)
    for code, dates in by_code.items():
        df = _load(code)
        if df is None or len(df) < 70:
            continue
        idx = list(df.index)
        pos = {d.strftime("%Y-%m-%d"): k for k, d in enumerate(idx)}
        o, h, l, c = (df[x].to_numpy() for x in ("Open", "High", "Low", "Close"))
        cser = df["Close"]
        for sd in dates:
            if sd not in pos:
                continue
            rr = sim_exit(o, h, l, c, pos[sd])
            if rr is None:
                continue
            e, ep, xi, xp = rr
            tid = len(trades)
            path = {idx[d].strftime("%Y-%m-%d"): float(c[d]) for d in range(e, xi + 1)}
            trades.append(dict(tid=tid, code=code,
                               entry_date=idx[e].strftime("%Y-%m-%d"), entry_px=float(ep),
                               exit_date=idx[xi].strftime("%Y-%m-%d"), exit_px=float(xp)))
            closes[tid] = path
    trades.sort(key=lambda t: t["entry_date"])
    return trades, closes


def run_portfolio(trades, closes, max_pos, calendar):
    cash = INIT
    open_pos = {}   # tid -> dict(shares, code)
    entries_by_date = defaultdict(list)
    exits_by_date = defaultdict(list)
    for t in trades:
        entries_by_date[t["entry_date"]].append(t)
        exits_by_date[t["exit_date"]].append(t)
    equity_curve, taken, skipped, concur = [], 0, 0, []
    tmap = {t["tid"]: t for t in trades}
    for day in calendar:
        # 出场（先于进场，释放槽与资金）
        for t in exits_by_date.get(day, []):
            if t["tid"] in open_pos:
                sh = open_pos[t["tid"]]["shares"]
                cash += sh * t["exit_px"] * (1 - COST / 2)
                del open_pos[t["tid"]]
        # 进场
        for t in entries_by_date.get(day, []):
            if len(open_pos) >= max_pos:
                skipped += 1
                continue
            equity_now = cash + sum(op["shares"] * closes[tid].get(day, tmap[tid]["entry_px"])
                                    for tid, op in open_pos.items())
            size = equity_now / max_pos
            if cash < size or size <= 0:
                skipped += 1
                continue
            sh = size * (1 - COST / 2) / t["entry_px"]
            cash -= size
            open_pos[t["tid"]] = dict(shares=sh, code=t["code"])
            taken += 1
        # 盯市
        eq = cash + sum(op["shares"] * closes[tid].get(day, tmap[tid]["entry_px"])
                        for tid, op in open_pos.items())
        equity_curve.append((day, eq))
        concur.append(len(open_pos))
    return equity_curve, taken, skipped, concur


def metrics(curve):
    eq = np.array([e for _, e in curve], dtype=float)
    ret_total = eq[-1] / INIT - 1
    days = len(eq)
    years = days / 244.0
    cagr = (eq[-1] / INIT) ** (1 / years) - 1 if years > 0 else 0
    peak = np.maximum.accumulate(eq)
    mdd = ((eq - peak) / peak).min()
    daily = np.diff(eq) / eq[:-1]
    sharpe = (daily.mean() / (daily.std() + 1e-9)) * np.sqrt(244) if daily.std() > 0 else 0
    return ret_total, cagr, mdd, sharpe, years


def main():
    f = pd.read_csv(FEAT, encoding="utf-8-sig")
    f["量比_v"] = pd.to_numeric(f["量比"], errors="coerce")
    b = lambda col: pd.to_numeric(f.get(col, 0), errors="coerce").fillna(0) > 0
    rule = b("极限抄底") & (f["量比_v"] >= 1.3)
    print(f"[组合回测] 规则信号 {int(rule.sum())}，构建交易…", flush=True)
    trades, closes = build_trades(rule, f)
    print(f"  可成交交易 {len(trades)} 笔", flush=True)
    idx = pd.read_csv(IDXCSV, encoding="utf-8-sig")
    idx["日期"] = pd.to_datetime(idx["日期"]).dt.strftime("%Y-%m-%d")
    lo = min(t["entry_date"] for t in trades)
    hi = max(t["exit_date"] for t in trades)
    calendar = [d for d in sorted(idx["日期"]) if lo <= d <= hi]

    L = ["# 组合级回测 — 极限抄底+量比≥1.3", "",
         f"- 初始资金 {INIT:,.0f}；出场 TP{TP:.0f}%/SL{SL:.0f}%/{ND}日；成本往返 {COST*100:.1f}%；等权 1/N 仓位",
         f"- 可成交信号 {len(trades)} 笔；区间 {lo} ~ {hi}", "",
         "| 最大并发 | 进场笔数 | 跳过(满仓) | 总收益 | 年化CAGR | 最大回撤 | Sharpe | 平均持仓数 |",
         "|---|---|---|---|---|---|---|---|"]
    saved = None
    for mp in CONFIGS:
        curve, taken, skipped, concur = run_portfolio(trades, closes, mp, calendar)
        rt, cagr, mdd, sh, yrs = metrics(curve)
        L.append(f"| {mp} | {taken} | {skipped} | {rt*100:.0f}% | {cagr*100:.1f}% | "
                 f"{mdd*100:.1f}% | {sh:.2f} | {np.mean(concur):.1f} |")
        if mp == 10:
            saved = curve
    L += ["", f"- 区间约 {metrics(saved)[4]:.1f} 年。说明：等权满仓即跳过(不追)；盯市用持仓收盘价。",
          "- 局限：未含停牌/涨跌停无法成交、个股流动性冲击；仓位等权未做波动率/凯利优化；单一规则未叠加大盘择时(空头/危险期应降仓)。"]
    # 资金曲线落盘(并发=10)
    if saved:
        pd.DataFrame(saved, columns=["日期", "权益"]).to_csv(
            f"{OUTDIR}/组合回测_资金曲线_并发10.csv", index=False, encoding="utf-8-sig")
    open(f"{OUTDIR}/组合回测_报告.md", "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))
    print("[组合回测] 完成", flush=True)


if __name__ == "__main__":
    main()
