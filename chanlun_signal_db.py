# chanlun_signal_db.py
"""缠论选股信号落库（沿用 BaseDatabase.conn() 风格）。"""
import logging
import pandas as pd
from base_db import BaseDatabase

_COLS = ["code", "name", "board", "signal_type", "signal_date",
         "buy_price", "buy_reason", "stop_loss",
         "sell_type", "sell_date", "sell_reason", "level", "scan_date"]

# 旧库（含 exit_rule、缺新列）就地补列，旧 exit_rule 列残留但不再写/读
_NEW_COLS = ("buy_reason", "sell_type", "sell_date", "sell_reason")


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
                buy_reason TEXT,
                stop_loss REAL,
                sell_type TEXT,
                sell_date TEXT,
                sell_reason TEXT,
                level TEXT,
                scan_date TEXT NOT NULL,
                UNIQUE(code, signal_type, signal_date, scan_date)
            )""")
            existing = {r[1] for r in conn.execute("PRAGMA table_info(signals)")}
            for col in _NEW_COLS:
                if col not in existing:
                    conn.execute(f"ALTER TABLE signals ADD COLUMN {col} TEXT")
            if not self._unique_has_scan_date(conn):
                self._migrate_unique_key(conn)

    @staticmethod
    def _unique_has_scan_date(conn) -> bool:
        for idx in conn.execute("PRAGMA index_list(signals)"):
            name, is_unique = idx[1], idx[2]
            if not is_unique:
                continue
            cols = {r[2] for r in conn.execute(f"PRAGMA index_info('{name}')")}
            if {"code", "signal_type", "signal_date", "scan_date"} <= cols:
                return True
        return False

    def _migrate_unique_key(self, conn):
        old_cols = [r[1] for r in conn.execute("PRAGMA table_info(signals)")]
        conn.execute("""CREATE TABLE signals_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL, name TEXT, board TEXT,
            signal_type TEXT NOT NULL, signal_date TEXT NOT NULL,
            buy_price REAL, buy_reason TEXT, stop_loss REAL,
            sell_type TEXT, sell_date TEXT, sell_reason TEXT,
            level TEXT, scan_date TEXT NOT NULL,
            UNIQUE(code, signal_type, signal_date, scan_date))""")
        new_cols = ["code", "name", "board", "signal_type", "signal_date",
                    "buy_price", "buy_reason", "stop_loss",
                    "sell_type", "sell_date", "sell_reason", "level", "scan_date"]
        common = ",".join(c for c in new_cols if c in old_cols)
        conn.execute(f"INSERT INTO signals_new ({common}) SELECT {common} FROM signals")
        conn.execute("DROP TABLE signals")
        conn.execute("ALTER TABLE signals_new RENAME TO signals")
        self.logger.info("[缠论库] 唯一约束已迁移为含 scan_date(历史批次将完整保留)")

    def upsert_signals(self, rows):
        if not rows:
            return 0
        with self.conn() as conn:
            for r in rows:
                vals = [r.get(c) for c in _COLS]
                conn.execute(f"""
                    INSERT INTO signals ({','.join(_COLS)})
                    VALUES ({','.join(['?'] * len(_COLS))})
                    ON CONFLICT(code, signal_type, signal_date, scan_date) DO UPDATE SET
                        name=excluded.name, board=excluded.board,
                        buy_price=excluded.buy_price, buy_reason=excluded.buy_reason,
                        stop_loss=excluded.stop_loss,
                        sell_type=excluded.sell_type, sell_date=excluded.sell_date,
                        sell_reason=excluded.sell_reason, level=excluded.level
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
