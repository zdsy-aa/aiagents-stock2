# -*- coding: utf-8 -*-
"""interfaces.screen 批量选股与信号扫描接口测试(Phase4 Task4.2)。

- 简报 3 个用例逐字保留(未知选股器 ValueError / 名称扫描 / 列归一化)。
- 补充用例:真实选股器注册表、tuple 返回解包与中文列别名映射、映射缺失填空串、
  (ok=False) 失败转 RuntimeError(R4-A)、名称解析走 build_57_specs、未知组合名
  ValueError、默认 df 走 load_confirm_panel、输出保留面板原列名。
- 全部不依赖真实选股器跑批(monkeypatch SELECTORS / 合成 df);仅 TQ01 名称解析
  用例走真实 build_57_specs(与 Phase3 同源,本机已有测试同样调用)。
"""
import pandas as pd
import pytest

import interfaces.screen as scr
from interfaces.common import SCREEN_RESULT_COLS

# 简报合成面板:TQ01(极限抄底 AND 主力参与 AND 大盘空头)恰好全部命中第 1 行
SYN_DF = pd.DataFrame({
    "极限抄底": [1, 1, 0],
    "主力参与": [1, 0, 1],
    "大盘空头": [1, 1, 1],
    "股票代码": ["1", "2", "3"],
    "信号日期": ["20250101"] * 3,
})


# ---- 简报原用例(逐字保留) ----

def test_unknown_selector_raises():
    with pytest.raises(ValueError, match="未知选股器"):
        scr.screen_stocks("不存在的选股器")


def test_scan_signals_by_name():
    import backtest.combo_engine as ce
    df = SYN_DF.copy()
    spec = {"name": "TQ01", "conds": [{"col": c, "op": ">", "value": 0}
            for c in ("极限抄底", "主力参与", "大盘空头")], "join": "AND"}
    out = scr.scan_signals(spec, df)
    assert len(out) == 1 and out.iloc[0]["股票代码"] == "1"


def test_screen_result_columns_normalized(monkeypatch):
    monkeypatch.setitem(scr.SELECTORS, "fake", lambda params, universe: pd.DataFrame({"code": ["1"], "name": ["测试"]}))
    out = scr.screen_stocks("fake")
    assert list(out.columns) == SCREEN_RESULT_COLS


# ---- 补充用例 ----

def test_selectors_registry_has_real_entries():
    for name in ("main_force", "chanlun", "combo", "liumai"):
        assert name in scr.SELECTORS, name
        assert callable(scr.SELECTORS[name])


def test_screen_stocks_tuple_result_with_chinese_aliases(monkeypatch):
    def fake(params, universe):
        assert params == {"top_n": 3}
        assert universe is None
        return (True, pd.DataFrame({
            "股票代码": ["600000"], "股票简称": ["浦发银行"],
            "买点": ["一买"], "评分": [88], "buy_reason": ["理由"],
        }), "扫描批次 ok")

    monkeypatch.setitem(scr.SELECTORS, "fake2", fake)
    out = scr.screen_stocks("fake2", params={"top_n": 3})
    assert list(out.columns) == SCREEN_RESULT_COLS
    assert out.iloc[0].tolist() == ["600000", "浦发银行", "一买", "88", "理由"]


def test_screen_stocks_unmapped_cols_filled_empty(monkeypatch):
    monkeypatch.setitem(
        scr.SELECTORS, "fake3",
        lambda params, universe: (True, pd.DataFrame({"symbol": ["000001"]}), "ok"))
    out = scr.screen_stocks("fake3")
    assert out.iloc[0].tolist() == ["000001", "", "", "", ""]


def test_screen_stocks_failure_raises_runtime_error(monkeypatch):
    monkeypatch.setitem(
        scr.SELECTORS, "fake4",
        lambda params, universe: (False, None, "所有查询方案都失败了"))
    with pytest.raises(RuntimeError, match="screen_stocks"):
        scr.screen_stocks("fake4")


def test_screen_stocks_zero_overlap_cols_all_empty(monkeypatch):
    # 列名与 _ALIAS 五槽零交集的 DataFrame:不抛错,返回 N 行五列全空串
    monkeypatch.setitem(
        scr.SELECTORS, "fake5",
        lambda params, universe: pd.DataFrame({"abc": [1, 2], "xyz": ["a", "b"]}))
    out = scr.screen_stocks("fake5")
    assert list(out.columns) == SCREEN_RESULT_COLS
    assert len(out) == 2
    assert (out == "").all().all()


