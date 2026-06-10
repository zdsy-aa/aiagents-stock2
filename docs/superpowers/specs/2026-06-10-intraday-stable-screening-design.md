# 🛡️稳定选股 盘中化 + 4时点推送 — 设计文档

- 日期：2026-06-10
- 分支：feat/liumai-and-combo-screening
- 关联：缠论多类买卖点V2研究、核心/精选星级、部署与数据源

## 1. 背景与问题

现状 `🛡️稳定选股` 是**盘后**产品：
- `chanlun_batch.py`（盘后 20:00，用 `akshare_gw.local` 已收盘日K）扫全市场近 7 交易日缠论买点 → 写 `data/chanlun_signals.db`。
- `daily_watchlist.py`（盘后 21:00）读该库，套 A∪B 规则 + 星级 → 出 `每日自选股清单.csv`，邮件推送。

问题：信号都基于**已收盘**数据，盘后扫出来时常已"过窗"——`entry_status()` 里 `gap>2 已过窗`、`close>buy*1.05 已涨过`——错过当日入场。

## 2. 目标

每个交易日 **10:00 / 11:00 / 13:30 / 14:30** 四个时点，用"历史日K + 当天实时 bar"选股并推送：
- **C（两者都要）**：盘中既重算"当天新形成"的缠论买点，又复核"已有近期买点"的实时可入状态，合并。
- 推送 = **每次全量可入清单 + 本时段新增/变动置顶高亮**。
- 盘中跑**完整 A∪B**（含 baostock core-B），约 13min/轮。

## 3. 架构

在既有盘后管线之外新增**盘中管线**，共用引擎、各写各库、互不污染。

```
宿主 crontab(09:47/10:47/13:17/14:17 CST, 仅交易日)
  └─ ops/intraday_watchlist_and_mail.sh
       ├─ [门控] 非交易日直接退出
       ├─ docker exec agentsstock1:
       │    ① chanlun 盘中重算(注入今日实时bar) → data/chanlun_signals_intraday.db
       │    ② daily_watchlist 盘中模式(读 盘中库∪盘后库, 实时价重判entry_status)
       │       → watchlist_history/intraday/每日自选股清单_{date}_{HHMM}.csv + latest指针
       │       内含与本交易日上一轮快照对比得到的 🆕/⤴变动 标记
       └─ 宿主: export md/xlsx + push 邮件(主题带时段, 高亮区在最上)
```

触发时刻提前 ~13min，使结果/邮件落在 10:00/11:00/13:30/14:30 附近。提前量为脚本常量，可调。

## 4. 组件设计

### 4.1 实时 bar 注入工具（新建 `data/profit_mining/intraday_quote.py`）

职责：取当天实时快照并把它拼成"今日日K bar"。

接口：
- `fetch_market_snapshot() -> dict[str, dict]`
  - 经 `akshare_gw` 调 `stock_zh_a_spot_em`（走 5 级降级链）一次取全市场。
  - 返回 `{code(6位): {"Open":今开,"High":最高,"Low":最低,"Close":现价,"Volume":成交量}}`。
  - 字段缺失/异常的票跳过；整体失败返回 `{}`。
- `inject_today_bar(df, bar, today) -> DataFrame`
  - `df` = 标准 OHLCV（index=日期）。`today` = `pd.Timestamp(当天)`。
  - 若 `df` 末行已是今天 → 用 `bar` 覆盖该行；否则追加今天一行。返回新 df（不改入参）。
  - `bar` 为 None/空 → 原样返回 df（纯历史，降级）。

依赖：`akshare_gateway.akshare_gw`、pandas。可独立单测（构造 df + 假 bar）。

### 4.2 chanlun 盘中重算（改 `chanlun_batch.py`）

- `_load(symbol, kind, limit, live_bars=None)`：`live_bars` 提供 `{code:bar}` 时，取完本地日K后用 `inject_today_bar` 注入今日 bar。
- `scan_codes(..., live_bars=None, db_path=None)`：透传 `live_bars`；`db_path` 覆盖输出库。
- 盘中入口（`chanlun_batch.py --intraday` 或 `CHANLUN_INTRADAY=1`）：先 `fetch_market_snapshot()`，写 `data/chanlun_signals_intraday.db`。
- **盘后 `chanlun_signals.db` 完全不动**（默认行为零变化）。

### 4.3 daily_watchlist 盘中模式（改 `daily_watchlist.py`）

