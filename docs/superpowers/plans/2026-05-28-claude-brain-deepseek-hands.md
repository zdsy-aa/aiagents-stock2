# Claude出方案+DeepSeek执行 工作流落地 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 y7000ubantu 单机上搭好"Claude 写规格 → Aider+DeepSeek 执行"的协作工作流，并用一次端到端试跑验收。

**Architecture:** 同机同仓库。Claude（本 CLI）只产出规格文件 + review；Aider 以 DeepSeek 为模型，按规格改代码、跑 pytest、自动 commit。交接靠仓库内 markdown + git。

**Tech Stack:** aider-chat（litellm 路由 `deepseek/*` → api.deepseek.com）、DeepSeek-V3(`deepseek-chat`)/R1(`deepseek-reasoner`)、pytest、git、bash。设计文档见 `docs/superpowers/specs/2026-05-28-claude-brain-deepseek-hands-design.md`。

---

## 文件结构（本计划产出/改动）

- 创建 `.aider.conf.yml`（仓库根）— Aider 默认配置：模型、auto-test、auto-commit
- 修改 `.gitignore` — 忽略 aider 运行期产物（`.aider*`）
- 创建 `ds.sh`（仓库根）— 选模型 + 透传文件的启动器
- 创建 `docs/specs/_TEMPLATE.md` — Claude 写规格的模板
- 创建 `docs/specs/.gitkeep`（如目录不存在）
- 创建 `docs/WORKFLOW-claude-deepseek.md` — 工作流说明 + 省钱规则 + 升级阈值
- 试跑产出（由 DeepSeek 完成）：`base_scheduler.py` 加 `is_alive()` + `tests/test_base_scheduler.py` 加一条测试

---

## Task 1: 安装 Aider 并确认可用

**Files:** 无（环境安装）

- [ ] **Step 1: 安装 aider-chat**

Run:
```bash
python3 -m pip install --user aider-chat
```
Expected: 末尾 `Successfully installed aider-chat-0.86.2 ...`（或相近版本）。

- [ ] **Step 2: 确认 aider 在 PATH 且可执行**

Run:
```bash
export PATH="$HOME/.local/bin:$PATH"
aider --version
```
Expected: 打印 `aider 0.86.x`。若 `command not found`，确认 `~/.local/bin` 在 PATH（把上面的 export 写进 `~/.bashrc`）。

---

## Task 2: 忽略 Aider 运行期产物（在任何 aider 运行前做）

**Files:**
- Modify: `/home/tdxback/aiagents-stock/.gitignore`

- [ ] **Step 1: 追加 aider 产物忽略规则**

在 `.gitignore` 末尾追加：
```gitignore

# Aider 运行期产物（聊天历史/输入历史/标签缓存等），不入库
.aider*
!.aider.conf.yml
```
说明：`.aider*` 忽略全部产物；`!.aider.conf.yml` 例外放行配置文件（要入库）。

- [ ] **Step 2: 验证规则生效**

Run:
```bash
cd /home/tdxback/aiagents-stock
git check-ignore -v .aider.chat.history.md .aider.input.history && echo "IGNORED OK"
git check-ignore .aider.conf.yml; echo "conf exit=$? (期望 1=未被忽略)"
```
Expected: 前者打印命中 `.aider*` 规则 + `IGNORED OK`；后者 `exit=1`（`.aider.conf.yml` 不被忽略）。

- [ ] **Step 3: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add .gitignore
git commit -m "chore(workflow): gitignore 忽略 aider 运行期产物，放行 .aider.conf.yml"
```

---

## Task 3: 配置 Aider 用 DeepSeek（.aider.conf.yml）并验证连通

**Files:**
- Create: `/home/tdxback/aiagents-stock/.aider.conf.yml`

- [ ] **Step 1: 写配置文件**

创建 `.aider.conf.yml`：
```yaml
# Aider 默认配置：DeepSeek 驱动的"手"。
# API key 自动读仓库根 .env 的 DEEPSEEK_API_KEY（端点 https://api.deepseek.com/v1）。
model: deepseek/deepseek-chat   # DeepSeek-V3，便宜，干机械活；难逻辑用 ds.sh reasoner 切 R1
auto-commits: true              # 每次改动自动 git commit，便于回滚
auto-test: true                 # 改动后自动跑测试
test-cmd: python -m pytest -q tests/
gitignore: false                # 不让 aider 自动改写 .gitignore（我们已手动维护）
```

- [ ] **Step 2: 验证 DeepSeek 连通（一次性最小调用，几乎不花钱）**

Run:
```bash
cd /home/tdxback/aiagents-stock
export PATH="$HOME/.local/bin:$PATH"
aider --model deepseek/deepseek-chat --no-auto-commits --no-auto-test \
      --yes --message "只回复一个词：pong" 2>&1 | tail -15
