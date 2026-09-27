# -*- coding: utf-8 -*-
"""automation 包:Phase5 自动化风控复盘的任务编排骨架。

JobSpec 描述一个可编排任务,run_jobs 按依赖拓扑序执行一批任务:

- 依赖未满足(依赖名不在本批任务中、或依赖结果为 failed/skipped)的任务标 skipped;
- 执行抛异常按 retries 重试,耗尽后标 failed,不阻塞其它无依赖任务;
- 返回 {name: ok|failed|skipped} 结果字典,供告警模块(5.1)收集 failed。

只依赖标准库,便于单测与后续任务(5.1~5.6)复用。任务注册/依赖/重试钩子
收敛在本包,不侵入 base_scheduler.BaseScheduler(见 task-5.0-report.md 结论)。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["JobSpec", "run_jobs", "PHASES"]

PHASES = ("pre_market", "intraday", "post_market")


@dataclass
class JobSpec:
    """单个自动化任务规格。

    Attributes:
        name: 任务唯一名,作为依赖引用与结果字典的键。
        phase: 所属交易阶段,规范取值为 pre_market / intraday / post_market。
        fn: 无参可调用对象,任务主体;抛异常视为本次执行失败。
        depends_on: 依赖的任务名列表,全部为 ok 才执行本任务(默认为空)。
        retries: 失败后的重试次数,总尝试次数 = retries + 1(默认 0)。
        timeout_s: 预留的超时秒数;骨架暂不强制,0 表示不限制。
    """

    name: str
    phase: str
    fn: Callable[[], object]
    depends_on: List[str] = field(default_factory=list)
    retries: int = 0
    timeout_s: int = 0


def _run_with_retries(job: JobSpec) -> str:
    """按 retries 执行单个任务,返回 "ok" 或 "failed"。"""
    attempts = max(1, 1 + job.retries)
    for attempt in range(1, attempts + 1):
        try:
            job.fn()
            return "ok"
        except Exception as e:
            logger.warning("任务 %s 第 %d/%d 次执行失败: %s", job.name, attempt, attempts, e)
    return "failed"


def run_jobs(jobs: List[JobSpec], phase: Optional[str] = None) -> Dict[str, str]:
    """按依赖拓扑序执行任务,返回 {name: ok|failed|skipped}。

    规则:
    - phase 给定则只执行该阶段的任务,结果字典只含该阶段的任务;
    - 按依赖拓扑序执行,无依赖关系的任务保持 jobs 传入顺序(结果确定);
    - depends_on 中的名字不在本批任务中,或依赖结果非 ok → 本任务 skipped;
    - 执行抛异常时按 retries 重试,耗尽后标 failed 并继续后续无依赖任务;
    - 结果字典包含本批全部任务(含 failed/skipped),供告警模块收集。
    """
    selected = [j for j in jobs if phase is None or j.phase == phase]
    if not selected:
        return {}

    by_name: Dict[str, JobSpec] = {}
    for j in selected:
        if j.name in by_name:
            raise ValueError(f"任务名重复: {j.name!r}")
        by_name[j.name] = j

    # 依赖图:Kahn 拓扑序,外部依赖(不在本批任务中)视为永不满足
    indegree = {j.name: 0 for j in selected}
    dependents: Dict[str, List[str]] = {name: [] for name in by_name}
    for j in selected:
        for dep in j.depends_on:
            if dep in by_name:
                indegree[j.name] += 1
                dependents[dep].append(j.name)
            else:
                logger.warning("任务 %s 依赖的 %s 不在本批任务中,将被 skipped", j.name, dep)

    ready = [j.name for j in selected if indegree[j.name] == 0]
    results: Dict[str, str] = {}

    while ready:
        name = ready.pop(0)  # FIFO:同层任务保持传入顺序
        job = by_name[name]
        if any(d not in by_name or results.get(d, "ok") != "ok" for d in job.depends_on):
            results[name] = "skipped"
        else:
            results[name] = _run_with_retries(job)
        for dependent in dependents[name]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)

    # 未处理的剩余任务:依赖环或传递依赖了外部/失败任务,标 skipped
    for j in selected:
        if j.name not in results:
            logger.error("任务 %s 因依赖未满足(环或外部依赖)未执行,标 skipped", j.name)
            results[j.name] = "skipped"

    return results
