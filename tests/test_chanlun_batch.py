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
        assert isinstance(r["buy_reason"], str)
        assert r["sell_type"] in ("", "1卖", "2卖", "3卖")


def test_export_scan_csv(tmp_path):
    import pandas as pd
    from chanlun_batch import export_scan_csv
    db = ChanlunSignalDB(db_path=str(tmp_path / "s.db"))
    db.upsert_signals([
        {"code": "600000", "name": "浦发", "board": "沪主板", "signal_type": "1买",
         "signal_date": "2026-05-26", "buy_price": 10.0, "buy_reason": "x", "stop_loss": 9.8,
         "sell_type": "", "sell_date": "", "sell_reason": "", "level": "日线",
         "scan_date": "2026-05-27"}])
    out = tmp_path / "hist"
    path = export_scan_csv(db, "2026-05-27", out_dir=str(out))
    assert os.path.exists(path)
    assert path.endswith("2026-05-27.csv")
    df = pd.read_csv(path, dtype=str)
    assert len(df) == 1 and df.iloc[0]["code"] == "600000"
