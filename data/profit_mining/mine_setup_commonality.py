# mine_setup_commonality.py —— 蓄势期特征共性挖掘(buy向/仅zz6, L1单+L2两两)。
# 复用 mine_presetup 的起涨前蓄势窗口 + 段级覆盖率; 信号库=presetup_signals(蓄势特征)。
import os, sys, time, csv as _csv
from collections import defaultdict
import numpy as np
import pandas as pd

import swing_samples as SW
import presetup_signals as PSig
from mine_commonality import finalize, filter_rank, _load_kline, _universe
from turnover_features import chip_series

PCT = 0.06
NEAR_N = 20
FAR = 7
TIGHT_K = int(os.getenv("TIGHT_K")) if os.getenv("TIGHT_K") else None

_TURN = {}   # {code: pd.Series(turn% , index=datetime)}; fork前填,COW共享不pickle


def _win_arrays(windows, n):
    st = np.fromiter((w[0] for w in windows), dtype=np.int64, count=len(windows))
    en = np.fromiter((w[-1] for w in windows), dtype=np.int64, count=len(windows))
    np.clip(st, 0, n - 1, out=st); np.clip(en, 0, n - 1, out=en)
    return st, en


def accumulate_setup(df, code, turn=None, tight_k=None):
    """单股 -> counts dict key=("ALL",level,"buy",PCT,name) val=[seg_hit,seg_total,
    fires_pos,bars_pos,fires_all,n]。level∈{L1,L2}; name=信号名(L2='a & b')。
    turn=该股换手率Series(None则chip类全False)。"""
    out = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    n = len(df)
    if n == 0:
        return dict(out)
    piv = SW.Z.zigzag_pivots(df["High"].tolist(), df["Low"].tolist(), PCT)
    wins = SW.presetup_windows_from_pivots(piv, NEAR_N, FAR, tight_k=tight_k)
    if not wins:
        return dict(out)
    st, en = _win_arrays(wins, n)
    seg_total = len(wins)

    profit = None
    if turn is not None:
        try:
            profit = chip_series(df, turn)["获利盘"].to_numpy(float)
        except Exception:
            profit = None

    l1_arr = {}
    for spec in PSig.L1_SPECS:
        l1_arr[spec[0]] = PSig.eval_l1(spec, df, profit).astype(bool)

    def tally(level, name, sig):
        csum = np.concatenate(([0], np.cumsum(sig, dtype=np.int64)))
        fires_all = int(sig.sum())
        wf = csum[en + 1] - csum[st]
        seg_hit = int(np.count_nonzero(wf)); fires_pos = int(wf.sum())
        bars_pos = int((en - st + 1).sum())   # 近窗口按构造重叠->bars_pos重复计:coverage精确,lift近似
        a = out[("ALL", level, "buy", PCT, name)]
        a[0] += seg_hit; a[1] += seg_total; a[2] += fires_pos
        a[3] += bars_pos; a[4] += fires_all; a[5] += n

    for name, arr in l1_arr.items():
        tally("L1", name, arr)
    for a, b in PSig.l2_pairs(list(l1_arr.keys())):
        tally("L2", f"{a} & {b}", l1_arr[a] & l1_arr[b])
    return dict(out)


def merge_counts(dst, src):
    for k, v in src.items():
        acc = dst[k]
        for i in range(6):
            acc[i] += v[i]


_METRIC_COLS = ["seg_hit", "seg_total", "coverage", "rate_all", "lift", "precision"]


