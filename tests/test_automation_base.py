# tests/test_automation_base.py
import pytest

import automation
import automation.cli as cli
import automation.jobs as jobs


def test_run_jobs_order_and_dep():
    log = []
    specs = [
        automation.JobSpec(name="a", phase="pre_market", fn=lambda: log.append("a"), retries=0, timeout_s=5),
        automation.JobSpec(name="b", phase="pre_market", fn=lambda: log.append("b"), depends_on=["a"], retries=0, timeout_s=5),
        automation.JobSpec(name="c", phase="pre_market", fn=lambda: log.append("c"), retries=0, timeout_s=5),
    ]
    res = automation.run_jobs(specs, phase="pre_market")
    assert log.index("a") < log.index("b")
    assert res == {"a": "ok", "b": "ok", "c": "ok"}


def test_run_jobs_retry_then_failed():
    calls = []
    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("boom")
        return "ok"
    specs = [automation.JobSpec(name="f", phase="post_market", fn=flaky, retries=2, timeout_s=5)]
    res = automation.run_jobs(specs, phase="post_market")
    assert res["f"] == "ok" and len(calls) == 3


def test_failed_does_not_block_independent():
    def bad(): raise RuntimeError("bad")
    specs = [automation.JobSpec(name="x", phase="pre_market", fn=bad, retries=0, timeout_s=5),
             automation.JobSpec(name="y", phase="pre_market", fn=lambda: "y", retries=0, timeout_s=5)]
    res = automation.run_jobs(specs, phase="pre_market")
    assert res == {"x": "failed", "y": "ok"}


# ---- 边界用例(终审修复波⑥:重名 / 环依赖 / 外部依赖) ----

def test_run_jobs_duplicate_name_raises():
    specs = [automation.JobSpec(name="dup", phase="pre_market", fn=lambda: 1),
             automation.JobSpec(name="dup", phase="pre_market", fn=lambda: 2)]
    with pytest.raises(ValueError):
        automation.run_jobs(specs, phase="pre_market")


def test_run_jobs_cycle_skipped_no_hang():
    ran = []
    specs = [automation.JobSpec(name="a", phase="pre_market", fn=lambda: ran.append("a"),
                                depends_on=["b"]),
             automation.JobSpec(name="b", phase="pre_market", fn=lambda: ran.append("b"),
                                depends_on=["a"])]
    res = automation.run_jobs(specs, phase="pre_market")   # 环依赖不挂死,双方 skipped
    assert res == {"a": "skipped", "b": "skipped"}
    assert ran == []


def test_run_jobs_external_dep_skipped():
    ran = []
    specs = [automation.JobSpec(name="a", phase="pre_market", fn=lambda: ran.append("a"),
                                depends_on=["missing"]),
             automation.JobSpec(name="b", phase="pre_market", fn=lambda: ran.append("b"))]
    res = automation.run_jobs(specs, phase="pre_market")
    assert res == {"a": "skipped", "b": "ok"}     # 外部依赖视为永不满足
    assert ran == ["b"]


# ---- 编排入口(终审修复波④:automation.cli,monkeypatch 注入不真实执行) ----

def test_cli_run_phase_all_runs_jobs_and_alerts_failed(monkeypatch, capsys):
    run_calls = []
    def fake_run(specs, phase=None):
        run_calls.append((specs, phase))
        return {"收盘后选股": "ok", "收盘后分析": "failed"}
    monkeypatch.setattr(cli, "run_jobs", fake_run)
    alerts = []
    monkeypatch.setattr(cli, "alert_failures", lambda res, mail=True: alerts.append((res, mail)))
    res = cli.run_phase("all")
    assert run_calls == [(jobs.ALL_JOBS, None)]      # all → 全量清单,不筛 phase
    assert res == {"收盘后选股": "ok", "收盘后分析": "failed"}
    assert alerts == [({"收盘后选股": "ok", "收盘后分析": "failed"}, True)]  # 对 failed 调 alert_failures(mail=True)
    assert "收盘后分析" in capsys.readouterr().out   # 结果摘要打印


def test_cli_run_phase_pre_market_no_alert_when_all_ok(monkeypatch):
    run_calls = []
    def fake_run(specs, phase=None):
        run_calls.append((specs, phase))
        return {"开盘前新闻更新": "ok"}
    monkeypatch.setattr(cli, "run_jobs", fake_run)
    alerts = []
    monkeypatch.setattr(cli, "alert_failures", lambda res, mail=True: alerts.append((res, mail)))
    cli.run_phase("pre_market")
    assert run_calls == [(jobs.PRE_MARKET_JOBS, "pre_market")]
    assert alerts == []                              # 无 failed 不告警


def test_cli_run_phase_unknown_raises():
    with pytest.raises(ValueError):
        cli.run_phase("nope")


def test_cli_main_parses_phase_arg(monkeypatch, capsys):
    calls = []
    def fake_run(specs, phase=None):
        calls.append((specs, phase))
        return {"收盘后选股": "ok"}
    monkeypatch.setattr(cli, "run_jobs", fake_run)
    monkeypatch.setattr(cli, "alert_failures", lambda res, mail=True: None)
    assert cli.main(["--phase", "post_market"]) == 0
    assert calls == [(jobs.POST_MARKET_JOBS, "post_market")]
    assert "post_market" in capsys.readouterr().out
