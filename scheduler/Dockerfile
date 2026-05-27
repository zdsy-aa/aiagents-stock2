# kline-updater：轻量 sidecar 调度容器
# 每天 18:00 触发 tdx-api 增量 pull-kline，把本地 K 线补到最新交易日
# 不改 Go 代码、不改主应用镜像，详见 docs/superpowers/specs/2026-05-26-kline-incremental-auto-update-design.md
FROM alpine:3.20

# curl 发 HTTP；jq 解析任务接口 JSON；sqlite 读本地K线库做覆盖校验；tzdata 让 crond/date 走 Asia/Shanghai
RUN apk add --no-cache curl jq sqlite tzdata

COPY update.sh /update.sh
COPY crontab /var/spool/cron/crontabs/root
RUN chmod +x /update.sh && chmod 600 /var/spool/cron/crontabs/root

# 前台运行 busybox crond，日志级别 8（输出到容器 stdout，可 docker logs 看调度）
CMD ["crond", "-f", "-l", "8"]
