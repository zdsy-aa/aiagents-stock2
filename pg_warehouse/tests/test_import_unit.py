import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from import_all import build_create_table, build_comments, SIGNAL_DBS

def test_build_create_table():
    sql = build_create_table("chanlun_signals", [("id", "INTEGER"), ("code", "TEXT"), ("buy_price", "REAL")])
    assert sql.startswith("CREATE TABLE signals.chanlun_signals (")
    assert '"id" BIGINT PRIMARY KEY' in sql
    assert '"code" TEXT' in sql
    assert '"buy_price" DOUBLE PRECISION' in sql

def test_build_comments_has_table_and_columns():
    stmts = build_comments("chanlun_signals", [("id", "INTEGER"), ("code", "TEXT")])
    joined = "\n".join(stmts)
    assert "COMMENT ON TABLE signals.chanlun_signals" in joined
    assert "COMMENT ON COLUMN signals.chanlun_signals.code" in joined

def test_signal_dbs_nonempty():
    assert len(SIGNAL_DBS) >= 40
    # 所有 PG 表名都在 signals schema 下唯一
    names = [pg for _, _, pg in SIGNAL_DBS]
    assert len(names) == len(set(names))
