# build_features_v2.py —— 对 events_labeled.csv 每事件算 ±2 窗口特征 → features_v2.csv
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/build_features_v2.py
import sys, csv, time, os
sys.path.insert(0, "/app"); sys.path.insert(0, "/app/data/profit_mining")
from collections import defaultdict
import pandas as pd
import features as F

EVENTS_CSV = "/app/data/profit_mining/events_labeled.csv"
IDXCSV = "/app/data/profit_mining/index_sh000001.csv"
OUT = "/app/data/profit_mining/features_v2.csv"
_RENAME = {"开盘":"Open","最高":"High","最低":"Low","收盘":"Close","成交量":"Volume"}
OFFSET = 2

def _load(code):
    from akshare_gateway import akshare_gw
    df = akshare_gw.local.get_kline(code, kline_type="day", limit=10000)
    if df is None or df.empty:
        return None
    return df.rename(columns=_RENAME).set_index("日期").sort_index()[["Open","High","Low","Close","Volume"]]

def _load_index():
    df = pd.read_csv(IDXCSV, encoding="utf-8-sig"); df["日期"] = pd.to_datetime(df["日期"])
    return df.set_index("日期").sort_index()[["Open","High","Low","Close","Volume"]]

_G = {}
BY_CODE = {}   # 2.4M行事件按股分组:fork前在父进程赋值,worker经COW继承,避免pickle到每个worker(否则卡死)

def _init(ist, iclose, bool_cols):
    _G.update(ist=ist, iclose=iclose, bool_cols=bool_cols)

def _proc(code):
    df = _load(code)
    if df is None or len(df) < 80:
        return []
    rel = F.relative_strength(df["Close"], _G["iclose"].reindex(df.index).ffill()) if _G["iclose"] is not None else None
    ff = F.assemble_feature_frame(df, _G["ist"], rel, code=code)
    pos = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(df.index)}
    # 一次性向量化预算每列的后向窗口OR(信号日及前4根[i-4,i],不窥见信号后→消除前向泄漏)与连续值,
    # 避免逐事件×逐列切片(原逐调用21s/股,全量26h不可行)。rolling默认右对齐=只看当前及之前。
    W = 2 * OFFSET + 1
    win = {col: (ff[col].fillna(0) > 0).rolling(W, min_periods=1).max().to_numpy()
           for col in _G["bool_cols"] if col in ff.columns}
    cont = {col: ff[col].to_numpy() for col in F.CONTINUOUS_COLS if col in ff.columns}
    rows = []
    for r in BY_CODE.get(code, ()):
        sd = r["信号日期"]
        if sd not in pos:
            continue
        i = pos[sd]
        rec = {"组": r["组"], "family": r["family"], "direction": r["direction"],
               "股票代码": code, "信号日期": sd, "标签": int(r["标签"]),
               "极值收益": r["极值收益"], "truncated": r["truncated"]}
        for col in _G["bool_cols"]:
            rec[col] = int(win[col][i]) if col in win else ""
        for col in F.CONTINUOUS_COLS:
            if col in cont:
                v = cont[col][i]
                rec[col] = round(float(v), 4) if pd.notna(v) else ""
            else:
                rec[col] = ""
        rows.append(rec)
    return rows

def main():
    global BY_CODE
    ev = list(csv.DictReader(open(EVENTS_CSV, encoding="utf-8-sig")))
    by_code = defaultdict(list)
    for r in ev:
        by_code[r["股票代码"]].append(r)
    BY_CODE = by_code            # fork前赋值到模块全局,worker经COW共享(不进initargs)
    codes = sorted(by_code)
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if limit:
        codes = codes[:limit]
    idx = _load_index(); ist = F.index_state(idx); iclose = idx["Close"]
    # 探测布尔列
    bool_cols = None
    for code in codes:
        df = _load(code)
        if df is None or len(df) < 80:
            continue
        rel = F.relative_strength(df["Close"], iclose.reindex(df.index).ffill())
        ff = F.assemble_feature_frame(df, ist, rel, code=code)
        skip = set(F.CONTINUOUS_COLS) | {"大盘状态ID"}
        bool_cols = [c for c in ff.columns if c not in skip]
        break
    out_rows = []; t0 = time.time()
    from multiprocessing import Pool
    nproc = int(os.getenv("NPROC", "8"))
    with Pool(nproc, initializer=_init, initargs=(ist, iclose, bool_cols)) as p:
        for k, rows in enumerate(p.imap_unordered(_proc, codes, chunksize=30), 1):
            out_rows.extend(rows)
            if k % 1000 == 0:
                print(f"  …{k}/{len(codes)}，行 {len(out_rows)}，{int(time.time()-t0)}s", flush=True)
    head = ["组","family","direction","股票代码","信号日期","标签","极值收益","truncated"]
    cols = head + (bool_cols or []) + F.CONTINUOUS_COLS
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in out_rows:
            w.writerow(r)
    print(f"[特征V2] 完成 {len(out_rows)} 行，布尔 {len(bool_cols or [])}，写入 {OUT}，{int(time.time()-t0)}s", flush=True)

if __name__ == "__main__":
    main()
