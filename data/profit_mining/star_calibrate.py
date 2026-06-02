# star_calibrate.py —— 阶段一：全历史1买信号回测"合成分→样本外胜率"，
# 给核心/精选两层各自定固定星级阈值(诚实降档)，产出 star_thresholds.json + 验证报告。
# 运行(宿主机即可，纯标准库)：
#   cd /home/tdxback/aiagents-stock/data/profit_mining
#   PM_DIR=. REPORT_DIR=/home/tdxback/report python3 star_calibrate.py
import os
import csv
import json
import datetime

PM_DIR = os.getenv("PM_DIR", "/app/data/profit_mining")
FEATURES = os.path.join(PM_DIR, "signal_features.csv")
THRESH_OUT = os.path.join(PM_DIR, "star_thresholds.json")
REPORT_DIR = os.getenv("REPORT_DIR", PM_DIR)

WIN_THRESH = 4.0
BIGRISE_THRESH = 10.0
TRAIN_END = "2023-12-31"
OOS_START, OOS_END = "2024-01-01", "2025-10-31"
MIN_BUCKET_N = 200
MAX_STARS = 5
# 每层最终星档数：训练段先挑出单调的最大档(fit_buckets)，再诚实降到此目标。
# 核心层 5★ 样本外验证良好；精选层低星样本外不单调，故诚实降为 2 档
# (顶分位作精英档·样本外≈81%，其余合并·≈72-75%)，星级仍代表样本外验证过的胜率差。
TIER_STARS = {"核心": 5, "精选": 2}

BINARY_FEATS = ["极限抄底", "中枢极限底", "中枢底部回升"]


