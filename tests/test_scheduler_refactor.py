"""特征测试：锁定业务 scheduler 的 start/stop 行为，保护 BaseScheduler 重构。

以 SectorStrategyScheduler 为代表（实例化轻、start 仅排程无外部 I/O），验证继承
BaseScheduler 后 start/stop 行为不变：start 注册带 tag 的 job 且幂等，stop 清理
本模块 job 并置 running=False。news_flow/monitor 因实例化有依赖/副作用，依赖
py_compile + import + 全量 pytest + 容器重部署冒烟另行验证。
"""
import schedule

from sector_strategy_scheduler import SectorStrategyScheduler


def teardown_function():
    schedule.clear()


def test_sector_start_registers_tagged_job_and_is_idempotent():
    s = SectorStrategyScheduler()
    assert s.start("09:00") is True
    assert s.running is True
    assert any("sector_strategy" in j.tags for j in schedule.jobs)
    # 已运行：再次 start 应返回 False
    assert s.start("09:00") is False
    s.stop()


def test_sector_stop_clears_only_its_jobs_and_sets_running_false():
    s = SectorStrategyScheduler()
    s.start("09:00")
    # 放一个别的模块的 job，确认 stop 不误删
    other = schedule.every().day.at("23:59").do(lambda: None)
    other.tag("monitor")

    assert s.stop() is True
    assert s.running is False
    assert not any("sector_strategy" in j.tags for j in schedule.jobs)
    assert any("monitor" in j.tags for j in schedule.jobs)  # 他人 job 保留