`WL_INTRADAY=1` 时：
- `_load` 注入今日实时 bar（先在 main 取一次 `fetch_market_snapshot()` 传入，避免逐只请求）。
- 信号来源 = 盘中库 `chanlun_signals_intraday.db` 今日新信号 **∪** 盘后库 `chanlun_signals.db`（取最新 `scan_date` 那批）中 **signal_date 距今 ≤2 个交易日**（即 entry_status 仍可能为 可入/尾窗 的窗内信号）。按 `(code, signal_date)` 去重，盘中库优先。
- `scan_date` = 今天；`close_scan` = 今日实时价 → `entry_status` 反映此刻状态。
- 输出：`watchlist_history/intraday/每日自选股清单_{date}_{HHMM}.csv` + 盘中 latest 指针文件（原子替换，供前台读）。

默认（无 `WL_INTRADAY`）行为完全不变 = 盘后管线。

### 4.4 高亮变化

- 读"本交易日上一轮"盘中快照（同 date 下最近 HHMM 的 CSV）。
- 比对（按 code）：
  - 上轮不存在 → `🆕新出`
  - 可入状态变好（尾窗/已过窗 → 可入，或首次出现即可入）→ `⤴变动`
- 高亮行置顶，其余维持原排序键。新增列 `变化标记`。
- 本交易日首轮（无上轮）：全部不打标，正常全量。

### 4.5 推送（新建 `ops/intraday_watchlist_and_mail.sh`）

参照 `ops/daily_watchlist_and_mail.sh`：
1. 交易日门控（复用仓库已有交易日判断）。非交易日退出 0。
2. `docker exec ... CHANLUN_INTRADAY=1 python3 chanlun_batch.py`（盘中重算）。
3. `docker exec ... WL_INTRADAY=1 python3 daily_watchlist.py`（盘中清单）。
4. `export_watchlist_md.py / export_watchlist_xlsx.py` 加 `--intraday`（读盘中 latest，文件名带 `_{HHMM}`）。
5. `push_watchlist.py --intraday --slot {HH:MM}`：主题 `🛡️盘中选股 {date} {HH:MM} 时段`，正文最上"本时段新增/变动"区，下接全量可入清单；附 md/xlsx；收件人 `.env EMAIL_TO`。
6. 各步独立；重算/清单失败 → 用上一轮盘中清单照常发（参照盘后脚本）。

### 4.6 调度（宿主 crontab）

```
47 9  * * 1-5 /home/tdxback/aiagents-stock/ops/intraday_watchlist_and_mail.sh 10:00 >> /home/tdxback/report/intraday_watchlist_mail.log 2>&1
47 10 * * 1-5 /home/tdxback/aiagents-stock/ops/intraday_watchlist_and_mail.sh 11:00 >> ...
17 13 * * 1-5 /home/tdxback/aiagents-stock/ops/intraday_watchlist_and_mail.sh 13:30 >> ...
17 14 * * 1-5 /home/tdxback/aiagents-stock/ops/intraday_watchlist_and_mail.sh 14:30 >> ...
```
`1-5` 先粗筛工作日，脚本内再用交易日历精筛（排除节假日）。传入参数=目标时段标签（用于邮件主题/文件名）。

## 5. 错误处理

| 失败点 | 处理 |
|---|---|
| 实时快照取不到 | `inject_today_bar` 降级为纯历史；盘中管线退化为"只复核盘后已有买点"，不报错 |
| baostock 不通 | 既有 20s 超时 + `WL_SKIP_BAOSTOCK` 降级 A-only，不挂死 |
| 容器未起/重算失败 | cron 日志记错，沿用上一轮盘中清单照常发邮件 |
| 文件覆盖 | 各时段独立文件名；latest 指针原子替换 |

## 6. 测试

- 单测 `intraday_quote`：注入覆盖今日行 / 新增今日行 / 缺数据降级 三种。
- 单测 daily_watchlist 盘中 union 去重 + entry_status 实时价。
- AppTest 无头渲染盘中清单页（沿用既有方法）。
- 干跑：非交易日守卫退出 0；快照失败降级；与盘后库 union 正确。
- 回归：无 `WL_INTRADAY`/`CHANLUN_INTRADAY` 时盘后行为与现状逐字节一致。

## 7. 上线前置（运维）

- 拉起容器（当前 `docker exec` 取不到 agentsstock1）。
- 重建镜像：把**已存在但未提交**的🛡️稳定选股导航（`app.py` nav_stable / show_stable）、盘后 `chanlun_schedule.sh` 顺带跑 watchlist、`扫描日价` 列、`requirements.txt` baostock 一并纳入本次提交并随镜像生效。
- 装宿主 crontab 4 条 + 建 `report/intraday_watchlist_mail.log`。

## 8. 非目标（YAGNI）

- 不做盘中 1min/分时级 K 线缠论（仍是日线级，今日 bar 为当下快照的"未收盘日 bar"，信号为**临时态**会随价格变动，邮件需注明）。
- 不改前台为实时刷新（前台读盘中 latest CSV 即可）。
- 不引入新推送渠道（复用邮件）。
