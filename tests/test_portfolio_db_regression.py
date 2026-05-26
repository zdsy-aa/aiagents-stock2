"""回归测试：base_db 重构后 PortfolioDB 丢失的查询方法。

背景：portfolio_ui.py 调用 db.get_latest_analysis_history 时抛
AttributeError，根因是 base_db 重构重写 portfolio_db.py 时丢了若干仍被
UI / manager / scheduler 调用的方法。本测试覆盖这些方法，防止再次丢失。
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from portfolio_db import PortfolioDB


def _fresh_db():
    """建一个带目录的临时 db（base_db 只对裸文件名拼 DATA_DIR，带目录的原样使用）。"""
    fd, path = tempfile.mkstemp(suffix=".db", dir=tempfile.gettempdir())
    os.close(fd)
    os.remove(path)  # 让 PortfolioDB 自己建表
    return PortfolioDB(path)


def test_portfolio_db_restored_methods():
    db = _fresh_db()
    sid = db.add_stock("600519", "贵州茅台", 1650.5, 100, "test")
    db.save_analysis(sid, "买入", 8.5, 1700.0, 1850.0, 1600.0, 1650.0, 1900.0, 1500.0, "ok")
    db.save_analysis(sid, "卖出", 7.0, 1720.0, 1600.0, 1500.0, 1550.0, 1800.0, 1450.0, "转弱")

    # 1) UI 直接调用（本次报错点）
    hist = db.get_latest_analysis_history(sid, limit=5)
    assert isinstance(hist, list) and len(hist) == 2
    assert hist[0]["analysis_time"] >= hist[1]["analysis_time"]  # 按时间倒序

    # 2) manager 包装调用
    latest = db.get_latest_analysis(sid)
    assert isinstance(latest, dict) and latest["rating"] == "卖出"

    matches = db.search_stocks("600")
    assert isinstance(matches, list) and any(s["code"] == "600519" for s in matches)

    changes = db.get_rating_changes(sid, days=30)
    assert isinstance(changes, list) and len(changes) == 1
    assert changes[0][1] == "买入" and changes[0][2] == "卖出"  # (时间, 旧, 新)

    all_latest = db.get_all_latest_analysis()
    assert isinstance(all_latest, list) and len(all_latest) == 1
    assert all_latest[0]["code"] == "600519" and all_latest[0]["rating"] == "卖出"

    # 3) scheduler 直接调用
    assert db.get_stock_count() == 1

    print("PASS: PortfolioDB 全部丢失方法已恢复且行为正确")


if __name__ == "__main__":
    test_portfolio_db_restored_methods()
