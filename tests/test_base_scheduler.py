"""BaseScheduler 调度线程生命周期基类的单元测试。

覆盖 4 个业务 scheduler 重复的公共原语：running 标志 / daemon 线程 /
run_pending 循环 / 按 tag 清理 jobs。不依赖任何业务模块或重依赖。
"""
import time

import schedule

from base_scheduler import BaseScheduler


def teardown_function():
    # 防止用到全局 schedule 单例的测试相互污染
    schedule.clear()


def test_start_thread_sets_running_and_is_idempotent():
    s = BaseScheduler()
    s.loop_interval = 0.01
    assert s._start_thread() is True
    assert s.running is True
    assert s.thread is not None and s.thread.is_alive()

    # 已在运行：再次启动应返回 False，且不新建线程
    first_thread = s.thread
    assert s._start_thread() is False
    assert s.thread is first_thread

    s._stop_thread()


def test_stop_thread_stops_loop_and_clears_thread():
    s = BaseScheduler()
    s.loop_interval = 0.01
    s._start_thread()
    s._stop_thread(timeout=2)
    assert s.running is False
    assert s.thread is None


def test_run_loop_pumps_run_pending(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(schedule, "run_pending",
                        lambda: calls.__setitem__("n", calls["n"] + 1))
    s = BaseScheduler()
    s.loop_interval = 0.01
    s._start_thread()
    deadline = time.time() + 2
    while calls["n"] < 2 and time.time() < deadline:
        time.sleep(0.02)
    s._stop_thread()
    assert calls["n"] >= 2


def test_run_loop_survives_job_exception(monkeypatch):
    """run_pending 抛异常不应杀死循环线程。"""
    state = {"n": 0}

    def boom():
        state["n"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(schedule, "run_pending", boom)
    s = BaseScheduler()
    s.loop_interval = 0.01
    s._start_thread()
    deadline = time.time() + 2
    while state["n"] < 2 and time.time() < deadline:
        time.sleep(0.02)
    still_alive = s.thread.is_alive()
    s._stop_thread()
    assert state["n"] >= 2  # 异常后仍继续循环
    assert still_alive


def test_clear_jobs_removes_only_tagged():
    schedule.clear()
    schedule.every().day.at("09:00").do(lambda: None).tag("alpha")
    schedule.every().day.at("10:00").do(lambda: None).tag("beta")
    assert len(schedule.jobs) == 2

    BaseScheduler.clear_jobs("alpha")

    remaining_tags = {t for j in schedule.jobs for t in j.tags}
    assert "alpha" not in remaining_tags
    assert "beta" in remaining_tags
    assert len(schedule.jobs) == 1
