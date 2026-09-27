# tests/test_failure_db.py
"""失败策略库测试(Task3.4)。

全部用例经 tmp_path + monkeypatch 隔离 DB_PATH,绝不写真实 data/backtest_failures.db
(autouse fixture 兜底,即使单个用例忘了 patch 也打不到真实库)。
"""
import sqlite3

import pandas as pd
import pytest

import backtest.failure_db as fb


@pytest.fixture(autouse=True)
def _isolate_real_db(tmp_path, monkeypatch):
    """兜底隔离:默认把 DB_PATH 指向临时目录(简报硬要求:测试绝不写真实库)。"""
    monkeypatch.setattr(fb, "DB_PATH", str(tmp_path / "failures.db"))


def _df():
    return pd.DataFrame({"股票代码": ["1", "2"], "信号日期": ["20240101", "20240102"],
                         "是否盈利": [0, 1], "区间涨跌幅": [-0.1, 0.1], "年": ["2024", "2024"]})


def test_record_and_stats(tmp_path, monkeypatch):
    monkeypatch.setattr(fb, "DB_PATH", str(tmp_path / "t.db"))
    fb.init_db()
    df = pd.DataFrame({"股票代码": ["1", "2"], "信号日期": ["20240101", "20240102"],
                       "是否盈利": [0, 1], "区间涨跌幅": [-0.1, 0.1], "年": ["2024", "2024"]})
    mask = pd.Series([True, True])
    fb.record_failures("TQ01", df, mask, "市场环境")
    assert fb.failure_stats("TQ01")["市场环境"] == 1    # 只记未盈利行
    fb.record_failures("TQ01", df, mask, "市场环境")     # 重跑不重复
    assert fb.failure_stats("TQ01")["市场环境"] == 1


def test_mask_filters_rows():
    """mask 未命中的行不落库;mask 命中的盈利行同样不落库。"""
    fb.init_db()
    df = _df()                                        # 行0 未盈利,行1 盈利
    n = fb.record_failures("TQ01", df, pd.Series([True, False]), "参数")
    assert n == 1
    n = fb.record_failures("TQ01", df, pd.Series([False, True]), "参数")
    assert n == 0                                     # 命中的行1 是盈利行
    assert fb.failure_stats("TQ01")["参数"] == 1


def test_dedupe_key_is_combo_code_date():
    """去重键 = combo+code+date:换组合或换日期即新记录,同键重复不增。"""
    fb.init_db()
    df = _df()
    mask = pd.Series([True, False])
    fb.record_failures("TQ01", df, mask, "指标")
    fb.record_failures("TQ02", df, mask, "指标")       # 组合不同 -> 各记一条
    assert fb.failure_stats("TQ01")["指标"] == 1
    assert fb.failure_stats("TQ02")["指标"] == 1
    assert fb.failure_stats()["指标"] == 2             # 不传组合 = 全库聚合
    df2 = df.copy()
    df2["信号日期"] = ["20240103", "20240104"]          # 同组合同代码换日期 -> 新记录
    fb.record_failures("TQ01", df2, mask, "指标")
    assert fb.failure_stats("TQ01")["指标"] == 2


def test_stats_none_aggregates_and_missing_category_is_zero():
    fb.init_db()
    df = _df()
    fb.record_failures("TQ01", df, pd.Series([True, False]), "执行")
    fb.record_failures("TQ02", df, pd.Series([True, False]), "数据")
    stats = fb.failure_stats()
    assert stats["执行"] == 1 and stats["数据"] == 1
    assert stats["组合"] == 0                           # 未出现的分类按 0 计,不 KeyError
    assert fb.failure_stats("不存在")["执行"] == 0


def test_classify_failure_enum():
    """库不做自动分类:分类由调用方传入,只做六分类枚举校验。"""
    for cat in fb.CATEGORIES:
        assert fb.classify_failure("TQ01", cat) == cat
    assert set(fb.CATEGORIES) == {"指标", "参数", "市场环境", "数据", "组合", "执行"}
    with pytest.raises(ValueError):
        fb.classify_failure("TQ01", "心情不好")
    fb.init_db()
    with pytest.raises(ValueError):
        fb.record_failures("TQ01", _df(), pd.Series([True, False]), "心情不好")


def test_blank_code_or_date_rejected():
    """股票代码/信号日期为空的行拒绝落库(空串会污染 combo+code+date 去重键)。"""
    fb.init_db()
    df = _df()
    df.loc[0, "信号日期"] = None
    with pytest.raises(ValueError):
        fb.record_failures("TQ01", df, pd.Series([True, True]), "执行")
    assert fb.failure_stats("TQ01")["执行"] == 0


def test_stored_fields():
    """落库字段齐全且口径正确:code/date/year/win/ret/reason/classified_at。"""
    fb.init_db()
    fb.record_failures("TQ01", _df(), pd.Series([True, True]), "市场环境")
    with sqlite3.connect(fb.DB_PATH) as conn:
        rows = conn.execute(
            "SELECT combo, code, date, year, win, ret, reason, classified_at FROM failures"
        ).fetchall()
    assert rows == [("TQ01", "1", "20240101", "2024", 0, -0.1, "市场环境", rows[0][7])]
    assert rows[0][7]                                     # classified_at 非空