def _write_one(fpath, ranked):
    with open(fpath, "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.writer(f)
        w.writerow(["level", "signal"] + _METRIC_COLS)
        for r in ranked:
            w.writerow([r["plan"], r["params"]] + [r[c] for c in _METRIC_COLS])


def _write_setup_reports(rows, out_dir="/app/data/commonality_reports", ts=None,
                         cover_min=0.50, topn=30, suffix=""):
    """rows(finalize后) -> 主榜(coverage>=门槛) + 最佳可达Top + 横向对比md。"""
    ts = ts or time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(out_dir, exist_ok=True)
    main = filter_rank(rows, cover_min=cover_min)                      # coverage>=门槛,按lift降序
    best = sorted([r for r in rows if r["rate_all"] > 0 and r["lift"] != float("inf")],
                  key=lambda r: r["lift"], reverse=True)[:topn]
    main_path = os.path.join(out_dir, f"蓄势特征_共性_zz6{suffix}_{ts}.csv")
    best_path = os.path.join(out_dir, f"蓄势特征_最佳可达_zz6{suffix}_{ts}.csv")
    _write_one(main_path, main); _write_one(best_path, best)
    md_path = os.path.join(out_dir, f"蓄势特征_横向对比{suffix}_{ts}.md")
    edge = [r for r in main if r["lift"] > 1.0]
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# 蓄势期特征共性 横向对比\n\n生成 {ts}，zz6，buy向(起涨前蓄势窗口)，"
                f"覆盖率门槛 {cover_min}；段级覆盖率，重点看 coverage>0.5 且 lift>1\n\n")
        f.write(f"- **达标(coverage≥{cover_min}) 组合数**：{len(main)}；其中 **lift>1 的**：{len(edge)}\n")
        if edge:
            f.write("- **★coverage>0.5 且 lift>1（真 edge）Top10**：\n")
            for r in edge[:10]:
                f.write(f"  - [{r['plan']}] {r['params']}：覆盖{r['coverage']:.2f} 提升度{r['lift']:.2f} 精确{r['precision']:.2f}\n")
        else:
            f.write("- 无 coverage>0.5 且 lift>1 的组合。\n")
        if best:
            b = best[0]
            f.write(f"- 全局最高 lift（不卡覆盖）：[{b['plan']}] {b['params']} "
                    f"覆盖{b['coverage']:.2f} 提升度{b['lift']:.2f} 精确{b['precision']:.2f}\n")
    return [main_path, best_path, md_path]


def _load_turn_by_code(path="/app/data/profit_mining/turnover.csv"):
    """turnover.csv(code,date,turn) -> {code: Series(turn%, index=datetime)}。填入全局 _TURN。"""
    if not os.path.exists(path):
        return
    df = pd.read_csv(path, dtype={"code": str})
    df["date"] = pd.to_datetime(df["date"])
    for code, g in df.groupby("code", sort=False):
        _TURN[code] = pd.Series(g["turn"].to_numpy(float),
                                index=pd.DatetimeIndex(g["date"].to_numpy()))


def _proc(code):
    try:
        df = _load_kline(code)
        if df is None or len(df) < 70:
            return {}
        return accumulate_setup(df, code, turn=_TURN.get(code), tight_k=TIGHT_K)
    except Exception:
        return {}


def main():
    from multiprocessing import Pool
    t0 = time.time()
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    _load_turn_by_code()                       # fork前填全局,worker COW共享
    print(f"  turnover 覆盖 {len(_TURN)} 股", flush=True)
    print(f"  窗口模式: {'紧窗口 K='+str(TIGHT_K) if TIGHT_K else '自适应'}", flush=True)
    codes = _universe()
    if limit:
        codes = codes[:limit]
    nproc = int(os.getenv("NPROC", "8"))
    acc = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    with Pool(nproc) as p:
        for k, c in enumerate(p.imap_unordered(_proc, codes, chunksize=8), 1):
            merge_counts(acc, c)
            if k % 500 == 0:
                print(f"  …{k}/{len(codes)}，{int(time.time()-t0)}s", flush=True)
    rows = finalize(acc)
    run_ts = time.strftime("%Y%m%d_%H%M%S")
    suffix = f"_tightK{TIGHT_K}" if TIGHT_K else ""
    paths = _write_setup_reports(rows, out_dir="/app/data/commonality_reports", ts=run_ts, suffix=suffix)
    print(f"[蓄势特征] 股票{len(codes)} 信号keys{len(rows)} 用时{int(time.time()-t0)}s", flush=True)
    for pth in paths:
        print("  写", pth, flush=True)


if __name__ == "__main__":
    main()
