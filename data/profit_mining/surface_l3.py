# surface_l3.py —— L3 三指标独立榜浮出：后处理 各组方案_全部评分_*.csv，
# 筛 L3 + 算"第三条件增量价值" + 护栏 + 排序 → 独立榜 CSV + md。纯 pandas，只读。
import os, sys, glob, datetime
import pandas as pd

NUM_COLS = ["支持数", "盈利覆盖率", "非盈利覆盖率", "提升度",
            "条件内胜率", "基线胜率", "胜率增益"]


def split_conditions(plan_str):
    """方案名按 ' + ' 切成条件名列表。条件名内含 >=/<= 不受影响。"""
    return [p for p in str(plan_str).split(" + ")]


def load_scores(path):
    """读全量评分 CSV，数值列转 float。字符串列(分组/方案/层级)保持。"""
    df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False)
    for c in NUM_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def build_pair_lift(l2_df):
    """单组 L2 行 → {frozenset({条件x,条件y}): 提升度}。用集合做键,无视存储顺序。"""
    d = {}
    for _, r in l2_df.iterrows():
        names = split_conditions(r["方案"])
        if len(names) == 2:
            d[frozenset(names)] = r["提升度"]
    return d


def l3_marginal(plan_str, l3_lift, pair_lift):
    """L3 三元组 → (最优两两子集 str, 子集提升度, 增量提升度)。
    增量 = L3提升度 − 三个两两子集中提升度最高者。提升度 999 视为 inf 哨兵。"""
    names = split_conditions(plan_str)
    pairs = [(names[0], names[1]), (names[0], names[2]), (names[1], names[2])]
    best_pair, best_lift = None, float("-inf")
    for x, y in pairs:
        lift = pair_lift.get(frozenset((x, y)))
        if lift is None:
            continue
        if lift > best_lift:
            best_lift, best_pair = lift, (x, y)
    if best_pair is None:
        return ("", float("nan"), float("nan"))
    subset_str = f"{best_pair[0]} + {best_pair[1]}"
    if l3_lift >= 999:
        inc = float("inf")
    elif best_lift >= 999:
        inc = float("-inf")
    else:
        inc = l3_lift - best_lift
    return (subset_str, best_lift, inc)


OUT_COLS = ["分组", "方案", "支持数", "盈利覆盖率", "条件内胜率", "基线胜率",
            "胜率增益", "提升度", "最优两两子集", "子集提升度", "增量提升度"]


def surface(df, support_min=100, cover_min=0.20, topn=15):
    """筛 L3 + 算增量 + 护栏(支持≥support_min 且 覆盖≥cover_min) + 每组按提升度Top N。
    返回榜单 DataFrame(列见 OUT_COLS)。"""
    out = []
    for grp, g in df.groupby("分组", sort=False):
        pair_lift = build_pair_lift(g[g["层级"] == "L2"])
        l3 = g[(g["层级"] == "L3") &
               (g["支持数"] >= support_min) &
               (g["盈利覆盖率"] >= cover_min)].copy()
        if l3.empty:
            continue
        marg = l3["方案"].map(lambda p: l3_marginal(
            p, l3.loc[l3["方案"] == p, "提升度"].iloc[0], pair_lift))
        l3["最优两两子集"] = [m[0] for m in marg]
        l3["子集提升度"] = [round(m[1], 3) if pd.notna(m[1]) else m[1] for m in marg]
        l3["增量提升度"] = [round(m[2], 3) if pd.notna(m[2]) else m[2] for m in marg]
        l3 = l3.sort_values("提升度", ascending=False).head(topn)
        out.append(l3[OUT_COLS])
    if not out:
        return pd.DataFrame(columns=OUT_COLS)
    return pd.concat(out, ignore_index=True)


def write_outputs(board, out_dir, ts):
    """榜单 → CSV(全量) + md(每组Top5,标注正增量真协同/负零增量凑数)。返回 [csv, md] 路径。"""
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, f"L3独立榜_{ts}.csv")
    board.to_csv(csv_path, index=False, encoding="utf-8-sig")
    md_path = os.path.join(out_dir, f"L3独立榜_对比_{ts}.md")
    L = ["# L3 三指标独立榜 — 增量价值对比", "", f"生成 {ts}",
         "护栏: 支持≥100 且 盈利覆盖率≥0.20，每组按提升度 Top15；"
         "增量提升度 = L3提升度 − 最优两两子集提升度（正=第三条真协同，负/零=凑数）", ""]
    for grp, sub in board.groupby("分组", sort=False):
        L.append(f"## {grp}（{len(sub)} 条）")
        L.append("| 方案 | 提升度 | 覆盖率 | 增量 | 最优子集 | 判定 |")
        L.append("|---|---|---|---|---|---|")
        for _, r in sub.head(5).iterrows():
            inc = r["增量提升度"]
            good = isinstance(inc, (int, float)) and inc == inc and inc > 0
            verdict = "✅真协同" if good else "⚠️凑数"
            L.append(f"| {r['方案']} | {r['提升度']} | {r['盈利覆盖率']:.0%} | "
                     f"{inc} | {r['最优两两子集']} | {verdict} |")
        L.append("")
    open(md_path, "w", encoding="utf-8").write("\n".join(L))
    return [csv_path, md_path]


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg:
        path = arg
    else:
        cands = sorted(glob.glob("/home/tdxback/report/各组方案_全部评分_*.csv"))
        if not cands:
            print("找不到 各组方案_全部评分_*.csv，请先跑 mine_combos_v2.py"); sys.exit(1)
        path = cands[-1]
    df = load_scores(path)
    if int((df["层级"] == "L3").sum()) == 0:
        print(f"{os.path.basename(path)} 无 L3 行"); sys.exit(1)
    board = surface(df)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    paths = write_outputs(board, "/home/tdxback/report", ts)
    print(f"[L3榜] {len(board)} 行（源 {os.path.basename(path)}）")
    for p in paths:
        print("  写", p)


if __name__ == "__main__":
    main()
