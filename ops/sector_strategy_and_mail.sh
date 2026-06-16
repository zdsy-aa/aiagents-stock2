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
