# refine_backtest.py —— Task B：证明"精选层"在稳定选股基础集之上是否有样本外提升度。
#   基础集 = 生产稳定选股 A∪B（极限抄底+量比≥1.3 ∪ 尖刺金叉），剔除获利盘高 & 大盘空头/危险。
#   精选层 = 在基础集内叠加正交看多特征做"二次精选/排序"，看样本外胜率与收益能否显著抬升。
#   三策略：①单因子精选 ②共振确认数阈值 ③提升度加权打分Top1/3。全部 walk-forward（train≤T→test）。
# 运行(宿主机)：python3 refine_backtest.py   产物：/home/tdxback/report/精选层提升度_样本外_<ts>.md
import sys, datetime
import numpy as np
import pandas as pd

HERE = "/home/tdxback/aiagents-stock/data/profit_mining"
SF = f"{HERE}/signal_features.csv"
TS = f"{HERE}/turnover_signal.csv"
TS_MIN_SUP = 80           # 精选条件在 train 基础集内的最小支持
RET_COL = "区间涨跌幅"

# 基础集定义涉及/泄漏的列：精选候选必须排除，否则自我验证
LEAK = {"极限抄底", "量比大于1", "量比大于1_3", "量比大于2", "尖刺金叉", "获利盘高",
        "大盘空头", "大盘安全", "SID等于2", "SID小于等于2", "深度套牢", "筹码集中"}
META = {"股票代码", "股票名称", "板块", "买点类型", "信号日期", "是否盈利", RET_COL,
        "量比", "距60日高点", "距60日低点", "相对强弱",
        "换手率1_3", "换手率3_8", "换手率8_15"}


def fnum(s):
    return pd.to_numeric(s, errors="coerce")


def load():
    sf = pd.read_csv(SF, encoding="utf-8-sig")
    ts = pd.read_csv(TS, encoding="utf-8-sig")
    for d in (sf, ts):
        d["股票代码"] = d["股票代码"].astype(str)
        d["信号日期"] = d["信号日期"].astype(str)
    ts = ts.drop_duplicates(["股票代码", "信号日期"])          # 同键数值已验证一致，去重安全
    df = sf.merge(ts, on=["股票代码", "信号日期"], how="left").reset_index(drop=True)
    df["是否盈利"] = fnum(df["是否盈利"]).fillna(0).astype(int)
    df["年"] = df["信号日期"].str[:4]
    df[RET_COL] = fnum(df[RET_COL])
    return df


def base_mask(df):
    """生产稳定选股基础集 A∪B + 风控过滤。"""
    cd = fnum(df["极限抄底"]).fillna(0) > 0
    ql = fnum(df["量比"]).fillna(0) >= 1.3
    spike = fnum(df["尖刺金叉"]).fillna(0) > 0
    A = cd & ql
    B = spike
    win_profit = fnum(df["获利盘高"]).fillna(0) > 0
    sid_le2 = fnum(df["SID小于等于2"]).fillna(0) > 0       # 大盘非空头/危险
    return ((A | B) & (~win_profit) & sid_le2).to_numpy()


def candidate_conds(df):
    """精选候选：基础集之外的正交看多布尔特征 + 几个连续派生。"""
    conds = {}
    for col in df.columns:
        if col in META or col in LEAK or col == "年":
            continue
        s = fnum(df[col])
        if s.dropna().isin([0, 1]).all() and s.notna().any():
            conds[col] = (s.fillna(0) > 0).to_numpy()
    # 连续派生（与基础集正交）
    g = fnum(df["距60日高点"])
    conds["距前高深跌(<=0.6)"] = (g <= 0.6).fillna(False).to_numpy()
    rs = fnum(df["相对强弱"])
    conds["相对强弱>=5"] = (rs >= 5).fillna(False).to_numpy()
    conds["相对强弱>=0"] = (rs >= 0).fillna(False).to_numpy()
    conds["是1买"] = (df["买点类型"] == "1买").to_numpy()
    return conds


def wr_ret(mask, win, ret):
    sup = int(mask.sum())
    if not sup:
        return 0, np.nan, np.nan
    return sup, float(win[mask].mean()), float(np.nanmedian(ret[mask]))