def _f(v, default=0.0):
    """宽松转 float：空串/None/非数字字符串 → default；'nan'/'inf' 视为合法浮点透传。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def is_trap(row):
    """陷阱(精选层失效)：大盘多头 或 相对强弱>=0。复刻 daily_watchlist 的 trap 判定。
    相对强弱 缺失/空 → NaN（nan>=0 为 False，与 daily_watchlist 的 pd.notna 守卫一致），不判陷阱。"""
    return _f(row.get("大盘多头")) == 1 or _f(row.get("相对强弱"), default=float("nan")) >= 0


def reconstruct_tier(row):
    """复刻 daily_watchlist 层级：仅1买生效；陷阱→None；量能金叉→核心，否则精选。
    返回裸标签 '核心'/'精选'（不含★，供统计分组；展示用的★标签在 daily_watchlist）。"""
    if row.get("买点类型") != "1买":
        return None
    if is_trap(row):
        return None
    return "核心" if _f(row.get("量能金叉")) == 1 else "精选"


def bin_volratio(x):
    """量比分箱：>=2 →2，>=1.3 →1，否则 0（与 daily_watchlist 的 1.3 阈值一致）。"""
    v = _f(x)
    return 2 if v >= 2 else (1 if v >= 1.3 else 0)


def bin_relstr(x):
    """相对强弱分箱(越低越超跌、档位越高；非陷阱已保证 <0)：<=-5 →2，<=-2 →1，否则 0。"""
    v = _f(x)
    return 2 if v <= -5 else (1 if v <= -2 else 0)


CONT_FEATS = {"量比": bin_volratio, "相对强弱": bin_relstr}


def feature_values(row):
    """该信号每个打分特征的档位值（binary 0/1；连续 0/1/2）。"""
    fv = {k: _f(row.get(k)) for k in BINARY_FEATS}
    for k, fn in CONT_FEATS.items():
        fv[k] = fn(row.get(k))
    return fv


def fit_weights(rows, feat_names):
    """rows: [{"fv": {feat: level}, "win": 0/1}]。
    权重 = mean(win | level>0) − mean(win | level==0)。无对照组则 0。"""
    weights = {}
    for f in feat_names:
        on = [r["win"] for r in rows if r["fv"].get(f, 0) > 0]
        off = [r["win"] for r in rows if r["fv"].get(f, 0) == 0]
        if not on or not off:
            weights[f] = 0.0
        else:
            weights[f] = sum(on) / len(on) - sum(off) / len(off)
    return weights


def score_row(fv, weights):
    """合成分 = Σ 权重·档位值。"""
    return sum(weights.get(f, 0.0) * lvl for f, lvl in fv.items())


def assign_bucket(score, cuts):
    """按升序切点 cuts 返回档号 0..len(cuts)。score>=cuts[i] 则进更高档。"""
    b = 0
    for c in cuts:
        if score >= c:
            b += 1
        else:
            break
    return b


def _equal_freq_cuts(scored, k):
    """对已按 score 升序排好的 scored 取 k 等频切点(长度 k-1)。"""
    n = len(scored)
    return [scored[int(round(n * i / k))][0] for i in range(1, k)]


def _bucketize(scored, cuts):
    """按 cuts 把 scored 分进 len(cuts)+1 个桶(0=最低分..末=最高分)。"""
    buckets = [[] for _ in range(len(cuts) + 1)]
    for row in scored:
        buckets[assign_bucket(row[0], cuts)].append(row)
    return buckets


def fit_buckets(scored, max_stars=MAX_STARS, min_n=MIN_BUCKET_N):
    """scored: [(score, win, bigwin)] 按 score 升序。
    从 max_stars 往下试，找"每档>=min_n 且 训练胜率单调不降"的最大档数。
    返回 (n_stars, cuts, stats)；stats[i]={"star":i+1,"n":..,"train_win":..}。
    桶号低=分低=低星，故 star = 桶号+1。"""
    n = len(scored)
    for k in range(max_stars, 1, -1):
        if n < min_n * k:
            continue
        cuts = _equal_freq_cuts(scored, k)
        buckets = _bucketize(scored, cuts)
        if any(len(b) < min_n for b in buckets):
            continue
        wr = [sum(w for _, w, _ in b) / len(b) for b in buckets]
        if all(wr[i] <= wr[i + 1] + 1e-9 for i in range(len(wr) - 1)):
            stats = [{"star": i + 1, "n": len(b), "train_win": wr[i]}
                     for i, b in enumerate(buckets)]
            return k, cuts, stats
    wr0 = sum(w for _, w, _ in scored) / max(n, 1)
    return 1, [], [{"star": 1, "n": n, "train_win": wr0}]


def collapse_cuts(cuts, target):
    """诚实降档：把多分位切点降为 target 档，保留最高 target-1 个切点
    (顶分位作精英档、其余合并为基础档；只动档数、不偷看样本外重挑)。"""
    if target <= 1:
        return []
    return cuts[-(target - 1):]


def eval_buckets(scored, cuts):
    """样本外评估：返回各档 n / oos_win(>=4%) / oos_bigrise(>=10%)。空档为 None。"""
    buckets = _bucketize(scored, cuts)
    out = []
    for i, b in enumerate(buckets):
        nb = len(b)
        out.append({
            "star": i + 1,
            "n": nb,
            "oos_win": (sum(w for _, w, _ in b) / nb) if nb else None,
            "oos_bigrise": (sum(g for _, _, g in b) / nb) if nb else None,
        })
    return out


def load_thresholds(path=THRESH_OUT):
    """读阶段一固化的星级阈值 json。"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def assign_star(tier, row, thresholds):
    """服务端打星：给一只 tier='核心'/'精选' 候选(row=含打分特征列的 dict)打星。
    复用训练同一套 feature_values/score_row/分位切点，保证口径一致(无漂移)。
    返回 (star:int 1..n, est_win:float|None, bigrise:float|None, n_stars:int)。"""
    td = thresholds["tiers"][tier]
    fv = feature_values(row)
    b = assign_bucket(score_row(fv, td["weights"]), td["cuts"])
    st = td["stars"][b]
    return b + 1, st.get("oos_win"), st.get("oos_bigrise"), td["n_stars"]


def parse_signal_row(raw):
    """把 signal_features.csv 一行解析成标定用记录。非1买/陷阱 → tier=None(后续跳过)。"""
    chg = _f(raw.get("区间涨跌幅"))
    return {
        "tier": reconstruct_tier(raw),
        "date": raw.get("信号日期", ""),
        "fv": feature_values(raw),
        "win": 1 if chg >= WIN_THRESH else 0,
        "bigwin": 1 if chg >= BIGRISE_THRESH else 0,
    }


def split_train_oos(rows):
    """按信号日期切：训练 <=TRAIN_END；样本外 OOS_START..OOS_END(排除标签截断的近端)。"""
    train = [r for r in rows if r["date"] <= TRAIN_END]
    oos = [r for r in rows if OOS_START <= r["date"] <= OOS_END]
    return train, oos


