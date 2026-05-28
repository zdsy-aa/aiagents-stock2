#!/usr/bin/env bash
# 非交互"一轮"执行器：调 DeepSeek(经 Aider) 按规格改代码 + 跑测试，
# 末行输出机读结论（DS_RESULT=PASS/FAIL）给编排方(Claude)，并以测试退出码退出。
#
# 用法:
#   ./ds_auto.sh <规格.md> <要改的文件...>                      # 首轮：按规格实现
#   DS_FIX="失败用例/提示" ./ds_auto.sh <规格.md> <文件...>      # 重试轮：只修复上轮失败
#
# 模型/auto-commit/aider 内层 auto-test 等来自仓库根 .aider.conf.yml。
# 本脚本末尾再跑一次 python3 -m pytest 作为"权威闸门"，结论喂给 Claude 决定结束/重试。
set -uo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"

if [ "$#" -lt 2 ]; then
  echo "用法: ./ds_auto.sh <规格.md> <要改的文件...>" >&2
  exit 2
fi

SPEC="$1"; shift
FILES=("$@")

if [ -n "${DS_FIX:-}" ]; then
  MSG="上一轮 python3 -m pytest -q tests/ 未通过，失败信息如下：
${DS_FIX}
请只做修复让测试全绿，不要扩大改动范围，也不要篡改测试用例的断言意图。"
else
  MSG="$(cat "$SPEC")

请严格按以上规格实现，并确保 python3 -m pytest -q tests/ 全部通过。只改动规格涉及的范围。"
fi

echo "=== [ds_auto] 调 DeepSeek(aider) 改代码 ===" >&2
aider "${FILES[@]}" --yes --message "$MSG" >&2 2>&1 || true

echo "=== [ds_auto] 权威校验：python3 -m pytest -q tests/ ===" >&2
PYTEST_OUT="$(python3 -m pytest -q tests/ 2>&1)"
CODE=$?
echo "$PYTEST_OUT" | tail -6 >&2

if [ "$CODE" -eq 0 ]; then
  echo "DS_RESULT=PASS"
else
  echo "DS_RESULT=FAIL"
  echo "$PYTEST_OUT" | grep -Ei '^FAILED|^ERROR| failed|短测试摘要|short test summary' | head -20
fi
exit "$CODE"
