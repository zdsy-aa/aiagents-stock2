# -*- coding: utf-8 -*-
"""Phase4 Task4.4:AI 可验证性(extract_direction / comparison_table / trace_save)。

控制器裁决:
- database 相关测试一律用 tmp_path 临时库,绝不写真实库;
- comparison_table 测试用合成记录 + 合成面板(monkeypatch),不加载 15M 确认面板;
- 真实 comparison_table 一次在实现后手动跑(报告记录行数),不进测试。
"""
import sqlite3

import pandas as pd

import interfaces.ai_trace as at
from database import StockAnalysisDatabase


# ---------- extract_direction ----------

def test_direction_extraction():
    assert at.extract_direction("综合看多,建议买入") == "多"
    assert at.extract_direction("看空,回避") == "空"
    assert at.extract_direction("中性观望") == "中性"


def test_direction_extraction_keywords_and_dict():
    assert at.extract_direction("量价齐升,上涨趋势确立") == "多"
    assert at.extract_direction("破位下跌,建议卖出") == "空"
    assert at.extract_direction("暂不行动,重点观察") == "中性"
    assert at.extract_direction({"rating": "买入", "logic": "放量"}) == "多"
    assert at.extract_direction({"decision": "观望"}) == "中性"
    assert at.extract_direction(None) == "中性"
    assert at.extract_direction("") == "中性"


# ---------- comparison_table(合成记录 + 合成面板) ----------

def _records():
    return [
        {"symbol": "600519", "analysis_date": "2026-09-01 09:30:00",
         "final_decision": {"decision_text": "综合看多,建议买入"}},
        {"symbol": "1", "analysis_date": "2026-09-01 10:00:00",
         "final_decision": "看空,回避"},
    ]


def _panels():
    buy = pd.DataFrame({
        "股票代码": ["600519", "000001", "600519"],
        "信号日期": ["2026-09-01", "2026-09-01", "2026-09-02"],
        "是否盈利": [1, 0, 0],
    })
    confirm = pd.DataFrame({
        "股票代码": ["600519", "000001"],
        "信号日期": [20260904, 20260904],  # 2026-09-04
        "是否盈利": [1.0, 0.0],
    })
    return buy, confirm


def _patch(monkeypatch, records=None, buy=None, confirm=None):
    monkeypatch.setattr(at, "_load_analysis_records",
                        lambda: records if records is not None else _records())
    if buy is None and confirm is None:
        buy, confirm = _panels()
    monkeypatch.setattr(at, "load_panel", lambda: buy)
    monkeypatch.setattr(at, "load_confirm_panel", lambda **kw: confirm)


def test_comparison_table_shape(monkeypatch):
    _patch(monkeypatch)
    df = at.comparison_table()
    assert {"代码", "分析日期", "AI方向", "3天后是否盈利"} <= set(df.columns)
    assert "1天后是否盈利" in df.columns and "10天后是否盈利" in df.columns


def test_comparison_table_matches_panel_labels(monkeypatch):
    _patch(monkeypatch)
    df = at.comparison_table()
    row0 = df.iloc[0]
    assert row0["代码"] == "600519"
    assert row0["AI方向"] == "多"
    assert row0["1天后是否盈利"] == 0      # 买点面板 (600519, 2026-09-02)
    assert row0["3天后是否盈利"] == 1      # 确认面板 (600519, 2026-09-04)
    assert row0["5天后是否盈利"] == "无数据"
    assert row0["10天后是否盈利"] == "无数据"
    row1 = df.iloc[1]
    assert row1["代码"] == "1"            # 前导零归一后与面板 000001 匹配
    assert row1["AI方向"] == "空"
    assert row1["3天后是否盈利"] == 0     # 确认面板 (000001, 2026-09-04)
    assert row1["1天后是否盈利"] == "无数据"


def test_comparison_table_symbol_filter(monkeypatch):
    _patch(monkeypatch)
    df = at.comparison_table(symbol="600519")
    assert len(df) == 1 and df.iloc[0]["代码"] == "600519"
    df2 = at.comparison_table(symbol="000001")   # 前导零归一匹配
    assert len(df2) == 1 and df2.iloc[0]["代码"] == "1"


def test_comparison_table_custom_days_and_empty(monkeypatch):
    _patch(monkeypatch)
    df = at.comparison_table(days=(1,))
    assert list(df.columns) == ["代码", "分析日期", "AI方向", "1天后是否盈利"]
    monkeypatch.setattr(at, "_load_analysis_records", lambda: [])
    empty = at.comparison_table()
    assert len(empty) == 0
    assert "3天后是否盈利" in empty.columns


def test_comparison_table_skips_confirm_when_buy_covers(monkeypatch):
    buy = pd.DataFrame({
        "股票代码": ["600519"] * 4,
        "信号日期": ["2026-09-02", "2026-09-04", "2026-09-06", "2026-09-11"],
        "是否盈利": [1, 1, 0, 1],
    })
    monkeypatch.setattr(at, "_load_analysis_records", lambda: [
        {"symbol": "600519", "analysis_date": "2026-09-01 00:00:00",
         "final_decision": "看多"}])

    def boom(**kw):
        raise AssertionError("买点面板全覆盖时不应加载确认面板")
    monkeypatch.setattr(at, "load_panel", lambda: buy)
    monkeypatch.setattr(at, "load_confirm_panel", boom)
    df = at.comparison_table()
    assert df.iloc[0]["1天后是否盈利"] == 1
    assert df.iloc[0]["3天后是否盈利"] == 1
    assert df.iloc[0]["5天后是否盈利"] == 0
    assert df.iloc[0]["10天后是否盈利"] == 1


