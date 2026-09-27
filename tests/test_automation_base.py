# tests/test_automation_base.py
import automation


def test_run_jobs_order_and_dep():
    log = []
    jobs = [
        automation.JobSpec(name="a", phase="pre_market", fn=lambda: log.append("a"), retries=0, timeout_s=5),
        automation.JobSpec(name="b", phase="pre_market", fn=lambda: log.append("b"), depends_on=["a"], retries=0, timeout_s=5),
        automation.JobSpec(name="c", phase="pre_market", fn=lambda: log.append("c"), retries=0, timeout_s=5),
    ]
    res = automation.run_jobs(jobs, phase="pre_market")
    assert log.index("a") < log.index("b")
    assert res == {"a": "ok", "b": "ok", "c": "ok"}


def test_run_jobs_retry_then_failed():
    calls = []
    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("boom")
        return "ok"
    jobs = [automation.JobSpec(name="f", phase="post_market", fn=flaky, retries=2, timeout_s=5)]
    res = automation.run_jobs(jobs, phase="post_market")
    assert res["f"] == "ok" and len(calls) == 3


def test_failed_does_not_block_independent():
    def bad(): raise RuntimeError("bad")
    jobs = [automation.JobSpec(name="x", phase="pre_market", fn=bad, retries=0, timeout_s=5),
            automation.JobSpec(name="y", phase="pre_market", fn=lambda: "y", retries=0, timeout_s=5)]
    res = automation.run_jobs(jobs, phase="pre_market")
    assert res == {"x": "failed", "y": "ok"}
