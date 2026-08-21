"""pg-sync-updater 调度循环：每天 21:00 调 run_sync（容器 TZ=Asia/Shanghai）。"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import schedule
from sync_daily import run_sync

SYNC_AT = os.getenv("PG_SYNC_AT", "21:00")

def job():
    print(f"[pg-sync] 开始增量同步 @ {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    try:
        stats = run_sync()
        total = sum(stats.values())
        print(f"[pg-sync] 完成，新增 {total} 行", flush=True)
    except Exception as e:
        print(f"[pg-sync] 失败: {e}", flush=True)

schedule.every().day.at(SYNC_AT).do(job)
print(f"[pg-sync] 调度已就绪，每天 {SYNC_AT} 运行", flush=True)
while True:
    schedule.run_pending()
    time.sleep(60)