```
Expected: 输出中出现模型回复 `pong`（证明 key/端点/模型路由都通）。若报 `AuthenticationError`/`api_key`，检查 `.env` 的 `DEEPSEEK_API_KEY` 是否非空。

- [ ] **Step 3: 提交配置**

```bash
cd /home/tdxback/aiagents-stock
git add .aider.conf.yml
git commit -m "feat(workflow): 加 .aider.conf.yml — DeepSeek 模型 + auto-test/commit"
```

---

## Task 4: ds.sh 启动器

**Files:**
- Create: `/home/tdxback/aiagents-stock/ds.sh`

- [ ] **Step 1: 写启动脚本**

创建 `ds.sh`：
```bash
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
```

- [ ] **Step 2: 赋可执行权限**

Run:
```bash
cd /home/tdxback/aiagents-stock
chmod +x ds.sh
```

- [ ] **Step 3: 验证脚本语法与模型切换逻辑（不真正启动 aider）**

Run:
```bash
cd /home/tdxback/aiagents-stock
bash -n ds.sh && echo "syntax OK"
# 把 exec aider 临时换成 echo 来确认参数拼接：
sed 's/^exec aider/echo aider/' ds.sh | bash -s -- reasoner foo.py
sed 's/^exec aider/echo aider/' ds.sh | bash -s -- bar.py
```
Expected:
```
syntax OK
aider --model deepseek/deepseek-reasoner foo.py
aider --model deepseek/deepseek-chat bar.py
```

- [ ] **Step 4: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add ds.sh
git commit -m "feat(workflow): ds.sh — Aider 启动器(默认 V3，reasoner 切 R1)"
```

---

## Task 5: 规格模板 docs/specs/_TEMPLATE.md

**Files:**
- Create: `/home/tdxback/aiagents-stock/docs/specs/_TEMPLATE.md`

- [ ] **Step 1: 写模板**

创建 `docs/specs/_TEMPLATE.md`：
```markdown
# 规格：<一句话标题>

> Claude 填写本规格 → 交给 Aider+DeepSeek 执行。越精确，DeepSeek 越不跑偏。

## 目标
<这次要达成什么，1-3 句>

## 涉及文件
- 修改：`path/to/file.py`（具体哪个函数/类）
- 新增：`path/to/new.py`
- 测试：`tests/test_xxx.py`

## 精确改动
<逐条说明改什么、改成什么样；能给伪代码/签名就给。不要含糊。>

## 验收（DeepSeek 必须让其通过）
- 测试命令：`python -m pytest -q tests/test_xxx.py`
- 期望：全部通过；不破坏 `python -m pytest -q tests/` 其余用例。

## 不做（out-of-scope）
- <明确不要碰的东西，防止 DeepSeek 扩大改动>
```

- [ ] **Step 2: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add docs/specs/_TEMPLATE.md
git commit -m "docs(workflow): 加 Claude→DeepSeek 规格模板"
```

---

## Task 6: 工作流说明文档

**Files:**
- Create: `/home/tdxback/aiagents-stock/docs/WORKFLOW-claude-deepseek.md`

- [ ] **Step 1: 写说明**

创建 `docs/WORKFLOW-claude-deepseek.md`：
```markdown
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
```

- [ ] **Step 2: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add docs/WORKFLOW-claude-deepseek.md
git commit -m "docs(workflow): Claude+DeepSeek 协作工作流使用说明"
```

---

## Task 7: 端到端试跑（验收）— DeepSeek 实现 BaseScheduler.is_alive()

