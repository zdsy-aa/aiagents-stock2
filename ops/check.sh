#!/usr/bin/env bash
# =============================================================================
# check.sh —— 服务器 / aiagents-stock 项目 一键健康检核脚本
#   覆盖：系统状态、磁盘/内存、mihomo 代理、Docker 项目与各容器、
#         网口、网络连通性(内网/DNS/直连/代理出口)、网页端口与健康检查。
#   特点：只读、不需 root(需 root 的项会优雅跳过)、彩色输出、结尾汇总。
#   用法：bash /home/tdxback/check.sh            # 全量
#         bash /home/tdxback/check.sh --no-color # 关闭颜色(便于重定向到文件)
# =============================================================================
set -uo pipefail

# ---------- 配置(按本机实际)----------
PROJECT_DIR="/home/tdxback/aiagents-stock"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.yml"
# 期望存在的容器：名称|说明|本机健康检查URL(可空)
EXPECTED_CONTAINERS=(
  "agentsstock1|Streamlit 主网页(8503)|http://127.0.0.1:8503/_stcore/health"
  "tdx-stock-web|通达信行情API(8080)|http://127.0.0.1:8080/api/health"
  "aktools|AKTools 数据网关(8088)|http://127.0.0.1:8088/version"
  "kline-updater|本地K线日增量(18:00)|"
  "chanlun-updater|缠论信号日调度(20:00)|"
)
DISK_WARN=80          # 根分区使用率告警阈值(%)
DISK_CRIT=90          # 严重阈值(%)
MEM_WARN=90           # 内存使用率告警阈值(%)
PROXY_HTTP="http://127.0.0.1:7890"
PRUNE_LOG="/home/tdxback/docker-prune.log"

# ---------- 颜色与计数 ----------
if [[ "${1:-}" == "--no-color" ]] || [[ ! -t 1 ]]; then
  C_RED=""; C_GRN=""; C_YEL=""; C_CYN=""; C_BLD=""; C_RST=""
else
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YEL=$'\033[33m'
  C_CYN=$'\033[36m'; C_BLD=$'\033[1m'; C_RST=$'\033[0m'
fi
N_OK=0; N_WARN=0; N_FAIL=0

ok()   { echo -e "  ${C_GRN}✔${C_RST} $*"; N_OK=$((N_OK+1)); }
warn() { echo -e "  ${C_YEL}▲${C_RST} $*"; N_WARN=$((N_WARN+1)); }
fail() { echo -e "  ${C_RED}✘${C_RST} $*"; N_FAIL=$((N_FAIL+1)); }
info() { echo -e "  ${C_CYN}·${C_RST} $*"; }
hdr()  { echo -e "\n${C_BLD}${C_CYN}== $* ==${C_RST}"; }
have() { command -v "$1" >/dev/null 2>&1; }

echo -e "${C_BLD}┌─────────────────────────────────────────────────────────┐${C_RST}"
echo -e "${C_BLD}│  服务器健康检核  $(date '+%Y-%m-%d %H:%M:%S')  $(hostname)${C_RST}"
echo -e "${C_BLD}└─────────────────────────────────────────────────────────┘${C_RST}"

# =============================================================================
hdr "1. 系统概况"
# =============================================================================
info "内核     : $(uname -srm)"
if have lsb_release; then info "发行版   : $(lsb_release -ds 2>/dev/null)"; fi
info "运行时长 : $(uptime -p 2>/dev/null || uptime)"
info "系统时间 : $(date '+%Y-%m-%d %H:%M:%S %Z')"
# 负载与 CPU 核数对比
if [[ -r /proc/loadavg ]]; then
  read -r l1 l5 l15 _ < /proc/loadavg
  ncpu=$(nproc 2>/dev/null || echo 1)
  info "平均负载 : $l1 (1m) / $l5 (5m) / $l15 (15m)  | CPU 核数 $ncpu"
  # 用 awk 判断 1 分钟负载是否超过核数
  if awk "BEGIN{exit !($l1 > $ncpu)}"; then
    warn "1分钟负载 $l1 高于 CPU 核数 $ncpu(可能繁忙)"
  else
    ok "负载正常(低于核数)"
  fi
fi

