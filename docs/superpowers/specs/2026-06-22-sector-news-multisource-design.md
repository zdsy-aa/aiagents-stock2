# 智策财经新闻 多源真实新闻链 设计

2026-06-22。智策 `sector_strategy_data._get_financial_news` 现仅 财联社(`stock_info_global_cls`)→东财(`stock_info_global_em`)，
两个都 flaky（实测会挂起；已有 30s `_call_with_timeout` 兜底但常落空→AI 缺消息面）。本方案把新闻扩成
**多源真实新闻链**（全部 akshare 真实新闻接口，零新依赖），只要任一源活着就拿到真新闻，不再轻易落空。

复用现成基础：`_call_with_timeout`（daemon 线程硬超时，已存在）+ `_try_sources`（按序取首个非空，已存在）。

## 目标
- `_get_financial_news` 改为按序多源链，逐源套硬超时，第一个返回非空（标准化后非空 list）即用：
  `财联社 cls → 新浪 sina → 同花顺 ths → 富途 futu → 东财 em`。
- 各源 df 列名不同 → 每源一个小适配器，统一成 `{title, content, publish_time, source}` 的 list[dict]。
- 全失败仍走既有兜底（空新闻 + `format_data_for_ai` 提示 AI 勿臆测消息面）。

## 非目标（YAGNI）
- 不接联网搜索 / 付费新闻 API / RSS（akshare 真实源已够，零依赖）。
- 不让 deepseek 编新闻（缺新闻就空+提示，已有）。
- 不改智策其它取数/分析/邮件逻辑；不改 `_call_with_timeout`/`_try_sources`。

## 组件（改 `sector_strategy_data.py`）
- 新增每源适配器（模块级纯函数，输入 df→标准 list[dict]，列名以**实现阶段实测各源真实列**为准）：
  - `_news_from_cls(df)`：财联社（列：标题/内容/发布日期/发布时间）。
  - `_news_from_sina(df)` / `_news_from_ths(df)` / `_news_from_futu(df)` / `_news_from_em(df)`（东财：标题/摘要/发布时间/链接）。
  - 每适配器：缺列容错（`row.get`），截断 content，`source` 标注来源名；空/异常→返回 `[]`。
- 重写 `_get_financial_news()`：
  ```
  sources = [("财联社", lambda: _news_from_cls(_call_with_timeout(ak.stock_info_global_cls, 25)), ...),
             ("新浪",  ...sina...), ("同花顺", ...ths...), ("富途", ...futu...), ("东财", ...em...)]
  逐源:取 df(超时)→适配器→非空即 return；全空 return []
  ```
  实现可用 `_try_sources` 包装「取数+适配」闭包，或直接 for 循环逐源 try。每源硬超时（如 25s）。
- `hasattr(ak, fn)` 防御（某 akshare 版本缺某接口则跳过该源）。

## 错误处理 / 边界
- 单源超时/异常/空 → 跳下一源（`_call_with_timeout` 返回 None → 适配器收 None 返回 []）。
- 全部源失败 → 返回 []；`format_data_for_ai` 既有「无新闻提示」生效（不臆测消息面）。
- 列名缺失 → `row.get` 兜底空串，不抛。

## 测试（tests/test_sector_data_multisource.py 追加或新文件）
- 每源适配器纯函数：构造该源样式的合成 df（中文列），断言输出 `{title,content,publish_time,source}` 正确、空 df→[]、缺列不崩。
- 多源链选取：前两源返回 []（桩），第三源非空 → 用第三源（可用注入/monkeypatch akshare 函数与 `_call_with_timeout`）。
- 全失败 → []（既有 format 提示测试已覆盖空新闻分支）。

## 上线 / 影响面
- 仅改 `sector_strategy_data.py` + 测试。改 root → `docker compose build agentsstock`+`up -d agentsstock` recreate。
- 实现后容器端到端实测：逐源耗时/可用性，确认至少一源稳定返回真新闻（与 #1 分开一次构建）。
- develop on main，用户自行 push stock2。
