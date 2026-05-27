#!/bin/sh
# 触发 tdx-api 增量 pull-kline，轮询至结束，并做「覆盖校验 + 重拉漏票」兜底，
# 结果追加写到 /data/update.log。由 crond 每天 18:00 调用，也可手动
# `docker exec kline-updater /update.sh` 跑一次。busybox sh 兼容；依赖 curl + jq + sqlite3。
#
# 背景：pull-kline 引擎层本身增量（按每表已存最后一条 Date 续拉）。但其 Run() 对每只票
# 的 pull 出错只 logs.Err 后 return、任务仍返回 success——所以 "success" 不保证全票更新成功
# （实测热门票常因 SQLite 写锁冲突被静默跳过）。故全量跑后再扫一遍本地库，把落后的票用
# 低并发(limit=1)重拉补回。
set -u

API="http://tdx-stock-web:8080"
LOG="/data/update.log"
KLINE_DIR="/data/database/kline"
WORKDAY_DB="/data/database/workday.db"
TABLES='["day","30minute","5minute"]'
LIMIT=10               # 全量并发；补漏阶段固定用 limit=1
POLL_INTERVAL=30       # 轮询间隔（秒）
POLL_MAX=60            # 轮询上限：60 × 30s = 30 分钟超时，防卡死

log() {
    # $1=LEVEL  $2=message —— 行格式：YYYY-MM-DD HH:MM:SS [LEVEL] message
    echo "$(date '+%Y-%m-%d %H:%M:%S') [$1] $2" >> "$LOG"
}

# 触发一次 pull-kline 并轮询至结束。
#   $1 = 请求体 JSON；$2 = 日志标签
# 成功 return 0；失败/取消/超时 return 1（均已写日志）。
trigger_and_wait() {
    body="$1"; label="$2"
    resp=$(curl -s -m 30 -X POST "$API/api/tasks/pull-kline" \
        -H 'Content-Type: application/json' -d "$body")
    code=$(echo "$resp" | jq -r '.code // empty' 2>/dev/null)
    task_id=$(echo "$resp" | jq -r '.data.task_id // empty' 2>/dev/null)
    if [ "$code" != "0" ] || [ -z "$task_id" ]; then
        log ERROR "[$label] 触发失败（tdx-api 未就绪或网络问题，无 task_id），响应：$resp"
        return 1
    fi
    log INFO "[$label] 任务已创建 task_id=$task_id，开始轮询"
    i=0
    while [ "$i" -lt "$POLL_MAX" ]; do
        i=$((i + 1))
        sleep "$POLL_INTERVAL"
        tresp=$(curl -s -m 30 "$API/api/tasks/$task_id")
        status=$(echo "$tresp" | jq -r '.data.status // empty' 2>/dev/null)
        case "$status" in
            success)
                log INFO "[$label] 任务成功 task_id=$task_id（轮询 $i 次）"
                return 0 ;;
            failed)
                err=$(echo "$tresp" | jq -r '.data.error // "未知错误"' 2>/dev/null)
                log ERROR "[$label] 任务失败 task_id=$task_id error=$err"
                return 1 ;;
            cancelled)
                log WARN "[$label] 任务被取消 task_id=$task_id"
                return 1 ;;
            running|pending) : ;;            # 继续轮询
            *) log WARN "[$label] 轮询第 $i 次拿到异常/空状态 status='$status'，响应：$tresp" ;;
        esac
    done
    log WARN "[$label] 轮询超时（${POLL_MAX}×${POLL_INTERVAL}s）task_id=$task_id 仍未结束"
    return 1
}

# 取某库 DayKline 最新 bar 的日期(YYYYMMDD, CST)；无表/读不到则 echo 空。
db_latest_day() {
    sqlite3 -cmd ".timeout 3000" "$1" \
        "SELECT strftime('%Y%m%d', MAX(Date)+28800, 'unixepoch') FROM DayKline;" 2>/dev/null
}

# 判断 $1(日期串,可空) 是否落后于目标 $2。空 或 数值小于目标 → 落后(return 0)。
is_behind() {
    [ -z "$1" ] && return 0
    [ "$1" -lt "$2" ] 2>/dev/null && return 0
    return 1
}

start_ts=$(date +%s)
log INFO "增量更新开始：全市场 pull-kline tables=$TABLES limit=$LIMIT"

# ── 1. 全市场增量 ──────────────────────────────────────────────
if ! trigger_and_wait "{\"tables\":$TABLES,\"limit\":$LIMIT}" "全量"; then
    log ERROR "全市场增量未成功，跳过覆盖校验，本次结束"
    exit 1
fi

# ── 2. 覆盖校验：算目标交易日 ─────────────────────────────────
today=$(date +%Y%m%d)
target=$(sqlite3 -cmd ".timeout 3000" "$WORKDAY_DB" \
    "SELECT MAX(Date) FROM workday WHERE Date <= '$today';" 2>/dev/null)
if [ -z "$target" ]; then
    elapsed=$(( $(date +%s) - start_ts ))
    log WARN "无法从 workday.db 取目标交易日，跳过覆盖校验。总耗时 ${elapsed}s"
    exit 0
fi
log INFO "目标交易日=$target，扫描本地库覆盖情况…"

# ── 3. 扫描漏票（DayKline 最新 < target，或无表/读不到）──────────
stragglers=""; n_behind=0
for f in "$KLINE_DIR"/*.db; do
    [ -e "$f" ] || continue
    code=$(basename "$f" .db)
    if is_behind "$(db_latest_day "$f")" "$target"; then
        stragglers="$stragglers $code"
        n_behind=$((n_behind + 1))
    fi
done

if [ "$n_behind" -eq 0 ]; then
    elapsed=$(( $(date +%s) - start_ts ))
    log INFO "覆盖校验：全部已到 $target，无漏票。总耗时 ${elapsed}s"
    exit 0
fi
log INFO "覆盖校验：$n_behind 只落后于 $target，低并发(limit=1)重拉补漏…"

# ── 4. 重拉漏票（limit=1 避开并发写锁冲突）──────────────────────
codes_json=$(echo $stragglers | tr ' ' '\n' | jq -R . 2>/dev/null | jq -s -c . 2>/dev/null)
trigger_and_wait "{\"codes\":$codes_json,\"tables\":$TABLES,\"limit\":1}" "补漏"

# ── 5. 复扫漏票集，报告仍落后的（停牌/退市/长期无新数据会留底）──
still=0
for code in $stragglers; do
    if is_behind "$(db_latest_day "$KLINE_DIR/$code.db")" "$target"; then
        still=$((still + 1))
    fi
done
elapsed=$(( $(date +%s) - start_ts ))
recovered=$((n_behind - still))
if [ "$still" -eq 0 ]; then
    log INFO "补漏完成：$n_behind 只全部补回到 $target。总耗时 ${elapsed}s"
else
    log WARN "补漏：$recovered/$n_behind 只已补回，仍有 $still 只落后于 $target（多为停牌/退市/长期无新数据），待次日。总耗时 ${elapsed}s"
fi
exit 0