# =============================================================================
hdr "2. 磁盘空间"
# =============================================================================
# 根分区使用率
root_use=$(df -P / | awk 'NR==2{gsub("%","",$5); print $5}')
root_line=$(df -hP / | awk 'NR==2{print $3"/"$2" 已用 "$5", 可用 "$4}')
info "根分区 / : $root_line"
if   [[ "$root_use" -ge "$DISK_CRIT" ]]; then fail "根分区使用率 ${root_use}% ≥ ${DISK_CRIT}%(严重!)"
elif [[ "$root_use" -ge "$DISK_WARN" ]]; then warn "根分区使用率 ${root_use}% ≥ ${DISK_WARN}%"
else ok "根分区使用率 ${root_use}%(健康)"; fi
# 其它已挂载的本地大分区
df -hPT 2>/dev/null | awk 'NR>1 && $2!~/tmpfs|overlay|squashfs|devtmpfs/ && $1!~/^\/dev\/loop/ {print "    "$1" ("$7") "$4" 可用 / 已用 "$6}' | grep -v "已用 ${root_use}%" 2>/dev/null | head -8
# Docker 占用(含 build cache —— 本机历史真凶)
if have docker && docker info >/dev/null 2>&1; then
  echo "  Docker 磁盘占用:"
  docker system df 2>/dev/null | sed 's/^/    /'
  bc_reclaim=$(docker system df 2>/dev/null | awk '/Build Cache/{print $NF}')
  [[ -n "${bc_reclaim:-}" ]] && info "Build Cache 可回收: $bc_reclaim(>20GB 建议 docker builder prune)"
fi
# 自动回收脚本与日志
if [[ -f /home/tdxback/docker-prune.sh ]]; then
  ok "docker-prune.sh 存在(crontab 周日03:00自动回收)"
  [[ -f "$PRUNE_LOG" ]] && info "最近回收日志: $(tail -n1 "$PRUNE_LOG" 2>/dev/null | cut -c1-80)"
else
  warn "未找到 /home/tdxback/docker-prune.sh(自动回收脚本)"
fi

# =============================================================================
hdr "3. 内存与交换"
# =============================================================================
if have free; then
  free -h | sed 's/^/  /'
  mem_use=$(free | awk '/^Mem:/{printf "%d", $3/$2*100}')
  if [[ "$mem_use" -ge "$MEM_WARN" ]]; then warn "内存使用率 ${mem_use}%(偏高)"; else ok "内存使用率 ${mem_use}%"; fi
fi

# =============================================================================
hdr "4. mihomo 代理"
# =============================================================================
# 4.1 systemd 服务
if have systemctl; then
  if systemctl is-active --quiet mihomo 2>/dev/null; then
    ok "systemd 服务 mihomo.service: active(running)"
  else
    st=$(systemctl is-active mihomo 2>/dev/null || echo unknown)
    fail "mihomo.service 非运行态: $st"
  fi
fi
# 4.2 进程
if pgrep -x mihomo >/dev/null 2>&1; then
  pid=$(pgrep -x mihomo | head -1)
  ok "mihomo 进程在跑 (PID $pid)"
else
  fail "未发现 mihomo 进程"
fi
# 4.3 监听端口(7890 http / 7891 socks / 9090 api)
for p in 7890 7891 9090; do
  if ss -tlnH 2>/dev/null | grep -q ":$p "; then ok "端口 $p 监听中"; else warn "端口 $p 未监听"; fi
