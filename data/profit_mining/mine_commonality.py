# mine_commonality.py —— 方案A/B 涨跌前期共性挖掘：逐股累加→覆盖率/提升度/精确度→报告。
import numpy as np


def count_for_signal(signal, windows):
    """signal: bool序列(len=n_bars)；windows: list[list[int]] (每段的W=5正样本bar索引)。
    返回 (seg_hit, seg_total, fires_pos, bars_pos, fires_all, bars_all)。
    seg_hit: 窗口内任一根信号True则该段命中；bars_pos: 所有窗口索引去重后的根数；
    fires_pos: 正样本根里信号True数；fires_all/bars_all: 全体。"""
    sig = np.asarray(signal, dtype=bool)
    n = len(sig)
    seg_total = len(windows)
    seg_hit = 0
    pos_idx = set()
    for w in windows:
        idx = [i for i in w if 0 <= i < n]
        if any(bool(sig[i]) for i in idx):
            seg_hit += 1
        pos_idx.update(idx)
    pos_idx = sorted(pos_idx)
    bars_pos = len(pos_idx)
    fires_pos = int(sum(bool(sig[i]) for i in pos_idx))
    fires_all = int(sig.sum())
    bars_all = n
    return seg_hit, seg_total, fires_pos, bars_pos, fires_all, bars_all


# key = (plan, side, pct, paramtuple)；paramtuple: A=(N,ratio,band,f,s,sig) B=(periods,f,s,sig)
def finalize(counts):
    """counts(已跨股累加) → list[dict] 含 coverage/lift/precision 等。"""
    rows = []
    for (plan, side, pct, params), c in counts.items():
        seg_hit, seg_total, fires_pos, bars_pos, fires_all, bars_all = c
        coverage = seg_hit / seg_total if seg_total else 0.0
        rate_pos = fires_pos / bars_pos if bars_pos else 0.0
        rate_all = fires_all / bars_all if bars_all else 0.0
        lift = rate_pos / rate_all if rate_all > 0 else float("inf")
        precision = fires_pos / fires_all if fires_all else 0.0
        rows.append({"plan": plan, "side": side, "pct": pct, "params": params,
                     "seg_hit": seg_hit, "seg_total": seg_total,
                     "coverage": coverage, "rate_all": rate_all,
                     "lift": lift, "precision": precision})
    return rows


def filter_rank(rows, cover_min=0.70):
    """筛 coverage≥门槛 且 rate_all>0(剔除退化/哪都不亮)，按提升度降序。"""
    keep = [r for r in rows
            if r["seg_total"] > 0 and r["coverage"] >= cover_min and r["rate_all"] > 0]
    return sorted(keep, key=lambda r: r["lift"], reverse=True)


import swing_samples as SW
import param_signals as PS
from collections import defaultdict

DEFAULT_PCTS = (0.10, 0.15, 0.20)


def accumulate_stock(df, pcts=DEFAULT_PCTS, fwd=4):
    """单股 → 计数dict key=(plan,side,pct,params) val=[6元累计]。
    df 需含 High/Low/Close 列、时间升序。正样本=拐点后 fwd 根(起涨/起跌初期)。"""
    out = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    high = df["High"].tolist(); low = df["Low"].tolist()
    for pct in pcts:
        up_win, down_win = SW.positive_windows(high, low, pct, fwd)
        for side, windows in (("buy", up_win), ("sell", down_win)):
            if not windows:
                continue
            for params in PS.PLAN_A_GRID:
                sig = PS.plan_a_signal(df, *params, side=side).to_numpy()
                _merge(out[("A", side, pct, params)], count_for_signal(sig, windows))
            for params in PS.PLAN_B_GRID:
                sig = PS.plan_b_signal(df, *params, side=side).to_numpy()
                _merge(out[("B", side, pct, params)], count_for_signal(sig, windows))
    return dict(out)


def _merge(acc, c):
    for i in range(6):
        acc[i] += c[i]


def merge_counts(dst, src):
    """跨股合并：把 src(单股dict) 累加进 dst(defaultdict)。"""
    for k, v in src.items():
        a = dst[k]
        for i in range(6):
            a[i] += v[i]


import os, csv as _csv

SIDE_CN = {"buy": "上涨前", "sell": "下跌前"}


def _expand_params(plan, params):
    if plan == "A":
        N, ratio, band, f, s, sig = params
        return {"N": N, "ratio": ratio, "band": band, "fast": f, "slow": s, "signal": sig}
    periods, f, s, sig = params
    return {"periods": "/".join(map(str, periods)), "fast": f, "slow": s, "signal": sig}