# walk-forward 窗口：train≤年 → test 年（聚焦近年可信段，2024有beta/2025中性最可信）
WINDOWS = [
    ("≤2022", 2023, "2023"),
    ("≤2023", 2024, "2024"),
    ("≤2024", 2025, "2025"),
]


def main():
    df = load()
    win = (df["是否盈利"] == 1).to_numpy()
    ret = df[RET_COL].to_numpy()
    yr = df["年"].to_numpy()
    base = base_mask(df)
    conds = candidate_conds(df)
    cnames = list(conds)

    L = ["# 精选层样本外提升度检验（Task B）", "",
         "**问题**：稳定选股(A∪B)选出很多票，叠加精选层能否在样本外显著提高胜率/收益？", "",
         f"- 基础集=生产稳定选股：(极限抄底+量比≥1.3) ∪ 尖刺金叉，剔除获利盘高 & 大盘SID≤2",
         f"- 全样本基础集 {int(base.sum())} 个信号（占全部缠论买点 {base.mean()*100:.1f}%）；"
         f"基础集胜率 {win[base].mean()*100:.1f}%，收益中位数 {np.nanmedian(ret[base]):.1f}%",
         f"- 精选候选条件 {len(cnames)} 个（已剔除定义基础集的泄漏列）",
         "- 判据：测试段 胜率 / 收益中位数 / 保留只数；train→test 落差检测过拟合", ""]

    # ---------- 描述性：全样本基础集内各正交条件的条件提升 ----------
    L.append("## 一、全样本：基础集内各正交条件的胜率增益（先看谁有信息量）")
    base_wr = win[base].mean()
    rows = []
    for n in cnames:
        m = base & conds[n]
        sup, w, r = wr_ret(m, win, ret)
        if sup >= 150:
            rows.append((n, sup, w, r, w - base_wr))
    rows.sort(key=lambda x: -x[4])
    L.append(f"基础集胜率基线 {base_wr*100:.1f}%。条件内胜率增益 Top12 / Bottom6（支持≥150）：")
    L.append("| 叠加条件 | 基础集内支持 | 条件内胜率 | 收益中位% | 胜率增益 |")
    L.append("|---|---|---|---|---|")
    for n, sup, w, r, g in rows[:12]:
        L.append(f"| {n} | {sup} | {w*100:.1f}% | {r:.1f} | {g*100:+.1f}pt |")
    L.append("| … | | | | |")
    for n, sup, w, r, g in rows[-6:]:
        L.append(f"| {n} | {sup} | {w*100:.1f}% | {r:.1f} | {g*100:+.1f}pt |")
    L.append("")

    # ---------- 策略1：单因子精选（train选基础集内胜率最高的正交条件）----------
    L.append("## 二、策略1 单因子精选（样本外）")
    L.append("> train段在基础集内挑胜率最高的正交条件(支持≥80)，test段叠加该条件 vs 基础集。")
    L.append("| 窗口 | 基础集test胜率(n) | 选中条件 | 精选test胜率(n) | 收益中位 基→精 | 胜率提升 | train落差 |")
    L.append("|---|---|---|---|---|---|---|")
    for trlab, teyear, telab in WINDOWS:
        tr = base & (yr <= trlab.replace("≤", ""))  # 字符串比较年份(等宽)
        tr = base & (df["年"].to_numpy() <= trlab.replace("≤", ""))
        te = base & (yr == telab)
        # train内挑最佳条件
        best, best_w, best_sup = None, -1, 0
        for n in cnames:
            m = tr & conds[n]
            s = int(m.sum())
            if s >= TS_MIN_SUP:
                w = win[m].mean()
                if w > best_w:
                    best, best_w, best_sup = n, w, s
        b_sup, b_w, b_r = wr_ret(te, win, ret)
        m_te = te & conds[best]
        r_sup, r_w, r_r = wr_ret(m_te, win, ret)
        tr_te_gap = best_w - r_w
        L.append(f"| {trlab}→{telab} | {b_w*100:.1f}%({b_sup}) | {best} | "
                 f"{r_w*100:.1f}%({r_sup}) | {b_r:.1f}→{r_r:.1f} | {(r_w-b_w)*100:+.1f}pt | {tr_te_gap*100:+.1f}pt |")
    L.append("")

    # ---------- 策略2：共振确认数阈值（命中≥k个正交看多确认）----------
    # 用一组稳健的"看多确认"子集（避免噪声列）；按全样本基础集内增益为正且支持充足者
    confirm = [n for n, sup, w, r, g in rows if g > 0 and sup >= 300]
    L.append("## 三、策略2 共振确认数阈值（样本外）")
    L.append(f"> 看多确认池={len(confirm)}个(全样本基础集内增益>0且支持≥300)：{('、'.join(confirm[:12]))}…")
    L.append(f"> 注：确认池由全样本选出，含轻微look-ahead，作趋势参考；策略3用纯train权重更严。")
    cnt = np.zeros(len(df), dtype=int)
    for n in confirm:
        cnt += conds[n].astype(int)
    L.append("| 窗口 | 基础集test胜率(n) | ≥1确认(n) | ≥2确认(n) | ≥3确认(n) |")
    L.append("|---|---|---|---|---|")
    for trlab, teyear, telab in WINDOWS:
        te = base & (yr == telab)
        b_sup, b_w, _ = wr_ret(te, win, ret)
        cells = [f"{b_w*100:.1f}%({b_sup})"]
        for k in (1, 2, 3):
            m = te & (cnt >= k)
            s, w, _ = wr_ret(m, win, ret)
            cells.append(f"{w*100:.1f}%({s})" if s else "—")
        L.append("| " + f"{trlab}→{telab} | " + " | ".join(cells) + " |")
    L.append("")

    # ---------- 策略3：提升度加权打分 Top1/3（纯train权重，最严）----------
    L.append("## 四、策略3 提升度加权打分 Top1/3（样本外，纯train权重）")
    L.append("> 权重_i = max(0, train基础集内[条件i胜率 - 基础集胜率])；得分=Σ权重·命中。")
    L.append("> test段对基础集按得分排序取前1/3 vs 全基础集。这是最诚实的精选层检验。")
    L.append("| 窗口 | 基础集test 胜率/收益中位(n) | Top1/3 胜率/收益中位(n) | 胜率提升 | 收益提升 |")
    L.append("|---|---|---|---|---|")
    for trlab, teyear, telab in WINDOWS:
        tryear = trlab.replace("≤", "")
        tr = base & (df["年"].to_numpy() <= tryear)
        tr_wr = win[tr].mean()
        weights = {}
        for n in cnames:
            m = tr & conds[n]
            s = int(m.sum())
            if s >= TS_MIN_SUP:
                weights[n] = max(0.0, win[m].mean() - tr_wr)
        score = np.zeros(len(df))
        for n, wt in weights.items():
            score += conds[n].astype(float) * wt
        te = base & (yr == telab)
        b_sup, b_w, b_r = wr_ret(te, win, ret)
        te_scores = score[te]
        if b_sup >= 6:
            thr = np.quantile(te_scores, 2/3)
            top = te & (score >= thr)
            t_sup, t_w, t_r = wr_ret(top, win, ret)
            L.append(f"| {trlab}→{telab} | {b_w*100:.1f}% / {b_r:.1f}% ({b_sup}) | "
                     f"{t_w*100:.1f}% / {t_r:.1f}% ({t_sup}) | {(t_w-b_w)*100:+.1f}pt | {(t_r-b_r):+.1f}pt |")
    L.append("")

    L.append("## 五、结论判读")
    L.append("- 若策略3 Top1/3 测试段胜率/收益**稳定高于**基础集且 train→test 落差小 → 精选层有真实样本外edge，值得写工程代码。")
    L.append("- 若仅train高、test回落到基础集 → 精选层过拟合，不值得，直接用基础集即可。")
    L.append("- 单因子(策略1)最稳健、共振(策略2)折中、打分(策略3)信息最全但最易过拟合——三者一致才下结论。")

    ts_now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = f"/home/tdxback/report/精选层提升度_样本外_{ts_now}.md"
    open(out, "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))
    print(f"\n[refine_backtest] 报告写入 {out}", flush=True)


if __name__ == "__main__":
    main()