done
# 4.4 经代理实际出网测试 + 代理出口公网IP
if have curl; then
  pcode=$(curl -sS -m 10 -x "$PROXY_HTTP" -o /dev/null -w '%{http_code}' https://www.gstatic.com/generate_204 2>/dev/null)
  if [[ "$pcode" == "204" || "$pcode" == "200" ]]; then
    ok "经 mihomo($PROXY_HTTP) 访问境外成功 (HTTP $pcode)"
    pxip=$(curl -sS -m 10 -x "$PROXY_HTTP" https://api.ipify.org 2>/dev/null)
    [[ -n "$pxip" ]] && info "代理出口公网IP: $pxip"
  else
    fail "经 mihomo 访问境外失败 (HTTP ${pcode:-超时}) —— 节点可能失效"
  fi
fi

# =============================================================================
hdr "5. Docker 与项目状态"
# =============================================================================
if ! have docker; then
  fail "未安装 docker"
elif ! docker info >/dev/null 2>&1; then
  fail "docker 守护进程不可用(daemon 未运行或无权限)"
else
  ok "docker 守护进程正常: $(docker version --format '{{.Server.Version}}' 2>/dev/null)"
  # compose 项目
  if [[ -f "$COMPOSE_FILE" ]]; then
    proj_state=$(docker compose -f "$COMPOSE_FILE" ls 2>/dev/null | awk 'NR==2{print $2}')
    info "compose 项目: $PROJECT_DIR  状态: ${proj_state:-未知}"
  else
    warn "未找到 $COMPOSE_FILE"
  fi
fi

# =============================================================================
hdr "6. 各容器状态"
# =============================================================================
if have docker && docker info >/dev/null 2>&1; then
  for entry in "${EXPECTED_CONTAINERS[@]}"; do
    cname="${entry%%|*}"; rest="${entry#*|}"; desc="${rest%%|*}"; hurl="${rest##*|}"
    if ! docker inspect "$cname" >/dev/null 2>&1; then
      fail "$cname [$desc] —— 容器不存在"
      continue
    fi
    status=$(docker inspect --format '{{.State.Status}}' "$cname" 2>/dev/null)
    health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}}' "$cname" 2>/dev/null)
    restarts=$(docker inspect --format '{{.RestartCount}}' "$cname" 2>/dev/null)
    case "$status" in
      running)
        if [[ "$health" == "unhealthy" ]]; then
          fail "$cname [$desc] running 但 health=unhealthy (重启${restarts}次)"
        elif [[ "$health" == "starting" ]]; then
          warn "$cname [$desc] running, health=starting(启动中)"
        else
          ok "$cname [$desc] running, health=$health (重启${restarts}次)"
        fi ;;
      created)
        fail "$cname [$desc] 状态=created 从未启动 —— restart 策略不会自愈, 需 docker compose up -d $cname" ;;
      exited)
        ec=$(docker inspect --format '{{.State.ExitCode}}' "$cname" 2>/dev/null)
        fail "$cname [$desc] 已退出(ExitCode=$ec)" ;;
      restarting)
        warn "$cname [$desc] 正在反复重启(可能崩溃循环)" ;;
      *)
        warn "$cname [$desc] 状态=$status" ;;
    esac
    # 容器健康URL本机探测
    if [[ -n "$hurl" && "$status" == "running" ]]; then
      hc=$(curl -sS -m 6 -o /dev/null -w '%{http_code}' "$hurl" 2>/dev/null)
      if [[ "$hc" =~ ^2|^3 ]]; then info "    └ 健康探测 $hurl → HTTP $hc"
      else warn "    └ 健康探测 $hurl → HTTP ${hc:-超时}(端口未就绪?)"; fi
    fi
  done
fi

# =============================================================================
hdr "7. 网口(网络接口)"
# =============================================================================
if have ip; then
  # 默认路由的出口网卡
  defdev=$(ip route 2>/dev/null | awk '/^default/{print $5; exit}')
  defgw=$(ip route 2>/dev/null | awk '/^default/{print $3; exit}')
  info "默认路由: 经 $defdev → 网关 $defgw"
  # 遍历非 lo 接口
  while read -r ifc state addr; do
    [[ "$ifc" == "lo" ]] && continue
    case "$state" in
      UP|UNKNOWN)
        if [[ "$ifc" == "$defdev" ]]; then ok "$ifc: $state  ${addr:-(无IP)}  ← 主出口"
        else info "$ifc: $state  ${addr:-(无IP)}"; fi ;;
      DOWN)
        # docker0/未用网卡 DOWN 属正常,仅提示
        info "$ifc: DOWN (未启用)" ;;
      *) info "$ifc: $state  ${addr:-}" ;;
    esac
  done < <(ip -br addr 2>/dev/null)
  # 主出口必须有IP
  if [[ -n "$defdev" ]]; then
    if ip -br addr show "$defdev" 2>/dev/null | grep -qE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+'; then
      ok "主出口网卡 $defdev 已获取 IP"
    else
      fail "主出口网卡 $defdev 无 IPv4 地址"
    fi
  else
    fail "无默认路由 —— 无法出网"
  fi
