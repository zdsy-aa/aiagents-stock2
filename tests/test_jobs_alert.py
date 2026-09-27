# -*- coding: utf-8 -*-
"""automation.jobs 三时段任务清单 + automation.alert 失败告警测试(Phase5 Task5.1)。

全部用例注入假实现(monkeypatch 被封装模块的接口函数),不真实跑网络/发信/
加载 15M 确认面板;收盘后任务链以注入方式整链实测,记录各环节调用。
"""
import pandas as pd
import pytest

import automation
import automation.jobs as jobs
import interfaces.screen as scr


# ---- 简报用例(逐字保留) ----

def test_post_market_jobs_defined():
    names = [j.name for j in jobs.POST_MARKET_JOBS]
    assert "收盘后选股" in names and "收盘后分析" in names


def test_raise_on_empty_param(monkeypatch):
    monkeypatch.setitem(scr.SELECTORS, "empty_sel", lambda params, universe: __import__("pandas").DataFrame({"代码": []}))
    out = scr.screen_stocks("empty_sel", raise_on_empty=False)
    assert len(out) == 0          # 空表而非抛错
    with pytest.raises(RuntimeError):
        scr.screen_stocks("empty_sel", raise_on_empty=True)


def test_alert_failures_mail_off(monkeypatch, capsys):
    monkeypatch.setattr(jobs, "send_mail", lambda subj, body: (_ for _ in ()).throw(AssertionError("不应发信")))
    jobs.alert_failures({"任务A": "failed"}, mail=False)
    assert "任务A" in capsys.readouterr().out


# ---- 补充用例:三时段清单结构 ----

def test_three_phase_jobs_defined():
    assert {j.name for j in jobs.PRE_MARKET_JOBS} >= {"开盘前新闻更新", "盘前列表"}
    assert {j.name for j in jobs.INTRADAY_JOBS} >= {"盘中信号扫描"}
    assert {j.name for j in jobs.POST_MARKET_JOBS} >= {"收盘后选股", "收盘后分析", "收盘后信号记录"}
    for j in jobs.PRE_MARKET_JOBS + jobs.INTRADAY_JOBS + jobs.POST_MARKET_JOBS:
        assert callable(j.fn), j.name
        assert j.phase in automation.PHASES, j.name


def test_stable_selector_registered():
    # 盘前列表任务依赖的 "stable" 选股器(本地每日自选股清单只读版)
    assert "stable" in scr.SELECTORS and callable(scr.SELECTORS["stable"])


# ---- 补充用例:告警 ----

def test_alert_failures_mail_on(monkeypatch):
    sent = []
    monkeypatch.setattr(jobs, "send_mail", lambda subj, body: sent.append((subj, body)))
    jobs.alert_failures({"任务A": "failed", "任务B": "ok", "任务C": "skipped"}, mail=True)
    assert len(sent) == 1
    assert "任务A" in sent[0][0] + sent[0][1]
    assert "任务B" not in sent[0][1]   # 只报 failed,不报 ok/skipped


def test_alert_failures_no_failure_skips_mail(monkeypatch, capsys):
    monkeypatch.setattr(jobs, "send_mail",
                        lambda subj, body: (_ for _ in ()).throw(AssertionError("无失败不应发信")))
    jobs.alert_failures({"任务A": "ok"}, mail=True)
    assert "无失败" in capsys.readouterr().out


def test_alert_failures_mail_error_does_not_raise(monkeypatch, capsys):
    def boom(subj, body):
        raise RuntimeError("smtp down")
    monkeypatch.setattr(jobs, "send_mail", boom)
    jobs.alert_failures({"任务A": "failed"}, mail=True)   # 告警通道失败不打断
    assert "任务A" in capsys.readouterr().out


# ---- 补充用例:开盘前任务链(注入式,不跑网络) ----

def test_pre_market_chain_injected(monkeypatch):
    calls = []
    import news_fetch
    monkeypatch.setattr(news_fetch, "fetch_daily_news",
                        lambda: calls.append("fetch_daily_news"))

    def fake_screen(selector, params=None, universe=None, raise_on_empty=True):
        calls.append(("screen", selector, raise_on_empty))
        return pd.DataFrame(columns=["代码", "名称", "信号", "得分", "备注"])
    monkeypatch.setattr(scr, "screen_stocks", fake_screen)

    res = automation.run_jobs(jobs.PRE_MARKET_JOBS, phase="pre_market")
    assert res == {"开盘前新闻更新": "ok", "盘前列表": "ok"}
    assert calls == ["fetch_daily_news", ("screen", "stable", False)]


def test_pre_market_news_failure_retries_then_failed(monkeypatch):
    attempts = []
    def flaky():
        attempts.append(1)
        raise RuntimeError("新闻源不可用")
    import news_fetch
    monkeypatch.setattr(news_fetch, "fetch_daily_news", flaky)
    monkeypatch.setattr(scr, "screen_stocks",
                        lambda *a, **k: pd.DataFrame(columns=["代码", "名称", "信号", "得分", "备注"]))
    res = automation.run_jobs(jobs.PRE_MARKET_JOBS, phase="pre_market")
    assert res["开盘前新闻更新"] == "failed" and len(attempts) == 2   # retries=1
    assert res["盘前列表"] == "ok"                                    # 不阻塞无依赖任务


# ---- 补充用例:盘中信号扫描(重点池) ----

def test_intraday_scan_skips_when_pool_empty(monkeypatch):
    monkeypatch.setattr(jobs, "WATCHLIST", [])
    import backtest.dataio as dio
    def panel_boom():
        raise AssertionError("重点池为空时不应加载确认面板")
    monkeypatch.setattr(dio, "load_confirm_panel", panel_boom)
    res = automation.run_jobs(jobs.INTRADAY_JOBS, phase="intraday")
    assert res["盘中信号扫描"] == "ok"


