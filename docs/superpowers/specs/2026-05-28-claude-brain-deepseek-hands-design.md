# 设计：Claude 出方案 + DeepSeek 执行 的协作工作流

**日期**：2026-05-28
**目标项目**：aiagents-stock
**机器**：y7000ubantu（单机，Claude Code 与执行器共享同一 git 仓库与文件系统）
**核心动机**：省 Claude 额度——Claude 只做高价值的方案设计与关键 review，把机械的改文件/跑测试/提交交给便宜的 DeepSeek（经 Aider 驱动）。

## 1. 架构与角色

单机、同一个 git 仓库，两个"agent"分工：

| 角色 | 由谁担任 | 职责 | 成本特征 |
|------|---------|------|---------|
| **大脑** | Claude Code（本 CLI 会话） | 产出精确规格、关键节点 review、卡住时兜底诊断 | token 用量小、按需 |
| **手** | Aider + DeepSeek（另开终端） | 按规格改代码、跑测试、自动 commit | 便宜、承担大头 |

**交接介质 = 仓库内文件**（规格 markdown + git 历史）。同机共享文件系统，无跨机同步。

## 2. 控制流（核心循环）

```
你 → Claude：描述需求
  → Claude：设计 + 写规格文件 docs/specs/<日期>-<主题>.md（commit）
    → 你：ds.sh 起 Aider，指向规格 + 目标文件
      → Aider+DeepSeek：改代码 → 自动 pytest -q tests/ → 失败自修 → 绿则 commit
        → 你/Claude(里程碑)：看 diff
          → [Aider 重试 N 次仍红] → 才把 Claude 拉回来诊断（成本上限锁在"设计+兜底"）
```

关键点：**Claude 不直接驱动 DeepSeek**。Claude 的产物是"规格文件"，DeepSeek（经 Aider）异步消费。这样 Claude 会话可短、可关，省额度。

## 3. 要落地的组件

1. **安装 Aider**：`pip install aider-chat`（PyPI 最新 0.86.2，已确认可达）。一次性。
2. **`.aider.conf.yml`**（仓库根）：
   - `model: deepseek/deepseek-chat`（DeepSeek-V3，最便宜，干机械活）
   - `auto-test: true`、`test-cmd: python -m pytest -q tests/`
   - `auto-commits: true`
   - key 复用：Aider 自动读仓库根 `.env` 的 `DEEPSEEK_API_KEY`（端点 `https://api.deepseek.com/v1`，OpenAI 兼容，litellm 的 `deepseek/*` 前缀自动路由）。
3. **`ds.sh` 启动器**：
   - 默认 `aider --model deepseek/deepseek-chat`（V3）
   - `ds.sh reasoner ...` → 切 `deepseek/deepseek-reasoner`（R1，仅难逻辑用，更贵）
   - 透传目标文件参数；统一 quiet/auto-test 等默认值
4. **规格模板 `docs/specs/_TEMPLATE.md`**：字段=目标 / 涉及文件 / 精确改动 / 验收(测试命令) / 不做什么(out-of-scope)。规格越精确，DeepSeek 越不容易跑偏。
5. **工作流说明**：写进仓库（独立 `docs/WORKFLOW-claude-deepseek.md` 或追加 CLAUDE.md），含成本规则与升级阈值。

## 4. 省钱规则（设计约束）

- **Claude 侧**：短会话；规格精确、自包含；不读大文件；只做设计 + review + 兜底。
- **DeepSeek 侧**：机械改动用 `deepseek-chat`（最便宜）；仅难逻辑切 `deepseek-reasoner`。
- **安全网替代 Claude 复核**：现有 82 个测试 + 已统一的 LF `.gitattributes` + git 历史 = 便宜的正确性闸门，DeepSeek 出错由测试兜住，不必每次惊动 Claude。
- **升级阈值**：Aider 自动重试约 2–3 次仍未过测试，才把失败上下文带回 Claude 诊断。

## 5. 安全 / 容错

- **可回滚**：Aider 每次改动自动 git commit → DeepSeek 跑偏可 `git revert`/`git reset --hard` 秒退。
- **测试闸门**：每次改动后自动跑 `pytest -q tests/`，红则不算完成。
- **部署隔离**：`docker compose up -d --build`（部署生效）保持**手动 / Claude 把关**，不交给 DeepSeek 自动跑——部署慢、有风险、且需 ~70s healthcheck 启动窗口（见本仓库 healthcheck 修复史）。
- **规格只读**：Aider 用 `/read` 加载规格作只读上下文，不会改坏规格本身。
- **换行符**：仓库已 `.gitattributes eol=lf`，Aider/DeepSeek 的编辑保持 LF，不会再引入 CRLF 噪音。

## 6. 不做（YAGNI / 明确排除）

- 不让 Claude 在运行时通过 API 直接调 DeepSeek（那需要自建 agent 循环，违背"省 Claude"与"少维护"）。
- 不上 OpenHands / VSCode 插件（重、需 Node/GUI，本机无 Node）。
- 不让 DeepSeek 自动执行部署 / docker / 数据更新等运维命令（范围聚焦代码开发）。
- 不做跨机同步（单机）。

## 7. 验收标准（这套工作流"搭好了"的判定）

1. `aider --version` 可用；`.aider.conf.yml` 与 `ds.sh` 就位。
2. 一次**试跑**：Claude 写一个最小规格（如给某模块加一个带测试的小函数）→ `ds.sh` 跑 Aider → DeepSeek 完成编辑 → 自动 pytest 通过 → 自动 commit。全程不需 Claude 介入编辑。
3. 工作流说明文档在仓库内，含成本规则与升级阈值。