fi

# =============================================================================
hdr "8. 网络连通性"
# =============================================================================
# 8.1 内网网关
if [[ -n "${defgw:-}" ]] && have ping; then
  if ping -c1 -W2 "$defgw" >/dev/null 2>&1; then ok "内网网关 $defgw 可达"; else fail "内网网关 $defgw 不可达"; fi
fi
# 8.2 DNS 解析
if have getent; then
  if getent hosts baidu.com >/dev/null 2>&1; then ok "DNS 解析正常 (baidu.com)"; else fail "DNS 解析失败"; fi
fi
# 8.3 直连境内(不经代理)
if have curl; then
  dcode=$(curl -sS -m 8 -o /dev/null -w '%{http_code}' https://www.baidu.com 2>/dev/null)
  if [[ "$dcode" =~ ^2|^3 ]]; then ok "境内直连正常 (baidu HTTP $dcode)"; else fail "境内直连失败 (HTTP ${dcode:-超时})"; fi
  # 8.4 本机直连出口公网IP(不经代理)
  realip=$(curl -sS -m 8 https://myip.ipip.net 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -1)
  [[ -z "$realip" ]] && realip=$(curl -sS -m 8 ifconfig.me 2>/dev/null)
  [[ -n "$realip" ]] && info "本机直连出口公网IP: $realip"
  # 8.5 关键数据源 tdx 通达信上游连通性：不硬探单个行情IP(地址多变易误报)，
  #      改为查 tdx-stock-web 是否真能取到行情数据来反映上游链路。
  if docker inspect tdx-stock-web >/dev/null 2>&1; then
    th=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}}' tdx-stock-web 2>/dev/null)
    # 拉一条平安银行(000001)日线探活；接口异常或空则告警
    kbody=$(curl -sS -m 8 "http://127.0.0.1:8080/api/kline?code=000001&type=day&count=1" 2>/dev/null)
    if echo "$kbody" | grep -qiE '"close"|"Close"|"data"'; then
      ok "通达信上游数据可取(tdx-stock-web 行情接口返回数据, health=$th)"
    elif [[ "$th" == "healthy" ]]; then
      info "tdx-stock-web health=healthy；行情探活接口未返回标准字段(接口路径可能不同, 非故障)"
    else
      warn "通达信上游可能异常(tdx-stock-web health=$th, 行情接口无数据)"
    fi
  fi
fi

# =============================================================================
hdr "9. 网页对外可达性提示"
# =============================================================================
info "主网页 Streamlit: http://<公网IP>:8503  (本机健康见第6节 agentsstock1)"
info "若本机 8503 正常但外网打不开 → 多为云安全组/路由器未放行 TCP 8503 入站"
# 列出对 0.0.0.0 开放的网页端口
echo "  当前对外(0.0.0.0)监听的服务端口:"
ss -tlnH 2>/dev/null | awk '$4 ~ /0\.0\.0\.0:|\[::\]:/ {print $4}' | grep -vE ':22$|:53$' | sort -u | sed 's/^/    /'

# =============================================================================
# 汇总
# =============================================================================
echo -e "\n${C_BLD}┌──────────────────────── 检核汇总 ────────────────────────┐${C_RST}"
echo -e "  ${C_GRN}通过 $N_OK${C_RST}   ${C_YEL}告警 $N_WARN${C_RST}   ${C_RED}失败 $N_FAIL${C_RST}"
if   [[ "$N_FAIL" -gt 0 ]]; then echo -e "  ${C_RED}${C_BLD}⇒ 存在故障项, 请优先处理上面标 ✘ 的条目${C_RST}"; ec=2
elif [[ "$N_WARN" -gt 0 ]]; then echo -e "  ${C_YEL}${C_BLD}⇒ 基本正常, 有 ${N_WARN} 项告警可关注${C_RST}"; ec=1
else echo -e "  ${C_GRN}${C_BLD}⇒ 全部正常 ✅${C_RST}"; ec=0; fi
echo -e "${C_BLD}└──────────────────────────────────────────────────────────┘${C_RST}"
exit $ec
