"""全量导入：market（codes/calendar/kline）+ signals（自动建表+导入）。幂等：表先 DROP 重建。"""
import csv, io, os, sys
import sqlite3
from db import get_pg_conn, ro_sqlite
from convert import (
    to_ts, to_price, to_amount, to_bool, to_tstamp_str, sqlite_to_pg_type, TABLE_COMMENTS, COLUMN_COMMENTS,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # aiagents-stock/
KLINE_DIR = os.path.join(ROOT, "tdx-data", "database", "kline")
CODES_DB = os.path.join(ROOT, "tdx-data", "database", "codes.db")
WORKDAY_DB = os.path.join(ROOT, "tdx-data", "database", "workday.db")
DATA_DIR = os.path.join(ROOT, "data")

# 每个信号库的表： (源db路径, 源表名, PG表名)。来源前缀规则见 spec 5.2。
SIGNAL_DBS = [
    ("data/chanlun_signals.db", "signals", "chanlun_signals"),
    ("data/chanlun_signals_intraday.db", "signals", "chanlun_signals_intraday"),
    ("data/combo_signals.db", "combo_signals", "combo_signals"),
    ("data/liumai_signals.db", "liumai_signals", "liumai_signals"),
    ("data/longhubang.db", "longhubang_records", "longhubang_records"),
    ("data/longhubang.db", "longhubang_analysis", "longhubang_analysis"),
    ("data/longhubang.db", "stock_tracking", "stock_tracking"),
    ("data/low_price_bull_monitor.db", "monitored_stocks", "low_price_bull_monitored_stocks"),
    ("data/low_price_bull_monitor.db", "sell_alerts", "low_price_bull_sell_alerts"),
    ("data/main_force_batch.db", "batch_analysis_history", "main_force_batch_analysis_history"),
    ("data/news_flow.db", "flow_snapshots", "news_flow_snapshots"),
    ("data/news_flow.db", "platform_news", "news_flow_platform_news"),
    ("data/news_flow.db", "stock_related_news", "news_flow_stock_related_news"),
    ("data/news_flow.db", "hot_topics", "news_flow_hot_topics"),
    ("data/news_flow.db", "flow_statistics", "news_flow_statistics"),
    ("data/news_flow.db", "sentiment_records", "news_flow_sentiment_records"),
    ("data/news_flow.db", "flow_alerts", "news_flow_alerts"),
    ("data/news_flow.db", "ai_analysis", "news_flow_ai_analysis"),
    ("data/news_flow.db", "scheduler_logs", "news_flow_scheduler_logs"),
    ("data/news_flow.db", "alert_config", "news_flow_alert_config"),
    ("data/news_flow.db", "keyword_rankings", "news_flow_keyword_rankings"),
    ("data/news_flow.db", "keyword_history", "news_flow_keyword_history"),
    ("data/portfolio_stocks.db", "portfolio_stocks", "portfolio_stocks"),
    ("data/portfolio_stocks.db", "portfolio_analysis_history", "portfolio_analysis_history"),
    ("data/profit_growth_monitor.db", "monitored_stocks", "profit_growth_monitored_stocks"),
    ("data/profit_growth_monitor.db", "sell_alerts", "profit_growth_sell_alerts"),
    ("data/qizhang_picks.db", "daily_picks", "qizhang_daily_picks"),
    ("data/qizhang_picks.db", "realized", "qizhang_realized"),
    ("data/qizhang_picks.db", "run_meta", "qizhang_run_meta"),
    ("data/sector_strategy.db", "sector_raw_data", "sector_raw_data"),
    ("data/sector_strategy.db", "sector_news_data", "sector_news_data"),
    ("data/sector_strategy.db", "sector_analysis_reports", "sector_analysis_reports"),
    ("data/sector_strategy.db", "sector_tracking", "sector_tracking"),
    ("data/sector_strategy.db", "data_versions", "sector_data_versions"),
    ("data/smart_monitor.db", "monitor_tasks", "smart_monitor_tasks"),
    ("data/smart_monitor.db", "ai_decisions", "smart_monitor_ai_decisions"),
    ("data/smart_monitor.db", "trade_records", "smart_monitor_trade_records"),
    ("data/smart_monitor.db", "position_monitor", "smart_monitor_position_monitor"),
    ("data/smart_monitor.db", "notifications", "smart_monitor_notifications"),
    ("data/smart_monitor.db", "system_logs", "smart_monitor_system_logs"),
    ("data/stock_analysis.db", "analysis_records", "stock_analysis_records"),
    ("data/stock_monitor.db", "monitored_stocks", "stock_monitor_monitored_stocks"),
    ("data/stock_monitor.db", "price_history", "stock_monitor_price_history"),
    ("data/stock_monitor.db", "notifications", "stock_monitor_notifications"),
]


def build_create_table(pg_table, cols):
    defs = []
    for i, (n, t) in enumerate(cols):
        col = f'"{n}" {sqlite_to_pg_type(t)}'
        if i == 0 and n == "id":
            col += " PRIMARY KEY"   # 首列名为 id 时建为主键，供增量同步 ON CONFLICT 去重
        defs.append(col)
    return f'CREATE TABLE signals.{pg_table} ({", ".join(defs)});'


def build_comments(pg_table, cols):
    stmts = [f"COMMENT ON TABLE signals.{pg_table} IS '{TABLE_COMMENTS.get(pg_table, pg_table)}';"]
    for n, _t in cols:
        c = COLUMN_COMMENTS.get(n, n)
        stmts.append(f"COMMENT ON COLUMN signals.{pg_table}.{n} IS '{c}';")
    return stmts


def copy_csv(conn, table, rows):
    """rows: iterable of str tuples；用 COPY ... FROM STDIN CSV 批量写入。"""
    buf = io.StringIO()
    w = csv.writer(buf)
    for r in rows:
        # 源库脏数据兜底：数值列里混入 BLOB（如 low_price_bull_sell_alerts.current_price
        # 实为本地时间/打包整数错写），一律置 NULL，避免整表导入崩溃
        w.writerow([('' if isinstance(v, (bytes, bytearray)) else v) for v in r])
    buf.seek(0)
    cur = conn.cursor()
    cur.copy_expert(f"COPY {table} FROM STDIN WITH CSV", buf)
    conn.commit()


def import_codes_calendar(conn):
    c = ro_sqlite(CODES_DB)
    rows = c.execute("SELECT ID,Name,Code,Exchange,Multiple,Decimal,LastPrice,EditDate,InDate FROM codes")
    out = ((r[0], r[1], r[2], r[3], r[4], r[5], r[6], to_ts(r[7]), to_ts(r[8])) for r in rows)
    copy_csv(conn, "market.stock_codes", out)
    w = ro_sqlite(WORKDAY_DB)
    rows = w.execute("SELECT ID,Unix,Date FROM workday")
    # Date 可能是 'YYYYMMDD' 或 'YYYY-MM-DD'，统一转 DATE
    def conv_date(d):
        if not d:
            return None
        d = str(d)
        if "-" not in d and len(d) == 8:
            d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        return d
    out = ((r[0], to_ts(r[1]), conv_date(r[2])) for r in rows)
    copy_csv(conn, "market.trade_calendar", out)


def import_market_kline(conn):
    files = sorted(os.listdir(KLINE_DIR))
    files = [f for f in files if f.endswith(".db")]
    tables = [("DayKline", "market.kline_day"), ("Minute5Kline", "market.kline_5min"), ("Minute30Kline", "market.kline_30min")]
    for i, fn in enumerate(files):
        code = fn[:-3]  # 去掉 .db
        path = os.path.join(KLINE_DIR, fn)
        try:
            c = ro_sqlite(path)
        except sqlite3.Error as e:
            print(f"[跳过] {fn}: {e}", flush=True); continue
        for src_tbl, pg_tbl in tables:
            rows = c.execute(f"SELECT Date,Open,High,Low,Close,Volume,Amount,InDate FROM {src_tbl}")
            out = ((code, to_ts(r[0]), to_price(r[1]), to_price(r[2]), to_price(r[3]),
                    to_price(r[4]), r[5], to_amount(r[6]), to_ts(r[7])) for r in rows)
            copy_csv(conn, pg_tbl, out)
        c.close()
        if (i + 1) % 500 == 0:
            print(f"  进度 {i+1}/{len(files)}", flush=True)
    print(f"K线导入完成：{len(files)} 只", flush=True)


def import_signals(conn):
    cur = conn.cursor()
    for rel, src_tbl, pg_tbl in SIGNAL_DBS:
        path = os.path.join(ROOT, rel)
        c = ro_sqlite(path)
        cols = [(r[1], r[2]) for r in c.execute(f"PRAGMA table_info({src_tbl})")]
        cur.execute(f"DROP TABLE IF EXISTS signals.{pg_tbl} CASCADE")
        cur.execute(build_create_table(pg_tbl, cols))
        for s in build_comments(pg_tbl, cols):
            cur.execute(s)
        conn.commit()
        sel_cols = ",".join('"%s"' % n for n, _t in cols)
        rows = c.execute("SELECT %s FROM %s" % (sel_cols, src_tbl))
        # 逐列类型转换：BOOLEAN→to_bool，TIMESTAMP/DATETIME→to_tstamp_str（源声明 TIMESTAMP 实为本地时间 TEXT 字符串），其余原样
        # 注意：market K 线用 to_ts（Date 是 Unix 秒）；信号库 TIMESTAMP 字段是文本字符串，必须用 to_tstamp_str
        convs = [to_bool if t.upper() in ("BOOLEAN","BOOL") else (to_tstamp_str if t.upper() in ("TIMESTAMP","DATETIME") else (lambda x: x))
                 for _n, t in cols]
        out = (tuple(cv(v) for cv, v in zip(convs, r)) for r in rows)
        copy_csv(conn, f"signals.{pg_tbl}", out)
        c.close()
        print(f"  {pg_tbl}: 导入完成", flush=True)


def rebuild_market_schema(conn):
    """幂等重建 market schema：DROP 下表再按 schema.sql 建（含唯一索引）。"""
    cur = conn.cursor()
    for t in ("stock_codes", "trade_calendar", "kline_day", "kline_5min", "kline_30min"):
        cur.execute(f"DROP TABLE IF EXISTS market.{t} CASCADE")
    conn.commit()
    schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
    with open(schema_path) as f:
        sql_text = f.read()
    # psycopg2 不支持一条 execute 跑多条 SQL，按分号拆成语句逐条执行
    for stmt in sql_text.split(";\n"):
        stmt = stmt.strip()
        if stmt:
            cur.execute(stmt)
    conn.commit()


def main():
    import shutil
    total, _used, free = shutil.disk_usage(ROOT)
    free_gb = free // 1024**3
    print(f"[磁盘] 剩余 {free_gb}GB（建议 30GB 以上）", flush=True)
    if free < 30 * 1024**3:
        print(f"[警告] 剩余磁盘不足 30GB，PG 数据约需 15-25GB，建议先清理", flush=True)
    conn = get_pg_conn()
    cur = conn.cursor()
    cur.execute("CREATE SCHEMA IF NOT EXISTS market")
    cur.execute("CREATE SCHEMA IF NOT EXISTS signals")
    conn.commit()
    # 幂等：先 DROP 再重建 market 表（避免重跑数据翻倍）
    rebuild_market_schema(conn)
    print("导入 codes / workday …", flush=True)
    import_codes_calendar(conn)
    print("导入 K线（约 2 亿行，需 10-30 分钟）…", flush=True)
    import_market_kline(conn)
    print("导入信号库 …", flush=True)
    import_signals(conn)
    conn.close()
    print("全部完成", flush=True)


if __name__ == "__main__":
    main()
