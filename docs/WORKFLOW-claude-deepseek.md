# 工作流：Claude 出方案 + DeepSeek 执行

单机 y7000ubantu，同一 git 仓库。设计见 `docs/superpowers/specs/2026-05-28-claude-brain-deepseek-hands-design.md`。

## 循环
1. 跟 Claude 说需求 → Claude 设计并把规格写进 `docs/specs/<日期>-<主题>.md`（照 `_TEMPLATE.md`）并 commit。
2. 另开终端跑：`./ds.sh <要改的文件...>`
3. 进 aider 后：`/read docs/specs/<那个规格>.md`，再输入"按规格实现"。
4. Aider+DeepSeek 改代码 → 自动 `pytest -q tests/` → 失败自修 → 绿则自动 commit。
5. `git log -p -1` / `git diff` 看改动；满意就继续，跑偏就 `git revert HEAD` 或 `git reset --hard HEAD~1`。

## 自动模式（Claude 编排、DeepSeek 干活，全自动到绿）
让 Claude 一条龙：写规格 → 调 DeepSeek → 跑测试校验 → 错就让 DeepSeek 重改，最多 3 轮、只信测试套件。
核心是 `ds_auto.sh`（一轮 = 调 aider 非交互改码 + 权威 `python3 -m pytest`，末行输出 `DS_RESULT=PASS/FAIL`）：
```bash
# 首轮：按规格实现
./ds_auto.sh docs/specs/<规格>.md <要改的文件...>
# 重试轮：把上一轮失败用例塞进 DS_FIX，让 DeepSeek 只修复
DS_FIX="<失败用例/报错>" ./ds_auto.sh docs/specs/<规格>.md <要改的文件...>
```
**token 真相**：`ds_auto.sh` 是阻塞子进程，DeepSeek 干活那几分钟 Claude 不产 token；Claude 只在轮次边界花少量 token（发起命令 + 读 `DS_RESULT` + 决定）。代码生成成本在便宜的 DeepSeek。⚠️单轮超 ~5 分钟会触发 Claude 提示缓存过期、那次恢复略贵，故单个规格别太大。
**Claude 编排循环**：轮1 `ds_auto.sh` → 读末行 `DS_RESULT`；PASS→结束；FAIL→取失败用例塞 `DS_FIX` 再跑；最多 3 轮仍 FAIL → 停下叫人（多半是规格不清或任务太难，需 Claude 改规格或切 reasoner）。
**前提**：规格里必须带能判对错的验收测试——测试是唯一的低成本校验尺，覆盖不到的逻辑这套自动模式判不了。

## 手动模式（你在终端跑，最省 Claude）
1. Claude 写规格到 `docs/specs/<日期>-<主题>.md`。
2. `./ds.sh <文件...>` → 进 aider → `/read docs/specs/<规格>.md` → "按规格实现"。
3. 自动跑测试、绿则自动 commit；`/diff` 看、`/quit` 退、跑偏 `git reset --hard HEAD~1`。

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
