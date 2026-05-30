# combo_signal_db.py
"""缠论×六脉组合信号落库(沿用 BaseDatabase.conn() 风格)。"""
import logging
import pandas as pd
from base_db import BaseDatabase

_COLS = ["code", "name", "board", "chanlun_type", "chanlun_date", "buy_reason",
         "liumai_date", "liumai_bull_count", "liumai_score", "scan_date"]


class ComboSignalDB(BaseDatabase):
    def __init__(self, db_path="combo_signals.db"):
        self.logger = logging.getLogger(__name__)
        super().__init__(db_path)

    def init_tables(self):
        with self.conn() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS combo_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL, name TEXT, board TEXT,
                chanlun_type TEXT, chanlun_date TEXT, buy_reason TEXT,
                liumai_date TEXT, liumai_bull_count INTEGER, liumai_score INTEGER,
                scan_date TEXT NOT NULL,
                UNIQUE(code, chanlun_date, scan_date)
            )""")

    def upsert_signals(self, rows):
        if not rows:
            return 0
        with self.conn() as conn:
            for r in rows:
                vals = [r.get(c) for c in _COLS]
                conn.execute(f"""
                    INSERT INTO combo_signals ({','.join(_COLS)})
                    VALUES ({','.join(['?'] * len(_COLS))})
                    ON CONFLICT(code, chanlun_date, scan_date) DO UPDATE SET
                        name=excluded.name, board=excluded.board,
                        chanlun_type=excluded.chanlun_type, buy_reason=excluded.buy_reason,
                        liumai_date=excluded.liumai_date,
                        liumai_bull_count=excluded.liumai_bull_count,
                        liumai_score=excluded.liumai_score
                """, vals)
        return len(rows)

    def get_latest_signals(self) -> pd.DataFrame:
        with self.conn() as conn:
            row = conn.execute("SELECT MAX(scan_date) FROM combo_signals").fetchone()
            latest = row[0] if row else None
            if not latest:
                return pd.DataFrame(columns=_COLS)
            return pd.read_sql_query(
                "SELECT * FROM combo_signals WHERE scan_date=? "
                "ORDER BY chanlun_date DESC, code", conn, params=(latest,))

    def list_scan_dates(self) -> list:
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT scan_date FROM combo_signals ORDER BY scan_date DESC"
            ).fetchall()
        return [r[0] for r in rows]

    def get_signals_by_scan_date(self, scan_date: str) -> pd.DataFrame:
        with self.conn() as conn:
            return pd.read_sql_query(
                "SELECT * FROM combo_signals WHERE scan_date=? "
                "ORDER BY chanlun_date DESC, code", conn, params=(scan_date,))

    def clear_scan(self, scan_date: str):
        with self.conn() as conn:
            conn.execute("DELETE FROM combo_signals WHERE scan_date=?", (scan_date,))