def _write_board(fpath, plan, side, pct, ranked):
    """把 ranked(已排序的 finalize 行) 写成一张 CSV。"""
    pcols = (["N", "ratio", "band", "fast", "slow", "signal"] if plan == "A"
             else ["periods", "fast", "slow", "signal"])
    metric_cols = ["seg_hit", "seg_total", "coverage", "rate_all", "lift", "precision"]
    with open(fpath, "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.writer(f)
        w.writerow(["plan", "side", "pct"] + pcols + metric_cols)
        for r in ranked:
            ep = _expand_params(plan, r["params"])
            w.writerow([r["plan"], r["side"], r["pct"]] +
                       [ep[c] for c in pcols] + [r[c] for c in metric_cols])


def write_reports(rows, out_dir="/app/data/commonality_reports", ts=None,
                  cover_min=0.70, topn=20):
    """已 finalize 的 rows → 按 (plan,side,pct) 分文件写两类 CSV + 一份横向对比 md：
    - 达标主榜：覆盖率≥cover_min 硬门槛，按提升度降序(可能空)；
    - 最佳可达榜：不卡覆盖率(仅 rate_all>0)，按提升度降序取 Top topn(保证非空)。"""
    import time
    ts = ts or time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    groups = {}
    for r in rows:
        groups.setdefault((r["plan"], r["side"], r["pct"]), []).append(r)
    md_lines = ["# 方案A/B 涨跌前期共性 横向对比", "",
                f"生成 {ts}，覆盖率门槛 {cover_min}，最佳可达取 Top{topn}",
                "（窗口=拐点后[L,L+4]起涨/起跌初期；提升度=正样本bar命中率÷全体bar命中率）", ""]
    for (plan, side, pct), grp in sorted(groups.items()):
        zz = f"zz{int(pct * 100)}"
        kept = filter_rank(grp, cover_min)                         # 达标主榜
        best = sorted([r for r in grp if r["rate_all"] > 0],
                      key=lambda r: r["lift"], reverse=True)[:topn]  # 最佳可达榜
        main_path = os.path.join(out_dir, f"方案{plan}_{SIDE_CN[side]}共性_{zz}_{ts}.csv")
        best_path = os.path.join(out_dir, f"方案{plan}_{SIDE_CN[side]}最佳可达_{zz}_{ts}.csv")
        _write_board(main_path, plan, side, pct, kept)
        _write_board(best_path, plan, side, pct, best)
        paths.extend([main_path, best_path])
        if kept:
            t = kept[0]; ep = _expand_params(plan, t["params"])
            md_lines.append(f"- **方案{plan} {SIDE_CN[side]} {zz}**：达标{len(kept)}组，"
                            f"最佳 {ep} 覆盖{t['coverage']:.2f} 提升度{t['lift']:.2f} 精确{t['precision']:.2f}")
        else:
            t = best[0] if best else None
            if t:
                ep = _expand_params(plan, t["params"])
                md_lines.append(f"- **方案{plan} {SIDE_CN[side]} {zz}**：无≥{cover_min}达标；"
                                f"最佳可达 {ep} 覆盖{t['coverage']:.2f} 提升度{t['lift']:.2f} 精确{t['precision']:.2f}")
            else:
                md_lines.append(f"- **方案{plan} {SIDE_CN[side]} {zz}**：无有效组合")
    md_path = os.path.join(out_dir, f"方案AB_共性横向对比_{ts}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")
    paths.append(md_path)
    return paths


def _load_kline(code):
    """容器内本地K源 → 标准列 df（时间升序）。复用 build_features_v2 同款读取。"""
    import sys
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")   # akshare_gateway.py 在 /app 根，worker的sys.path起于脚本目录
    from akshare_gateway import akshare_gw
    df = akshare_gw.local.get_kline(code, kline_type="day", limit=10000)
    if df is None or df.empty:
        return None
    rename = {"开盘": "Open", "最高": "High", "最低": "Low", "收盘": "Close", "成交量": "Volume"}
    return (df.rename(columns=rename).set_index("日期").sort_index()
            [["Open", "High", "Low", "Close", "Volume"]])


def _universe():
    """股票池：events_labeled.csv 去重股票代码（≈全A历史，已证可加载）。"""
    import csv as c2
    path = "/app/data/profit_mining/events_labeled.csv"
    codes = set()
    with open(path, encoding="utf-8-sig") as f:
        for r in c2.DictReader(f):
            codes.add(r["股票代码"])
    return sorted(codes)


def _proc(code):
    df = _load_kline(code)
    if df is None or len(df) < 80:
        return {}
    return accumulate_stock(df, pcts=DEFAULT_PCTS, fwd=4)


def main():
    import sys, time, os
    from multiprocessing import Pool
    codes = _universe()
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if limit:
        codes = codes[:limit]
    total = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    t0 = time.time()
    nproc = int(os.getenv("NPROC", "8"))
    with Pool(nproc) as p:
        for k, sc in enumerate(p.imap_unordered(_proc, codes, chunksize=20), 1):
            merge_counts(total, sc)
            if k % 500 == 0:
                print(f"  …{k}/{len(codes)}，{int(time.time()-t0)}s", flush=True)
    rows = finalize(dict(total))
    paths = write_reports(rows, out_dir="/app/data/commonality_reports")  # 已挂载,宿主可见
    print(f"[共性挖掘] 股票{len(codes)} 组合keys{len(rows)} 用时{int(time.time()-t0)}s", flush=True)
    for pth in paths:
        print("  写", pth, flush=True)


if __name__ == "__main__":
    main()
