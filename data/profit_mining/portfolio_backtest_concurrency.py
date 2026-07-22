# portfolio_backtest_concurrency.py —— 并发敏感性:精选层"信号聚集→满仓跳过"是否因放宽并发而改善。
#   承接 portfolio_backtest_refine 的发现:★精选笔胜率89%最高,但并发10下95%满仓跳过→年化仅3%。
#   本脚本:每个信号集 build_trades 只跑一次(IO重),复用到多个并发档 run_portfolio(轻量),
#   看放宽 MAXPOS(10→20→30→50)能否把精选层的高笔胜率转成更高年化(且回撤可控)。
#   等权 1/N 仓位:放宽并发=单笔自动变小(更分散),不超资金。
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/portfolio_backtest_concurrency.py
import sys
sys.path.insert(0, "/app"); sys.path.insert(0, "/app/data/profit_mining")
import pandas as pd
import features as F
import portfolio_backtest_v2 as PB
from portfolio_backtest_refine import _signal_sets

DIR = "/app/data/profit_mining"
IDXCSV = f"{DIR}/index_sh000001.csv"
MAXPOS_GRID = [10, 20, 30, 50]


def main():
    idx = pd.read_csv(IDXCSV, encoding="utf-8-sig"); idx["日期"] = pd.to_datetime(idx["日期"])
    idx = idx.set_index("日期").sort_index()
    ist = F.index_state(idx[["Open", "High", "Low", "Close", "Volume"]])
    idx_state = {d.strftime("%Y-%m-%d"): int(s) for d, s in ist["大盘状态ID"].items()}
    cal_all = [d.strftime("%Y-%m-%d") for d in idx.index]

    sets = _signal_sets()
    rows = []
    for name, sigs in sets.items():
        # build 一次(含全历史K线加载+成交约束模拟),复用到各并发档
        tr, cl, bl = PB.build_trades(sigs, real=True, idx_state=idx_state)
        if not tr:
            print(f"[conc] {name}: 无可成交,跳过", flush=True); continue
        lo, hi = min(t["entry_date"] for t in tr), max(t["exit_date"] for t in tr)
        cal = [d for d in cal_all if lo <= d <= hi]
        wins = sum(1 for t in tr if t["exit_px"] > t["entry_px"])
        wr = wins / len(tr)
        print(f"[conc] {name}: 可成交{len(tr)} 笔胜率{wr*100:.0f}% — 扫并发档…", flush=True)
        for mp in MAXPOS_GRID:
            PB.MAXPOS = mp                       # monkey-patch:run_portfolio/单笔size 均读 PB.MAXPOS
            cv, tk, sk = PB.run_portfolio(tr, cl, PB.COST_REAL, cal)
            rt, cg, md, sh, yr = PB.metrics(cv)
            util = tk / len(tr) if tr else 0      # 进场/可成交 = 资金利用率代理
            rows.append((name, mp, len(tr), tk, sk, util, rt, cg, md, sh, wr))
            print(f"    并发{mp}: 进场{tk} 跳过{sk} 利用率{util*100:.0f}% "
                  f"年化{cg*100:.1f}% 回撤{md*100:.1f}% Sharpe{sh:.2f}", flush=True)
    PB.MAXPOS = 10                                # 复原默认,避免污染同进程后续

    L = ["# 并发敏感性 — 精选层信号聚集能否靠放宽并发消化", "",
         f"- 引擎 portfolio_backtest_v2(出场TP{PB.TP:.0f}·SL{PB.SL:.0f}·{PB.ND}日/真实约束/滑点{PB.COST_REAL*100:.1f}%);等权1/N,放宽并发=单笔自动变小。",
         "- 问题:★精选笔胜率89%却年化仅3%(并发10下95%满仓跳过)。放宽并发能否把高胜率转成高年化?", "",
         "| 信号集 | 并发上限 | 可成交 | 进场 | 满仓跳过 | 利用率 | 总收益 | 年化 | 最大回撤 | Sharpe | 笔胜率 |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, mp, nt, tk, sk, util, rt, cg, md, sh, wr in rows:
        L.append(f"| {name} | {mp} | {nt} | {tk} | {sk} | {util*100:.0f}% | {rt*100:.0f}% | "
                 f"{cg*100:.1f}% | {md*100:.1f}% | {sh:.2f} | {wr*100:.0f}% |")
    L += ["", "## 解读",
          "- 若精选层年化随并发放宽显著上升且回撤可控 → 之前年化低纯是并发约束(信号聚集)所致,edge是真的,放宽并发即可释放。",
          "- 若年化提升有限/Sharpe下降 → 信号聚集太极端(同期扎堆),即便放宽并发也只是摊薄,需加仓/分批等机制,或确认精选层只适合做排序而非独立组合。",
          "- 放宽并发的代价:单笔仓位变小→个股层面收益贡献摊薄;实盘还有最低交易额/管理成本约束,并发不宜无限大。",
          "- 仍为样本内+逐笔近似。"]
    out = f"{DIR}/并发敏感性_精选层_报告.md"
    open(out, "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))
    print(f"[conc] 报告 -> {out}", flush=True)


if __name__ == "__main__":
    main()
