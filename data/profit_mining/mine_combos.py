# mine_combos.py —— 阶段2：在 signal_features.csv 上生成 L1/L2/L5 测试方案，
#   向量化算覆盖率/提升度/胜率并排序出榜。
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/mine_combos.py
import itertools
import numpy as np
import pandas as pd

FEAT = "/app/data/profit_mining/signal_features.csv"
OUTDIR = "/app/data/profit_mining"
COVER_MIN = 0.70      # 主榜盈利覆盖率门槛
SUPPORT_MIN = 50      # 进榜最小支持数
TOPK_FOR_PAIR = None  # None=全部布尔条件两两组合
TOPK_TRIPLE = 18      # L3三联：取L1提升度Top-N做三联AND（C(18,3)=816/组）

# L4 参数遍历：连续量的精细阈值网格 (列, 方向, [阈值...])
L4_GRID = {
    "量比": (">=", [1.0, 1.3, 1.5, 2.0, 2.5, 3.0]),
    "距60日高点贴近": ("距60日高点", ">=", [0.85, 0.9, 0.95, 1.0]),
    "距60日高点深跌": ("距60日高点", "<=", [0.5, 0.6, 0.7, 0.8]),
    "距60日低点": ("距60日低点", "<=", [1.0, 1.05, 1.1, 1.2]),
    "相对强弱": (">=", [-5.0, 0.0, 5.0, 10.0, 15.0]),
}
# L4 锚点：与精细阈值条件配对的强基础条件
L4_ANCHORS = ["极限抄底", "量能金叉", "大盘安全", "偏多共振", "中枢进机会区"]

# 连续列派生的布尔条件： (列, 运算, 阈值, 展示名)
CONT_CONDS = [
    ("量比", ">=", 1.3, "量比>=1.3"),
    ("量比", ">=", 2.0, "量比>=2"),
    ("距60日高点", ">=", 0.9, "距前高<=10%"),
    ("距60日高点", "<=", 0.6, "深跌(距前高>40%)"),
    ("距60日低点", "<=", 1.1, "距前低<=10%"),
    ("相对强弱", ">=", 0.0, "相对强弱>=0"),
    ("相对强弱", ">=", 5.0, "相对强弱>=5"),
]

# L5 手册精选强方案（仅用首轮已实现的条件；缺失条件的方案自动跳过）
L5_SCHEMES = {
    "S-威科夫最强": ["威科夫B3弹簧", "大盘安全", "量比>=1.3"],
    "S-威科夫突破": ["威科夫B1突破", "SID小于等于2", "放量"],
    "S-斐波趋势": ["斐波全多头", "价涨量增", "相对强弱>=0"],
    "S-中枢突破": ["中枢上方", "突破前高", "MACD_DIF大于0"],
    "S-六脉震荡": ["六脉6红首发", "SID等于2", "量能递增"],
    "S-黄金柱妖股": ["黄金柱", "大盘多头", "相对强弱>=5"],
    "S-MACD金叉多头": ["MACD零轴上金叉", "趋势多头", "放量"],
    "S-超跌反弹": ["深跌(距前高>40%)", "大盘5日上涨", "MACD金叉态"],
    "S-火箭打板": ["火箭信号", "大盘多头", "相对强弱>=5"],
    "S-回马枪": ["回马枪", "SID小于等于2"],
    "S-极限抄底反弹": ["极限抄底", "大盘安全"],
    "S-中枢机会区": ["中枢进机会区", "量比>=1.3"],
    "S-主力启动": ["主力启动", "大盘多头"],
    "S-摇钱树": ["摇钱树", "放量"],
    "S-纳财突破": ["纳财", "相对强弱>=0"],
}

META = ["股票代码", "股票名称", "板块", "买点类型", "信号日期", "区间涨跌幅", "是否盈利"]


def load():
    df = pd.read_csv(FEAT, encoding="utf-8-sig")
    df["是否盈利"] = pd.to_numeric(df["是否盈利"], errors="coerce").fillna(0).astype(int)
    return df


def build_conditions(df):
    """返回 {条件名: 布尔ndarray}。含布尔列 + 连续派生。"""
    cont_src = {c for c, _, _, _ in CONT_CONDS}
    conds = {}
    for col in df.columns:
        if col in META or col in cont_src:
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        if s.dropna().isin([0, 1]).all() and s.notna().any():
            conds[col] = (s.fillna(0) > 0).to_numpy()
    for col, op, thr, disp in CONT_CONDS:
        if col in df.columns:
            s = pd.to_numeric(df[col], errors="coerce")
            conds[disp] = ((s >= thr) if op == ">=" else (s <= thr)).fillna(False).to_numpy()
    return conds


def metrics(mask, win, group, name):
    sup = int(mask.sum())
    nwin, nlose = int(win.sum()), int((~win).sum())
    cw = float((mask & win).sum()) / nwin if nwin else 0
    cl = float((mask & ~win).sum()) / nlose if nlose else 0
    wr = float((mask & win).sum()) / sup if sup else 0
    base = nwin / len(win) if len(win) else 0
    lift = cw / cl if cl > 0 else np.inf
    return {"分组": group, "方案": name, "支持数": sup,
            "盈利覆盖率": round(cw, 4), "非盈利覆盖率": round(cl, 4),
            "提升度": round(lift, 3) if np.isfinite(lift) else 999,
            "条件内胜率": round(wr, 4), "基线胜率": round(base, 4),
            "胜率增益": round(wr - base, 4)}


def build_l4_conds(df):
    """L4 精细阈值条件 {展示名: 布尔ndarray}。"""
    out = {}
    for key, spec in L4_GRID.items():
        if len(spec) == 2:
            col, (op, thrs) = key, spec
        else:
            col, op, thrs = spec
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        for thr in thrs:
            disp = f"{col}{op}{thr}"
            out[disp] = ((s >= thr) if op == ">=" else (s <= thr)).fillna(False).to_numpy()
    return out


