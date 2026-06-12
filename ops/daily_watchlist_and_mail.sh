#!/bin/bash
# 每天 21:00：刷新每日稳定选股清单 → 生成 Markdown + Excel 文档 → 发"文档式"邮件(正文HTML文档+md+xlsx附件)。
# 注意：必须晚于 chanlun-updater 的 20:00 缠论重算，否则读到的 MAX(scan_date) 是昨天，会发昨天数据（曾因 19:00 早于重算踩坑）。
# crontab(宿主机): 0 21 * * * /home/tdxback/aiagents-stock/ops/daily_watchlist_and_mail.sh >> /home/tdxback/report/daily_watchlist_mail.log 2>&1
# 说明：刷新在容器内跑(含核心B尖刺金叉,需baostock;不通会超时降级A-only,不挂死)。各步独立,刷新失败仍会用上次清单发文档。
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"   # cron 环境 PATH 兜底
OPS="/home/tdxback/aiagents-stock/ops"
REPORT="/home/tdxback/report"
TS=$(date +%F)   # YYYY-MM-DD，与邮件附件名 每日稳定选股_<扫描日期> 同格式
echo "[$(date '+%F %T')] === 每日清单刷新+发送 开始 ==="

# 1) 刷新清单(容器内)
if docker exec -w /app agentsstock1 python3 -u /app/data/profit_mining/daily_watchlist.py; then
  echo "[$(date '+%F %T')] 清单刷新完成"
else
  echo "[$(date '+%F %T')] ⚠ 清单刷新失败(用上次清单继续)"
fi

# 2) 生成 Markdown + Excel 文档到 report(带当日日期)
python3 "$OPS/export_watchlist_md.py" --out "$REPORT/每日稳定选股_${TS}.md" \
  && echo "[$(date '+%F %T')] Markdown 已生成 $REPORT/每日稳定选股_${TS}.md"
python3 "$OPS/export_watchlist_xlsx.py" --out "$REPORT/每日稳定选股_${TS}.xlsx" \
  && echo "[$(date '+%F %T')] Excel 已生成 $REPORT/每日稳定选股_${TS}.xlsx"

# 3) 发邮件(正文HTML文档 + md附件,收件人取 .env EMAIL_TO)
if python3 "$OPS/push_watchlist.py"; then
  echo "[$(date '+%F %T')] 邮件已发送"
else
  echo "[$(date '+%F %T')] ⚠ 邮件发送失败"
fi
echo "[$(date '+%F %T')] === 完成 ==="
