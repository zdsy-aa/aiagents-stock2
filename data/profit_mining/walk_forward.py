# walk_forward.py —— 滚动样本外检验：训练段挖规则，测试段纯验证，量化样本内偏差。
#   规则=条件组合(L1单/L2两两/L3三联Top)；选择=训练段条件内胜率最高(支持≥阈值)；测试=未来段。
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/walk_forward.py
import itertools
import numpy as np
import pandas as pd
import mine_combos as MC

FEAT = "/app/data/profit_mining/signal_features.csv"
OUTDIR = "/app/data/profit_mining"
SUP_TRAIN = 200    # 训练段最小支持(选广义规则,抑制小样本过拟合)
SUP_TEST = 30      # 测试段最小支持(可测)
TOPK_TRIPLE = 16

def _yrs(a, b):
    return [str(y) for y in range(a, b)]


WINDOWS = [   # 全历史滚动:训练段→测试关键年(含牛熊崩盘)
    ("≤2007", _yrs(1993, 2008), "2008金融危机", ["2008"]),
    ("≤2014", _yrs(1993, 2015), "2015股灾", ["2015"]),
    ("≤2017", _yrs(1993, 2018), "2018熊市", ["2018"]),
    ("≤2019", _yrs(1993, 2020), "2020疫情", ["2020"]),
    ("≤2023", _yrs(1993, 2024), "2024", ["2024"]),
    ("≤2024", _yrs(1993, 2025), "2025", ["2025"]),
]


def wr(mask, win):
    sup = int(mask.sum())
    return sup, (float((mask & win).sum()) / sup if sup else np.nan)


def candidates(conds, names, tr, win_all):
    """生成 单/两两/三联 候选。三联取训练段条件内胜率Top的单条件组合。"""
    cand = [(n,) for n in names]
    cand += list(itertools.combinations(names, 2))
    score = {}
    for n in names:
        s, w = wr(conds[n] & tr, win_all)
        score[n] = w if (s >= 50 and w == w) else -1   # w==w 排除NaN
    top = sorted(names, key=lambda n: -score[n])[:TOPK_TRIPLE]
    cand += list(itertools.combinations(top, 3))
    return cand


def main():
    df = MC.load()
    df["年"] = df["信号日期"].str[:4]
    df = df.reset_index(drop=True)
    conds = MC.build_conditions(df)
    names = list(conds)
    win_all = (df["是否盈利"] == 1).to_numpy()
    yr = df["年"].to_numpy()
    f_quiet = lambda c: pd.to_numeric(df.get(c, 0), errors="coerce").fillna(0).to_numpy() > 0
    human = f_quiet("极限抄底") & (pd.to_numeric(df["量比"], errors="coerce").fillna(0).to_numpy() >= 1.3)

    L = ["# 滚动样本外检验（walk-forward）", "",
         "- 训练段挖规则(条件内胜率最高,训练支持≥200),测试段=之后年份纯验证",
         "- 量化样本内偏差：训练胜率 vs 测试胜率的落差", ""]
    for wlabel, tr_years, te_label, te_years in WINDOWS:
        tr = np.isin(yr, tr_years)
        te = np.isin(yr, te_years)
        cand = candidates(conds, names, tr, win_all)
        rows = []
        for combo in cand:
            m = np.ones(len(df), dtype=bool)
            for n in combo:
                m &= conds[n]
            s_tr, w_tr = wr(m & tr, win_all)
            if s_tr < SUP_TRAIN or w_tr is np.nan:
                continue
            s_te, w_te = wr(m & te, win_all)
            rows.append((" + ".join(combo), s_tr, w_tr, s_te, w_te))
        if not rows:
            L.append(f"## 训练{wlabel} → 测试{te_label}：训练段无满足支持≥{SUP_TRAIN}的规则\n"); continue
        rd = pd.DataFrame(rows, columns=["规则", "训练支持", "训练胜率", "测试支持", "测试胜率"])
        # 选训练段胜率最高(且测试可测)的规则
        sel = rd[rd["测试支持"] >= SUP_TEST].sort_values("训练胜率", ascending=False)
        base_tr = win_all[tr].mean()
        base_te = win_all[te].mean()
        L.append(f"## 训练{wlabel} → 测试{te_label}")
        L.append(f"- 训练段基线胜率 {base_tr:.0%}（n={int(tr.sum())}）；测试段基线胜率 {base_te:.0%}（n={int(te.sum())}）")
        # 人工规则参照
        hs_tr, hw_tr = wr(human & tr, win_all)
        hs_te, hw_te = wr(human & te, win_all)
        L.append(f"- 人工规则[极限抄底+量比≥1.3]：训练 {hw_tr:.0%}(n={hs_tr}) → 测试 "
                 f"{(f'{hw_te:.0%}(n={hs_te})' if hs_te>=SUP_TEST else f'样本不足n={hs_te}')}")
        L.append("\n训练段挑出的 Top5 规则在测试段的表现：")
        L.append("| 训练段选出的规则 | 训练胜率(支持) | → 测试胜率(支持) | 落差 |")
        L.append("|---|---|---|---|")
        for _, r in sel.head(5).iterrows():
            gap = r["训练胜率"] - r["测试胜率"]
            L.append(f"| {r['规则'][:42]} | {r['训练胜率']:.0%}({int(r['训练支持'])}) | "
                     f"{r['测试胜率']:.0%}({int(r['测试支持'])}) | {gap*100:+.0f}pt |")
        # 汇总落差
        topN = sel.head(10)
        if len(topN):
            avg_tr, avg_te = topN["训练胜率"].mean(), topN["测试胜率"].mean()
            L.append(f"\n> Top10训练规则平均：训练 {avg_tr:.0%} → 测试 {avg_te:.0%}（平均落差 {(avg_tr-avg_te)*100:+.0f}pt）；"
                     f"测试段相对其基线 {base_te:.0%} 的超额 {(avg_te-base_te)*100:+.0f}pt\n")
    L.append("## 总评")
    L.append("- 若测试段胜率显著>测试段基线 → 规则真有盘外edge；落差大但仍超基线 → 有效但被样本内高估；测试≈基线 → 过拟合无效。")
    L.append("- 2026测试段右截断严重(下一买点label太近),仅供参考。")
    open(f"{OUTDIR}/样本外检验_报告.md", "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))
    print("[walk-forward] 完成", flush=True)


if __name__ == "__main__":
    main()
