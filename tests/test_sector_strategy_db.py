"""sector_strategy_db.SectorStrategyDatabase 回路特征测试

覆盖：save_raw_data / get_latest_raw_data / save_analysis_report /
get_analysis_reports / get_analysis_report / delete_analysis_report
"""
import os
import tempfile

from sector_strategy_db import SectorStrategyDatabase


def _make_db():
    return SectorStrategyDatabase(db_path=os.path.join(tempfile.mkdtemp(), "t.db"))


def test_save_and_get_raw_data():
    db = _make_db()

    item = {
        "名称": "新能源汽车",
        "最新价": 12.34,
        "涨跌幅": 1.23,
        "成交量": 100000,
        "成交额": 99999999,
        "总市值": 123456789000,
        "市盈率": 25.6,
        "市净率": 3.2,
    }

    n = db.save_raw_data("quote", [item])
    assert n == 1

    df = db.get_latest_raw_data("quote")
    assert not df.empty
    assert len(df) == 1
    row = df.iloc[0]
    assert row["data_type"] == "quote"
    assert row["sector_name"] == "新能源汽车"
    assert row["price"] == 12.34
    assert row["change_pct"] == 1.23


def test_save_raw_data_with_english_keys():
    db = _make_db()

    item = {
        "sector": "半导体",
        "price": 88.8,
        "change_pct": -2.5,
        "volume": 5000,
        "turnover": 444000,
        "market_cap": 5000000000,
        "pe_ratio": 30.1,
        "pb_ratio": 4.5,
    }

    n = db.save_raw_data("fund_flow", [item])
    assert n == 1

    df = db.get_latest_raw_data("fund_flow")
    assert len(df) == 1
    assert df.iloc[0]["sector_name"] == "半导体"
    assert df.iloc[0]["price"] == 88.8


def test_save_raw_data_empty_list_returns_zero():
    db = _make_db()
    assert db.save_raw_data("quote", []) == 0


def test_get_latest_raw_data_empty_when_no_match():
    db = _make_db()
    db.save_raw_data("quote", [{"名称": "A", "最新价": 1}])
    df = db.get_latest_raw_data("overview")
    assert df.empty


def test_analysis_report_roundtrip():
    db = _make_db()

    report_id = db.save_analysis_report(
        data_date_range="2026-06-01~2026-06-13",
        analysis_content={"summary": "市场偏强", "score": 80},
        recommended_sectors=["半导体", "新能源汽车"],
        summary="近期成交活跃，关注半导体板块",
        confidence_score=0.75,
        risk_level="中",
        investment_horizon="短期",
        market_outlook="震荡向上",
    )
    assert isinstance(report_id, int)
    assert report_id > 0

    reports = db.get_analysis_reports(10)
    assert not reports.empty
    assert report_id in reports["id"].values

    detail = db.get_analysis_report(report_id)
    assert detail is not None
    assert detail["id"] == report_id
    assert detail["data_date_range"] == "2026-06-01~2026-06-13"
    assert detail["summary"] == "近期成交活跃，关注半导体板块"
    assert detail["confidence_score"] == 0.75
    assert detail["risk_level"] == "中"
    assert detail["investment_horizon"] == "短期"
    assert detail["market_outlook"] == "震荡向上"
    # JSON 字段已被解析
    assert detail["analysis_content_parsed"] == {"summary": "市场偏强", "score": 80}
    assert detail["recommended_sectors"] == ["半导体", "新能源汽车"]

    deleted = db.delete_analysis_report(report_id)
    assert deleted == 1

    assert db.get_analysis_report(report_id) is None


def test_save_analysis_report_with_string_content():
    db = _make_db()

    report_id = db.save_analysis_report(
        data_date_range="2026-06-13",
        analysis_content="纯文本分析内容",
        recommended_sectors=[],
        summary="无推荐",
    )
    detail = db.get_analysis_report(report_id)
    assert detail["analysis_content"] == "纯文本分析内容"
    # 非 JSON 字符串解析失败应为 None
    assert detail["analysis_content_parsed"] is None
    assert detail["recommended_sectors"] == []
    assert detail["confidence_score"] is None
    assert detail["risk_level"] is None


def run_all():
    test_save_and_get_raw_data()
    test_save_raw_data_with_english_keys()
    test_save_raw_data_empty_list_returns_zero()
    test_get_latest_raw_data_empty_when_no_match()
    test_analysis_report_roundtrip()
    test_save_analysis_report_with_string_content()


if __name__ == "__main__":
    run_all()
    print("ALL sector_strategy_db OK")
