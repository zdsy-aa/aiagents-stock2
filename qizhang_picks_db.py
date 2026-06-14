# qizhang_picks_db.py
"""起涨预测 paper-tracking 落库（沿用 BaseDatabase.conn() 风格）。

三表：
- daily_picks：每日 top-N 候选(scan_date 当日)。riskoff 日不写候选,只在 run_meta 记 gate。
- realized   ：候选到期后回填的 C4(移动止盈)退出结果。
- run_meta   ：每次批跑一行,可观测。
"""
import logging

import pandas as pd

from base_db import BaseDatabase

_PICK_COLS = ["scan_date", "code", "name", "score", "rank", "entry_ref_price", "riskoff"]
_REAL_COLS = ["scan_date", "code", "exit_date", "holding_days", "realized_return",
              "hit_10pct", "exit_reason", "bench_return"]


class QizhangPicksDatabase(BaseDatabase):
    def __init__(self, db_path="qizhang_picks.db"):
        self.logger = logging.getLogger(__name__)
        super().__init__(db_path)

    def init_tables(self):
        with self.conn() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_picks (
                scan_date TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT,
                score REAL,
                rank INTEGER,
                entry_ref_price REAL,
                riskoff INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(scan_date, code)
            )""")
            conn.execute("""
            CREATE TABLE IF NOT EXISTS realized (
                scan_date TEXT NOT NULL,
                code TEXT NOT NULL,
                exit_date TEXT,
                holding_days INTEGER,
                realized_return REAL,
                hit_10pct INTEGER,
                exit_reason TEXT,
                bench_return REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(scan_date, code)
            )""")
            conn.execute("""
            CREATE TABLE IF NOT EXISTS run_meta (
                scan_date TEXT PRIMARY KEY,
                model_train_rows INTEGER,
                train_end_date TEXT,
                sh_ma20_gate INTEGER,
                status TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")

    def save_daily_picks(self, scan_date, picks, riskoff=False):
        """picks: list[dict(code,name,score,rank,entry_ref_price)]。riskoff 日通常传 []。"""
        with self.conn() as conn:
            conn.execute("DELETE FROM daily_picks WHERE scan_date=?", (scan_date,))
            for p in picks:
                conn.execute(
                    f"INSERT INTO daily_picks ({','.join(_PICK_COLS)}) "
                    f"VALUES ({','.join(['?'] * len(_PICK_COLS))})",
                    (scan_date, p["code"], p.get("name"), p.get("score"),
                     p.get("rank"), p.get("entry_ref_price"), 1 if riskoff else 0))
        return len(picks)

    def get_picks_by_date(self, scan_date) -> pd.DataFrame:
        with self.conn() as conn:
            return pd.read_sql_query(
                "SELECT * FROM daily_picks WHERE scan_date=? ORDER BY rank", conn,
                params=(scan_date,))

    def get_latest_pick_date(self):
        with self.conn() as conn:
            row = conn.execute("SELECT MAX(scan_date) FROM daily_picks").fetchone()
        return row[0] if row and row[0] else None

    def get_unrealized_picks(self):
        """返回尚未回填 realized 的 (scan_date, code) 列表（仅非 riskoff 候选）。"""
        with self.conn() as conn:
            rows = conn.execute("""
                SELECT d.scan_date, d.code FROM daily_picks d
                LEFT JOIN realized r ON d.scan_date=r.scan_date AND d.code=r.code
                WHERE d.riskoff=0 AND r.code IS NULL
            """).fetchall()
        return [(r[0], r[1]) for r in rows]

    def save_realized(self, rows):
        """rows: list[dict(_REAL_COLS)]。"""
        if not rows:
            return 0
        with self.conn() as conn:
            for r in rows:
                conn.execute(
                    f"INSERT OR REPLACE INTO realized ({','.join(_REAL_COLS)}) "
                    f"VALUES ({','.join(['?'] * len(_REAL_COLS))})",
                    (r["scan_date"], r["code"], r.get("exit_date"), r.get("holding_days"),
                     r.get("realized_return"), 1 if r.get("hit_10pct") else 0,
                     r.get("exit_reason"), r.get("bench_return")))
        return len(rows)

    def get_realized_df(self) -> pd.DataFrame:
        with self.conn() as conn:
            return pd.read_sql_query("SELECT * FROM realized ORDER BY scan_date, code", conn)

    def save_run_meta(self, scan_date, model_train_rows, train_end_date, sh_ma20_gate, status):
        with self.conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO run_meta
                (scan_date, model_train_rows, train_end_date, sh_ma20_gate, status)
                VALUES (?, ?, ?, ?, ?)
            """, (scan_date, int(model_train_rows), train_end_date,
                  1 if sh_ma20_gate else 0, status))

    def get_latest_run_meta(self):
        with self.conn() as conn:
            conn.row_factory = None
            row = conn.execute(
                "SELECT scan_date, model_train_rows, train_end_date, sh_ma20_gate, status "
                "FROM run_meta ORDER BY scan_date DESC LIMIT 1").fetchone()
        if not row:
            return None
        return {"scan_date": row[0], "model_train_rows": row[1], "train_end_date": row[2],
                "sh_ma20_gate": row[3], "status": row[4]}
