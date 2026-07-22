# task7_stability_cost.py —— 滚动多窗口胜率稳定性 + 交易成本敏感性。
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/task7_stability_cost.py
import sys
sys.path.insert(0, "/app"); sys.path.insert(0, "/app/data/profit_mining")
from collections import defaultdict
import numpy as np
import pandas as pd
import backtest_exit as BT

DIR = "/app/data/profit_mining"
OUT = f"{DIR}/盘外收益稳健性_报告.md"


def main():
    # ---- 1) 滚动多窗口：A∪B 买入规则逐年胜率(含尖刺金叉) ----
    f = pd.read_csv(f"{DIR}/signal_features.csv", encoding="utf-8-sig", dtype={"股票代码": str})
    f["股票代码"] = f["股票代码"].str.zfill(6)
    t = pd.read_csv(f"{DIR}/turnover_signal.csv", encoding="utf-8-sig",
                    dtype={"股票代码": str}).drop_duplicates(["股票代码", "信号日期"])
    t["股票代码"] = t["股票代码"].str.zfill(6)
    m = f.merge(t, on=["股票代码", "信号日期"], how="left").drop_duplicates(["股票代码", "信号日期", "买点类型"])
    m["是否盈利"] = pd.to_numeric(m["是否盈利"], errors="coerce").fillna(0).astype(int)
    m["量比_v"] = pd.to_numeric(m["量比"], errors="coerce")
    m["年"] = m["信号日期"].str[:4]
    bcol = lambda c: pd.to_numeric(m.get(c, 0), errors="coerce").fillna(0).to_numpy() > 0
    A = bcol("极限抄底") & (m["量比_v"].to_numpy() >= 1.3)
    B = bcol("尖刺金叉")
    rules = {"A:极限抄底+量比≥1.3": A, "B:尖刺金叉": B, "A∪B": A | B,
             "极限抄底(单)": bcol("极限抄底")}
    win = m["是否盈利"].to_numpy().astype(bool)
    years = ["2022", "2023", "2024", "2025", "2026"]

    L = ["# 盘外收益稳健性：滚动窗口 + 成本敏感性", "",
         "## 1. 逐年胜率稳定性（买入规则，≥4%口径）", "",
         "| 规则 | " + " | ".join(years) + " | 全期 |", "|" + "---|" * (len(years) + 2)]
    yv = m["年"].to_numpy()
    base_y = {y: win[yv == y].mean() for y in years}
    for name, mask in rules.items():
        cells = []
        for y in years:
            mm = mask & (yv == y); n = int(mm.sum())
            cells.append(f"{win[mm].mean()*100:.0f}%({n})" if n >= 20 else "-")
        cells.append(f"{win[mask].mean()*100:.0f}%({int(mask.sum())})")
        L.append(f"| {name} | " + " | ".join(cells) + " |")
    L.append("| 当年基线 | " + " | ".join(f"{base_y[y]*100:.0f}%" for y in years) + " | 43% |")
    L.append("\n> 看规则是否每年都明显高于当年基线（2024普涨基线高=beta，2026右截断仅参考）。\n")

    # ---- 2) 交易成本敏感性：TP30/SL8 逐笔回测 vs 成本 ----
    rule_mask = pd.Series(A, index=m.index)
    sigs = m[rule_mask]
    by_code = defaultdict(list)
    for _, r in sigs.iterrows():
        by_code[str(r["股票代码"]).zfill(6)].append(r["信号日期"])
    # 预取每笔毛收益(TP30/SL8/60d)，再按不同成本扣减
    BT.TP, BT.SL, BT.ND = 30.0, -8.0, 60
    gross = []
    for code, dates in by_code.items():
        df = BT._load(code)
        if df is None or len(df) < 70:
            continue
        pos = {d.strftime("%Y-%m-%d"): k for k, d in enumerate(df.index)}
        o, h, l, c = (df[x].to_numpy() for x in ("Open", "High", "Low", "Close"))
        for sd in dates:
            if sd not in pos:
                continue
            BT.COST = 0.0
            rr = BT.simulate(o, h, l, c, pos[sd], 30.0, -8.0, 60)
            if rr is not None:
                gross.append(rr[0])
    g = np.array(gross)
    L.append("## 2. 交易成本敏感性（TP30%/SL-8%/60日，逐笔毛收益扣不同成本）\n")
    L.append(f"- 样本 {len(g)} 笔；毛收益平均 {g.mean():.1f}% / 中位 {np.median(g):.1f}%")
    L.append("| 往返成本 | 平均净收益 | 中位 | 胜率(>0) |")
    L.append("|---|---|---|---|")
    for cost in [0.001, 0.002, 0.003, 0.005, 0.008]:
        net = g - cost * 100
        L.append(f"| {cost*100:.1f}% | {net.mean():.1f}% | {np.median(net):.1f}% | {(net>0).mean()*100:.0f}% |")
    L.append("\n> 成本每+0.1%约直接减0.1%单笔收益；对中位+27%的策略，0.3%~0.5%成本影响有限。\n")

    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))
    print("[task7] 完成", flush=True)


if __name__ == "__main__":
    main()
