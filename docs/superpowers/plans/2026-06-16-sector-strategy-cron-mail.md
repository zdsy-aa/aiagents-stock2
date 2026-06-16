# 智策定时分析+邮件 改主机 crontab（方案①）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把智策板块定时分析+邮件从 Streamlit 内存态 scheduler 改为主机 crontab 触发，重启不丢、无需 UI 手动开。

**Architecture:** 新增宿主机 bash 脚本 `ops/sector_strategy_and_mail.sh`，用 `docker exec` 调容器内现成的 `sector_strategy_scheduler._run_analysis()`（fetch→AI分析→发邮件一条龙），host crontab 每工作日 17:30 触发。零新分析代码、不重建镜像。

**Tech Stack:** bash、host crontab、docker exec、复用 `sector_strategy_scheduler`（Python，容器内）。

**关键约束（已核对）：**
- `sector_strategy_scheduler._run_analysis()` 存在、**无参**、是 fetch(`get_all_sector_data`)→`run_comprehensive_analysis`→`_send_analysis_notification`(发邮件) 完整一条龙；失败内部会发"失败通知邮件"。单例：`from sector_strategy_scheduler import sector_strategy_scheduler`。
- 容器 `agentsstock1` 常驻；`.env`（DeepSeek key + 邮件配置）已挂载；SMTP 已验证可达；`send_email` 已验证可发。
- develop on `main`；用户自行 push stock2。这是 shell/ops 任务，**无单元测试**（与现有 `ops/*_and_mail.sh` 一致，靠手动跑一次验证）。
- **执行位**必须 `chmod +x` + `git update-index --chmod=+x`（100755），否则重蹈本周刚修的 cron `Permission denied`。

---

## File Structure

| 文件 | 责任 |
|------|------|
| `ops/sector_strategy_and_mail.sh`（新） | 宿主机入口：PATH 兜底 + 日志 + `docker exec agentsstock1` 调 `_run_analysis()` |
| 宿主机 crontab（改） | 加 `30 17 * * 1-5` 条目，日志重定向到 `report/sector_strategy_mail.log` |

---

## Task 1: 新增 ops/sector_strategy_and_mail.sh

**Files:**
- Create: `ops/sector_strategy_and_mail.sh`
- Reference（对齐风格，勿改）：`ops/daily_watchlist_and_mail.sh`

- [ ] **Step 1: 写脚本**

写入 `ops/sector_strategy_and_mail.sh`，内容：

```bash
#!/bin/bash
# 每工作日 17:30（盘后）：在容器内跑智策板块综合分析并发邮件（复用 sector_strategy_scheduler._run_analysis）。
# 改主机 crontab 触发（脱离 Streamlit 内存态 scheduler，重启不丢、无需 UI 手动开）。
# crontab(宿主机): 30 17 * * 1-5 /home/tdxback/aiagents-stock/ops/sector_strategy_and_mail.sh >> /home/tdxback/report/sector_strategy_mail.log 2>&1
# 说明：_run_analysis 内部 fetch→AI研判→发邮件一条龙；数据/分析失败会自动发"失败通知邮件"。
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"   # cron 环境 PATH 兜底
echo "[$(date '+%F %T')] === 智策定时分析+邮件 开始 ==="

if docker exec -w /app agentsstock1 python3 -u -c "from sector_strategy_scheduler import sector_strategy_scheduler as s; s._run_analysis()"; then
  echo "[$(date '+%F %T')] === 智策分析+邮件 完成 ==="
else
  echo "[$(date '+%F %T')] ⚠ 智策分析+邮件 失败(docker exec 非零退出)"
fi
```

- [ ] **Step 2: 校验 bash 语法**

Run: `bash -n ops/sector_strategy_and_mail.sh && echo "bash syntax OK"`
Expected: `bash syntax OK`

- [ ] **Step 3: 赋可执行位 + 让 git 跟踪 100755**