def test_intraday_scan_runs_with_pool(monkeypatch):
    panel = pd.DataFrame({
        "股票代码": ["1", "2"], "信号日期": ["20250101"] * 2,
        "极限抄底": [1, 0], "主力参与": [1, 1], "大盘空头": [0, 0]})
    calls = []
    import backtest.dataio as dio
    monkeypatch.setattr(dio, "load_confirm_panel", lambda: panel)
    monkeypatch.setattr(scr, "scan_signals",
                        lambda spec, df=None: calls.append(spec) or df.iloc[:1])
    monkeypatch.setattr(jobs, "WATCHLIST", ["1"])
    res = automation.run_jobs(jobs.INTRADAY_JOBS, phase="intraday")
    assert res["盘中信号扫描"] == "ok"
    assert calls == ["TQ01"]          # 默认组合规格


# ---- 补充用例:收盘后任务链(注入式实测,记录各环节调用) ----

def _fake_analysis_result(code):
    return {
        "symbol": code, "name": f"{code}股", "period": "1y",
        "generated_at": "2026-09-27 15:30:00", "current_state": "买入",
        "trend": "上升", "chip": "集中", "capital": "流入", "industry": "制造",
        "news": "无", "signals": "放量", "scenarios": [], "evidence": "讨论",
        "degraded": False, "degraded_reason": "",
    }


def test_post_market_chain_end_to_end_injected(monkeypatch):
    import interfaces.analyze as az
    import interfaces.ai_trace as ait
    calls = []

    def fake_screen(selector, params=None, universe=None, raise_on_empty=True):
        calls.append(("screen", selector, raise_on_empty))
        rows = {"chanlun": [("600000", "浦发"), ("600519", "茅台")],
                "combo": [("600519", "茅台"), ("601318", "平安")]}[selector]
        return pd.DataFrame({"代码": [r[0] for r in rows], "名称": [r[1] for r in rows],
                             "信号": [""] * len(rows), "得分": [""] * len(rows),
                             "备注": [""] * len(rows)})

    monkeypatch.setattr(scr, "screen_stocks", fake_screen)
    monkeypatch.setattr(az, "analyze_stock",
                        lambda code, period="1y", with_ai=True: calls.append(("analyze", code)) or _fake_analysis_result(code))
    def fake_trace(symbol, name, period, stock_info, agents_results, discussion_result,
                   final_decision, prompt_version="", model_version="", input_snapshot=""):
        calls.append(("trace", symbol, prompt_version, model_version))
        return 42
    monkeypatch.setattr(ait, "trace_save", fake_trace)

    res = automation.run_jobs(jobs.POST_MARKET_JOBS, phase="post_market")
    assert res == {"收盘后选股": "ok", "收盘后分析": "ok", "收盘后信号记录": "ok"}

    # 环节调用记录:chanlun → combo(均 raise_on_empty=False)→ 去重后前 N 只分析 → trace 落版本
    assert calls[:2] == [("screen", "chanlun", False), ("screen", "combo", False)]
    assert [c for c in calls if c[0] == "analyze"] == [
        ("analyze", "600000"), ("analyze", "600519"), ("analyze", "601318")]  # 600519 去重
    traces = [c for c in calls if c[0] == "trace"]
    assert [t[1] for t in traces] == ["600000", "600519", "601318"]
    for t in traces:
        assert isinstance(t[2], str) and t[2].startswith("{")   # prompt_version 非空(PROMPT_VERSIONS 快照)
        assert isinstance(t[3], str) and t[3]                    # model_version 非空


def test_post_market_analysis_degraded_marks_failed(monkeypatch):
    import interfaces.analyze as az
    import interfaces.ai_trace as ait
    monkeypatch.setattr(scr, "screen_stocks",
                        lambda *a, **k: pd.DataFrame({"代码": ["600000"], "名称": ["浦发"],
                                                      "信号": [""], "得分": [""], "备注": [""]}))
    def degraded_result(code, period="1y", with_ai=True):
        r = _fake_analysis_result(code)
        r["degraded"] = True
        r["degraded_reason"] = "网络超时"
        return r
    monkeypatch.setattr(az, "analyze_stock", degraded_result)
    monkeypatch.setattr(ait, "trace_save", lambda *a, **k: 1)
    res = automation.run_jobs(jobs.POST_MARKET_JOBS, phase="post_market")
    assert res["收盘后选股"] == "ok"
    assert res["收盘后分析"] == "failed"          # 降级不得静默(全局约束)
    assert res["收盘后信号记录"] == "skipped"     # 依赖 failed → 跳过


def test_post_market_no_candidates_skips_analysis(monkeypatch):
    import interfaces.analyze as az
    monkeypatch.setattr(scr, "screen_stocks",
                        lambda *a, **k: pd.DataFrame(columns=["代码", "名称", "信号", "得分", "备注"]))
    monkeypatch.setattr(az, "analyze_stock",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("无候选不应分析")))
    res = automation.run_jobs(jobs.POST_MARKET_JOBS, phase="post_market")
    assert res["收盘后选股"] == "ok" and res["收盘后分析"] == "ok"


def test_post_market_screen_total_failure_marks_failed(monkeypatch):
    def boom(selector, params=None, universe=None, raise_on_empty=True):
        raise RuntimeError(f"{selector} 数据源不可用")
    monkeypatch.setattr(scr, "screen_stocks", boom)
    res = automation.run_jobs(jobs.POST_MARKET_JOBS, phase="post_market")
    assert res["收盘后选股"] == "failed"
    assert res["收盘后分析"] == "skipped" and res["收盘后信号记录"] == "skipped"
