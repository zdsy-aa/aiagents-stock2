# 智策板块 大盘指数/涨跌家数/换手率 多源兜底 设计

2026-06-17。`sector_strategy_data.py` 直连原生 akshare 的**东财**接口取大盘指数与全A涨跌家数，
这两个接口（`stock_zh_index_spot_em` / `stock_zh_a_spot_em`）正是 `akshare_gateway.py` 标注的
**东财被封清单 `BLOCKED_EM_FUNCS`**，服务器 IP 被封/反爬时直接失败（实测 `stock_zh_index_spot_em`
当场 ConnectionError），导致智策报告缺大盘指数、涨跌家数。换手率则因主源（同花顺）本就不带、
只有东财板块接口带，正常运行恒为 0。

本方案在 `sector_strategy_data.py` **inline 加多源兜底**（仿其已有的「同花顺主 + 东财兜底」`_get_sector_fund_flow` 模式），
东财失败时切到**新浪 / 腾讯**等不受东财封锁的源。**已实测**备源可用（2026-06-17 容器内）：
新浪 `stock_zh_index_spot_sina`(1.2s, 上证/深证/创业板齐) / 腾讯 `qt.gtimg.cn`(0.3s 最快) /
新浪 `stock_zh_a_spot`(16.7s, 全A 5527 只, 涨跌可算)。

## 目标
- 大盘指数、涨跌家数/涨停在东财失败时自动切备源取到数据，不再空缺。
- 换手率 best-effort 兜底；取不到时保持 0 并在 AI 提示中注明，避免误导。
- 不动已是双源的资金流向（同花顺主+东财兜底）；不改 `akshare_gateway`；不引入重型成份股汇总。

## 非目标（YAGNI）
- 不走/不扩 `akshare_gateway`（本次 inline 接法，与 sector_strategy_data 现有多源模式一致）。
- 板块换手率不做「成份股→逐股换手率→汇总」的重型方案（B 方案弃用）。
- 不改资金流向、不改板块/概念涨跌取数主链路（除换手率 enrichment 外）。
- 不改 deepseek/引擎/邮件/DB。

## 架构（inline 多源，复用已加的超时工具）
在 `sector_strategy_data.py` 加一个按序兜底的小工具，并把三处取数改为多源链。每个源调用都用
**已存在的 `_call_with_timeout`**（本仓 2026-06-17 已加，daemon 线程硬超时）套住，避免东财无超时挂起。

```
_try_sources(sources) -> 第一个返回"非空有效"结果的源的产物；全失败返回 None/默认。
  sources = [(label, callable, timeout_sec), ...]，逐个 _call_with_timeout 调，
  callable 抛异常/超时/空 → 试下一个；记 logger.info 命中的源。
```

## 组件与数据流

### 1. 大盘指数（`_get_market_overview` 指数段）
- 新增 `_get_index_quotes() -> dict`，按链取上证/深证/创业板 {close, change_pct, change}：
  1. **腾讯** `qt.gtimg.cn/q=sh000001,sz399001,sz399006`（urllib, timeout 8s, gbk 解析；字段:名称[1]/最新[3]/涨跌额[31]?/涨跌幅[32]——**字段下标实现阶段以实际报文为准**）。
  2. **新浪** `ak.stock_zh_index_spot_sina()`（按"名称"取 上证指数/深证成指/创业板指 行）。
  3. **东财** `ak.stock_zh_index_spot_em(...)`（保留为最后兜底）。
- 第一个成功取到三个指数即用；写回 `overview["sh_index"/"sz_index"/"cyb_index"]`（结构不变）。

### 2. 涨跌家数/涨停（`_get_market_overview` 广度段）
- 全A快照链：**新浪 `ak.stock_zh_a_spot()` → 东财 `ak.stock_zh_a_spot_em()`**。
- 取到 DataFrame 后按"涨跌幅"列计算：total/up(>0)/down(<0)/flat、up_ratio、涨停(≥9.5)/跌停(≤-9.5)。
  统计逻辑抽成纯函数 `_breadth_from_spot(df) -> dict`，两个源产出的 df 都含"涨跌幅"列，统一处理。

### 3. 换手率（板块换手率，`_get_sector_performance`，best-effort=A）
- 维持现状主链（同花顺取板块涨跌/资金/领涨，turnover 缺省 0）。
- **新增 best-effort enrichment**：东财板块接口 `ak.stock_board_industry_name_em` 用 `_call_with_timeout`（短超时，如 15s）尝试取一次，成功则把"换手率"按板块名回填到对应板块 turnover；失败/超时则保持 0。
- `format_data_for_ai` 在板块换手率整体缺失（全 0）时追加一句提示："板块换手率本次暂缺，请勿据此判断量能"。

## 错误处理 / 边界
- 每源 `_call_with_timeout` 硬超时 + try/except，单源失败只切下一个、不抛。
- 全链失败：大盘指数/涨跌家数返回空 dict（现有 `_get_market_overview` 已容忍空，AI 据其余数据分析）。
- 腾讯报文解析防御：字段不足/格式异常 → 视为该源失败切下一个。
- 不改变 `_get_market_overview` 对外返回结构（下游 `format_data_for_ai` 无需改，除换手率提示）。

## 测试（纯逻辑，不联网）
- `_breadth_from_spot(df)`：构造含"涨跌幅"列的合成 df，断言 up/down/flat/涨停/跌停 计数正确（含边界 9.5/-9.5）。
- 腾讯指数报文解析函数：喂一段固定 `v_sh000001="..."` 文本，断言解析出 close/change_pct。
- `_try_sources`：第一个源抛异常/返回空 → 落到第二个；全失败 → None。可用本地桩 callable，不联网。
- `format_data_for_ai`：板块全 0 换手率 → 含"换手率本次暂缺"提示；有换手率 → 不含。
- 复用现有 `_call_with_timeout` 的超时行为已被 `test_sector_strategy_data_news_timeout.py` 覆盖。

## 影响面 / 上线
- 仅改 `sector_strategy_data.py`（root，烤进镜像）+ 新增测试。
- 改 root 代码需 `docker compose build agentsstock` + `up -d agentsstock` recreate 才在容器/智策 cron 生效。
- develop on main，用户自行 push stock2。