def load_rows(path=FEATURES):
    """读 signal_features.csv → 解析后、仅保留 tier 非空(核心/精选)的记录。"""
    out = []
    with open(path, encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            p = parse_signal_row(raw)
            if p["tier"]:
                out.append(p)
    return out


def calibrate(rows):
    """对核心/精选两层分别：训练定权重→打分→分档→样本外评估。返回结构化结果。"""
    feat_names = BINARY_FEATS + list(CONT_FEATS)
    result = {}
    for tier in ("核心", "精选"):
        trows = [r for r in rows if r["tier"] == tier]
        train, oos = split_train_oos(trows)
        weights = fit_weights(
            [{"fv": r["fv"], "win": r["win"]} for r in train], feat_names)
        tr_scored = sorted(
            (score_row(r["fv"], weights), r["win"], r["bigwin"]) for r in train)
        n_stars, cuts, _ = fit_buckets(tr_scored)
        # 诚实降档到该层最终星档数(保留顶分位精英档)
        target = min(TIER_STARS.get(tier, n_stars), n_stars)
        final_cuts = collapse_cuts(cuts, target)
        oos_scored = [(score_row(r["fv"], weights), r["win"], r["bigwin"])
                      for r in oos]
        # 用最终切点重算训练/样本外各档统计
        tr_buckets = _bucketize(tr_scored, final_cuts)
        oos_stats = eval_buckets(oos_scored, final_cuts)
        stars = []
        for i, tb in enumerate(tr_buckets):
            nb = len(tb)
            o = oos_stats[i]
            stars.append({
                "star": i + 1, "n": nb,
                "train_win": (sum(w for _, w, _ in tb) / nb) if nb else None,
                "oos_n": o["n"], "oos_win": o["oos_win"], "oos_bigrise": o["oos_bigrise"],
            })
        result[tier] = {
            "n_stars": len(final_cuts) + 1,
            "weights": {k: round(v, 4) for k, v in weights.items()},
            "cuts": [round(c, 4) for c in final_cuts],
            "train_n": len(train), "oos_n": len(oos),
            "stars": stars,
        }
    return result


def write_report(result, ts):
    """人读 markdown 报告 → REPORT_DIR/star_calibration_report_<ts>.md。"""
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"star_calibration_report_{ts}.md")
    L = [f"# 核心/精选层星级标定报告 {ts}", "",
         f"- 主口径 ≥{WIN_THRESH}% / 辅口径 ≥{BIGRISE_THRESH}%",
         f"- 训练段 ≤{TRAIN_END}；样本外 {OOS_START}~{OOS_END}（排除标签截断的近端）", ""]
    for tier, d in result.items():
        L += [f"## {tier}层（实际 {d['n_stars']} 档，训练 {d['train_n']} / 样本外 {d['oos_n']}）",
              f"权重：{d['weights']}", "",
              "| 星级 | 训练样本 | 训练胜率 | 样本外样本 | 样本外胜率(≥4%) | 样本外大涨率(≥10%) |",
              "|---|---|---|---|---|---|"]
        for s in d["stars"]:
            star = "★" * s["star"]
            tw = f"{s.get('train_win'):.1%}" if s.get("train_win") is not None else "—"
            ow = f"{s.get('oos_win'):.1%}" if s.get("oos_win") is not None else "—"
            ob = f"{s.get('oos_bigrise'):.1%}" if s.get("oos_bigrise") is not None else "—"
            L.append(f"| {star} | {s['n']} | {tw} | "
                     f"{s.get('oos_n', 0)} | {ow} | {ob} |")
        L.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return path


def main():
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    rows = load_rows()
    result = calibrate(rows)
    payload = {
        "generated": ts, "win_thresh": WIN_THRESH, "bigrise_thresh": BIGRISE_THRESH,
        "train_end": TRAIN_END, "oos": [OOS_START, OOS_END],
        "binary_feats": BINARY_FEATS, "cont_feats": list(CONT_FEATS),
        "tiers": result,
    }
    with open(THRESH_OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    rp = write_report(result, ts)
    for tier, d in result.items():
        print(f"[星级标定] {tier}层 {d['n_stars']}档 训练{d['train_n']}/样本外{d['oos_n']}")
    print(f"[星级标定] 阈值 → {THRESH_OUT}；报告 → {rp}")


if __name__ == "__main__":
    main()
