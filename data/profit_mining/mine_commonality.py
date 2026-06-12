# mine_commonality.py —— 方案A/B 涨跌前期共性挖掘：逐股累加→覆盖率/提升度/精确度→报告。
import os
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


# key = (group, plan, side, pct, paramtuple)；paramtuple: A=(N,ratio,band,f,s,sig) B=(periods,form,f,s,sig)
def finalize(counts):
    """counts(已跨股累加,键含group) → list[dict] 含 group/coverage/lift/precision 等。"""
    rows = []
    for (group, plan, side, pct, params), c in counts.items():
        seg_hit, seg_total, fires_pos, bars_pos, fires_all, bars_all = c
        coverage = seg_hit / seg_total if seg_total else 0.0
        rate_pos = fires_pos / bars_pos if bars_pos else 0.0
        rate_all = fires_all / bars_all if bars_all else 0.0
        lift = rate_pos / rate_all if rate_all > 0 else float("inf")
        precision = fires_pos / fires_all if fires_all else 0.0
        rows.append({"group": group, "plan": plan, "side": side, "pct": pct,
                     "params": params, "seg_hit": seg_hit, "seg_total": seg_total,
                     "fires_all": fires_all, "coverage": coverage, "rate_all": rate_all,
                     "lift": lift, "precision": precision})
    return rows


def filter_rank(rows, cover_min=0.70):
    """筛 coverage≥门槛 且 rate_all>0(剔除退化/哪都不亮)，按提升度降序。"""
    keep = [r for r in rows
            if r["seg_total"] > 0 and r["coverage"] >= cover_min and r["rate_all"] > 0]
    return sorted(keep, key=lambda r: r["lift"], reverse=True)


import swing_samples as SW
import param_signals as PS
import group_dims as GD
from collections import defaultdict

DEFAULT_PCTS = (0.10, 0.15, 0.20)


def _win_arrays(windows, n):
    """连续整数窗口 list → (starts, ends) numpy 数组(int64,含端,均在[0,n))。
    同侧 zigzag 窗口互不相交，故 union 计数可按窗口求和不会重复。"""
    st = np.fromiter((w[0] for w in windows), dtype=np.int64, count=len(windows))
    en = np.fromiter((w[-1] for w in windows), dtype=np.int64, count=len(windows))
    np.clip(st, 0, n - 1, out=st); np.clip(en, 0, n - 1, out=en)
    return st, en


def accumulate_stock(df, pcts=DEFAULT_PCTS, fwd=4, groups=None):
    """单股 → 计数dict key=(group,plan,side,pct,params) val=[6元累计]。
    groups=None → 仅 ALL(向后兼容)。否则 groups={'board':标签或None,'size':标签或None,
    'vol_cuts':[c1,c2]或None}。ALL/板块/市值整股复用同一窗口计数；波动率按拐点vol20切子集。
    信号每股每(plan,params,side)只算一次,跨pct与跨组复用。"""
    out = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    n = len(df)
    high = df["High"].tolist(); low = df["Low"].tolist()
    shared = ["ALL"]
    if groups:
        if groups.get("board"):
            shared.append(groups["board"])
        if groups.get("size"):
            shared.append(groups["size"])
    vol_cuts = groups.get("vol_cuts") if groups else None
    vol20 = GD.vol20_series(df) if vol_cuts else None

    # 窗口结构 per (side,pct): list of (labels, starts, ends, seg_total, bars_pos)
    W = {}
    for pct in pcts:
        up, down = SW.positive_windows(high, low, pct, fwd)
        for side, wins in (("buy", up), ("sell", down)):
            entries = []
            if wins:
                st, en = _win_arrays(wins, n)
                entries.append((shared, st, en, len(wins), int((en - st + 1).sum())))
                if vol20 is not None:
                    for b, sub in GD.split_windows_by_vol(wins, vol20, vol_cuts).items():
                        if sub:
                            sst, sen = _win_arrays(sub, n)
                            entries.append(([f"波动率={GD.VOL_LABELS[b]}"], sst, sen,
                                            len(sub), int((sen - sst + 1).sum())))
            W[(side, pct)] = entries

    for side in ("buy", "sell"):
        has = any(W[(side, pct)] for pct in pcts)
        if not has:
            continue
        macd_cache, fib_cache, bbi_cache = {}, {}, {}

        def macd_mask(f, s, sg):
            m = macd_cache.get((f, s, sg))
            if m is None:
                m = (PS.macd_golden(df, f, s, sg) if side == "buy"
                     else PS.macd_dead(df, f, s, sg)).to_numpy()
                macd_cache[(f, s, sg)] = m
            return m

        def fib_mask(N, r, b):
            m = fib_cache.get((N, r, b))
            if m is None:
                m = (PS.fib_support_hold(df, N, r, b) if side == "buy"
                     else PS.fib_resist_reject(df, N, r, b)).to_numpy()
                fib_cache[(N, r, b)] = m
            return m

        def bbi_mask(periods, form):
            m = bbi_cache.get((periods, form))
            if m is None:
                m = PS._bbi_form(df, periods, form, side).to_numpy()
                bbi_cache[(periods, form)] = m
            return m

        def tally(plan, params, sig):
            csum = np.concatenate(([0], np.cumsum(sig, dtype=np.int64)))
            fires_all = int(sig.sum())
            for pct in pcts:
                for labels, st, en, seg_total, bars_pos in W[(side, pct)]:
                    wf = csum[en + 1] - csum[st]
                    seg_hit = int(np.count_nonzero(wf)); fires_pos = int(wf.sum())
                    for g in labels:
                        a = out[(g, plan, side, pct, params)]
                        a[0] += seg_hit; a[1] += seg_total; a[2] += fires_pos
                        a[3] += bars_pos; a[4] += fires_all; a[5] += n

        for params in PS.PLAN_A_GRID:
            N, r, b, f, s, sg = params
            tally("A", params, fib_mask(N, r, b) & macd_mask(f, s, sg))
        for params in PS.PLAN_B_GRID:
            periods, form, f, s, sg = params
            tally("B", params, bbi_mask(periods, form) & macd_mask(f, s, sg))
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
    periods, form, f, s, sig = params
    return {"periods": "/".join(map(str, periods)), "form": form,
            "fast": f, "slow": s, "signal": sig}


