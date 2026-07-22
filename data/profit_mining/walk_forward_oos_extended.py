# walk_forward_oos_extended.py —— 尖刺金叉(买)与缠论卖点 跨牛熊全历史滚动OOS。
#   承接 walk_forward_v2(只测2024/2025);本脚本扩成 expanding 滚动:每个 regime 测试年 T,
#   训练=T之前全部历史→测试T,覆盖 2008金融危机/2015股灾/2018熊/2020疫情V/2021结构/2022下跌/2023弱/2024先抑后扬/2025中性。
#   末尾汇总每条规则"几个测试年里几个超基线"=跨regime稳健性,区分 真edge vs 个别年份侥幸。
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/walk_forward_oos_extended.py
import numpy as np
import pandas as pd

DIR = "/app/data/profit_mining"
OUT = f"{DIR}/样本外检验_尖刺与卖点_全历史滚动_报告.md"
MIN_SUP = 25                       # 测试段支持<25视为样本不足,不计入稳健性统计

# (测试年, regime标签) —— expanding:训练=该年之前全部
REGIMES = [("2008", "金融危机·大熊"), ("2015", "股灾(牛转崩)"), ("2018", "单边熊"),
           ("2020", "疫情V反弹"), ("2021", "结构/抱团"), ("2022", "下跌"),
           ("2023", "弱震荡"), ("2024", "先抑后扬"), ("2025", "中性活跃")]


def yr(s):
    return s.str[:4].to_numpy()


def wr(mask, win):
    n = int(mask.sum())
    return n, (float(win[mask].mean()) if n else np.nan)


def eval_side(df, rules_fn, title, L, summ):
    win = (df["是否盈利"] == 1).to_numpy().astype(bool)
    y = yr(df["信号日期"])
    rules = rules_fn(df)
    L.append(f"## {title}\n")
    for te_year, regime in REGIMES:
        te = (y == te_year)
        tr = (y < te_year)               # expanding:之前全部历史
        if te.sum() < MIN_SUP or tr.sum() < 200:
            continue
        base_te = win[te].mean()
        L.append(f"### 测试 {te_year}（{regime}）  训练≤{int(te_year)-1}")
        L.append(f"- 测试基线 {base_te:.0%}(n={int(te.sum())})；训练 n={int(tr.sum())}")
        L.append("| 规则 | 训练胜率(支持) | → 测试胜率(支持) | 超基线 |")
        L.append("|---|---|---|---|")
        for name, mask in rules:
            st, wt = wr(mask & tr, win)
            se, we = wr(mask & te, win)
            if se >= MIN_SUP:
                exc = (we - base_te) * 100
                L.append(f"| {name} | {wt:.0%}({st}) | {we:.0%}({se}) | {exc:+.0f}pt |")
                summ.setdefault((title, name), []).append((te_year, regime, exc, se))
            else:
                L.append(f"| {name} | {wt:.0%}({st}) | 样本不足({se}) | - |")
        L.append("")


def summarize(summ, L):
    L.append("## 跨 regime 稳健性汇总")
    L.append("- 统计每条规则：有效测试年数 / 其中超基线年数(超基线>0)、平均超基线、最差年。")
    L.append("- 多数 regime 超基线 → 真盘外edge；仅个别年份正/常负 → 过拟合或择时依赖。\n")
    L.append("| 侧 | 规则 | 测试年数 | 超基线年数 | 平均超基线 | 最差(年/regime/pt) |")
    L.append("|---|---|---|---|---|---|")
    for (side, name), recs in summ.items():
        n = len(recs)
        npos = sum(1 for _, _, e, _ in recs if e > 0)
        avg = np.mean([e for _, _, e, _ in recs])
        worst = min(recs, key=lambda r: r[2])
        L.append(f"| {side} | {name} | {n} | {npos}/{n} | {avg:+.1f}pt | "
                 f"{worst[0]}/{worst[1]}/{worst[2]:+.0f}pt |")
    L.append("")


def main():
    L = ["# 全历史滚动样本外检验：尖刺金叉(买) 与 缠论卖点（跨牛熊 9 个 regime）", "",
         "- expanding 窗口：每个测试年 训练=该年之前全部历史；测试超基线>0 才算盘外 edge。",
         f"- 测试段支持<{MIN_SUP} 不计入稳健性统计。承接 walk_forward_v2(原仅2024/2025)。", ""]
    summ = {}

    # 买侧
    f = pd.read_csv(f"{DIR}/signal_features.csv", encoding="utf-8-sig", dtype={"股票代码": str})
    f["股票代码"] = f["股票代码"].str.zfill(6)
    t = pd.read_csv(f"{DIR}/turnover_signal.csv", encoding="utf-8-sig",
                    dtype={"股票代码": str}).drop_duplicates(["股票代码", "信号日期"])
    t["股票代码"] = t["股票代码"].str.zfill(6)
    m = f.merge(t, on=["股票代码", "信号日期"], how="left").drop_duplicates(
        ["股票代码", "信号日期", "买点类型"])
    m["是否盈利"] = pd.to_numeric(m["是否盈利"], errors="coerce").fillna(0).astype(int)
    m["量比_v"] = pd.to_numeric(m["量比"], errors="coerce")

    def buy_rules(d):
        b = lambda c: pd.to_numeric(d.get(c, 0), errors="coerce").fillna(0).to_numpy() > 0
        jc = b("尖刺金叉"); ed = b("极限抄底") & (d["量比_v"].to_numpy() >= 1.3)
        t1 = (d["买点类型"] == "1买").to_numpy()
        return [("极限抄底+量比≥1.3", ed),
                ("尖刺金叉", jc),
                ("尖刺金叉·1买", jc & t1),
                ("尖刺金叉 ∪ (极限抄底+量比13)", jc | ed)]

    eval_side(m, buy_rules, "买侧（尖刺金叉/极限抄底）", L, summ)

    # 卖侧
    s = pd.read_csv(f"{DIR}/sell_features.csv", encoding="utf-8-sig")
    s["是否盈利"] = pd.to_numeric(s["是否盈利"], errors="coerce").fillna(0).astype(int)
    s["相对强弱_v"] = pd.to_numeric(s["相对强弱"], errors="coerce")

    def sell_rules(d):
        b = lambda c: pd.to_numeric(d.get(c, 0), errors="coerce").fillna(0).to_numpy() > 0
        return [("二连板+斐波全多头", b("二连板") & b("斐波全多头")),
                ("二连板+斐波长多头", b("二连板") & b("斐波长多头")),
                ("上升中回调+相对强弱≥5", b("上升中回调") & (d["相对强弱_v"].to_numpy() >= 5)),
                ("斐波全多头(单)", b("斐波全多头"))]

    eval_side(s, sell_rules, "卖侧（好卖点=卖后跌≥4%）", L, summ)

    summarize(summ, L)
    L.append("## 综评")
    L.append("- 超基线年数 ≥ 测试年数的 2/3 且平均为正 → 跨 regime 稳健,可作核心规则。")
    L.append("- 最差年常出现在系统性危机(2008/2015)或强趋势市,对应'极限抄底=震荡超跌反弹,危机/单边失效'的既有结论。")
    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))
    print(f"[wf-ext] 报告 -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
