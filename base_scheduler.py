"""调度器线程生命周期基类。

monitor / portfolio / news_flow / sector_strategy 四个 scheduler 都重复了同一套
后台线程逻辑：running 标志、daemon 线程、`while running: schedule.run_pending()`
循环、以及按 tag 清理 jobs。本基类把这些公共原语抽出来，子类继承后保留各自的
公有 API（start/stop/start_scheduler 等）与具体排程逻辑，内部调用这些原语即可。

只依赖 schedule/threading/time/logging，不引入任何业务模块，便于单测。
"""
import logging
import threading
import time

import schedule

logger = logging.getLogger(__name__)


class BaseScheduler:
    # run_pending 之间的睡眠秒数；子类可按需覆盖
    loop_interval = 1

    def __init__(self):
        self.running = False
        self.thread = None

    def _run_loop(self):
        """后台线程体：running 期间反复 run_pending，单次异常不杀线程。"""
        while self.running:
            try:
                schedule.run_pending()
            except Exception as e:
                logger.error(f"调度循环执行出错: {e}")
            time.sleep(self.loop_interval)

    def _start_thread(self):
        """启动后台调度线程。已在运行则返回 False（幂等），否则启动并返回 True。"""
        if self.running:
            return False
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        return True

    def _stop_thread(self, timeout=5):
        """停止后台线程：清 running 标志并 join，最后清空 thread 引用。"""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=timeout)
        self.thread = None

    @staticmethod
    def clear_jobs(tag):
        """取消所有带指定 tag 的 schedule job，保留其它 job。"""
        for job in [j for j in schedule.jobs if tag in j.tags]:
            schedule.cancel_job(job)

    def is_alive(self) -> bool:
        """running 且后台线程存在并存活时返回 True。"""
        return bool(self.running and self.thread is not None and self.thread.is_alive())
