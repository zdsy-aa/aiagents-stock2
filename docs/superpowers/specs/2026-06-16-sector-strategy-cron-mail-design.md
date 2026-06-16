# 智策板块定时分析+邮件 改主机 crontab（方案①）设计

2026-06-16。智策板块的定时分析+发邮件原靠 **Streamlit 进程内 `schedule` 线程**
（`sector_strategy_scheduler`），只能在 UI「⏰ 定时分析设置」手动开，且是**内存态、容器/Streamlit 重启即丢**。
2026-06-14 重建容器后就再没跑过（`sector_strategy.db` 最后落库停在 06-13），表现为"智策发不出邮件"。

已诊断确认**邮件链路本身完好**：notification_service 配置完整（163/465/账号密码齐）、`send_email` 的
465→SMTP_SSL 逻辑正确、容器→smtp.163.com:465 连通、容器内手动 `send_email` 返回 True。
根因是**定时分析根本没在跑**（触发机制不可靠），而非发送失败。

本方案把触发从"Streamlit 进程内 schedule 线程"改为"**主机 crontab 定时 → docker exec 调容器内现成分析一条龙**"，
彻底脱离 Streamlit，重启不丢、无需 UI 手动开。

## 目标
- 每天 **17:30（盘后）、仅工作日（周一至周五）** 自动运行智策板块分析并发邮件。
- **零新分析代码**：复用容器内现成的 `sector_strategy_scheduler._run_analysis()`
  （内部已是 `SectorStrategyDataFetcher().get_all_sector_data()` → `SectorStrategyEngine().run_comprehensive_analysis()`
  → `_send_analysis_notification()` 发邮件 的完整一条龙）。
- 触发可靠：宿主机 cron 触发、容器内执行，**容器/Streamlit 重启不影响**。

## 非目标（YAGNI）
- 不改 `notification_service` / `sector_strategy_engine` / `sector_strategy_data` / DB / 分析逻辑。
- 不重建镜像（docker exec 调用容器内已有模块即可）。
- 不接节假日日历（用 crontab `1-5`，与现有盘中邮件一致；节假日最多发一份基于上一交易日数据的报告，无害）。
- 不删除/改动 UI 的「⏰ 定时分析设置」（保留原样，用户以后改用 cron）。
- 不做单元测试（重活 + 发真邮件，按既有 ops 邮件脚本惯例靠手动跑一次验证）。

## 架构（对齐现有 `ops/daily_watchlist_and_mail.sh` 模式）
```
host crontab:  30 17 * * 1-5  /home/tdxback/aiagents-stock/ops/sector_strategy_and_mail.sh \
                                  >> /home/tdxback/report/sector_strategy_mail.log 2>&1
   └─ ops/sector_strategy_and_mail.sh (新, bash):
        - export PATH 兜底(cron 环境)
        - 时间戳日志(开始/完成)
        - docker exec -w /app agentsstock1 python3 -c \
            "from sector_strategy_scheduler import sector_strategy_scheduler as s; s._run_analysis()"
        - 据退出码记 "完成/失败"
```

## 组件
- **新增 `ops/sector_strategy_and_mail.sh`**（宿主机脚本，bash，`#!/bin/bash`）：
  - `export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"`（cron PATH 兜底，与现有脚本一致）。
  - 打印开始时间戳日志。
  - 调 `docker exec -w /app agentsstock1 python3 -c "from sector_strategy_scheduler import sector_strategy_scheduler as s; s._run_analysis()"`。
  - 据 docker exec 退出码打印"智策分析+邮件完成 / ⚠ 失败"。
- **新增 crontab 条目**（宿主机 `crontab -e`）：`30 17 * * 1-5 .../ops/sector_strategy_and_mail.sh >> /home/tdxback/report/sector_strategy_mail.log 2>&1`。
- **执行位**：`chmod +x` + `git update-index --chmod=+x`（提交为 100755），避免重蹈本周刚修的 Permission denied。

## 数据流 / 复用
- `_run_analysis()` 内部：取板块/概念/资金流/北向数据 → DeepSeek 综合研判 → 格式化邮件正文 →
  `notification_service.send_email(subject, body)` 发到 `.env` 的 `EMAIL_TO`。
- 依赖：容器 `agentsstock1` 在跑（常驻）、`.env`（API key + 邮件配置，已挂载）、DeepSeek API 可用、SMTP 可达（均已验证）。

## 错误处理 / 边界
- **分析/数据失败**：`_run_analysis` 内部捕获并调 `_send_error_notification` 发"失败通知邮件"，用户可感知。
- **docker exec 非零退出**：脚本记 "⚠ 失败" 到日志（不阻塞下次 cron）。
- **节假日**：`1-5` 不排除法定节假日；当天若市场休市，分析仍会产出（基于最近交易日数据），可接受。
- **重复发送风险**：若用户另在 UI 手动开了 schedule（另一进程），cron 与 UI 两条路径跨进程不互相去重，可能重复发。
  缓解：文档明确建议以后只用 cron、不再开 UI 定时；不强制改 UI。

## 验证（实施计划阶段执行）
- 手动跑一次 `bash ops/sector_strategy_and_mail.sh`：确认邮件送达 + 日志出现"完成" + 无 Python traceback。
- `crontab -l` 确认新条目已装。
- `git ls-files -s ops/sector_strategy_and_mail.sh` 确认 mode 为 100755。

## 影响面
- 宿主机：新增 1 个 ops 脚本 + 1 条 crontab + 1 个日志文件 `report/sector_strategy_mail.log`。
- 仓库：新增 `ops/sector_strategy_and_mail.sh`（develop on main，用户自行 push stock2）。
- 容器/镜像：**无改动、无需重建**。
