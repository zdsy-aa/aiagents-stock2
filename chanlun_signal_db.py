# chanlun_signal_db.py
"""缠论选股信号落库（沿用 BaseDatabase.conn() 风格）。"""
import logging
import pandas as pd
from base_db import BaseDatabase

_COLS = ["code", "name", "board", "signal_type", "signal_date",
         "buy_price", "stop_loss", "exit_rule", "level", "scan_date"]


class ChanlunSignalDB(BaseDatabase):
    def __init__(self, db_path="chanlun_signals.db"):
        self.logger = logging.getLogger(__name__)
        super().__init__(db_path)

    def init_tables(self):
        with self.conn() as conn:
            conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                name TEXT,
                board TEXT,
                signal_type TEXT NOT NULL,
                signal_date TEXT NOT NULL,
                buy_price REAL,
                stop_loss REAL,
                exit_rule TEXT,
                level TEXT,
                scan_date TEXT NOT NULL,
                UNIQUE(code, signal_type, signal_date)
            )""")

    def upsert_signals(self, rows):
        if not rows:
            return 0
        with self.conn() as conn:
            for r in rows:
                vals = [r.get(c) for c in _COLS]
                conn.execute(f"""
                    INSERT INTO signals ({','.join(_COLS)})
                    VALUES ({','.join(['?'] * len(_COLS))})
                    ON CONFLICT(code, signal_type, signal_date) DO UPDATE SET
                        name=excluded.name, board=excluded.board,
                        buy_price=excluded.buy_price, stop_loss=excluded.stop_loss,
                        exit_rule=excluded.exit_rule, level=excluded.level,
                        scan_date=excluded.scan_date
                """, vals)
        return len(rows)

    def get_latest_signals(self) -> pd.DataFrame:
        """返回最新批次(scan_date 最大)的全部信号。"""
        with self.conn() as conn:
            row = conn.execute("SELECT MAX(scan_date) FROM signals").fetchone()
            latest = row[0] if row else None
            if not latest:
                return pd.DataFrame(columns=_COLS)
            return pd.read_sql_query(
                "SELECT * FROM signals WHERE scan_date=? ORDER BY signal_date DESC, code",
                conn, params=(latest,))

    def clear_scan(self, scan_date: str):
        with self.conn() as conn:
            conn.execute("DELETE FROM signals WHERE scan_date=?", (scan_date,))
