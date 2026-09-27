# -*- coding: utf-8 -*-
"""automation.cli 编排入口(Phase5 终审修复波):``python -m automation.cli --phase <阶段>``。

- --phase pre_market|intraday|post_market|all:选对应任务清单
  (automation.jobs 的三时段清单;all = ALL_JOBS 全量)交 run_jobs 执行;
- 执行后打印结果摘要(各状态计数,stdout);
- 存在 failed 任务时调 alert_failures(mail=True) 告警(经统一 notify 通道,
  mail=False 语义由 alert_failures 自身保留)。

本模块只做编排,不做任何数据/网络操作;测试 monkeypatch ``cli.run_jobs``
与 ``cli.alert_failures`` 即可断言调用与参数(不真实执行任务)。
"""
import argparse
import sys

from automation import run_jobs
from automation.jobs import (
    ALL_JOBS,
    INTRADAY_JOBS,
    POST_MARKET_JOBS,
    PRE_MARKET_JOBS,
    alert_failures,
)

__all__ = ["main", "run_phase", "build_parser"]

_PHASE_JOBS = {
    "pre_market": PRE_MARKET_JOBS,
    "intraday": INTRADAY_JOBS,
    "post_market": POST_MARKET_JOBS,
    "all": ALL_JOBS,
}


def build_parser():
    """--phase 参数解析器(choices 覆盖三时段 + all)。"""
    parser = argparse.ArgumentParser(
        prog="python -m automation.cli",
        description="自动化风控复盘编排入口(三时段任务清单)")
    parser.add_argument(
        "--phase", required=True, choices=sorted(_PHASE_JOBS),
        help="执行阶段: pre_market / intraday / post_market / all")
    return parser


def run_phase(phase):
    """执行某阶段任务清单 → 打印摘要 → 对 failed 调 alert_failures(mail=True)。

    Args:
        phase: pre_market / intraday / post_market / all(未知值抛 ValueError)。

    Returns:
        run_jobs 的结果字典 {name: ok|failed|skipped}(不抛异常)。
    """
    jobs_list = _PHASE_JOBS.get(phase)
    if jobs_list is None:
        raise ValueError(f"未知阶段: {phase!r}(可用: {sorted(_PHASE_JOBS)})")
    res = run_jobs(jobs_list, phase=None if phase == "all" else phase)
    n_ok = sum(1 for s in res.values() if s == "ok")
    n_failed = sum(1 for s in res.values() if s == "failed")
    n_skipped = sum(1 for s in res.values() if s == "skipped")
    print(f"[automation.cli] 阶段 {phase}: 共 {len(res)} 个任务,"
          f"ok={n_ok}, failed={n_failed}, skipped={n_skipped}")
    if n_failed:
        failed_names = [name for name, status in res.items() if status == "failed"]
        print("[automation.cli] failed 任务: " + "、".join(failed_names))
        alert_failures(res, mail=True)
    return res


def main(argv=None):
    """CLI 入口:python -m automation.cli --phase <阶段>。"""
    args = build_parser().parse_args(argv)
    run_phase(args.phase)
    return 0


if __name__ == "__main__":
    sys.exit(main())
