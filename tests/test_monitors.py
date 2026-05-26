"""迁移到 BaseDatabase 的两个监控类：增删查回路。"""
from low_price_bull_monitor import LowPriceBullMonitor
from profit_growth_monitor import ProfitGrowthMonitor


def test_low_price_bull_add_dedup_remove(tmp_path):
    m = LowPriceBullMonitor(str(tmp_path / "lpb.db"))
    ok, _ = m.add_stock("600519", "茅台", 1800.0)
    assert ok
    assert any(s['stock_code'] == "600519" for s in m.get_monitored_stocks())

    ok_dup, _ = m.add_stock("600519", "茅台", 1800.0)  # 重复应失败
    assert ok_dup is False

    ok_rm, _ = m.remove_stock("600519")
    assert ok_rm
    assert not any(s['stock_code'] == "600519" for s in m.get_monitored_stocks())


def test_profit_growth_add_and_list(tmp_path):
    m = ProfitGrowthMonitor(str(tmp_path / "pg.db"))
    ok, _ = m.add_stock("000001", "平安银行", 10.0)
    assert ok
    assert any(s['stock_code'] == "000001" for s in m.get_monitoring_stocks())
