# -*- coding: utf-8 -*-
"""automation.risk_filter 风险前置过滤测试(Phase5 Task5.2)。

简报用例逐字保留;补充用例覆盖:
- default_risk_filter:ST/流动性/重大事件三项默认开启,市场门控 None;
- ST 判定大小写不敏感、简称列亦生效;
- min_amount 缺成交额列时原样透传并记录;
- exclude_events 接风险模块(monkeypatch 假模块,不真实联网):
  任一风险项 has_data 剔除、模块不可用透传并记录、取数异常保留该行;
- market_env_gate:返回假值整表清空、None 跳过、抛异常透传并记录;
- 过滤不改动输入 df、空表安全。

测试不真实调网络:风险模块通过 monkeypatch 注入假 risk_data_fetcher
或把 sys.modules 置 None 模拟不可用。
"""
import sys
import types

import pandas as pd
import pytest

from automation.risk_filter import DEFAULT_MIN_AMOUNT, build_risk_filter, default_risk_filter


def _base_df():
    return pd.DataFrame({
        "代码": ["1", "2", "3"],
        "名称": ["A", "ST股", "C"],
        "成交额": [1e8, 5e7, 3e6],
    })


def _install_fake_risk_module(monkeypatch, fetcher_cls):
    mod = types.ModuleType("risk_data_fetcher")
    mod.RiskDataFetcher = fetcher_cls
    monkeypatch.setitem(sys.modules, "risk_data_fetcher", mod)


# ---- 简报原用例(逐字保留) ----

def test_st_and_liquidity_filter():
    df = pd.DataFrame({"代码": ["1", "2", "3"], "名称": ["A", "ST股", "C"],
                       "成交额": [1e8, 5e7, 3e6]})
    f = build_risk_filter({"exclude_st": True, "min_amount": 1e7})
    out = f(df)
    # 简报期望 {"1","2"} 与其自身规则冲突:exclude_st 按「名称含 ST」剔除
    # "ST股"(代码 2),min_amount 剔除 3e6(代码 3),按规则正确结果为 {"1"}。
    # 保留简报数据不变,仅修正期望值(见 task-5.2-report.md 疑点记录)。
    assert set(out["代码"]) == {"1"}


# ---- 补充用例 ----

def test_exclude_st_case_insensitive_and_alias_col():
    # "ST股" 在名称列、小写 "st退" 在简称列,均剔除;大小写不敏感
    df = pd.DataFrame({
        "代码": ["1", "2", "3", "4"],
        "名称": ["A", "ST股", "C", "D"],
        "简称": ["x", "y", "st退", "z"],
    })
    f = build_risk_filter({"exclude_st": True})
    assert set(f(df)["代码"]) == {"1", "4"}


def test_min_amount_missing_col_passthrough_recorded():
    df = pd.DataFrame({"代码": ["1"], "名称": ["A"]})
    f = build_risk_filter({"min_amount": 1e7})
    out = f(df)
    assert out.equals(df)
    assert any("min_amount" in r for r in f.records)


def test_exclude_events_drops_rows_with_risk_data(monkeypatch):
    calls = []

    class FakeFetcher:
        def __init__(self):
            pass

        def get_risk_data(self, symbol):
            calls.append(symbol)
            has = symbol == "2"
            return {
                "symbol": symbol,
                "data_success": has,
                "lifting_ban": {"has_data": has},
                "shareholder_reduction": {"has_data": False},
                "important_events": {"has_data": False},
                "error": None,
            }

    _install_fake_risk_module(monkeypatch, FakeFetcher)
    f = build_risk_filter({"exclude_events": True})
    out = f(_base_df())
    assert set(out["代码"]) == {"1", "3"}
    assert calls == ["1", "2", "3"]


def test_exclude_events_module_unavailable_passthrough(monkeypatch):
    # sys.modules 置 None -> import 即 ImportError,模拟模块不可用:
    # 规则原样透传并记录(简报:模块不可用则该规则返回原样并记录)
    monkeypatch.setitem(sys.modules, "risk_data_fetcher", None)
    df = _base_df()
    f = build_risk_filter({"exclude_events": True})
    out = f(df)
    assert out.equals(df)
    assert any("exclude_events" in r for r in f.records)


def test_exclude_events_fetch_error_keeps_row(monkeypatch):
    class BadFetcher:
        def __init__(self):
            pass

        def get_risk_data(self, symbol):
            raise RuntimeError("network down")

    _install_fake_risk_module(monkeypatch, BadFetcher)
    df = _base_df()
    f = build_risk_filter({"exclude_events": True})
    out = f(df)
    assert out.equals(df)
    assert any("取数失败" in r for r in f.records)


def test_exclude_events_no_code_col_passthrough():
    df = pd.DataFrame({"名称": ["A", "B"]})
    f = build_risk_filter({"exclude_events": True})
    assert f(df).equals(df)
    assert any("exclude_events" in r for r in f.records)


def test_market_env_gate_false_clears_all():
    df = _base_df()
    f = build_risk_filter({"market_env_gate": lambda d: False})
    out = f(df)
    assert len(out) == 0
    assert list(out.columns) == list(df.columns)


def test_market_env_gate_none_skips():
    df = _base_df()
    f = build_risk_filter({"market_env_gate": None})
    assert f(df).equals(df)


def test_market_env_gate_raising_passthrough_recorded():
    def gate(d):
        raise RuntimeError("5.6 未就绪")

    f = build_risk_filter({"market_env_gate": gate})
    assert f(_base_df()).equals(_base_df())
    assert any("market_env_gate" in r for r in f.records)


def test_default_risk_filter_enables_three_rules(monkeypatch):
    # 默认:ST + 流动性(min_amount 默认下限 1e7)+ 重大事件开启,市场门控 None
    class EmptyFetcher:
        def __init__(self):
            pass

        def get_risk_data(self, symbol):
            return {"symbol": symbol, "data_success": False,
                    "lifting_ban": None, "shareholder_reduction": None,
                    "important_events": None, "error": None}

    _install_fake_risk_module(monkeypatch, EmptyFetcher)
    f = default_risk_filter()
    out = f(_base_df())  # "2"=ST 剔除;"3"=3e6 < 1e7 剔除
    assert set(out["代码"]) == {"1"}
    assert DEFAULT_MIN_AMOUNT == 1e7


def test_filter_does_not_mutate_input():
    df = _base_df()
    f = build_risk_filter({"exclude_st": True, "min_amount": 1e7})
    f(df)
    assert len(df) == 3


def test_filter_on_empty_df_returns_empty():
    df = pd.DataFrame({"代码": [], "名称": [], "成交额": []})
    f = build_risk_filter({"exclude_st": True, "min_amount": 1e7})
    out = f(df)
    assert len(out) == 0
    assert list(out.columns) == list(df.columns)
