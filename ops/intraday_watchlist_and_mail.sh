#!/bin/bash
# 盘中稳定选股+推送：宿主 crontab 在 09:47/10:47/13:17/14:17 提前~13min 触发。
# 用法: intraday_watchlist_and_mail.sh <时段标签如 10:00>
# 流程: 交易日门控 → 缠论盘中重算(独立库) → daily_watchlist 盘中清单(实时价+高亮) → 发邮件。
# crontab(宿主): 47 9 * * 1-5 .../intraday_watchlist_and_mail.sh 10:00 >> /home/tdxback/report/intraday_watchlist_mail.log 2>&1
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
SLOT="${1:-$(date +%H:%M)}"
HHMM=$(echo "$SLOT" | tr -d ':')
OPS="/home/tdxback/aiagents-stock/ops"
INTRA_LATEST="/app/data/profit_mining/watchlist_history/intraday/每日自选股清单_latest.csv"

# -1) 并发锁(已定)：抢不到说明上一轮还在跑 → 直接退出，不与上一轮叠跑抢资源
exec 9>/tmp/intraday_watchlist.lock
if ! flock -n 9; then
  echo "[$(date '+%F %T')] 上一轮仍在运行(未获锁)，跳过 slot=$SLOT"; exit 0
fi

echo "[$(date '+%F %T')] === 盘中选股 $SLOT 开始 ==="

# 0) 交易日门控(容器内判，复用 intraday_quote.is_cn_trading_day)
if ! docker exec -w /app/data/profit_mining agentsstock1 python3 -c \
     "import intraday_quote as IQ,sys; sys.exit(0 if IQ.is_cn_trading_day() else 1)"; then
  echo "[$(date '+%F %T')] 非交易日，跳过"; exit 0
fi

# 1) 缠论盘中重算(写独立库;失败仅用盘后库复核)
if docker exec -w /app -e CHANLUN_INTRADAY=1 agentsstock1 python3 -u /app/chanlun_batch.py; then
  echo "[$(date '+%F %T')] 缠论盘中重算完成"
else
  echo "[$(date '+%F %T')] ⚠ 缠论盘中重算失败(仅复核盘后已有买点)"
fi

# 2) 盘中清单(实时价+union+高亮)
if docker exec -w /app -e WL_INTRADAY=1 -e WL_SLOT="$HHMM" agentsstock1 \
     python3 -u /app/data/profit_mining/daily_watchlist.py; then
  echo "[$(date '+%F %T')] 盘中清单已更新"
else
  echo "[$(date '+%F %T')] ⚠ 盘中清单生成失败(用上一轮清单继续发)"
fi

# 3) 发邮件(读盘中 latest，主题带时段)
if docker exec -w /app agentsstock1 python3 /app/ops/push_watchlist.py \
     --csv "$INTRA_LATEST" --slot "$SLOT"; then
  echo "[$(date '+%F %T')] 邮件已发送"
else
  echo "[$(date '+%F %T')] ⚠ 邮件发送失败"
fi
echo "[$(date '+%F %T')] === 盘中选股 $SLOT 完成 ==="
