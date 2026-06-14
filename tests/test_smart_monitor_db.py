"""SmartMonitorDB 回路特征测试：monitor_tasks / ai_decisions 的增删改查。"""
import os
import tempfile

from smart_monitor_db import SmartMonitorDB


def _make_db():
    tmp_dir = tempfile.mkdtemp()
    return SmartMonitorDB(db_file=os.path.join(tmp_dir, "t.db"))


def test_monitor_task_crud_roundtrip():
    db = _make_db()

    task_data = {
        "task_name": "测试任务",
        "stock_code": "sh600000",
        "stock_name": "浦发银行",
        "enabled": 1,
        "check_interval": 300,
        "auto_trade": 0,
        "trading_hours_only": 1,
        "position_size_pct": 20,
        "stop_loss_pct": 5,
        "take_profit_pct": 10,
        "qmt_account_id": "ACC001",
        "notify_email": "a@b.com",
        "notify_webhook": None,
        "has_position": 0,
        "position_cost": 0,
        "position_quantity": 0,
        "position_date": None,
    }

    task_id = db.add_monitor_task(task_data)
    assert isinstance(task_id, int) and task_id > 0

    tasks = db.get_monitor_tasks(enabled_only=False)
    matches = [t for t in tasks if t["id"] == task_id]
    assert len(matches) == 1
    added = matches[0]
    assert added["stock_code"] == "sh600000"
    assert added["task_name"] == "测试任务"
    assert added["enabled"] == 1

    # 更新：按 stock_code 定位
    ok = db.update_monitor_task("sh600000", {"task_name": "更新后的任务", "enabled": 0})
    assert ok

    tasks = db.get_monitor_tasks(enabled_only=False)
    updated = next(t for t in tasks if t["id"] == task_id)
    assert updated["task_name"] == "更新后的任务"
    assert updated["enabled"] == 0

    # enabled_only=True 应过滤掉刚禁用的任务
    enabled_tasks = db.get_monitor_tasks(enabled_only=True)
    assert all(t["id"] != task_id for t in enabled_tasks)

    # 删除：按 task_id
    deleted = db.delete_monitor_task(task_id)
    assert deleted

    tasks_after = db.get_monitor_tasks(enabled_only=False)
    assert all(t["id"] != task_id for t in tasks_after)


def test_ai_decision_save_and_get():
    db = _make_db()

    decision_data = {
        "stock_code": "sz000001",
        "stock_name": "平安银行",
        "decision_time": "2026-06-14 10:00:00",
        "trading_session": "morning",
        "action": "buy",
        "confidence": 80,
        "reasoning": "缠论买点共振",
        "position_size_pct": 15,
        "stop_loss_pct": 5,
        "take_profit_pct": 10,
        "risk_level": "medium",
        "key_price_levels": {"support": 10.0, "resistance": 12.0},
        "market_data": {"price": 11.0},
        "account_info": {"cash": 100000},
    }

    decision_id = db.save_ai_decision(decision_data)
    assert isinstance(decision_id, int) and decision_id > 0

    decisions = db.get_ai_decisions(stock_code="sz000001")
    assert len(decisions) == 1
    d = decisions[0]
    assert d["id"] == decision_id
    assert d["stock_code"] == "sz000001"
    assert d["action"] == "buy"
    assert d["confidence"] == 80
    assert d["key_price_levels"] == {"support": 10.0, "resistance": 12.0}
    assert d["market_data"] == {"price": 11.0}
    assert d["account_info"] == {"cash": 100000}

    # 全量查询也应包含该记录
    all_decisions = db.get_ai_decisions()
    assert any(x["id"] == decision_id for x in all_decisions)


def _run_all():
    test_monitor_task_crud_roundtrip()
    test_ai_decision_save_and_get()


if __name__ == "__main__":
    _run_all()
    print("ALL smart_monitor_db OK")
