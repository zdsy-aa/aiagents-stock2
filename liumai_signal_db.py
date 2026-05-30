# liumai_signal_db.py
"""六脉神剑选股信号落库(沿用 BaseDatabase.conn() 风格)。"""
import logging
import pandas as pd
from base_db import BaseDatabase

_COLS = ["code", "name", "board", "signal_date", "bull_count", "score", "state",
         "macd", "kdj", "rsi", "lwr", "bbi", "mtm", "scan_date"]


class LiumaiSignalDB(BaseDatabase):
    def __init__(self, db_path="liumai_signals.db"):
        self.logger = logging.getLogger(__name__)
        super().__init__(db_path)

    def init_tables(self):
        with self.conn() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS liumai_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL, name TEXT, board TEXT,
                signal_date TEXT NOT NULL,
                bull_count INTEGER, score INTEGER, state TEXT,
                macd INTEGER, kdj INTEGER, rsi INTEGER, lwr INTEGER,
                bbi INTEGER, mtm INTEGER,
                scan_date TEXT NOT NULL,
                UNIQUE(code, scan_date)
            )""")

    def upsert_signals(self, rows):
        if not rows:
            return 0
        with self.conn() as conn:
            for r in rows:
                vals = [r.get(c) for c in _COLS]
                conn.execute(f"""
                    INSERT INTO liumai_signals ({','.join(_COLS)})
                    VALUES ({','.join(['?'] * len(_COLS))})
                    ON CONFLICT(code, scan_date) DO UPDATE SET
                        name=excluded.name, board=excluded.board,
                        signal_date=excluded.signal_date, bull_count=excluded.bull_count,
                        score=excluded.score, state=excluded.state,
                        macd=excluded.macd, kdj=excluded.kdj, rsi=excluded.rsi,
                        lwr=excluded.lwr, bbi=excluded.bbi, mtm=excluded.mtm
                """, vals)
        return len(rows)

    def get_latest_signals(self) -> pd.DataFrame:
        with self.conn() as conn:
            row = conn.execute("SELECT MAX(scan_date) FROM liumai_signals").fetchone()
            latest = row[0] if row else None
            if not latest:
                return pd.DataFrame(columns=_COLS)
            return pd.read_sql_query(
                "SELECT * FROM liumai_signals WHERE scan_date=? "
                "ORDER BY bull_count DESC, score DESC, code", conn, params=(latest,))

    def list_scan_dates(self) -> list:
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT scan_date FROM liumai_signals ORDER BY scan_date DESC"
            ).fetchall()
        return [r[0] for r in rows]

    def get_signals_by_scan_date(self, scan_date: str) -> pd.DataFrame:
        with self.conn() as conn:
            return pd.read_sql_query(
                "SELECT * FROM liumai_signals WHERE scan_date=? "
                "ORDER BY bull_count DESC, score DESC, code", conn, params=(scan_date,))

    def clear_scan(self, scan_date: str):
        with self.conn() as conn:
            conn.execute("DELETE FROM liumai_signals WHERE scan_date=?", (scan_date,))
