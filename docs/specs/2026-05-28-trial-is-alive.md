# 规格：BaseScheduler 增加 is_alive() 便捷方法

## 目标
给 base_scheduler.BaseScheduler 增加 is_alive()，返回"调度线程是否真的在跑"。

## 涉及文件
- 修改：`base_scheduler.py`（BaseScheduler 类，加方法）
- 测试：`tests/test_base_scheduler.py`（加一条测试）

## 精确改动
在 BaseScheduler 内新增方法：

    def is_alive(self) -> bool:
        """running 且后台线程存在并存活时返回 True。"""
        return bool(self.running and self.thread is not None and self.thread.is_alive())

在 tests/test_base_scheduler.py 末尾新增测试：

    def test_is_alive_reflects_thread_state():
        s = BaseScheduler()
        s.loop_interval = 0.01
        assert s.is_alive() is False          # 未启动
        s._start_thread()
        assert s.is_alive() is True           # 启动后
        s._stop_thread()
        assert s.is_alive() is False          # 停止后

## 验收（必须让其通过）
- 测试命令：`python -m pytest -q tests/test_base_scheduler.py`
- 期望：全部通过；不破坏 `python -m pytest -q tests/` 其余用例。

## 不做（out-of-scope）
- 不动其它 scheduler 子类；不改已有方法签名。