def test_screen_stocks_non_dataframe_result_wraps_runtime_error(monkeypatch):
    # callable 返回非 DataFrame(list):抛 RuntimeError(消息含 selector 名),
    # 不逃逸原始 AttributeError
    monkeypatch.setitem(
        scr.SELECTORS, "fake6",
        lambda params, universe: (True, ["1", "2"], "ok"))
    with pytest.raises(RuntimeError, match="screen_stocks") as ei:
        scr.screen_stocks("fake6")
    assert "fake6" in str(ei.value)
    assert isinstance(ei.value.__cause__, AttributeError)


def test_scan_signals_name_resolves_via_build_57_specs():
    # 名称字符串走真实 build_57_specs 解析(Phase3 同源),合成面板 TQ01 命中第 1 行
    out = scr.scan_signals("TQ01", SYN_DF.copy())
    assert len(out) == 1 and out.iloc[0]["股票代码"] == "1"


def test_scan_signals_keeps_code_date_and_signal_cols():
    spec = {"name": "TQ01", "conds": [{"col": c, "op": ">", "value": 0}
            for c in ("极限抄底", "主力参与", "大盘空头")], "join": "AND"}
    out = scr.scan_signals(spec, SYN_DF.copy())
    assert list(out.columns) == ["股票代码", "信号日期", "极限抄底", "主力参与", "大盘空头"]
    assert out["信号日期"].iloc[0] == "20250101"


def test_scan_signals_unknown_spec_name_raises():
    with pytest.raises(ValueError, match="未知组合规格"):
        scr.scan_signals("TQ99", SYN_DF.copy())


def test_scan_signals_invalid_spec_type_raises():
    with pytest.raises(ValueError):
        scr.scan_signals(123, SYN_DF.copy())


def test_scan_signals_default_df_uses_confirm_panel(monkeypatch):
    calls = []

    def fake_panel():
        calls.append(1)
        return SYN_DF.copy()

    monkeypatch.setattr(scr, "load_confirm_panel", fake_panel)
    spec = {"name": "TQ01", "conds": [{"col": c, "op": ">", "value": 0}
            for c in ("极限抄底", "主力参与", "大盘空头")], "join": "AND"}
    out = scr.scan_signals(spec)  # df=None -> load_confirm_panel
    assert calls == [1]
    assert len(out) == 1 and out.iloc[0]["股票代码"] == "1"


def test_scan_signals_missing_col_wraps_runtime_error():
    spec = {"name": "X", "conds": [{"col": "不存在的列", "op": ">", "value": 0}], "join": "AND"}
    with pytest.raises(RuntimeError, match="scan_signals"):
        scr.scan_signals(spec, SYN_DF.copy())


# ---- Phase5 Task5.2: risk_filter 参数 ----

def test_screen_stocks_risk_filter_applied_after_normalize(monkeypatch):
    # 归一化后的 df(名称槽已映射)再应用风险过滤:ST 行被剔除,列仍为五槽
    from automation.risk_filter import build_risk_filter
    monkeypatch.setitem(
        scr.SELECTORS, "fake7",
        lambda params, universe: pd.DataFrame(
            {"股票代码": ["1", "2"], "股票简称": ["A", "ST股"]}))
    out = scr.screen_stocks(
        "fake7", risk_filter=build_risk_filter({"exclude_st": True}))
    assert list(out.columns) == SCREEN_RESULT_COLS
    assert out["代码"].tolist() == ["1"]


def test_screen_stocks_risk_filter_default_none(monkeypatch):
    # 缺省 risk_filter=None:不过滤,保持旧行为(ST 行原样返回)
    monkeypatch.setitem(
        scr.SELECTORS, "fake8",
        lambda params, universe: pd.DataFrame(
            {"code": ["1", "2"], "name": ["A", "ST股"]}))
    out = scr.screen_stocks("fake8")
    assert out["代码"].tolist() == ["1", "2"]


def test_screen_stocks_risk_filter_not_callable_raises(monkeypatch):
    monkeypatch.setitem(
        scr.SELECTORS, "fake9",
        lambda params, universe: pd.DataFrame({"code": ["1"]}))
    with pytest.raises(TypeError, match="risk_filter"):
        scr.screen_stocks("fake9", risk_filter=123)


def test_screen_stocks_risk_filter_bad_return_wraps_runtime_error(monkeypatch):
    # risk_filter 返回非 DataFrame:按 R4-A 包装为 RuntimeError(消息含接口名)
    monkeypatch.setitem(
        scr.SELECTORS, "fake10",
        lambda params, universe: pd.DataFrame({"code": ["1"]}))
    with pytest.raises(RuntimeError, match="screen_stocks"):
        scr.screen_stocks("fake10", risk_filter=lambda df: ["1"])
