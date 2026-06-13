# mine_regime.py —— 震荡市(SID=2)子样本内精排：在最有效的市场环境里找最优完整配方。
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/mine_regime.py
import pandas as pd
import mine_combos as MC

OUTDIR = "/app/data/profit_mining"


def main():
    df = MC.load()
    # 震荡市 = SID等于2 为真（多头=SID1，空头/危险=其余）
    sid2 = pd.to_numeric(df["SID等于2"], errors="coerce").fillna(0) > 0
    reg = df[sid2].reset_index(drop=True)
    print(f"[震荡市精排] 震荡市样本 {len(reg)}，盈利率 {reg['是否盈利'].mean()*100:.1f}%", flush=True)

    groups = {"震荡-全样本": reg}
    for t in ("1买", "2买", "3买"):
        sub = reg[reg["买点类型"] == t]
        if len(sub) >= 200:
            groups[f"震荡-{t}"] = sub

    all_rows = []
    for lbl, g in groups.items():
        conds = MC.build_conditions(g.reset_index(drop=True))
        all_rows.append(MC.score_group(g.reset_index(drop=True), lbl, conds))
    scores = pd.concat(all_rows, ignore_index=True)
    scores = scores[scores["支持数"] >= MC.SUPPORT_MIN]
    scores.to_csv(f"{OUTDIR}/震荡市精排_全部评分.csv", index=False, encoding="utf-8-sig")

    # 榜单：支持数>=80 且 提升度>=1.5，按 (条件内胜率, 支持数) 排
    board = scores[(scores["支持数"] >= 80) & (scores["提升度"] >= 1.5)].sort_values(
        ["分组", "条件内胜率", "支持数"], ascending=[True, False, False])
    board.to_csv(f"{OUTDIR}/震荡市精排_优选榜.csv", index=False, encoding="utf-8-sig")

    # 报告
    L = ["# 震荡市(SID=2)子样本精排报告", "",
         f"- 震荡市样本 {len(reg)}，该环境基线胜率 {reg['是否盈利'].mean()*100:.1f}%",
         "- 优选条件：支持数≥80 且 提升度≥1.5，按条件内胜率排序", ""]
    for lbl in groups:
        base = groups[lbl]["是否盈利"].mean()
        sub = board[board["分组"] == lbl].head(12)
        L.append(f"## {lbl}（基线 {base:.0%}）")
        if len(sub) == 0:
            L.append("（无满足条件的方案）\n"); continue
        L.append("| 配方 | 层 | 条件内胜率 | 提升度 | 支持数 |")
        L.append("|---|---|---|---|---|")
        for _, r in sub.iterrows():
            L.append(f"| {r['方案'][:46]} | {r['层级']} | {r['条件内胜率']:.0%} | {r['提升度']} | {int(r['支持数'])} |")
        L.append("")
    open(f"{OUTDIR}/震荡市精排_报告.md", "w", encoding="utf-8").write("\n".join(L))
    print(f"[震荡市精排] 完成：方案 {len(scores)}；优选 {len(board)}", flush=True)


if __name__ == "__main__":
    main()
