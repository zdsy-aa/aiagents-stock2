# 规格：<一句话标题>

> Claude 填写本规格 → 交给 Aider+DeepSeek 执行。越精确，DeepSeek 越不跑偏。

## 目标
<这次要达成什么，1-3 句>

## 涉及文件
- 修改：`path/to/file.py`（具体哪个函数/类）
- 新增：`path/to/new.py`
- 测试：`tests/test_xxx.py`

## 精确改动
<逐条说明改什么、改成什么样；能给伪代码/签名就给。不要含糊。>

## 验收（DeepSeek 必须让其通过）
- 测试命令：`python3 -m pytest -q tests/test_xxx.py`（本机用 python3，不是 python）
- 期望：全部通过；不破坏 `python3 -m pytest -q tests/` 其余用例。

## 不做（out-of-scope）
- <明确不要碰的东西，防止 DeepSeek 扩大改动>