def test_comparison_table_panel_failure_wraps_runtime_error(monkeypatch):
    def boom():
        raise FileNotFoundError("面板缺失")
    monkeypatch.setattr(at, "_load_analysis_records", _records)
    monkeypatch.setattr(at, "load_panel", boom)
    try:
        at.comparison_table()
    except RuntimeError as e:
        assert "comparison_table" in str(e)  # R4-A:接口名入错误消息
    else:
        raise AssertionError("面板加载失败应包装为 RuntimeError(R4-A)")


# ---------- database 迁移 + trace_save(临时库) ----------

LEGACY_SCHEMA = """
CREATE TABLE analysis_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    stock_name TEXT,
    analysis_date TEXT NOT NULL,
    period TEXT NOT NULL,
    stock_info TEXT,
    agents_results TEXT,
    discussion_result TEXT,
    final_decision TEXT,
    created_at TEXT NOT NULL
)"""


def _make_legacy_db(path):
    conn = sqlite3.connect(path)
    conn.execute(LEGACY_SCHEMA)
    conn.execute(
        """INSERT INTO analysis_records
        (symbol, stock_name, analysis_date, period, stock_info, agents_results,
         discussion_result, final_decision, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("000001", "平安银行", "2026-06-25 10:07:21", "1y",
         '{"name": "平安银行"}', '{}', '{}', '{"rating": "买入"}',
         "2026-06-25T10:07:21"))
    conn.commit()
    conn.close()


def _columns(path):
    conn = sqlite3.connect(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(analysis_records)")}
    conn.close()
    return cols


def test_migration_adds_version_columns_idempotent(tmp_path):
    path = str(tmp_path / "legacy.db")
    _make_legacy_db(path)
    db = StockAnalysisDatabase(db_path=path)   # 触发 init_tables 迁移
    assert {"prompt_version", "model_version", "input_snapshot"} <= _columns(path)
    detail = db.get_record_by_id(1)            # 老数据完好可读
    assert detail["symbol"] == "000001"
    assert detail["prompt_version"] == "" and detail["model_version"] == ""
    assert detail["input_snapshot"] == {}
    db2 = StockAnalysisDatabase(db_path=path)  # 二次初始化幂等
    assert {"prompt_version", "model_version", "input_snapshot"} <= _columns(path)
    assert db2.get_record_by_id(1)["symbol"] == "000001"


def test_save_analysis_backward_compat_defaults(tmp_path):
    db = StockAnalysisDatabase(db_path=str(tmp_path / "new.db"))
    rid = db.save_analysis("600519", "贵州茅台", "1y", {"name": "x"},
                           {"t": "x"}, "讨论", {"rating": "买入"})
    assert isinstance(rid, int) and rid > 0
    detail = db.get_record_by_id(rid)
    assert detail["final_decision"]["rating"] == "买入"
    assert detail["prompt_version"] == "" and detail["model_version"] == ""
    assert detail["input_snapshot"] == {}


def test_trace_save_writes_version_fields(tmp_path, monkeypatch):
    db = StockAnalysisDatabase(db_path=str(tmp_path / "trace.db"))
    monkeypatch.setattr(at, "get_db", lambda: db)
    rid = at.trace_save(
        "600519", "贵州茅台", "1y", {"name": "x"}, {"t": "x"}, "讨论",
        {"rating": "买入"},
        prompt_version="v1", model_version="deepseek-chat",
        input_snapshot={"code": "600519", "period": "1y"},
    )
    assert isinstance(rid, int) and rid > 0
    detail = db.get_record_by_id(rid)
    assert detail["prompt_version"] == "v1"
    assert detail["model_version"] == "deepseek-chat"
    assert detail["input_snapshot"] == {"code": "600519", "period": "1y"}


def test_trace_save_defaults_empty(monkeypatch):
    class FakeDB:
        def __init__(self):
            self.calls = []

        def save_analysis(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return 7

    fake = FakeDB()
    monkeypatch.setattr(at, "get_db", lambda: fake)
    rid = at.trace_save("600519", "n", "1y", {}, {}, "", {})
    assert rid == 7
    assert fake.calls[0][1]["prompt_version"] == ""
    assert fake.calls[0][1]["model_version"] == ""
    assert fake.calls[0][1]["input_snapshot"] == ""


# ---------- deepseek_client.PROMPT_VERSIONS ----------

def test_prompt_versions_catalog():
    import deepseek_client as dc
    assert dc.PROMPT_VERSIONS["SCENARIO_PROMPT_TEMPLATE"] == dc.SCENARIO_PROMPT_VERSION == "v1"
    legacy = ("technical_analysis", "fundamental_analysis", "fund_flow_analysis",
              "comprehensive_discussion", "final_decision")
    for name in legacy:
        assert name in dc.PROMPT_VERSIONS
    assert dc.PROMPT_VERSIONS["final_decision"] == "未版本化"
