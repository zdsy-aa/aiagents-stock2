"""
龙虎榜数据库模块（longhubang_db.py）回路特征测试

覆盖：save_longhubang_data / get_longhubang_data / get_top_stocks /
save_analysis_report / get_analysis_reports / get_analysis_report /
delete_analysis_report
"""
import os
import tempfile

import pandas as pd
import pytest

from longhubang_db import LonghubangDatabase


@pytest.fixture
def db():
    tmpdir = tempfile.mkdtemp()
    return LonghubangDatabase(db_path=os.path.join(tmpdir, "t.db"))


def test_save_and_get_longhubang_data(db):
    data_list = [
        {
            "日期": "2026-06-12",
            "股票代码": "600519",
            "股票名称": "贵州茅台",
            "游资名称": "知名游资席位",
            "营业部": "某营业部",
            "榜单类型": "涨幅偏离值达7%",
            "买入金额": 12345678.0,
            "卖出金额": 2345678.0,
            "净流入金额": 10000000.0,
            "概念": "白酒,消费",
        }
    ]

    saved = db.save_longhubang_data(data_list)
    assert saved == 1

    df = db.get_longhubang_data()
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["stock_code"] == "600519"
    assert row["stock_name"] == "贵州茅台"
    assert row["youzi_name"] == "知名游资席位"
    assert row["list_type"] == "涨幅偏离值达7%"
    assert row["net_inflow"] == 10000000.0
    assert row["concepts"] == "白酒,消费"

    # 按股票代码过滤
    df_code = db.get_longhubang_data(stock_code="600519")
    assert len(df_code) == 1

    # 按日期范围过滤（命中）
    df_range = db.get_longhubang_data(start_date="2026-06-01", end_date="2026-06-30")
    assert len(df_range) == 1

    # 按日期范围过滤（不命中）
    df_none = db.get_longhubang_data(start_date="2026-07-01")
    assert len(df_none) == 0


def test_save_longhubang_data_alt_keys(db):
    """支持拼音字段别名（rq/gpdm/gpmc/yzmc/yyb/sblx/mrje/mcje/jlrje/gl）"""
    data_list = [
        {
            "rq": "2026-06-12",
            "gpdm": "000001",
            "gpmc": "平安银行",
            "yzmc": "游资甲",
            "yyb": "营业部甲",
            "sblx": "卖出偏离值达7%",
            "mrje": 1000000.0,
            "mcje": 2000000.0,
            "jlrje": -1000000.0,
            "gl": "金融",
        }
    ]

    saved = db.save_longhubang_data(data_list)
    assert saved == 1

    df = db.get_longhubang_data(stock_code="000001")
    assert len(df) == 1
    assert df.iloc[0]["stock_name"] == "平安银行"
    assert df.iloc[0]["net_inflow"] == -1000000.0


def test_save_longhubang_data_empty(db):
    assert db.save_longhubang_data([]) == 0


def test_get_top_stocks(db):
    data_list = [
        {
            "日期": "2026-06-12",
            "股票代码": "600519",
            "股票名称": "贵州茅台",
            "游资名称": "游资A",
            "营业部": "营业部A",
            "榜单类型": "涨幅偏离值达7%",
            "买入金额": 5000000.0,
            "卖出金额": 1000000.0,
            "净流入金额": 4000000.0,
            "概念": "白酒",
        },
        {
            "日期": "2026-06-12",
            "股票代码": "600519",
            "股票名称": "贵州茅台",
            "游资名称": "游资B",
            "营业部": "营业部B",
            "榜单类型": "涨幅偏离值达7%",
            "买入金额": 3000000.0,
            "卖出金额": 500000.0,
            "净流入金额": 2500000.0,
            "概念": "白酒",
        },
    ]
    db.save_longhubang_data(data_list)

    top = db.get_top_stocks()
    assert isinstance(top, pd.DataFrame)
    assert len(top) == 1
    assert top.iloc[0]["stock_code"] == "600519"
    assert top.iloc[0]["youzi_count"] == 2
    assert top.iloc[0]["total_net_inflow"] == pytest.approx(6500000.0)

    # 无数据情况下也应正常返回空 DataFrame
    db2 = LonghubangDatabase(db_path=os.path.join(tempfile.mkdtemp(), "t.db"))
    top_empty = db2.get_top_stocks()
    assert isinstance(top_empty, pd.DataFrame)
    assert len(top_empty) == 0


def test_analysis_report_crud(db):
    report_id = db.save_analysis_report(
        data_date_range="2026-06-01~2026-06-12",
        analysis_content={"summary": "测试分析内容", "score": 88},
        recommended_stocks=[{"code": "600519", "name": "贵州茅台"}],
        summary="测试摘要",
    )
    assert isinstance(report_id, int)
    assert report_id > 0

    # get_analysis_reports 应包含该 id
    reports = db.get_analysis_reports(10)
    assert isinstance(reports, pd.DataFrame)
    assert report_id in reports["id"].tolist()

    # get_analysis_report 详情
    report = db.get_analysis_report(report_id)
    assert report is not None
    assert report["id"] == report_id
    assert report["data_date_range"] == "2026-06-01~2026-06-12"
    assert report["summary"] == "测试摘要"
    assert report["recommended_stocks"] == [{"code": "600519", "name": "贵州茅台"}]
    assert report["analysis_content_parsed"] == {"summary": "测试分析内容", "score": 88}

    # 删除
    deleted = db.delete_analysis_report(report_id)
    assert deleted is True

    # 删除后应不可见
    assert db.get_analysis_report(report_id) is None
    reports_after = db.get_analysis_reports(10)
    assert report_id not in reports_after["id"].tolist()

    # 删除不存在的报告
    assert db.delete_analysis_report(report_id) is False


def test_save_analysis_report_string_content(db):
    """analysis_content 传字符串而非 dict 时也应正常存取"""
    report_id = db.save_analysis_report(
        data_date_range="2026-06-13",
        analysis_content="纯文本分析内容",
        recommended_stocks=[],
        summary="摘要文本",
    )
    report = db.get_analysis_report(report_id)
    assert report["analysis_content"] == "纯文本分析内容"
    assert report["recommended_stocks"] == []
    # 非 JSON 字符串解析应被置为 None 而不是抛异常
    assert report["analysis_content_parsed"] is None


def run_all():
    tmpdir = tempfile.mkdtemp()
    inst = LonghubangDatabase(db_path=os.path.join(tmpdir, "t.db"))
    test_save_and_get_longhubang_data(inst)

    tmpdir2 = tempfile.mkdtemp()
    inst2 = LonghubangDatabase(db_path=os.path.join(tmpdir2, "t.db"))
    test_save_longhubang_data_alt_keys(inst2)

    tmpdir3 = tempfile.mkdtemp()
    inst3 = LonghubangDatabase(db_path=os.path.join(tmpdir3, "t.db"))
    test_save_longhubang_data_empty(inst3)

    tmpdir4 = tempfile.mkdtemp()
    inst4 = LonghubangDatabase(db_path=os.path.join(tmpdir4, "t.db"))
    test_get_top_stocks(inst4)

    tmpdir5 = tempfile.mkdtemp()
    inst5 = LonghubangDatabase(db_path=os.path.join(tmpdir5, "t.db"))
    test_analysis_report_crud(inst5)

    tmpdir6 = tempfile.mkdtemp()
    inst6 = LonghubangDatabase(db_path=os.path.join(tmpdir6, "t.db"))
    test_save_analysis_report_string_content(inst6)


if __name__ == "__main__":
    run_all()
    print("ALL longhubang_db OK")
