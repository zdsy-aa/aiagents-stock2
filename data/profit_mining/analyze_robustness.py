# analyze_robustness.py —— 稳健性与时间维度分析（在 signal_features.csv 上）
#   验证核心结论在 年份/月份/大盘状态/板块/买点类型 各分层是否稳定。
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/analyze_robustness.py
import numpy as np
import pandas as pd

FEAT = "/app/data/profit_mining/signal_features.csv"
OUTDIR = "/app/data/profit_mining"


def load():
    df = pd.read_csv(FEAT, encoding="utf-8-sig")
    df["是否盈利"] = pd.to_numeric(df["是否盈利"], errors="coerce").fillna(0).astype(int)
    df["年"] = df["信号日期"].str[:4]
    df["月"] = df["信号日期"].str[5:7]
    df["量比"] = pd.to_numeric(df["量比"], errors="coerce")
    df["距60日高点"] = pd.to_numeric(df["距60日高点"], errors="coerce")
    # 大盘状态分层
    sid1 = pd.to_numeric(df.get("SID等于1", 0), errors="coerce").fillna(0) > 0
    sid2 = pd.to_numeric(df.get("SID等于2", 0), errors="coerce").fillna(0) > 0
    df["大盘分层"] = np.where(sid1, "多头", np.where(sid2, "震荡", "空头/危险"))
    return df


# 要追踪稳健性的核心信号(布尔mask函数)
def signals(df):
    b = lambda c: pd.to_numeric(df.get(c, 0), errors="coerce").fillna(0) > 0
    return {
        "极限抄底": b("极限抄底"),
        "极限抄底+量比≥1.3": b("极限抄底") & (df["量比"] >= 1.3),
        "极限抄底+低位(≤0.6)": b("极限抄底") & (df["距60日高点"] <= 0.6),
        "极限抄底+量比≥1.3+中枢极限底": b("极限抄底") & (df["量比"] >= 1.3) & b("中枢极限底"),
        "量能金叉": b("量能金叉"),
        "火箭信号": b("火箭信号"),
        "放量(普通基准)": b("放量"),
        "全部缠论买点(基线)": pd.Series(True, index=df.index),
    }


def wr(df, mask):
    sub = df[mask]
    n = len(sub)
    return n, (sub["是否盈利"].mean() if n else np.nan)


def stratified_table(df, mask, by):
    base = df["是否盈利"].mean()
    rows = []
    for key, g in df.groupby(by):
        n, w = wr(g, mask.reindex(g.index).fillna(False))
        if n >= 30:
            gb = g["是否盈利"].mean()  # 该层基线
            rows.append({by: key, "支持数": n, "胜率": round(w, 3),
                         "该层基线": round(gb, 3), "相对该层": round(w - gb, 3)})
    return pd.DataFrame(rows)


def main():
    df = load()
    sigs = signals(df)
    base = df["是否盈利"].mean()
    L = ["# 缠论盈利买点 — 稳健性与时间维度分析", "",
         f"- 样本 {len(df)}；总基线胜率 {base:.1%}",
         "- 验证核心结论(极限抄底/量比/低位)在各分层是否稳定。支持数<30的格子略去。", ""]

    # 1) 年份稳健性
    L.append("## 1. 年份稳健性（信号年份 × 核心信号胜率）")
    years = sorted(df["年"].unique())
    L.append("| 信号 | " + " | ".join(years) + " | 总体 |")
    L.append("|" + "---|" * (len(years) + 2))
    for name, mask in sigs.items():
        cells = []
        for y in years:
            g = df[df["年"] == y]
            n, w = wr(g, mask.reindex(g.index).fillna(False))
            cells.append(f"{w:.0%}({n})" if n >= 20 else "-")
        n_all, w_all = wr(df, mask)
        L.append(f"| {name} | " + " | ".join(cells) + f" | {w_all:.0%}({n_all}) |")
    L.append("\n> 格式：胜率(支持数)。看核心信号是否每年都明显高于当年基线。\n")

    # 当年基线行
    L.append("**各年基线胜率**：" + "；".join(
        f"{y}={df[df['年']==y]['是否盈利'].mean():.0%}" for y in years) + "\n")

    # 2) 大盘状态分层
    L.append("## 2. 大盘状态分层（极限抄底类在不同市场环境）")
    L.append("| 信号 | 多头 | 震荡 | 空头/危险 |")
    L.append("|---|---|---|---|")
    for name in ["极限抄底", "极限抄底+量比≥1.3", "量能金叉", "全部缠论买点(基线)"]:
        mask = sigs[name]
        cells = []
        for lay in ["多头", "震荡", "空头/危险"]:
            g = df[df["大盘分层"] == lay]
            n, w = wr(g, mask.reindex(g.index).fillna(False))
            cells.append(f"{w:.0%}({n})" if n >= 20 else "-")
        L.append(f"| {name} | " + " | ".join(cells) + " |")
    L.append("")

    # 3) 买点类型分层
    L.append("## 3. 买点类型分层")
    L.append("| 信号 | 1买 | 2买 | 3买 |")
    L.append("|---|---|---|---|")
    for name in ["极限抄底", "极限抄底+量比≥1.3", "极限抄底+低位(≤0.6)", "全部缠论买点(基线)"]:
        mask = sigs[name]
        cells = []
        for t in ["1买", "2买", "3买"]:
            g = df[df["买点类型"] == t]
            n, w = wr(g, mask.reindex(g.index).fillna(False))
            cells.append(f"{w:.0%}({n})" if n >= 20 else "-")
        L.append(f"| {name} | " + " | ".join(cells) + " |")
    L.append("")

    # 4) 月份季节性（全部缠论买点）
    L.append("## 4. 月份季节性（全部缠论买点胜率）")
    mt = stratified_table(df, pd.Series(True, index=df.index), "月").sort_values("月")
    L.append("| 月 | 支持数 | 胜率 |")
    L.append("|---|---|---|")
    for _, r in mt.iterrows():
        L.append(f"| {r['月']} | {int(r['支持数'])} | {r['胜率']:.0%} |")
    L.append("")

    # 5) 板块分层（极限抄底+量比≥1.3）
    L.append("## 5. 板块分层（极限抄底+量比≥1.3）")
    bt = stratified_table(df, sigs["极限抄底+量比≥1.3"], "板块").sort_values("胜率", ascending=False)
    L.append("| 板块 | 支持数 | 胜率 | 该板块基线 |")
    L.append("|---|---|---|---|")
    for _, r in bt.iterrows():
        L.append(f"| {r['板块']} | {int(r['支持数'])} | {r['胜率']:.0%} | {r['该层基线']:.0%} |")
    L.append("")

    open(f"{OUTDIR}/稳健性分析_报告.md", "w", encoding="utf-8").write("\n".join(L))
    print(f"[稳健性] 完成，写入 稳健性分析_报告.md", flush=True)


if __name__ == "__main__":
    main()
