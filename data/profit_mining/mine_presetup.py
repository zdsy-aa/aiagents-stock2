# mine_presetup.py —— 起涨前蓄势窗口共性挖掘(buy向/仅zz6)。
# 窗口=每个>=6%上涨段起涨前的蓄势期(近=上一涨段+下降段/远=前7天,含波谷L)。
# 段级覆盖率: 窗口内任一bar触发即该段命中。复用 mine_commonality 的 finalize/写榜。
import os, sys, time
from collections import defaultdict
import numpy as np

import swing_samples as SW
import param_signals as PS
from mine_commonality import (finalize, filter_rank, _write_board, _expand_params,
                              _load_kline, _universe)

PCT = 0.06
NEAR_N = 20
FAR = 7


def _win_arrays(windows, n):
    st = np.fromiter((w[0] for w in windows), dtype=np.int64, count=len(windows))
    en = np.fromiter((w[-1] for w in windows), dtype=np.int64, count=len(windows))
    np.clip(st, 0, n - 1, out=st); np.clip(en, 0, n - 1, out=en)
    return st, en


def accumulate_presetup(df, pct=PCT, near_n=NEAR_N, far=FAR):
    """单股 -> counts dict key=("ALL",plan,"buy",pct,params) val=[seg_hit,seg_total,
    fires_pos,bars_pos,fires_all,n]。窗口=presetup(buy向)。"""
    out = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    n = len(df)
    if n == 0:
        return dict(out)
    piv = SW.Z.zigzag_pivots(df["High"].tolist(), df["Low"].tolist(), pct)
    wins = SW.presetup_windows_from_pivots(piv, near_n, far)
    if not wins:
        return dict(out)
    st, en = _win_arrays(wins, n)
    seg_total = len(wins)
    macd_cache, fib_cache, bbi_cache = {}, {}, {}

    def tally(plan, params, sig):
        csum = np.concatenate(([0], np.cumsum(sig, dtype=np.int64)))
        fires_all = int(sig.sum())
        wf = csum[en + 1] - csum[st]            # 每窗口命中bar数
        seg_hit = int(np.count_nonzero(wf)); fires_pos = int(wf.sum())
        bars_pos = int((en - st + 1).sum())     # 近窗口"按构造"会与上一段窗口重叠,bars_pos/fires_pos按窗口求和(共享bar重复计)→lift为近似;coverage(seg级)不受影响,精确
        a = out[("ALL", plan, "buy", pct, params)]
        a[0] += seg_hit; a[1] += seg_total; a[2] += fires_pos
        a[3] += bars_pos; a[4] += fires_all; a[5] += n

    for params in PS.PLAN_A_GRID:
        N, r, b, f, s, sg = params
        m = fib_cache.get((N, r, b))
        if m is None:
            m = PS.fib_support_hold(df, N, r, b).to_numpy(); fib_cache[(N, r, b)] = m
        mc = macd_cache.get((f, s, sg))
        if mc is None:
            mc = PS.macd_golden(df, f, s, sg).to_numpy(); macd_cache[(f, s, sg)] = mc
        tally("A", params, m & mc)
    for params in PS.PLAN_B_GRID:
        periods, form, f, s, sg = params
        bb = bbi_cache.get((periods, form))
        if bb is None:
            bb = PS._bbi_form(df, periods, form, "buy").to_numpy(); bbi_cache[(periods, form)] = bb
        mc = macd_cache.get((f, s, sg))
        if mc is None:
            mc = PS.macd_golden(df, f, s, sg).to_numpy(); macd_cache[(f, s, sg)] = mc
        tally("B", params, bb & mc)
    return dict(out)


def merge_counts(dst, src):
    for k, v in src.items():
        a = dst[k]
        for i in range(6):
            a[i] += v[i]


def write_presetup_reports(rows, out_dir="/app/data/commonality_reports", ts=None,
                           cover_min=0.50, topn=30):
    """rows(finalize后,仅group=ALL/buy/zz6) -> 每方案两类CSV + 横向对比md。"""
    ts = ts or time.strftime("%Y%m%d_%H%M%S")
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    summary = []
    for plan in ("A", "B"):
        sub = [r for r in rows if r["plan"] == plan]
        # 主榜: coverage>=门槛
        main = filter_rank(sub, cover_min=cover_min)
        main_path = os.path.join(out_dir, f"方案{plan}_起涨前蓄势_zz6_{ts}.csv")
        _write_board(main_path, plan, "buy", PCT, main); paths.append(main_path)
        # 最佳可达: 不卡覆盖率,按lift取Top
        best = sorted([r for r in sub if r["rate_all"] > 0 and r["lift"] != float("inf")],
                      key=lambda r: r["lift"], reverse=True)[:topn]
        best_path = os.path.join(out_dir, f"方案{plan}_起涨前蓄势最佳可达_zz6_{ts}.csv")
        _write_board(best_path, plan, "buy", PCT, best); paths.append(best_path)
        if main:
            b = main[0]
            summary.append(f"- **方案{plan} 起涨前蓄势 zz6**：达标{len(main)}组，"
                           f"最佳 {_expand_params(plan, b['params'])} 覆盖{b['coverage']:.2f} "
                           f"提升度{b['lift']:.2f} 精确{b['precision']:.2f}")
        elif best:
            b = best[0]
            summary.append(f"- **方案{plan} 起涨前蓄势 zz6**：无≥{cover_min}达标；"
                           f"最佳可达 {_expand_params(plan, b['params'])} 覆盖{b['coverage']:.2f} "
                           f"提升度{b['lift']:.2f} 精确{b['precision']:.2f}")
        else:
            summary.append(f"- **方案{plan} 起涨前蓄势 zz6**：无数据")
    md_path = os.path.join(out_dir, f"起涨前蓄势_横向对比_{ts}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# 起涨前蓄势窗口共性 横向对比\n\n生成 {ts}，zz6，buy向，覆盖率门槛 {cover_min}，"
                f"近窗口=上一涨段+下降段(gap≤{NEAR_N})/远窗口=前{FAR}天(均含波谷L)\n\n")
        f.write("\n".join(summary) + "\n")
    paths.append(md_path)
    return paths


def _proc(code):
    try:
        df = _load_kline(code)
        if df is None or len(df) < 60:
            return {}
        return accumulate_presetup(df)
    except Exception:
        return {}


def main():
    from multiprocessing import Pool
    t0 = time.time()
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
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
    paths = write_presetup_reports(rows, out_dir="/app/data/commonality_reports", ts=run_ts)
    print(f"[起涨前蓄势] 股票{len(codes)} 组合keys{len(rows)} 用时{int(time.time()-t0)}s", flush=True)
    for pth in paths:
        print("  写", pth, flush=True)


if __name__ == "__main__":
    main()