Run:
```bash
chmod +x ops/sector_strategy_and_mail.sh
git add ops/sector_strategy_and_mail.sh
git update-index --chmod=+x ops/sector_strategy_and_mail.sh
git ls-files -s ops/sector_strategy_and_mail.sh
```
Expected: 输出以 `100755` 开头（可执行位已被 git 跟踪）。

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(ops): 智策定时分析+邮件脚本(主机cron,docker exec调_run_analysis)

脱离 Streamlit 内存态 scheduler;复用 sector_strategy_scheduler._run_analysis 一条龙;
脚本 100755 防 cron Permission denied。

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: 端到端手动验证（确认邮件送达）

**Files:** 无（运行验证）

本步会**真发一封智策邮件**到 `.env` 的 `EMAIL_TO`。这是计划验收，必须执行。

- [ ] **Step 1: 手动跑一次脚本**

Run: `bash /home/tdxback/aiagents-stock/ops/sector_strategy_and_mail.sh`
Expected: 末行出现 `=== 智策分析+邮件 完成 ===`；过程日志含智策数据获取/AI分析/`✓ 邮件发送成功`（来自 `_send_analysis_notification`）；无 Python traceback。
（分析含 DeepSeek 调用，耗时约 1–3 分钟，属正常。）

- [ ] **Step 2: 确认邮件链路成功（看日志关键行）**

在上一步输出里确认存在 `[智策定时] ✓ 邮件发送成功`（或 `[智策定时] ✓ 定时分析完成`）。
若出现 `✗ 邮件发送失败` 或 traceback：STOP，贴出错误（不要继续装 crontab）。

---

## Task 3: 安装宿主机 crontab 条目

**Files:** 无（宿主机 crontab）

- [ ] **Step 1: 确认条目尚未存在（避免重复）**

Run: `crontab -l 2>/dev/null | grep -F "ops/sector_strategy_and_mail.sh" || echo "未安装"`
Expected: `未安装`（若已存在则跳过 Step 2）。

- [ ] **Step 2: 追加 crontab 条目（17:30 工作日）**

Run:
```bash
( crontab -l 2>/dev/null; echo "30 17 * * 1-5 /home/tdxback/aiagents-stock/ops/sector_strategy_and_mail.sh >> /home/tdxback/report/sector_strategy_mail.log 2>&1" ) | crontab -
```

- [ ] **Step 3: 确认已装**

Run: `crontab -l | grep -F "ops/sector_strategy_and_mail.sh"`
Expected: 输出 `30 17 * * 1-5 /home/tdxback/aiagents-stock/ops/sector_strategy_and_mail.sh >> /home/tdxback/report/sector_strategy_mail.log 2>&1`

---

## Self-Review

**1. Spec 覆盖**
- 17:30 / 工作日(1-5) → Task 3 crontab `30 17 * * 1-5` ✅
- 复用 `_run_analysis()` 零新分析代码 → Task 1 docker exec 一行 ✅
- 不重建镜像 → 全程 docker exec 调容器内现有模块 ✅
- 执行位 100755 防 Permission denied → Task 1 Step 3 ✅
- 失败兜底（内部发告警邮件）→ 复用 `_run_analysis` 既有逻辑（spec 已述）✅
- 手动跑一次验证邮件送达 → Task 2 ✅
- 日志 `report/sector_strategy_mail.log` → Task 3 重定向 ✅

**2. Placeholder 扫描**：无 TBD/TODO；每步均有完整命令/脚本内容。

**3. 一致性**：脚本路径 `ops/sector_strategy_and_mail.sh`、容器名 `agentsstock1`、方法 `_run_analysis()`、crontab 表达式在 Task 1/2/3 中一致；与 spec 一致。

**无单元测试说明**：shell/ops 脚本，按既有 `ops/*_and_mail.sh` 惯例以手动端到端运行（Task 2）作为验证，符合 spec「不做单元测试」。