def score_group(df, group_label, conds):
    win = (df["是否盈利"] == 1).to_numpy()
    names = list(conds)
    rows = []
    # L1 单条件
    l1 = {}
    for n in names:
        m = metrics(conds[n], win, group_label, n)
        l1[n] = m
        rows.append({**m, "层级": "L1"})
    # L2 两两AND
    pair_names = names if TOPK_FOR_PAIR is None else names[:TOPK_FOR_PAIR]
    for a, b in itertools.combinations(pair_names, 2):
        m = conds[a] & conds[b]
        if int(m.sum()) < SUPPORT_MIN:
            continue
        rows.append({**metrics(m, win, group_label, f"{a} + {b}"), "层级": "L2"})
    # L3 三联AND：取L1提升度Top-N(支持数>=100)
    cand = sorted([n for n in names if l1[n]["支持数"] >= 100],
                  key=lambda n: -l1[n]["提升度"])[:TOPK_TRIPLE]
    for a, b, cc in itertools.combinations(cand, 3):
        m = conds[a] & conds[b] & conds[cc]
        if int(m.sum()) < SUPPORT_MIN:
            continue
        rows.append({**metrics(m, win, group_label, f"{a} + {b} + {cc}"), "层级": "L3"})
    # L4 参数遍历：精细阈值单条件 + 与锚点配对
    l4 = build_l4_conds(df)
    for n, arr in l4.items():
        if int(arr.sum()) >= SUPPORT_MIN:
            rows.append({**metrics(arr, win, group_label, n), "层级": "L4"})
        for anc in L4_ANCHORS:
            if anc in conds:
                m = arr & conds[anc]
                if int(m.sum()) >= SUPPORT_MIN:
                    rows.append({**metrics(m, win, group_label, f"{anc} + {n}"), "层级": "L4"})
    # L5 手册方案
    for sname, parts in L5_SCHEMES.items():
        if not all(p in conds for p in parts):
            continue
        m = np.ones(len(df), dtype=bool)
        for p in parts:
            m &= conds[p]
        rows.append({**metrics(m, win, group_label, f"{sname}［{' + '.join(parts)}］"), "层级": "L5"})
    return pd.DataFrame(rows)


def main():
    df = load()
    groups = {"全样本": df}
    for t in ("1买", "2买", "3买"):
        sub = df[df["买点类型"] == t]
        if len(sub):
            groups[t] = sub

    all_rows = []
    for lbl, g in groups.items():
        conds = build_conditions(g.reset_index(drop=True))
        all_rows.append(score_group(g.reset_index(drop=True), lbl, conds))
    scores = pd.concat(all_rows, ignore_index=True)
    scores = scores[scores["支持数"] >= SUPPORT_MIN]
    scores.to_csv(f"{OUTDIR}/scores_all_combos.csv", index=False, encoding="utf-8-sig")

    # 主榜：盈利覆盖率>=70%，按提升度降序
    main_b = scores[scores["盈利覆盖率"] >= COVER_MIN].sort_values(
        ["分组", "提升度"], ascending=[True, False])
    main_b.to_csv(f"{OUTDIR}/盈利方案_主榜.csv", index=False, encoding="utf-8-sig")
    # 高提升度榜：按提升度降序（已卡支持数>=50）
    lift_b = scores.sort_values(["分组", "提升度"], ascending=[True, False])
    lift_b.to_csv(f"{OUTDIR}/盈利方案_高提升度榜.csv", index=False, encoding="utf-8-sig")

    _report(df, groups, scores, main_b, lift_b)
    print(f"[阶段2] 完成：方案 {len(scores)} 个(支持数≥{SUPPORT_MIN})；"
          f"主榜 {len(main_b)}；高提升度榜 {len(lift_b)}", flush=True)


def _report(df, groups, scores, main_b, lift_b):
    L = ["# 缠论盈利买点共同特征 — 组合方案报告", "",
         f"- 样本 {len(df)}；盈利(≥4%) {int((df['是否盈利']==1).sum())} "
         f"({(df['是否盈利']==1).mean()*100:.1f}%)；进榜门槛 支持数≥{SUPPORT_MIN}",
         "- 层级：L1单条件 / L2两两AND / L5手册强方案；排序判据=提升度(盈利覆盖率÷非盈利覆盖率)",
         "- 观察窗口=信号日±2交易日 OR", ""]
    for lbl in groups:
        L.append(f"## {lbl}")
        gl = lift_b[lift_b["分组"] == lbl]
        L.append("### 高提升度 Top15（不卡覆盖率）")
        L += _table(gl.head(15))
        gm = main_b[main_b["分组"] == lbl]
        L.append(f"### 共同点主榜 Top15（盈利覆盖率≥{int(COVER_MIN*100)}%）")
        L += _table(gm.head(15)) if len(gm) else ["（无覆盖率≥70%的方案）", ""]
    open(f"{OUTDIR}/盈利方案_报告.md", "w", encoding="utf-8").write("\n".join(L))


def _table(d):
    if len(d) == 0:
        return ["（空）", ""]
    out = ["| 方案 | 层 | 提升度 | 条件内胜率 | 基线 | 盈利覆盖率 | 支持数 |",
           "|---|---|---|---|---|---|---|"]
    for _, r in d.iterrows():
        out.append(f"| {r['方案']} | {r['层级']} | {r['提升度']} | {r['条件内胜率']:.0%} | "
                   f"{r['基线胜率']:.0%} | {r['盈利覆盖率']:.0%} | {int(r['支持数'])} |")
    out.append("")
    return out


if __name__ == "__main__":
    main()
