# mine_combos_v2.py —— 多组(12)挖掘：每组剔本族信号防泄漏，L1-L5，出榜+横向对比。
# 运行(宿主机): python3 mine_combos_v2.py   或容器内 /app/data/profit_mining/
import os, sys, itertools, datetime
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import event_registry as ER

HERE = os.path.dirname(os.path.abspath(__file__))
FEAT = os.path.join(HERE, "features_v2.csv")
REPORT_DIR = "/home/tdxback/report" if os.path.isdir("/home/tdxback/report") else HERE
COVER_MIN, SUPPORT_MIN, TOPK_TRIPLE = 0.70, 50, 18
META = ["组","family","direction","股票代码","信号日期","标签","极值收益","truncated"]
CONT_CONDS = [
    ("量比", ">=", 1.3, "量比>=1.3"), ("量比", ">=", 2.0, "量比>=2"),
    ("距60日高点", ">=", 0.9, "距前高<=10%"), ("距60日高点", "<=", 0.6, "深跌(距前高>40%)"),
    ("距60日低点", "<=", 1.1, "距前低<=10%"), ("相对强弱", ">=", 0.0, "相对强弱>=0"),
    ("相对强弱", ">=", 5.0, "相对强弱>=5"), ("吸筹值", ">=", 50.0, "吸筹>=50"),
    ("庄家线", ">=", 50.0, "庄家>=50"), ("六脉红灯数", ">=", 5.0, "六脉红灯>=5"),
    # Phase E 新连续量阈值(网格基于241.9万行全量分位数;退化列波动档(全=2)/MACD背驰强度(全=0)已略)
    ("主力强度", ">=", 0.002, "主力强度高"),
    ("资金强度", ">=", 10.0, "资金强度>=10"), ("资金强度", ">=", 20.0, "资金强度>=20"),
    ("资金强度", "<=", 0.0, "资金强度<=0(机构净卖)"),
    ("波动率", "<=", 2.85, "低波动(波动率<=2.85)"), ("波动率", ">=", 5.0, "高波动(波动率>=5)"),
    ("波动率百分位", "<=", 44.0, "波动率分位<=44"),
    ("MA20斜率", ">=", 0.0, "MA20上行"), ("MA20斜率", ">=", 2.0, "MA20强上行"),
    ("MA20斜率", "<=", -2.0, "MA20下行"),
    ("缠论趋势评分", ">=", 50.0, "缠论评分>=50"), ("缠论趋势评分", ">=", 70.0, "缠论评分>=70"),
    ("做多权重", ">=", 1.0, "做多权重>=1"), ("做多权重", "<=", -1.0, "做多权重<=-1"),
]

def metrics(mask, win, group, name):
    sup = int(mask.sum()); nwin = int(win.sum()); nlose = int((~win).sum())
    cw = float((mask & win).sum())/nwin if nwin else 0
    cl = float((mask & ~win).sum())/nlose if nlose else 0
    wr = float((mask & win).sum())/sup if sup else 0
    base = nwin/len(win) if len(win) else 0
    lift = cw/cl if cl > 0 else np.inf
    return {"分组": group, "方案": name, "支持数": sup, "盈利覆盖率": round(cw,4),
            "非盈利覆盖率": round(cl,4), "提升度": round(lift,3) if np.isfinite(lift) else 999,
            "条件内胜率": round(wr,4), "基线胜率": round(base,4), "胜率增益": round(wr-base,4)}

def build_conditions(df, exclude):
    cont_src = {c for c,_,_,_ in CONT_CONDS}
    conds = {}
    for col in df.columns:
        if col in META or col in cont_src or col in exclude:
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        if s.dropna().isin([0,1]).all() and s.notna().any():
            conds[col] = (s.fillna(0) > 0).to_numpy()
    for col, op, thr, disp in CONT_CONDS:
        if col in df.columns and disp not in exclude and col not in exclude:
            s = pd.to_numeric(df[col], errors="coerce")
            conds[disp] = ((s >= thr) if op == ">=" else (s <= thr)).fillna(False).to_numpy()
    return conds

