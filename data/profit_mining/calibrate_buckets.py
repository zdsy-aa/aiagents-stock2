# calibrate_buckets.py —— 算市值/波动率三分位切点 → group_buckets.json。轻量,无信号计算。
import json
import os
import sys
import time

import numpy as np

OUT = "/app/data/profit_mining/group_buckets.json"
SNAP = "/app/data/profit_mining/stock_mktcap_snapshot.csv"


def terciles(values):
    """→ [c1,c2] 三分位切点(33.33/66.67 百分位)。空输入抛 ValueError。"""
    arr = np.asarray(list(values), dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        raise ValueError("terciles: 空输入")
    c1, c2 = np.percentile(arr, [100 / 3.0, 200 / 3.0])
    return [float(c1), float(c2)]


def _size_cuts():
    """读快照 → 总市值三分位；快照缺则返回 None(市值维度本轮不可用)。"""
    if not os.path.exists(SNAP):
        print(f"[标定] 无 {SNAP}，跳过市值切点（市值维度将不分组）")
        return None
    import csv
    vals = []
    with open(SNAP, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                vals.append(float(r["总市值"]))
            except (ValueError, KeyError):
                pass
    return terciles(vals) if vals else None


def _vol_cuts():
    """遍历股票池,收集各 pct 事件拐点的 vol20 → 三分位。"""
    import mine_commonality as M
    import swing_samples as SW
    import group_dims as GD
    codes = M._universe()
    samples = []
    for k, code in enumerate(codes, 1):
        df = M._load_kline(code)
        if df is None or len(df) < 80:
            continue
        vol20 = GD.vol20_series(df)
        high = df["High"].tolist(); low = df["Low"].tolist()
        for pct in M.DEFAULT_PCTS:
            up, down = SW.positive_windows(high, low, pct)
            for wins in (up, down):
                for w in wins:
                    v = vol20[w[0]]
                    if np.isfinite(v):
                        samples.append(float(v))
        if k % 1000 == 0:
            print(f"  vol标定 …{k}/{len(codes)}，样本{len(samples)}", flush=True)
    return terciles(samples)


def main():
    t0 = time.time()
    size_cuts = _size_cuts()
    vol_cuts = _vol_cuts()
    out = {"市值": {"cuts": size_cuts}, "波动率": {"cuts": vol_cuts},
           "标定时间": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[标定] 写 {OUT} 市值cuts={size_cuts} 波动率cuts={vol_cuts} 用时{int(time.time()-t0)}s")


if __name__ == "__main__":
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    main()
