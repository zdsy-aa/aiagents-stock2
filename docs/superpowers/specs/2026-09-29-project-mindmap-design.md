# 项目思维导图(实时更新)设计文档

> 状态:待实现 | 日期:2026-09-29 | 需求来源:用户要求「生成整个项目的思维导图,在前台页面展示,项目有改动实时更新,要求写入记忆」

## 1. 目标

在 Streamlit 主应用(8503)新增「🧠 项目思维导图」页,展示整个 aiagents-stock 仓库的结构脑图;宿主机项目代码有改动时,导图在 1 分钟内自动重建,页面定时刷新呈现最新结构。

## 2. 需求确认(用户已逐项选择)

| 决策点 | 选择 |
|---|---|
| 展示载体 | Streamlit 新增页面(文档大类),入口 8503 |
| 实时更新机制 | 宿主机 crontab 每分钟跑生成器,快照对比,有变更才重建 |
| 导图内容 | 自动扫描目录树 + `tools/mindmap_annotations.yaml` 手工注解合并 |
| 渲染形式 | markmap 经典脑图(CDN 加载 JS,浏览器侧) |

**否决的备选**:常驻 watchdog 进程(需保活,维护成本高);容器内生成(容器只挂载 `./data`、`./.env`、`./tdx-data:ro`,看不到宿主机根目录代码,需改部署拓扑)。

## 3. 架构

### 3.1 组件与职责

| 组件 | 位置 | 入库 | 职责 |
|---|---|---|---|
| `tools/mindmap_generator.py` | 仓库 tools/ | 是 | 纯 stdlib;扫描→快照对比→重建→注解合并→原子写产物 |
| `tools/mindmap_annotations.yaml` | 仓库 tools/ | 是 | 手工维护的关键模块/策略注解(初版按 docs/项目记忆.md 模块清单生成) |
| crontab 条目 | 宿主机 crontab | 否 | `* * * * * /home/tdxback/venv-data/bin/python /home/tdxback/aiagents-stock/tools/mindmap_generator.py` |
| `mindmap_ui.py` | 仓库根目录 | 是 | `display_mindmap()`:读产物 → markmap 渲染 + 元信息 + 定时刷新 |
| `views/nav_model.py` / `views/page_router.py` | views/ | 是 | 文档大类加「🧠 项目思维导图」`show_mindmap` 条目与路由分支 |
| 产物 `data/mindmap/` | ./data 挂载内 | 否(.gitignore 补) | project_map.md、meta.json、.snapshot.json、sync.log |

### 3.2 数据流

```
宿主机仓库代码改动
  → crontab 每分钟:mindmap_generator.py
  → 与 data/mindmap/.snapshot.json 对比(相对路径 → (mtime, size))
  → 无变更:仅追加一行 sync.log,退出;有变更:重建
  → data/mindmap/project_map.md + meta.json(原子写:临时文件 → os.replace)
  → ./data 挂载即时对容器可见
  → Streamlit 页 st.fragment(run_every=60) 重读文件 → markmap 渲染
```

延迟上界:代码改动后 ≤1 分钟(生成)+ ≤1 分钟(页面刷新)≈ 2 分钟内可见。

### 3.3 扫描规则

- 起点:仓库根目录 `/home/tdxback/aiagents-stock`(由脚本 `Path(__file__).resolve().parents[1]` 推导,不硬编码)。
- 排除:`.git`、`__pycache__`、`*.pyc`、`*.log`、`*.log.*`、`*.bak`、`*.pybak`、`data/`、`tdx-data/`、`pgdata/`、`venv`、`venv-data`、`.pytest_cache`、`docs/superpowers`。
- 收录文件类型:`.py`、`.md`、`.sh`、`.yml`、`.yaml`、`.json`、`Dockerfile`、`.txt`、`.js`、`.go`。
- 导图骨架 = 物理目录树;注解可把相关文件挂到「逻辑分组」节点下(见 3.4)。

### 3.4 注解合并(`tools/mindmap_annotations.yaml`)

```yaml
# 结构:相对路径(文件或目录) → 说明文字;说明渲染为该节点文本的后缀
chanlun_engine.py: "缠论引擎(简化缠论:分型→笔→线段→中枢→MACD背驰)"
views/page_router.py: "页面路由(show_* 标志分派)"
```

