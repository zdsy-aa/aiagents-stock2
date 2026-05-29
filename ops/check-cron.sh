#!/usr/bin/env bash
# check.sh 的定时调度包装：由 crontab 调用。
#   - 每次把完整报告覆盖写到 check-latest.log(随时可查最新一次)
#   - 仅当检核出现“失败项”(check.sh 退出码=2)时，追加一行到 check-fail.log
#   - 告警(退出码1，如 build cache 偏大)视为正常，不刷告警日志
LOG_LATEST="/home/tdxback/check-latest.log"
LOG_FAIL="/home/tdxback/check-fail.log"
HOSTN="$(hostname)"

bash /home/tdxback/check.sh --no-color > "$LOG_LATEST" 2>&1
ec=$?
ts=$(date '+%Y-%m-%d %H:%M:%S')

# 失败(退出码2)追加告警日志
if [ "$ec" -ge 2 ]; then
  summary=$(grep -E '通过|失败|故障' "$LOG_LATEST" | tail -2 | tr '\n' ' ')
  echo "$ts exit=$ec | $summary(详见 $LOG_LATEST)" >> "$LOG_FAIL"
fi

# 每次都把完整报告发邮件(用户选择)；主题带状态标识便于一眼区分
case "$ec" in
  0) tag="✅正常" ;;
  1) tag="▲告警" ;;
  *) tag="✘失败" ;;
esac
python3 /home/tdxback/send_mail.py "[服务器检核 $tag] $HOSTN $ts" "$LOG_LATEST" \
  >> /home/tdxback/check-mail.log 2>&1 || echo "$ts 发信失败(见 check-mail.log)" >> /home/tdxback/check-mail.log

exit "$ec"
