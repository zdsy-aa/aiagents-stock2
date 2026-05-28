# 工作流：Claude 出方案 + DeepSeek 执行

单机 y7000ubantu，同一 git 仓库。设计见 `docs/superpowers/specs/2026-05-28-claude-brain-deepseek-hands-design.md`。

## 循环
1. 跟 Claude 说需求 → Claude 设计并把规格写进 `docs/specs/<日期>-<主题>.md`（照 `_TEMPLATE.md`）并 commit。
2. 另开终端跑：`./ds.sh <要改的文件...>`
3. 进 aider 后：`/read docs/specs/<那个规格>.md`，再输入"按规格实现"。
4. Aider+DeepSeek 改代码 → 自动 `pytest -q tests/` → 失败自修 → 绿则自动 commit。
5. `git log -p -1` / `git diff` 看改动；满意就继续，跑偏就 `git revert HEAD` 或 `git reset --hard HEAD~1`。

## 模型选择（省钱）
- 默认 `./ds.sh ...` = deepseek-chat(V3)，最便宜，干机械改动。
- `./ds.sh reasoner ...` = deepseek-reasoner(R1)，仅难逻辑/算法才用。

## 省 Claude 额度的规则
- Claude 只做：设计规格、关键 review、DeepSeek 卡住时兜底。
- 不要让 Claude 读大文件或反复来回；规格写到自包含。
- 升级阈值：Aider 自修 ~2-3 次仍过不了测试，才把失败日志带回 Claude。

## 边界
- 部署（`docker compose up -d --build`）手动/Claude 把关，不交给 DeepSeek 自动跑。
- 仓库已 `.gitattributes eol=lf`，DeepSeek 改动保持 LF。
