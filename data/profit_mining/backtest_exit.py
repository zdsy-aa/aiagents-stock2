# backtest_exit.py —— 逐bar回测：验证出场规则(止盈/止损/时间止损)的真实收益。
#   进场=信号次日开盘；逐日判定TP/SL(含缺口与同日优先级);扣交易成本。
#   对照=持有到下一缠论买点(区间涨跌幅)。
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/backtest_exit.py
import sys, time
sys.path.insert(0, "/app")
from collections import defaultdict
import numpy as np
import pandas as pd

FEAT = "/app/data/profit_mining/signal_features.csv"
OUTDIR = "/app/data/profit_mining"
_RENAME = {"开盘": "Open", "最高": "High", "最低": "Low", "收盘": "Close", "成交量": "Volume"}
COST = 0.003   # 单边+双边合计交易成本(佣金+印花+滑点)≈0.3%往返
# 待测出场策略 (止盈%, 止损%, 时间止损交易日)
STRATS = [
    ("TP30/SL8/60d", 30, -8, 60),
    ("TP30/SL10/40d", 30, -10, 40),
    ("TP25/SL8/40d", 25, -8, 40),
    ("TP20/SL8/30d", 20, -8, 30),
    ("TP50/SL10/60d", 50, -10, 60),
    ("TP15/SL6/20d", 15, -6, 20),
]


def _load(symbol):
    from akshare_gateway import akshare_gw
    df = akshare_gw.local.get_kline(symbol, kline_type="day", limit=1200)
    if df is None or df.empty:
        return None
    df = df.rename(columns=_RENAME).set_index("日期").sort_index()
    return df[["Open", "High", "Low", "Close"]]


def simulate(o, h, l, c, i, tp, sl, nd):
    """从信号位i进场(次日开盘)，返回(净收益%, 持有天数, 出场类型)。"""
    n = len(c)
    if i + 1 >= n:
        return None
    entry = o[i + 1]
    if entry <= 0:
        return None
    tp_px, sl_px = entry * (1 + tp / 100), entry * (1 + sl / 100)
    end = min(i + nd, n - 1)
    for d in range(i + 1, end + 1):
        # 缺口优先：开盘已穿
        if o[d] >= tp_px:
            return (o[d] / entry - 1) * 100 - COST * 100, d - i, "止盈(缺口)"
        if o[d] <= sl_px:
            return (o[d] / entry - 1) * 100 - COST * 100, d - i, "止损(缺口)"
        # 同日TP/SL：保守假设先触止损
        if l[d] <= sl_px:
            return sl - COST * 100, d - i, "止损"
        if h[d] >= tp_px:
            return tp - COST * 100, d - i, "止盈"
    # 时间止损：末日收盘
    return (c[end] / entry - 1) * 100 - COST * 100, end - i, "时间止损"


def run_rule(df_feat, rule_mask, label):
    sigs = df_feat[rule_mask]
    by_code = defaultdict(list)
    for _, r in sigs.iterrows():
        by_code[str(r["股票代码"]).zfill(6)].append((r["信号日期"], float(r["区间涨跌幅"])))
    results = {s[0]: [] for s in STRATS}
    base = []   # 对照：持有到下一买点
    t0 = time.time()
    for code, lst in by_code.items():
        df = _load(code)
        if df is None or len(df) < 70:
            continue
        pos = {d.strftime("%Y-%m-%d"): k for k, d in enumerate(df.index)}
        o, h, l, c = (df[x].to_numpy() for x in ("Open", "High", "Low", "Close"))
        for sd, qj in lst:
            if sd not in pos:
                continue
            i = pos[sd]
            base.append(qj - COST * 100)
            for name, tp, sl, nd in STRATS:
                rr = simulate(o, h, l, c, i, tp, sl, nd)
                if rr is not None:
                    results[name].append(rr)
    return results, base


def stats(rets):
    a = np.array([r[0] if isinstance(r, tuple) else r for r in rets], dtype=float)
    if len(a) == 0:
        return None
    wins, losses = a[a > 0], a[a <= 0]
    pf = wins.sum() / (-losses.sum()) if losses.sum() < 0 else np.inf
    return dict(n=len(a), 胜率=float((a > 0).mean()),
                平均=float(a.mean()), 中位=float(np.median(a)),
                盈亏比PF=float(pf) if np.isfinite(pf) else 99.0,
                最大单笔=float(a.max()), 最差单笔=float(a.min()))


def main():
    f = pd.read_csv(FEAT, encoding="utf-8-sig")
    f["量比_v"] = pd.to_numeric(f["量比"], errors="coerce")
    f["区间涨跌幅"] = pd.to_numeric(f["区间涨跌幅"], errors="coerce")
    b = lambda col: pd.to_numeric(f.get(col, 0), errors="coerce").fillna(0) > 0
    rule = b("极限抄底") & (f["量比_v"] >= 1.3)
    print(f"[回测] 规则信号数 {int(rule.sum())}，成本/往返 {COST*100:.1f}%", flush=True)
    results, base = run_rule(f, rule, "极限抄底+量比≥1.3")

    L = ["# 出场规则逐bar回测 — 极限抄底+量比≥1.3", "",
         f"- 信号 {int(rule.sum())}；进场=信号次日开盘；交易成本往返 {COST*100:.1f}%；同日TP/SL保守先止损",
         "- 收益单位 %（已扣成本）", "",
         "| 出场策略 | 笔数 | 胜率 | 平均收益 | 中位 | 盈亏比PF | 最大单笔 | 最差单笔 |",
         "|---|---|---|---|---|---|---|---|"]
    bs = stats(base)
    L.append(f"| 对照:持有到下一买点 | {bs['n']} | {bs['胜率']:.0%} | {bs['平均']:.1f}% | "
             f"{bs['中位']:.1f}% | {bs['盈亏比PF']:.2f} | {bs['最大单笔']:.0f}% | {bs['最差单笔']:.0f}% |")
    for name, *_ in STRATS:
        s = stats(results[name])
        if s:
            L.append(f"| {name} | {s['n']} | {s['胜率']:.0%} | {s['平均']:.1f}% | {s['中位']:.1f}% | "
                     f"{s['盈亏比PF']:.2f} | {s['最大单笔']:.0f}% | {s['最差单笔']:.0f}% |")
    open(f"{OUTDIR}/出场回测_报告.md", "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))
    print("[回测] 完成", flush=True)


if __name__ == "__main__":
    main()