这是设计文档"验收标准#2"：Claude 写最小规格 → ds.sh 跑 → DeepSeek 改码+测试通过+自动 commit，全程 Claude 不编辑代码。选 `BaseScheduler.is_alive()` 作真实小改动（安全、可测、契合）。

**Files:**
- Create: `/home/tdxback/aiagents-stock/docs/specs/2026-05-28-trial-is-alive.md`（Claude 写规格）
- 由 DeepSeek 改：`base_scheduler.py`、`tests/test_base_scheduler.py`

- [ ] **Step 1: Claude 写试跑规格**

创建 `docs/specs/2026-05-28-trial-is-alive.md`：
```markdown
# 规格：BaseScheduler 增加 is_alive() 便捷方法

## 目标
给 base_scheduler.BaseScheduler 增加 is_alive()，返回"调度线程是否真的在跑"。

## 涉及文件
- 修改：`base_scheduler.py`（BaseScheduler 类，加方法）
- 测试：`tests/test_base_scheduler.py`（加一条测试）

## 精确改动
在 BaseScheduler 内新增方法：
    def is_alive(self) -> bool:
        """running 且后台线程存在并存活时返回 True。"""
        return bool(self.running and self.thread is not None and self.thread.is_alive())

在 tests/test_base_scheduler.py 末尾新增测试：
    def test_is_alive_reflects_thread_state():
        s = BaseScheduler()
        s.loop_interval = 0.01
        assert s.is_alive() is False          # 未启动
        s._start_thread()
        assert s.is_alive() is True           # 启动后
        s._stop_thread()
        assert s.is_alive() is False          # 停止后

## 验收
- 测试命令：`python -m pytest -q tests/test_base_scheduler.py`
- 期望：全过；不破坏 `python -m pytest -q tests/` 其余用例。

## 不做
- 不动其它 scheduler 子类；不改已有方法签名。
```

提交规格：
```bash
cd /home/tdxback/aiagents-stock
git add docs/specs/2026-05-28-trial-is-alive.md
git commit -m "docs(spec): 试跑规格 BaseScheduler.is_alive()"
```

- [ ] **Step 2: 用 DeepSeek 执行该规格（人工在终端跑）**

Run（交互式）：
```bash
cd /home/tdxback/aiagents-stock
./ds.sh base_scheduler.py tests/test_base_scheduler.py
```
进入 aider 后依次输入：
```
/read docs/specs/2026-05-28-trial-is-alive.md
按该规格实现 is_alive() 方法和对应测试，然后运行测试确保通过。
```
Expected: DeepSeek 编辑两个文件 → aider 自动跑 `python -m pytest -q tests/` → 显示通过 → 自动 commit。输入 `/quit` 退出。

- [ ] **Step 3: 验收 — 确认改动正确且全套件绿**

Run:
```bash
cd /home/tdxback/aiagents-stock
grep -n "def is_alive" base_scheduler.py
grep -n "def test_is_alive_reflects_thread_state" tests/test_base_scheduler.py
python3 -m pytest -q tests/ 2>&1 | tail -5
git log --oneline -2
```
Expected: 两个 grep 都命中；pytest 末尾 `83 passed, 1 skipped`（比之前多 1 条）；git log 顶部有 aider 自动提交的 is_alive 改动。

- [ ] **Step 4: 验收结论**

若 Step 3 全部满足 → 工作流搭建完成（设计验收#1/#2/#3 均达成）。
若 DeepSeek 实现有偏差：`git reset --hard HEAD~1` 退回，按"升级阈值"把失败带回 Claude 调整规格后重试。

---

## Self-Review 结论
- 覆盖设计第 3 节全部组件（aider 安装/.aider.conf.yml/ds.sh/规格模板/工作流文档）+ 验收标准#1#2#3（Task1-3 工具就位、Task7 试跑、Task6 文档）。
- 无 TBD/占位符；每步给了真实命令/文件内容/期望输出。
- 命名一致：`.aider.conf.yml`、`ds.sh`、`deepseek/deepseek-chat`、`deepseek/deepseek-reasoner` 前后统一。
- 顺序正确：先 gitignore(Task2) 再任何 aider 运行(Task3+)，避免产物污染工作树。
