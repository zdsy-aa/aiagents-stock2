# tests/test_chanlun_batch.py
import os, tempfile
import pytest
from chanlun_batch import scan_codes
from chanlun_signal_db import ChanlunSignalDB


@pytest.mark.skipif(not os.path.exists("/app/tdx-data/database/kline/000001.db"),
                    reason="需容器内本地K线库")
def test_scan_codes_writes_db_without_error():
    db = ChanlunSignalDB(db_path=os.path.join(tempfile.mkdtemp(), "s.db"))
    # 跑 3 只主板票；不强求一定有买点，只验证流程不报错、落库可读
    n = scan_codes(["000001", "600000", "600519"], db, scan_date="2026-05-27", days=7)
    assert isinstance(n, int) and n >= 0
    df = db.get_latest_signals()
    for _, r in df.iterrows():
        assert r["signal_type"] in ("1买", "2买", "3买")
        assert r["stop_loss"] <= r["buy_price"]
        assert isinstance(r["exit_rule"], str) and len(r["exit_rule"]) > 0
