#!/bin/sh
# chanlun_schedule.sh —— 缠论买点信号每日自动重算 sidecar。
# 复用主应用镜像 aiagents-stock-app（含 python 环境、缠论模块、akshare 网关），
# 默认每天 20:00（CST）运行，即在 kline-updater 18:00 增量更新本地K线完成之后，
# 跑 chanlun_batch 把全市场近 7 交易日买点重算落库到 data/chanlun_signals.db，
# 供「缠论选股」页只读。busybox/GNU sh 兼容；时间用 GNU date（Debian 基础镜像）。
# 立即手动跑一次： docker exec chanlun-updater python3 /app/chanlun_batch.py
set -u

RUN_AT="${CHANLUN_RUN_AT:-20:00}"
LOG="/app/data/chanlun_update.log"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [$1] $2" | tee -a "$LOG"; }

log INFO "chanlun-updater 启动：每日 ${RUN_AT} 重算缠论买点信号（依赖最新本地K线）"
while true; do
    now=$(date +%s)
    target=$(date -d "today ${RUN_AT}" +%s 2>/dev/null)
    if [ -z "${target:-}" ] || [ "$target" -le "$now" ]; then
        target=$(date -d "tomorrow ${RUN_AT}" +%s)
    fi
    log INFO "下次重算：$(date -d "@${target}" '+%Y-%m-%d %H:%M') CST（约 $(( (target - now) / 60 )) 分钟后）"
    sleep "$(( target - now ))"

    log INFO "开始重算缠论信号 …"
    if python3 /app/chanlun_batch.py >>"$LOG" 2>&1; then
        log INFO "缠论信号重算完成"
    else
        log ERROR "缠论信号重算失败 exit=$?，等待下一周期重试"
    fi
done
