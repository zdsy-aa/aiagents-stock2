# walk_forward_v2.py —— 对 尖刺金叉(买) 与 卖点规则 做样本外检验。
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/walk_forward_v2.py
import numpy as np
import pandas as pd

DIR = "/app/data/profit_mining"
OUT = f"{DIR}/样本外检验_尖刺与卖点_报告.md"


def yr(s):
    return s.str[:4]


def wr(mask, win):
    n = int(mask.sum())
    return n, (float(win[mask].mean()) if n else np.nan)


def evalrule(df, rules, windows, title, L):
    win = (df["是否盈利"] == 1).to_numpy().astype(bool)
    y = yr(df["信号日期"]).to_numpy()
    L.append(f"## {title}")
    for tr_years, te_year in windows:
        tr = np.isin(y, tr_years); te = (y == te_year)
        base_tr, base_te = win[tr].mean(), win[te].mean()
        L.append(f"\n### 训练{tr_years[-1]}及之前 → 测试{te_year}")
        L.append(f"- 训练基线 {base_tr:.0%}(n={int(tr.sum())})；测试基线 {base_te:.0%}(n={int(te.sum())})")
        L.append("| 规则 | 训练胜率(支持) | → 测试胜率(支持) | 测试超基线 |")
        L.append("|---|---|---|---|")
        for name, mask in rules(df):
            st, wt = wr(mask & tr, win)
            se, we = wr(mask & te, win)
            te_str = f"{we:.0%}({se})" if se >= 25 else f"样本不足({se})"
            exc = f"{(we-base_te)*100:+.0f}pt" if se >= 25 else "-"
            L.append(f"| {name} | {wt:.0%}({st}) | {te_str} | {exc} |")
    L.append("")


def main():
    L = ["# 样本外检验：尖刺金叉(买) 与 缠论卖点规则", "",
         "- 训练段挖/定规则、测试段纯验证；测试超基线>0 才算真有盘外edge", ""]

    # ===== 买侧：尖刺金叉 + 极限抄底 =====
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

    evalrule(m, buy_rules, [(["2022", "2023"], "2024"),
                            (["2022", "2023", "2024"], "2025")],
             "买侧（尖刺金叉/极限抄底）", L)

    # ===== 卖侧：缠论卖点规则 =====
    s = pd.read_csv(f"{DIR}/sell_features.csv", encoding="utf-8-sig")
    s["是否盈利"] = pd.to_numeric(s["是否盈利"], errors="coerce").fillna(0).astype(int)
    s["相对强弱_v"] = pd.to_numeric(s["相对强弱"], errors="coerce")

    def sell_rules(d):
        b = lambda c: pd.to_numeric(d.get(c, 0), errors="coerce").fillna(0).to_numpy() > 0
        return [("二连板+斐波全多头", b("二连板") & b("斐波全多头")),
                ("二连板+斐波长多头", b("二连板") & b("斐波长多头")),
                ("上升中回调+相对强弱≥5", b("上升中回调") & (d["相对强弱_v"].to_numpy() >= 5)),
                ("斐波全多头(单)", b("斐波全多头"))]

    evalrule(s, sell_rules, [(["2022", "2023"], "2024"),
                             (["2022", "2023", "2024"], "2025")],
             "卖侧（好卖点=卖后跌≥4%）", L)

    L.append("## 综评")
    L.append("- 测试超基线显著>0 → 真盘外edge；落差大但仍超基线 → 有效但被样本内高估；≈0或负 → 过拟合。")
    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))
    print("[wf2] 完成", flush=True)


if __name__ == "__main__":
    main()
