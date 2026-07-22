# portfolio_backtest_refine.py —— 精选层 vs 基础集 真实约束组合回测对比。
#   复用 portfolio_backtest_v2 的回测引擎(simulate/build_trades/run_portfolio/metrics)。
#   三档同口径(都剔获利盘高 + 大盘择时SID<=2进场 + 持仓遇危险强退 + 成交约束/滑点)：
#     ① A∪B(基础集)      : (极限抄底&量比≥1.3) | 尖刺金叉
#     ② ★精选            : 基础集 ∩ 1买 ∩ 非陷阱(剔 相对强弱≥0 或 大盘多头)
#     ③ ★★核心          : ★精选 ∩ 量能金叉
#   回答：refine_backtest 在逐信号提升度上验证过的精选层，在【组合层+真实约束】是否仍更优(年化/回撤/Sharpe)。
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/portfolio_backtest_refine.py
import sys
sys.path.insert(0, "/app"); sys.path.insert(0, "/app/data/profit_mining")
import pandas as pd
import features as F
import portfolio_backtest_v2 as PB   # 复用引擎与常量(MAXPOS/TP/SL/ND/成本/约束)

DIR = "/app/data/profit_mining"
IDXCSV = f"{DIR}/index_sh000001.csv"


def _signal_sets():
    """构造三档同口径信号集(均已剔获利盘高 + 大盘择时SID<=2)。返回 dict[name]=DataFrame。"""
    f = pd.read_csv(f"{DIR}/signal_features.csv", encoding="utf-8-sig", dtype={"股票代码": str})
    f["股票代码"] = f["股票代码"].str.zfill(6)
    t = pd.read_csv(f"{DIR}/turnover_signal.csv", encoding="utf-8-sig",
                    dtype={"股票代码": str}).drop_duplicates(["股票代码", "信号日期"])
    t["股票代码"] = t["股票代码"].str.zfill(6)
    m = f.merge(t, on=["股票代码", "信号日期"], how="left").drop_duplicates(
        ["股票代码", "信号日期", "买点类型"])

    b = lambda c: pd.to_numeric(m.get(c, 0), errors="coerce").fillna(0).to_numpy() > 0
    ql = pd.to_numeric(m["量比"], errors="coerce").to_numpy()
    rs = pd.to_numeric(m.get("相对强弱", 0), errors="coerce").fillna(0).to_numpy()

    A = b("极限抄底") & (ql >= 1.3)
    B = b("尖刺金叉")
    base = A | B
    profit_high = b("获利盘高")              # 反向过滤(与生产 daily_watchlist 口径一致)
    sid_ok = b("SID小于等于2")               # 大盘择时:剔空头/危险,仅震荡/多头进场
    is1 = (m["买点类型"].to_numpy() == "1买")
    trap = (rs >= 0) | b("大盘多头")         # 陷阱:相对强弱转正 或 大盘多头(极限抄底=震荡超跌反弹,转强失效)
    vjc = b("量能金叉")

    keep = base & (~profit_high) & sid_ok
    refine = keep & is1 & (~trap)
    core = refine & vjc
    return {
        "A∪B(基础集)": m[keep],
        "★精选(1买∩非陷阱)": m[refine],
        "★★核心(精选∩量能金叉)": m[core],
    }


def main():
    idx = pd.read_csv(IDXCSV, encoding="utf-8-sig"); idx["日期"] = pd.to_datetime(idx["日期"])
    idx = idx.set_index("日期").sort_index()
    ist = F.index_state(idx[["Open", "High", "Low", "Close", "Volume"]])
    idx_state = {d.strftime("%Y-%m-%d"): int(s) for d, s in ist["大盘状态ID"].items()}
    cal_all = [d.strftime("%Y-%m-%d") for d in idx.index]

    sets = _signal_sets()
    for name, sg in sets.items():
        print(f"[refine] {name}: 信号 {len(sg)}", flush=True)

    rows = []
    for name, sigs in sets.items():
        tr, cl, bl = PB.build_trades(sigs, real=True, idx_state=idx_state)
        if not tr:
            rows.append((name, len(sigs), 0, bl, 0, 0, 0, 0, 0, 0, 0)); continue
        lo, hi = min(t["entry_date"] for t in tr), max(t["exit_date"] for t in tr)
        cal = [d for d in cal_all if lo <= d <= hi]
        cv, tk, sk = PB.run_portfolio(tr, cl, PB.COST_REAL, cal)
        rt, cg, md, sh, yr = PB.metrics(cv)
        # 笔级胜率(扣成本前的方向胜率,辅助看信号质量)
        wins = sum(1 for t in tr if t["exit_px"] > t["entry_px"])
        wr = wins / len(tr) if tr else 0
        rows.append((name, len(sigs), len(tr), bl, tk, sk, rt, cg, md, sh, wr))
        print(f"[refine] {name} done: 可成交{len(tr)} 进场{tk} 年化{cg*100:.1f}% "
              f"回撤{md*100:.1f}% Sharpe{sh:.2f} 笔胜率{wr*100:.0f}%", flush=True)

    yr_ref = PB.metrics([(d, PB.INIT) for d in cal_all])[4]
    L = ["# 精选层 vs 基础集 — 真实约束组合回测对比", "",
         f"- 引擎复用 portfolio_backtest_v2(并发{PB.MAXPOS}/出场TP{PB.TP:.0f}·SL{PB.SL:.0f}·{PB.ND}日/滑点成本{PB.COST_REAL*100:.1f}%)",
         "- **三档同口径**：都已剔获利盘高 + 大盘择时(SID≤2进场,持仓遇危险SID=4强退) + 成交约束(涨停买不进/一字跌停顺延/流动性≥2千万)。",
         "- 唯一差异 = 精选层叠加的过滤条件（1买 / 非陷阱 / 量能金叉）。", "",
         "| 信号集 | 信号数 | 可成交 | 约束挡掉 | 进场 | 满仓跳过 | 总收益 | 年化 | 最大回撤 | Sharpe | 笔胜率 |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, ns, nt, bl, tk, sk, rt, cg, md, sh, wr in rows:
        L.append(f"| {name} | {ns} | {nt} | {bl} | {tk} | {sk} | {rt*100:.0f}% | {cg*100:.1f}% | "
                 f"{md*100:.1f}% | {sh:.2f} | {wr*100:.0f}% |")
    L += ["", "## 解读",
          "- 若精选层(★精选/★★核心)相对基础集 年化↑ 且 回撤↓/Sharpe↑ → 逐信号提升度在组合层【真实约束下】成立,精选有实战价值。",
          "- 若精选层信号数太少导致进场笔数过少(满仓跳过少但绝对笔数低) → 收益方差大,结论需谨慎,可考虑放宽并发或与基础集混用。",
          "- 精选层因只取1买∩震荡市(非陷阱剔大盘多头)→ 天然集中在震荡市超跌反弹,牛市beta会被让出,这是其'高胜率低beta'特性的代价,非bug。",
          "- 仍为样本内+逐笔近似(非真实撮合),实盘再打折。"]
    out = f"{DIR}/精选层组合回测对比_报告.md"
    open(out, "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))
    print(f"[refine] 报告 -> {out}", flush=True)


if __name__ == "__main__":
    main()
