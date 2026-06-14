"""BaseDatabase：WAL、自动 commit/rollback、cleanup 白名单、连接工厂(含 row_factory)。"""
import sqlite3

import pytest
from base_db import BaseDatabase


class _DB(BaseDatabase):
    def init_tables(self):
        with self.conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)")


def test_wal_enabled(tmp_path):
    db = _DB(str(tmp_path / "x.db"))
    with db.conn() as c:
        assert c.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_autocommit_on_success(tmp_path):
    db = _DB(str(tmp_path / "x.db"))
    with db.conn() as c:
        c.execute("INSERT INTO t (v) VALUES (?)", ("a",))
    with db.conn() as c:  # 新连接应看到已提交数据
        assert c.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1


def test_rollback_on_exception(tmp_path):
    db = _DB(str(tmp_path / "x.db"))
    with pytest.raises(RuntimeError):
        with db.conn() as c:
            c.execute("INSERT INTO t (v) VALUES (?)", ("b",))
            raise RuntimeError("boom")
    with db.conn() as c:  # 异常应回滚，无残留
        assert c.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0


def test_connect_factory_sets_wal(tmp_path):
    db = _DB(str(tmp_path / "x.db"))
    c = db._connect()
    try:
        assert c.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert c.row_factory is None  # 默认不设行工厂(普通元组)
    finally:
        c.close()


def test_connect_factory_row_factory(tmp_path):
    db = _DB(str(tmp_path / "x.db"))
    c = db._connect(row_factory=sqlite3.Row)
    try:
        c.execute("INSERT INTO t (v) VALUES (?)", ("z",))
        row = c.execute("SELECT v FROM t").fetchone()
        assert row["v"] == "z"  # 支持按列名访问
    finally:
        c.close()


def test_conn_passes_row_factory(tmp_path):
    db = _DB(str(tmp_path / "x.db"))
    with db.conn(row_factory=sqlite3.Row) as c:
        c.execute("INSERT INTO t (v) VALUES (?)", ("q",))
    with db.conn(row_factory=sqlite3.Row) as c:
        row = c.execute("SELECT v FROM t").fetchone()
        assert dict(row) == {"v": "q"}


def test_cleanup_rejects_unknown_table(tmp_path):
    db = _DB(str(tmp_path / "x.db"))
    with pytest.raises(ValueError):
        db.cleanup_old_data("evil_table", time_column="created_at")


def test_cleanup_rejects_unknown_column(tmp_path):
    db = _DB(str(tmp_path / "x.db"))
    with pytest.raises(ValueError):
        db.cleanup_old_data("notifications", time_column="evil_col")
