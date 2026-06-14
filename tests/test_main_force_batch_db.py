#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main_force_batch_db.MainForceBatchDatabase 回路特征测试

覆盖 save_batch_analysis / get_all_history / get_record_by_id /
delete_record / get_statistics 的当前行为，作为防止未来重构悄悄
破坏这些方法签名/返回结构的回归安全网。
"""
import os
import tempfile

from main_force_batch_db import MainForceBatchDatabase


def test_save_and_query_round_trip():
    db_path = os.path.join(tempfile.mkdtemp(), "main_force_batch.db")
    db = MainForceBatchDatabase(db_path=db_path)

    results = [
        {"code": "600000", "name": "浦发银行", "score": 88.5, "signal": "buy"},
        {"code": "000001", "name": "平安银行", "score": 76.0, "signal": "hold"},
    ]

    record_id = db.save_batch_analysis(
        batch_count=2,
        analysis_mode="parallel",
        success_count=2,
        failed_count=0,
        total_time=12.34,
        results=results,
    )

    assert isinstance(record_id, int)
    assert record_id > 0

    # get_all_history 应包含刚保存的记录
    history = db.get_all_history(limit=10)
    assert isinstance(history, list)
    ids = [item["id"] for item in history]
    assert record_id in ids

    saved = next(item for item in history if item["id"] == record_id)
    assert saved["batch_count"] == 2
    assert saved["analysis_mode"] == "parallel"
    assert saved["success_count"] == 2
    assert saved["failed_count"] == 0
    assert saved["total_time"] == 12.34
    assert saved["results"] == results
    assert "created_at" in saved
    assert "analysis_date" in saved

    # get_record_by_id 单条记录回路
    record = db.get_record_by_id(record_id)
    assert record is not None
    assert record["id"] == record_id
    assert record["analysis_mode"] == "parallel"
    assert record["results"] == results

    # get_statistics 返回 dict 且数值符合刚写入的一条记录
    stats = db.get_statistics()
    assert isinstance(stats, dict)
    assert stats["total_records"] == 1
    assert stats["total_stocks_analyzed"] == 2
    assert stats["total_success"] == 2
    assert stats["total_failed"] == 0
    assert stats["average_time"] == 12.34
    assert stats["success_rate"] == 100.0

    # delete_record 之后记录消失
    deleted = db.delete_record(record_id)
    assert deleted is True

    assert db.get_record_by_id(record_id) is None
    history_after = db.get_all_history(limit=10)
    assert all(item["id"] != record_id for item in history_after)

    # 再次删除不存在的记录应返回 False
    assert db.delete_record(record_id) is False


if __name__ == "__main__":
    test_save_and_query_round_trip()
    print("ALL main_force_batch_db OK")
