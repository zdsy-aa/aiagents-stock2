# fetch_turnover_yearly.py —— baostock 换手率「按年」下载，存本地、可断点续传、并行、带超时重试。
#   每年一个文件 turnover_by_year/turnover_YYYY.csv；已完成的年自动跳过(续传)。
#   全部下完后自动合并成 turnover.csv。
# 运行: docker exec -w /app agentsstock1 python3 /app/data/profit_mining/fetch_turnover_yearly.py [起始年] [结束年]
#   或本机: ! docker exec -w /app agentsstock1 python3 /app/data/profit_mining/fetch_turnover_yearly.py 2001 2026
import sys, os, csv, time, socket, glob
socket.setdefaulttimeout(20)   # 防 baostock 无响应时无限卡死
csv.field_size_limit(10 ** 7)

LABELS = "/app/data/profit_mining/labels.csv"
YDIR = "/app/data/profit_mining/turnover_by_year"
MERGED = "/app/data/profit_mining/turnover.csv"
NPROC = int(os.getenv("NPROC", "8"))


def _bcode(code):
    code = str(code).zfill(6)
    if code[0] == "6":
        return "sh." + code
    if code[0] in ("0", "3"):
        return "sz." + code
    return None


def _codes():
    return sorted({r["股票代码"] for r in csv.DictReader(open(LABELS, encoding="utf-8-sig"))})


def _login_probe(q):
    try:
        import baostock as bs
        lg = bs.login()
        q.put((lg.error_code == "0", lg.error_msg))
        if lg.error_code == "0":
            bs.logout()
    except Exception as e:
        q.put((False, f"{type(e).__name__}: {str(e)[:80]}"))


def _check_baostock(timeout=25):
    """连通性预检：子进程登录+硬超时，避免 baostock 内部连接无限卡死。"""
    from multiprocessing import Process, Queue
    q = Queue()
    p = Process(target=_login_probe, args=(q,))
    p.start(); p.join(timeout)
    if p.is_alive():
        p.kill(); p.join(5)        # SIGKILL，C层socket卡死也能杀
        return False, f"登录超时>{timeout}s(服务端/网络不可达)"
    try:
        return q.get_nowait()
    except Exception:
        return False, "登录无返回"


# ---- 子进程：抓一批code某一年的换手率 ----
_W = {}


def _w_init(year):
    import baostock as bs
    bs.login()
    _W["bs"] = bs
    _W["start"] = f"{year}-01-01"
    _W["end"] = f"{year}-12-31"


def _w_proc(code):
    bs = _W["bs"]
    bc = _bcode(code)
    if not bc:
        return []
    for _ in range(2):   # 每只重试2次
        try:
            rs = bs.query_history_k_data_plus(bc, "date,turn", start_date=_W["start"],
                                              end_date=_W["end"], frequency="d", adjustflag="2")
            out = []
            while rs.error_code == "0" and rs.next():
                d, t = rs.get_row_data()
                if t:
                    out.append((code, d, t))
            return out
        except Exception:
            time.sleep(1)
    return []


def fetch_year(year, codes):
    from multiprocessing import Pool
    out_file = f"{YDIR}/turnover_{year}.csv"
    done_mark = out_file + ".done"
    if os.path.exists(done_mark):
        return None   # 已完成，跳过(续传)
    t0 = time.time()
    rows = 0
    with open(out_file, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["code", "date", "turn"])
        with Pool(NPROC, initializer=_w_init, initargs=(year,)) as p:
            for part in p.imap_unordered(_w_proc, codes, chunksize=40):
                for r in part:
                    w.writerow(r); rows += 1
    if rows >= 50000:                 # 行数太少视为baostock抖动失败,不标done,下次续传重抓
        open(done_mark, "w").write("ok")
        print(f"  [{year}] 完成 {rows} 行，{int(time.time()-t0)}s", flush=True)
    else:
        print(f"  [{year}] 仅 {rows} 行(疑似失败,未标done,下次重抓)，{int(time.time()-t0)}s", flush=True)
    return rows


def merge():
    files = sorted(glob.glob(f"{YDIR}/turnover_*.csv"))
    n = 0
    with open(MERGED, "w", newline="", encoding="utf-8-sig") as out:
        w = csv.writer(out); w.writerow(["code", "date", "turn"])
        for fp in files:
            try:
                with open(fp, encoding="utf-8-sig") as f:
                    rd = csv.reader(f); next(rd, None)
                    for r in rd:
                        if len(r) == 3:
                            w.writerow(r); n += 1
            except Exception as e:
                print(f"  [合并] 跳过损坏文件 {os.path.basename(fp)}: {type(e).__name__}", flush=True)
    print(f"[合并] {len(files)} 个年文件 -> {MERGED}，共 {n} 行", flush=True)


def main():
    y0 = int(sys.argv[1]) if len(sys.argv) > 1 else 2001
    y1 = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
    os.makedirs(YDIR, exist_ok=True)
    ok, msg = False, ""
    for attempt in range(3):     # 抗瞬时超时，重试3次
        ok, msg = _check_baostock()
        if ok:
            break
        print(f"[预检] 第{attempt+1}次连接失败({msg})，重试…", flush=True)
        time.sleep(3)
    if not ok:
        print(f"[预检] baostock 不可达({msg})；本次不下载。恢复后重跑即可(已完成的年会自动跳过)。", flush=True)
        # 即便不可达，也把已下好的年文件合并一次
        if glob.glob(f"{YDIR}/turnover_*.csv"):
            merge()
        return
    codes = _codes()
    print(f"[年度下载] baostock 可用；股票 {len(codes)} 只，年份 {y0}-{y1}，并行 {NPROC}", flush=True)
    for year in range(y0, y1 + 1):
        try:
            fetch_year(year, codes)
        except Exception as e:
            print(f"  [{year}] 失败 {type(e).__name__}: {str(e)[:80]}(该年未标done，下次续传)", flush=True)
    merge()
    print("[年度下载] 全部完成", flush=True)


if __name__ == "__main__":
    main()
