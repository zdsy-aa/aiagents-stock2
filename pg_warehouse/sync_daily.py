"""每日增量同步：只追加源库中 > PG 最新值的行，天然幂等（第二次 0 新增）。

K 线按 code 各自对比 PG 中该 code 的 max(ts)（用 SQL 在 PG 内换算 Unix 秒，
避免客户端时区歧义），只取 Date > 该值的新 bar；codes/workday 及带 id 主键的信号表
按 id 增量；无 id 主键的信号表（如 qizhang 三表）走 TRUNCATE+COPY 全量覆盖。
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db import get_pg_conn, ro_sqlite
from convert import to_ts, to_price, to_amount, to_tstamp_str, to_bool
from import_all import (
    ROOT, KLINE_DIR, CODES_DB, WORKDAY_DB, SIGNAL_DBS,
    build_create_table, build_comments, copy_csv,
)


KLINE_TABLES = [
    ("DayKline", "market.kline_day"),
    ("Minute5Kline", "market.kline_5min"),
    ("Minute30Kline", "market.kline_30min"),
]


def has_id_pk(cols):
    """cols: list[(name, sqlite_type)]；首列名为 id 且有主键语义 → True。"""
    return bool(cols) and cols[0][0] == "id"


def sync_kline(conn, max_codes=None):
    """K 线增量。max_codes: 仅同步前 N 只（调试/测试用）。返回 dict pg_tbl -> 新增数。"""
    cur = conn.cursor()
    stats = {}
    files = sorted(f for f in os.listdir(KLINE_DIR) if f.endswith(".db"))
    if max_codes is not None:
        files = files[:max_codes]
    for fn in files:
        code = fn[:-3]
        c = ro_sqlite(os.path.join(KLINE_DIR, fn))
        for src_tbl, pg_tbl in KLINE_TABLES:
            # 修正 A：截止值用 SQL 在 PG 内换算 Unix 秒，避免 Python 时区歧义错 8h
            cur.execute(f"SELECT EXTRACT(EPOCH FROM MAX(ts))::bigint FROM {pg_tbl} WHERE code=%s", (code,))
            unix = cur.fetchone()[0]   # 已是整数 Unix 秒，或 None
            if unix is None:
                rows = c.execute(f"SELECT Date,Open,High,Low,Close,Volume,Amount,InDate FROM {src_tbl}")
            else:
                rows = c.execute(f"SELECT Date,Open,High,Low,Close,Volume,Amount,InDate FROM {src_tbl} WHERE Date > ?", (unix,))
            buf = []
            for r in rows:
                # 修正 C：amount 与 import_all 一致，÷1000 转元
                buf.append((code, to_ts(r[0]), to_price(r[1]), to_price(r[2]),
                            to_price(r[3]), to_price(r[4]), r[5], to_amount(r[6]), to_ts(r[7])))
            if buf:
                copy_csv(conn, pg_tbl, buf)
                stats[pg_tbl] = stats.get(pg_tbl, 0) + len(buf)
        c.close()
    return stats


def sync_codes_calendar(conn):
    """codes / workday：按主键 id 增量。返回 dict pg_tbl -> 新增数。"""
    cur = conn.cursor()
    stats = {}
    for name, path, pg_tbl in [("codes", CODES_DB, "market.stock_codes"),
                               ("workday", WORKDAY_DB, "market.trade_calendar")]:
        c = ro_sqlite(path)
        cur.execute(f"SELECT COALESCE(MAX(id), -1) FROM {pg_tbl}")
        mx = cur.fetchone()[0]
        if name == "codes":
            rows = c.execute("SELECT ID,Name,Code,Exchange,Multiple,Decimal,LastPrice,EditDate,InDate FROM codes WHERE ID > ?", (mx,))
            out = [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], to_ts(r[7]), to_ts(r[8])) for r in rows]
        else:
            rows = c.execute("SELECT ID,Unix,Date FROM workday WHERE ID > ?", (mx,))
            out = [(r[0], to_ts(r[1]), r[2]) for r in rows]
        if out:
            copy_csv(conn, pg_tbl, out)
        c.close()
        stats[pg_tbl] = len(out)
    return stats


def sync_signals(conn):
    """信号库：带 id 主键按 id 增量；无 id 主键全量覆盖（TRUNCATE+COPY）。返回 dict pg_tbl -> 新增数。"""
    cur = conn.cursor()
    stats = {}
    for rel, src_tbl, pg_tbl in SIGNAL_DBS:
        path = os.path.join(ROOT, rel)
        c = ro_sqlite(path)
        cols = [(r[1], r[2]) for r in c.execute(f"PRAGMA table_info({src_tbl})")]
        # 表不存在则先建（首次运行）
        cur.execute("SELECT to_regclass(%s)", (f"signals.{pg_tbl}",))
        if cur.fetchone()[0] is None:
            cur.execute(build_create_table(pg_tbl, cols))
            for s in build_comments(pg_tbl, cols):
                cur.execute(s)
            conn.commit()
        has_id = has_id_pk(cols)
        if has_id:
            cur.execute(f"SELECT COALESCE(MAX(id), -1) FROM signals.{pg_tbl}")
            mx = cur.fetchone()[0]
            rows = c.execute(f"SELECT * FROM {src_tbl} WHERE id > ?", (mx,))
        else:
            # 修正 B：无 id 主键 → TRUNCATE 全量覆盖，避免每次追加数据翻倍
            cur.execute(f"TRUNCATE signals.{pg_tbl}")
            conn.commit()
            rows = c.execute(f"SELECT * FROM {src_tbl}")
        convs = [to_bool if t.upper() in ("BOOLEAN", "BOOL")
                 else (to_tstamp_str if t.upper() in ("TIMESTAMP", "DATETIME") else (lambda x: x))
                 for _n, t in cols]
        out = [tuple(cv(v) for cv, v in zip(convs, r)) for r in rows]
        if out:
            copy_csv(conn, f"signals.{pg_tbl}", out)
        c.close()
        stats[pg_tbl] = len(out)
    return stats


def run_sync(max_kline_codes=None):
    """每日增量同步入口。返回 dict：每表新增行数汇总（Task 5 调度调用）。"""
    conn = get_pg_conn()
    stats = {}

    print("同步 codes / workday …", flush=True)
    st = sync_codes_calendar(conn)
    stats.update(st)
    for k, v in st.items():
        print(f"  {k}: +{v}", flush=True)

    print("同步 K线 …", flush=True)
    st = sync_kline(conn, max_codes=max_kline_codes)
    stats.update(st)
    for k, v in st.items():
        print(f"  {k}: +{v}", flush=True)
    if max_kline_codes is not None:
        print(f"  (调试：仅限前 {max_kline_codes} 只)", flush=True)

    print("同步信号库 …", flush=True)
    st = sync_signals(conn)
    stats.update(st)
    for k, v in st.items():
        print(f"  {k}: +{v}", flush=True)

    conn.close()
    return stats


if __name__ == "__main__":
    run_sync()
