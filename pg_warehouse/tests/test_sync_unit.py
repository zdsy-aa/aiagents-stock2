import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sync_daily import has_id_pk
from import_all import SIGNAL_DBS
from convert import TABLE_COMMENTS

def test_has_id_pk():
    assert has_id_pk([("id", "INTEGER"), ("code", "TEXT")]) is True
    assert has_id_pk([("scan_date", "TEXT"), ("code", "TEXT")]) is False
    assert has_id_pk([]) is False

def test_all_signal_tables_have_comment():
    missing = [pg for _, _, pg in SIGNAL_DBS if pg not in TABLE_COMMENTS]
    assert missing == []

def test_qizhang_tables_have_no_id():
    # qizhang 三表应走 TRUNCATE+COPY 全量覆盖路径
    qz = [pg for _, _, pg in SIGNAL_DBS if pg.startswith("qizhang_")]
    assert len(qz) == 3
