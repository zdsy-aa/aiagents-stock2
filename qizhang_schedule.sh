#!/bin/sh
# qizhang_schedule.sh —— 起涨预测 paper-tracking 日批调度（sidecar qizhang-updater 用）。
# 复用主应用镜像；每天 20:30（CST，在 kline-updater 18:00、chanlun-updater 20:00 之后）跑
# qizhang_batch.py：重训 GBDT(扩展窗)→今日 top10 候选→realized 回填→写 data/qizhang_picks.db，
# 供「📈 起涨预测」页只读。busybox/GNU sh 兼容；时间用 GNU date（Debian 基础镜像）。
# 手动跑一次： docker exec qizhang-updater python3 /app/qizhang_batch.py
set -u
RUN_AT="${QIZHANG_RUN_AT:-20:30}"
LOG="/app/data/qizhang_update.log"
LOCK="/app/data/qizhang_update.lock"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [$1] $2" | tee -a "$LOG"; }

log INFO "qizhang-updater 启动：每日 ${RUN_AT} 重训打分并产候选（依赖最新本地K线）"
while true; do
    now=$(date +%s)
    target=$(date -d "today ${RUN_AT}" +%s 2>/dev/null)
    if [ "$now" -ge "$target" ]; then
        target=$(date -d "tomorrow ${RUN_AT}" +%s)
    fi
    log INFO "下次重算：$(date -d "@${target}" '+%Y-%m-%d %H:%M') CST（约 $(( (target - now) / 60 )) 分钟后）"
    sleep "$(( target - now ))"

    dow=$(date +%u)   # 1=周一 .. 7=周日
    if [ "$dow" -ge 6 ]; then
        log INFO "周末（dow=${dow}），跳过本次"
        continue
    fi
    log INFO "开始起涨日批 ..."
    if flock -n "$LOCK" python3 /app/qizhang_batch.py >>"$LOG" 2>&1; then
        log INFO "起涨日批完成"
    else
        log WARN "起涨日批失败或已有实例在跑（flock）"
    fi
done