def score_group(df, group, conds):
    win = (df["标签"] == 1).to_numpy(); names = list(conds); rows = []; l1 = {}
    for n in names:
        m = metrics(conds[n], win, group, n); l1[n] = m; rows.append({**m, "层级":"L1"})
    for a, b in itertools.combinations(names, 2):
        m = conds[a] & conds[b]
        if int(m.sum()) >= SUPPORT_MIN:
            rows.append({**metrics(m, win, group, f"{a} + {b}"), "层级":"L2"})
    cand = sorted([n for n in names if l1[n]["支持数"] >= 100], key=lambda n: -l1[n]["提升度"])[:TOPK_TRIPLE]
    for a, b, cc in itertools.combinations(cand, 3):
        m = conds[a] & conds[b] & conds[cc]
        if int(m.sum()) >= SUPPORT_MIN:
            rows.append({**metrics(m, win, group, f"{a} + {b} + {cc}"), "层级":"L3"})
    return pd.DataFrame(rows)

def _load_features():
    """读 features_v2.csv 并降型省内存(4.9M行规模):布尔特征列→int8, 连续→float32。"""
    df = pd.read_csv(FEAT, encoding="utf-8-sig", low_memory=False)
    cont = {c for c,_,_,_ in CONT_CONDS} | {"极值收益"}
    for col in df.columns:
        if col in META and col not in ("标签",):
            continue
        if col in cont:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float32")
        else:
            s = pd.to_numeric(df[col], errors="coerce")
            if s.dropna().isin([0,1]).all():
                df[col] = s.fillna(0).astype("int8")
    return df

def main():
    df = _load_features()
    df["标签"] = pd.to_numeric(df["标签"], errors="coerce").fillna(0).astype("int8")
    all_rows = []
    for group in ER.EVENTS:
        g = df[df["组"] == group]
        if len(g) < SUPPORT_MIN:
            continue
        conds = build_conditions(g.reset_index(drop=True), ER.leakage_signals(group))
        all_rows.append(score_group(g.reset_index(drop=True), group, conds))
    scores = pd.concat(all_rows, ignore_index=True)
    scores = scores[scores["支持数"] >= SUPPORT_MIN]
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    scores.to_csv(os.path.join(REPORT_DIR, f"各组方案_全部评分_{ts}.csv"), index=False, encoding="utf-8-sig")
    main_b = scores[scores["盈利覆盖率"] >= COVER_MIN].sort_values(["分组","提升度"], ascending=[True, False])
    main_b.to_csv(os.path.join(REPORT_DIR, f"各组共同点主榜_{ts}.csv"), index=False, encoding="utf-8-sig")
    _report(df, scores, ts)
    print(f"[V2挖掘] 方案 {len(scores)}，主榜 {len(main_b)}，产物 ts={ts}")

def _report(df, scores, ts):
    buy = [g for g in ER.EVENTS if ER.EVENTS[g]["direction"] == "buy"]
    sell = [g for g in ER.EVENTS if ER.EVENTS[g]["direction"] == "sell"]
    L = ["# 多类买卖点 × 全信号库 — 横向对比报告", "", f"- 时间戳 {ts}",
         "- 标签: 买=30日最高涨≥10% / 卖=30日最低跌≥10%；提升度=盈利覆盖率÷非盈利覆盖率", ""]
    for title, groups in [("买方", buy), ("卖方", sell)]:
        L.append(f"## {title}")
        for g in groups:
            sub = df[df["组"] == g]
            if len(sub) < SUPPORT_MIN:
                L.append(f"### {g}（样本不足）"); continue
            base = sub["标签"].mean()
            L.append(f"### {g}  样本{len(sub)}  基线{base*100:.1f}%")
            # 只展示主榜(盈利覆盖率≥70%)的共同点,按提升度排序;避免置顶过拟合尾(覆盖0%/支持极小/提升999)
            top = scores[(scores["分组"] == g) & (scores["盈利覆盖率"] >= COVER_MIN)
                         ].sort_values("提升度", ascending=False).head(10)
            L.append("| 方案 | 层 | 提升度 | 胜率 | 覆盖率 | 支持 |")
            L.append("|---|---|---|---|---|---|")
            for _, r in top.iterrows():
                L.append(f"| {r['方案']} | {r['层级']} | {r['提升度']} | {r['条件内胜率']:.0%} | {r['盈利覆盖率']:.0%} | {int(r['支持数'])} |")
            L.append("")
    open(os.path.join(REPORT_DIR, f"横向对比报告_{ts}.md"), "w", encoding="utf-8").write("\n".join(L))

if __name__ == "__main__":
    main()