- 文件注解:节点文本 = `文件名 — 说明`。
- 目录/虚拟分组注解:允许为目录节点加说明;允许 `__groups__` 区把零散顶层文件归入逻辑分组(如 `缠论*` → 「缠论选股」),分组节点渲染为导图分支。
- 注解路径在仓库中不存在时:跳过并记入 sync.log,不影响整体生成。

### 3.5 产物格式

- `data/mindmap/project_map.md`:markmap 格式 markdown,`#`~`######` 层级 = 树层级,叶子 = 文件节点。
- `data/mindmap/meta.json`:`generated_at`(ISO 本地时间)、`node_count`、`changed_files`(本次变更的相对路径清单)、`git_head`(`git rev-parse HEAD`)。
- `data/mindmap/.snapshot.json`:快照,供下次对比。
- `data/mindmap/sync.log`:每轮运行一行(时间/是否重建/错误)。

### 3.6 页面(`mindmap_ui.py`)

- 顶部:`st.metric` 显示生成时间、节点数、变更文件数;无产物时显示「等待宿主机 cron 生成(≤2 分钟)」提示,不抛异常。
- 主体:`st.components.v1.html`,内嵌:
  ```html
  <div class="markmap"><script type="text/template">{project_map.md 内容}</script></div>
  <script src="https://cdn.jsdelivr.net/npm/markmap-autoloader@0.18"></script>
  ```
- JS 加载失败兜底:内联一段 3 秒定时器 JS,若 `.markmap svg` 未出现,显示「脑图 JS 加载失败,请检查浏览器网络/代理」。
- 自动刷新:整页主体包在 `st.fragment(run_every=60)` 中(容器内 streamlit 1.57.0,支持 run_every),fragment 重跑重读产物文件;另提供手动刷新按钮(st.rerun)。
- 产物文件读取优先 `data/mindmap/`(容器内 `/app/data/mindmap/`),与宿主机同一份挂载。

### 3.7 错误处理

| 场景 | 行为 |
|---|---|
| 产物不存在(首分钟) | 页面提示等待,不报错 |
| 生成器异常 | 写 sync.log;产物不动(原子写保证旧产物始终可用) |
| 注解 yaml 格式错 | 跳过注解,结构照常生成 |
| 仓库外 git 不可用 | git_head 记空串,不失败 |
| markmap CDN 加载失败 | 页面内提示文字 |

## 4. 测试

- 新增 `tests/test_mindmap_generator.py`(pytest,纯 stdlib 可测):
  1. 临时目录假仓库 → 生成结构正确、排除规则生效;
  2. 注解合并(文件注解/虚拟分组)正确;
  3. 快照对比:无变更不重建(产物 mtime 不变)、有变更重建且 changed_files 正确;
  4. 原子写:产物始终是完整旧版或完整新版;
  5. 注解 yaml 非法时仍产出结构。
- 修改 `tests/test_ui_pages_smoke.py`:`PAGE_FLAGS` 加 `show_mindmap`,验证产物缺失时页面渲染不抛异常。

## 5. 部署与文档

1. `tools/mindmap_generator.py`、`tools/mindmap_annotations.yaml`、`mindmap_ui.py`、nav/router/tests 改动提交 git(仅任务产物,推送由用户执行)。
2. 宿主机 crontab 加第 5 条(加前给用户看)。
3. `.gitignore` 补 `data/mindmap/`。
4. 根目录新页面按项目惯例重建镜像:`docker compose build agentsstock && docker compose up -d agentsstock1`。
5. 更新 `docs/项目记忆.md`(模块清单/页面清单/坑清单加条目)。
6. 写入 Claude 持久记忆(用户明确要求「写在记忆中」):新增 project-mindmap.md 记录该子系统与 cron 条目,更新 MEMORY.md 索引。

## 6. 范围外(YAGNI)

- 不做 diff 高亮/历史版本对比;
- 不做逻辑分组自动推断(仅注解声明式);
- 不做容器内生成、不做常驻 watchdog;
- 不做独立静态网页(用户未选)。
