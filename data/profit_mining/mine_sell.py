# mine_sell.py —— 缠论卖点共同特征挖掘（复用 mine_combos 评分器）。
#   标签是否盈利=好卖点(卖后跌≥4%)。运行: docker exec -w /app agentsstock1 python3 .../mine_sell.py
import pandas as pd
import mine_combos as MC

MC.FEAT = "/app/data/profit_mining/sell_features.csv"
OUTDIR = "/app/data/profit_mining"


def main():
    df = MC.load()
    base = df["是否盈利"].mean()
    groups = {"全部卖点": df}
    for t in ("1卖", "2卖", "3卖"):
        sub = df[df["买点类型"] == t]
        if len(sub) >= 200:
            groups[t] = sub
    rows = []
    for lbl, g in groups.items():
        conds = MC.build_conditions(g.reset_index(drop=True))
        rows.append(MC.score_group(g.reset_index(drop=True), lbl, conds))
    scores = pd.concat(rows, ignore_index=True)
    scores = scores[scores["支持数"] >= MC.SUPPORT_MIN]
    scores.to_csv(f"{OUTDIR}/卖点方案_全部评分.csv", index=False, encoding="utf-8-sig")
    lift = scores.sort_values(["分组", "提升度"], ascending=[True, False])
    lift.to_csv(f"{OUTDIR}/卖点方案_高提升度榜.csv", index=False, encoding="utf-8-sig")

    L = ["# 缠论卖点共同特征报告", "",
         f"- 样本 {len(df)}；好卖点(卖后跌≥4%) {int((df['是否盈利']==1).sum())} ({base*100:.1f}%)",
         "- 标签：好卖点=到下一卖点区间跌≥4%；提升度=好卖点组/坏卖点组覆盖率之比", ""]
    for lbl in groups:
        gb = groups[lbl]["是否盈利"].mean()
        sub = lift[(lift["分组"] == lbl) & (lift["支持数"] >= 80)].head(12)
        L.append(f"## {lbl}（基线 {gb:.0%}）")
        if len(sub) == 0:
            L.append("（无满足条件方案）\n"); continue
        L.append("| 卖点特征/组合 | 层 | 提升度 | 条件内好卖率 | 支持数 |")
        L.append("|---|---|---|---|---|")
        for _, r in sub.iterrows():
            L.append(f"| {r['方案'][:44]} | {r['层级']} | {r['提升度']} | {r['条件内胜率']:.0%} | {int(r['支持数'])} |")
        L.append("")
    open(f"{OUTDIR}/卖点共同特征_报告.md", "w", encoding="utf-8").write("\n".join(L))
    print(f"[卖点挖掘] 完成：方案 {len(scores)}", flush=True)
    print("\n".join(L[:4]))


if __name__ == "__main__":
    main()
