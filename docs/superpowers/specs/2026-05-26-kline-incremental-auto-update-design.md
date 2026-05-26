# 每天 18:00 本地 K 线增量自动更新 — 设计

- 日期：2026-05-26
- 项目：aiagents-stock（route B 本地数据源）
- 状态：已确认，待写实现计划

## 背景与目标

route B 本地数据源已上线：tdx-api 的 `pull-kline` 任务把全 A 股的日线/30 分/5 分 K 线落地到
`tdx-data/database/kline/<6位代码>.db`，网关 `akshare_gateway.py` 的 `LocalDBClient`（降级链第 0 级）读它。

**目标**：每天 18:00 自动把本地 K 线补到最新交易日，无需人工触发。

**关键事实**：`pull-kline` 在引擎层（`tdx-api/extend/pull-kline.go`）**本身就是增量的**——
`Run()` 先取每只票每张表已存的最后一条 `Date`，再 `pull(code, lastDate, ...)`，停止条件为
「拉到 `Date <= lastDate` 就停」，插入前删 `Date >= 最新bar` 再重插（覆盖未收盘的当日 bar）。
因此**不需要写任何增量逻辑、不需要改 Go 代码**，本需求 = 「加一个每天 18:00 触发该 HTTP 任务的调度器」。

`POST /api/tasks/pull-kline` 为异步接口，立即返回 `data.task_id`，后台执行；
`GET /api/tasks/<id>` 返回任务状态。响应统一封装 `{"code":0,"message":"success","data":{...}}`，
任务 `status` 取值：`pending | running | success | failed | cancelled`。

## 架构概览

在 `docker-compose.yml` 新增一个轻量 **sidecar 调度容器** `kline-updater`，
与 `tdx-stock-web` 同处 `agentsstock-network`。容器内跑 busybox `crond`，
每天 18:00 走内网 `http://tdx-stock-web:8080` 触发增量 `pull-kline`，
轮询任务状态，结果追加写到宿主机挂载的日志文件。

不改 Go 代码，不改主应用镜像。

## 新增组件（独立目录 `scheduler/`）

| 文件 | 职责 |
|------|------|
| `scheduler/Dockerfile` | `FROM alpine` + `apk add --no-cache curl tzdata`；`COPY` crontab 与 update.sh；`CMD ["crond","-f","-l","8"]` |
| `scheduler/crontab` | 一行：`0 18 * * * /update.sh >> /data/cron.out 2>&1`（每天 18:00，容器 TZ=Asia/Shanghai） |
| `scheduler/update.sh` | 触发 + 轮询 + 写日志的核心脚本（`/bin/sh`，busybox 兼容） |

## docker-compose 新增服务

```yaml
  kline-updater:
    build: ./scheduler
    container_name: kline-updater
    environment:
      - TZ=Asia/Shanghai
    volumes:
      - ./tdx-data:/data          # 写 /data/update.log（宿主机 ./tdx-data/update.log）
    restart: unless-stopped
    depends_on:
      tdx-stock-web:
        condition: service_started
    networks:
      - agentsstock-network
```

## 数据流（`update.sh` 逻辑）

1. `POST http://tdx-stock-web:8080/api/tasks/pull-kline`，
   body `{"tables":["day","30minute","5minute"],"limit":10}`，解析 `data.task_id`。
2. 循环每 30s `GET /api/tasks/<id>`，读 `data.status`。
3. `status=success` → 记成功行（起止时间、task_id、耗时）；
   `status=failed` → 记失败行 + `data.error`；
   `status=cancelled` → 记取消行。
4. 全部追加到 `/data/update.log`，行格式：`YYYY-MM-DD HH:MM:SS [LEVEL] message`。

参数固定（与首次全量下载一致）：`tables=["day","30minute","5minute"]`、`limit=10`。
不传 `start_date`，纯靠引擎 lastDate 增量。

## 调度频率

`0 18 * * *` —— 每天 18:00 都跑（周末/节假日空转无害：增量拉不到新数据即无插入）。
A 股 15:00 收盘，18:00 时 TDX 当日数据已结算，安全。

## 错误处理

- POST 拿不到 `task_id`（tdx-api 未就绪/网络问题）→ 记 ERROR，本次退出，等次日；`crond` 不受影响。
- 轮询设上限（60 次 × 30s = 30 分钟超时）防卡死，超时记 WARN 退出。
- 容器 `restart: unless-stopped` + 随 docker 开机自启，宿主机重启后照常。
- 日志只追加不轮转（v1 YAGNI）；体量小，后续需要再加 logrotate。

## 测试 / 验证

1. `docker compose build kline-updater && docker compose up -d kline-updater`。
2. 手动 `docker exec kline-updater /update.sh` 跑一次：
   - 确认 `./tdx-data/update.log` 出现成功记录；
   - 抽查本地库 `database/kline/<code>.db` 的 `DayKline` 最后日期已推进到最新交易日。
3. `docker exec kline-updater date` 确认时区为 Asia/Shanghai；`docker exec kline-updater crontab -l` 确认 cron 已装。
4. `docker compose up -d` 后其余容器（agentsstock1 / tdx-stock-web / aktools）仍健康，互不影响。

## 不做（YAGNI）

- 失败推送告警（接现有通知渠道）——本期不做，仅写日志文件。
- 只在交易日跑（`1-5` + 节假日日历）——本期每天跑，空转无害。
- 日志轮转、增量统计指标。
- 改 Go 引擎 / 主应用镜像。