def _write_board(fpath, plan, side, pct, ranked):
    """把 ranked(已排序的 finalize 行) 写成一张 CSV。"""
    pcols = (["N", "ratio", "band", "fast", "slow", "signal"] if plan == "A"
             else ["periods", "form", "fast", "slow", "signal"])
    metric_cols = ["seg_hit", "seg_total", "coverage", "rate_all", "lift", "precision"]
    with open(fpath, "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.writer(f)
        w.writerow(["plan", "side", "pct"] + pcols + metric_cols)
        for r in ranked:
            ep = _expand_params(plan, r["params"])
            w.writerow([r["plan"], r["side"], r["pct"]] +
                       [ep[c] for c in pcols] + [r[c] for c in metric_cols])


GROUP_MIN_SEG = 3000      # 组级样本门槛(seg_total)
ROW_MIN_FIRES = 300       # 行级样本门槛(fires_all)
DIM_PREFIX = ("板块=", "市值=", "波动率=")


def attach_uplift(rows):
    """给每行补 lift_all / uplift / uplift_ratio（基线=同(plan,side,pct,params)的ALL行lift）。"""
    base = {}
    for r in rows:
        if r["group"] == "ALL":
            base[(r["plan"], r["side"], r["pct"], r["params"])] = r["lift"]
    out = []
    for r in rows:
        r = dict(r)
        la = base.get((r["plan"], r["side"], r["pct"], r["params"]))
        r["lift_all"] = la
        if la is not None and la > 0 and r["lift"] != float("inf"):
            r["uplift"] = r["lift"] - la
            r["uplift_ratio"] = r["lift"] / la
        else:
            r["uplift"] = float("-inf")
            r["uplift_ratio"] = 0.0
        out.append(r)
    return out


def _dim_of(group):
    for p in DIM_PREFIX:
        if group.startswith(p):
            return p.rstrip("=")
    return None


def write_reports(rows, out_dir="/app/data/commonality_reports", ts=None,
                  cover_min=0.50, topn=30):
    """已 finalize 的 rows → 按 (plan,side,pct) 分文件写两类 CSV + 一份横向对比 md：
    - 达标主榜：覆盖率≥cover_min 硬门槛，按提升度降序(可能空)；
    - 最佳可达榜：不卡覆盖率(仅 rate_all>0)，按提升度降序取 Top topn(保证非空)。"""
    rows = [r for r in rows if r["group"] == "ALL"]      # 全市场榜只用 ALL
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


def write_grouped_reports(rows, out_dir="/app/data/commonality_reports", ts=None,
                          topn=30, group_min_seg=GROUP_MIN_SEG, row_min_fires=ROW_MIN_FIRES):
    """按维度(板块/市值/波动率)出 uplift 榜 CSV + 总览 md。基线=ALL同参 lift。"""
    import time
    ts = ts or time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(out_dir, exist_ok=True)
    rows = attach_uplift(rows)
    paths = []
    md = ["# 分组挖掘总览(uplift vs 全市场)", "",
          f"生成 {ts}；组级门槛 seg_total≥{group_min_seg}，行级 fires_all≥{row_min_fires}，每组Top{topn}",
          "（uplift=组内lift−全市场同参lift；ratio=组内/全市场。⭐=ratio≥1.3 分组显著增强）", ""]
    pcols_A = ["N", "ratio", "band", "fast", "slow", "signal"]
    pcols_B = ["periods", "form", "fast", "slow", "signal"]
    metric = ["seg_total", "coverage", "lift", "lift_all", "uplift", "uplift_ratio",
              "precision", "fires_all"]
    for dim in ("板块", "市值", "波动率"):
        drows = [r for r in rows if _dim_of(r["group"]) == dim
                 and r["seg_total"] >= group_min_seg and r["fires_all"] >= row_min_fires
                 and r["uplift"] != float("-inf")]
        drows.sort(key=lambda r: r["uplift"], reverse=True)
        # 写 CSV(A/B 参数列不同,统一展开为字符串 params 列以避免混列)
        fpath = os.path.join(out_dir, f"分组uplift榜_{dim}_{ts}.csv")
        with open(fpath, "w", newline="", encoding="utf-8-sig") as f:
            w = _csv.writer(f)
            w.writerow(["group", "plan", "side", "pct", "params"] + metric)
            for r in drows[:topn * 12]:    # 每维度跨多组,放宽总条数
                ep = _expand_params(r["plan"], r["params"])
                w.writerow([r["group"], r["plan"], r["side"], r["pct"],
                            ";".join(f"{k}={v}" for k, v in ep.items())]
                           + [r.get(m) for m in metric])
        paths.append(fpath)
        # md: 每(组×side) 取 uplift 最高一条
        best = {}
        for r in drows:
            key = (r["group"], r["side"])
            if key not in best or r["uplift"] > best[key]["uplift"]:
                best[key] = r
        md.append(f"## 维度：{dim}")
        for (grp, side), r in sorted(best.items()):
            star = "⭐" if r["uplift_ratio"] >= 1.3 else ""
            ep = _expand_params(r["plan"], r["params"])
            md.append(f"- {star}**{grp} {SIDE_CN[side]}**：方案{r['plan']} {ep} "
                      f"lift {r['lift']:.2f}(全市场{r['lift_all']:.2f}, +{r['uplift']:.2f}/{r['uplift_ratio']:.2f}×) "
                      f"覆盖{r['coverage']:.2f} 样本{r['seg_total']}")
        md.append("")
    md_path = os.path.join(out_dir, f"分组挖掘总览_{ts}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
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


_GCTX = None


def _group_ctx():
    """懒加载(每 worker 一次): {board_map, mktcap_map, size_cuts, vol_cuts}。缺文件则对应维度为空。"""
    global _GCTX
    if _GCTX is not None:
        return _GCTX
    import csv as c2
    # 板块图: events_labeled.csv 代码->板块
    board_map = {}
    with open("/app/data/profit_mining/events_labeled.csv", encoding="utf-8-sig") as f:
        for r in c2.DictReader(f):
            code = r.get("股票代码")
            if code and code not in board_map:
                board_map[code] = r.get("板块") or None
    # 市值图
    mktcap_map = {}
    snap = "/app/data/profit_mining/stock_mktcap_snapshot.csv"
    if os.path.exists(snap):
        with open(snap, encoding="utf-8-sig") as f:
            for r in c2.DictReader(f):
                try:
                    mktcap_map[r["代码"]] = float(r["总市值"])
                except (ValueError, KeyError):
                    pass
    # 切点
    size_cuts = vol_cuts = None
    bpath = "/app/data/profit_mining/group_buckets.json"
    if os.path.exists(bpath):
        b = GD.load_buckets(bpath)
        size_cuts = b.get("市值", {}).get("cuts")
        vol_cuts = b.get("波动率", {}).get("cuts")
    _GCTX = {"board_map": board_map, "mktcap_map": mktcap_map,
             "size_cuts": size_cuts, "vol_cuts": vol_cuts}
    return _GCTX


def _proc(code):
    df = _load_kline(code)
    if df is None or len(df) < 80:
        return {}
    ctx = _group_ctx()
    groups = {"board": GD.board_group(ctx["board_map"].get(code)),
              "size": GD.size_group(ctx["mktcap_map"].get(code), ctx["size_cuts"]),
              "vol_cuts": ctx["vol_cuts"]}
    return accumulate_stock(df, pcts=DEFAULT_PCTS, fwd=4, groups=groups)


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
    run_ts = time.strftime("%Y%m%d_%H%M%S")
    paths = write_reports(rows, out_dir="/app/data/commonality_reports", ts=run_ts)           # 全市场ALL榜
    paths += write_grouped_reports(rows, out_dir="/app/data/commonality_reports", ts=run_ts)  # 分组uplift榜
    print(f"[共性挖掘] 股票{len(codes)} 组合keys{len(rows)} 用时{int(time.time()-t0)}s", flush=True)
    for pth in paths:
        print("  写", pth, flush=True)


if __name__ == "__main__":
    main()
