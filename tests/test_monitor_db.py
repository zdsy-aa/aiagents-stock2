"""monitor_db.py 回路特征测试（characterization test）。

覆盖 StockMonitorDatabase 的核心增删查改链路：
add_monitored_stock -> get_monitored_stocks -> update_stock_price ->
update_last_checked -> add_notification -> get_pending_notifications ->
mark_notification_sent -> has_recent_notification。
"""
import os
import tempfile

from monitor_db import StockMonitorDatabase


def _make_db():
    tmp_dir = tempfile.mkdtemp()
    return StockMonitorDatabase(db_path=os.path.join(tmp_dir, "t.db"))


def test_add_and_get_monitored_stock():
    db = _make_db()

    stock_id = db.add_monitored_stock(
        symbol="600519",
        name="贵州茅台",
        rating="★★★★★",
        entry_range={"min": 1500.0, "max": 1600.0},
        take_profit=1800.0,
        stop_loss=1400.0,
    )

    assert isinstance(stock_id, int)
    assert stock_id > 0

    stocks = db.get_monitored_stocks()
    assert len(stocks) == 1

    stock = stocks[0]
    assert stock["id"] == stock_id
    assert stock["symbol"] == "600519"
    assert stock["name"] == "贵州茅台"
    assert stock["rating"] == "★★★★★"
    assert stock["entry_range"] == {"min": 1500.0, "max": 1600.0}
    assert stock["take_profit"] == 1800.0
    assert stock["stop_loss"] == 1400.0
    assert stock["current_price"] is None
    assert stock["check_interval"] == 30
    assert stock["notification_enabled"] is True
    assert stock["trading_hours_only"] is True
    assert stock["quant_enabled"] is False
    assert stock["quant_config"] is None


def test_update_stock_price_round_trip():
    db = _make_db()

    stock_id = db.add_monitored_stock(
        symbol="000001",
        name="平安银行",
        rating="★★★",
        entry_range={"min": 10.0, "max": 12.0},
        take_profit=14.0,
        stop_loss=9.0,
    )

    db.update_stock_price(stock_id, 11.23)

    stocks = db.get_monitored_stocks()
    stock = next(s for s in stocks if s["id"] == stock_id)

    assert stock["current_price"] == 11.23
    assert stock["last_checked"] is not None


def test_update_last_checked_runs_without_error():
    db = _make_db()

    stock_id = db.add_monitored_stock(
        symbol="000002",
        name="万科A",
        rating="★★",
        entry_range={"min": 5.0, "max": 6.0},
        take_profit=7.0,
        stop_loss=4.0,
    )

    # 更新前应为空
    stocks = db.get_monitored_stocks()
    stock = next(s for s in stocks if s["id"] == stock_id)
    assert stock["last_checked"] is None

    db.update_last_checked(stock_id)

    stocks = db.get_monitored_stocks()
    stock = next(s for s in stocks if s["id"] == stock_id)
    assert stock["last_checked"] is not None


def test_notification_lifecycle_and_has_recent_notification():
    db = _make_db()

    stock_id = db.add_monitored_stock(
        symbol="600000",
        name="浦发银行",
        rating="★★★★",
        entry_range={"min": 8.0, "max": 9.0},
        take_profit=10.0,
        stop_loss=7.0,
    )

    # 添加前：has_recent_notification 应为 False
    assert db.has_recent_notification(stock_id, "entry") is False

    db.add_notification(stock_id, "entry", "价格进入买入区间")

    pending = db.get_pending_notifications()
    assert len(pending) == 1

    notif = pending[0]
    assert notif["stock_id"] == stock_id
    assert notif["symbol"] == "600000"
    assert notif["name"] == "浦发银行"
    assert notif["type"] == "entry"
    assert notif["message"] == "价格进入买入区间"

    notification_id = notif["id"]
    assert isinstance(notification_id, int)

    # 刚添加的通知应能被 has_recent_notification 识别为 True
    assert db.has_recent_notification(stock_id, "entry") is True
    assert isinstance(db.has_recent_notification(stock_id, "entry"), bool)

    db.mark_notification_sent(notification_id)

    pending_after = db.get_pending_notifications()
    assert all(n["id"] != notification_id for n in pending_after)
    assert len(pending_after) == 0


def main():
    test_add_and_get_monitored_stock()
    test_update_stock_price_round_trip()
    test_update_last_checked_runs_without_error()
    test_notification_lifecycle_and_has_recent_notification()


if __name__ == "__main__":
    main()
    print("ALL monitor_db OK")
