#!/usr/bin/env bash
# DeepSeek 执行器（Aider 封装）。
# 用法:
#   ./ds.sh <文件...>            # 默认 deepseek-chat (V3，便宜，机械活)
#   ./ds.sh reasoner <文件...>   # 切 deepseek-reasoner (R1，仅难逻辑用，更贵)
# 进入 aider 后:  /read docs/specs/<某规格>.md   再让它"按规格实现"。
# auto-test / auto-commit 等默认值来自仓库根 .aider.conf.yml。
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"

MODEL="deepseek/deepseek-chat"
if [ "${1:-}" = "reasoner" ]; then
  MODEL="deepseek/deepseek-reasoner"
  shift
fi

exec aider --model "$MODEL" "$@"
