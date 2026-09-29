# 项目思维导图(实时更新)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增「🧠 项目思维导图」Streamlit 页,展示整个 aiagents-stock 仓库的结构脑图;宿主机 cron 每分钟检测项目变更并自动重建,页面 60 秒定时刷新。

**Architecture:** 宿主机侧纯 stdlib 生成器 `tools/mindmap_generator.py`(扫描→快照对比→注解合并→原子写产物到 `data/mindmap/`,挂载即时对容器可见);容器内新页面 `mindmap_ui.py` 读产物、markmap(CDN)渲染、`st.fragment(run_every=60)` 自动刷新。导航沿用 `nav_model.py` + `page_router.py` 的 show_* 标志模式。

**Tech Stack:** Python 3.12 stdlib(生成器)、Streamlit 1.57.0 + markmap-autoloader 0.18(页面)、pytest(宿主机 venv-data 9.1.1 / 容器内)。

**Spec:** `docs/superpowers/specs/2026-09-29-project-mindmap-design.md`

> ⚠️ Spec 微调(经用户需求确认后的实现层修正):注解文件格式由 yaml 改为 **JSON**(`tools/mindmap_annotations.json`),因宿主机 venv-data 无 PyYAML,JSON 保持生成器纯 stdlib 零依赖。Task 4 中同步修订 spec 文件。

## Global Constraints

- 生成器纯 stdlib,宿主机 `/home/tdxback/venv-data/bin/python` 运行(3.12.3)
- 产物目录 `data/mindmap/` 不入库(.gitignore 补 `data/mindmap/`)
- 页面延迟上界:代码改动后 ≤1 分钟(生成)+ ≤1 分钟(页面刷新)
- UI smoke 测试必须在容器内跑(宿主机 venv-data 无 streamlit):`docker exec agentsstock1 python3 -m pytest`
- 只在 `main` 分支开发;推送由用户自行执行
- 提交只含任务产物(日志/缓存/产物不入库)
- 面向用户的输出一律中文
- crontab 第 5 条加前必须给用户看

---

### Task 1: 生成器核心(扫描 + markdown 渲染 + 产物写入)

**Files:**
- Create: `tools/mindmap_generator.py`
- Test: `tests/test_mindmap_generator.py`

**Interfaces:**
- Produces:
  - `scan_tree(root: Path) -> dict` — 节点 `{"name", "path", "type": "dir"|"file", "children": []}`
  - `render_markdown(tree: dict) -> str` — 标题层级=树层级,节点名+` — note` 后缀
  - `count_nodes(tree: dict) -> int`
  - `_atomic_write(path: Path, text: str) -> None` — 临时文件 + `os.replace`
  - `write_outputs(out_dir: Path, md: str, meta: dict) -> None` — 写 project_map.md + meta.json(均原子)
  - `run(root: Path, out_dir: Path, force: bool = False, annot_path: Path | None = None) -> str` — 返回日志行("rebuilt"/"error: ..."),本任务版:每次重建,不含快照/注解
  - `main()` — CLI,支持 `--force`,追加一行 sync.log
  - 常量:`ROOT`、`OUT_DIR`、`EXCLUDE_DIRS`、`INCLUDE_SUFFIXES`、`INCLUDE_NAMES`、`MAX_DEPTH = 6`

- [ ] **Step 1: 写失败测试**

`tests/test_mindmap_generator.py`:

```python
"""mindmap_generator 单测:临时目录构造假仓库,验证扫描/渲染/排除/产物。"""
import json
import time
from pathlib import Path

import pytest

import tools.mindmap_generator as mg


def make_repo(tmp_path: Path) -> Path:
    """构造假仓库:源码 + 需排除的目录/文件。"""
    (tmp_path / "app.py").write_text("print('hi')")
    (tmp_path / "views").mkdir()
    (tmp_path / "views" / "page_router.py").write_text("x = 1")
    (tmp_path / "views" / "empty_dir").mkdir()  # 无收录文件的目录不出现在树中
    (tmp_path / "README.md").write_text("# hi")
    (tmp_path / "Dockerfile").write_text("FROM python")
    (tmp_path / "data" / "x.db").mkdir(parents=True)
    (tmp_path / "tdx-data" / "k.db").mkdir(parents=True)
    (tmp_path / ".git" / "config").mkdir(parents=True)
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "app.cpython-312.pyc").write_text("x")
    (tmp_path / "notes.log").write_text("log")
    (tmp_path / "backup.bak").write_text("bak")
    return tmp_path


def test_scan_tree_includes_sources_and_excludes_ignored(tmp_path):
    root = make_repo(tmp_path)
    tree = mg.scan_tree(root)
    assert tree["type"] == "dir" and tree["name"] == root.name
    names = {(c["name"], c["type"]) for c in tree["children"]}
    assert ("app.py", "file") in names
    assert ("README.md", "file") in names
    assert ("Dockerfile", "file") in names
    assert ("views", "dir") in names
    for bad in ["data", "tdx-data", ".git", "__pycache__", "notes.log", "backup.bak"]:
        assert bad not in {n for n, _ in names}
    views = next(c for c in tree["children"] if c["name"] == "views")
    view_names = {c["name"] for c in views["children"]}
    assert "page_router.py" in view_names
    assert "empty_dir" not in view_names


def test_render_markdown_headings_follow_depth(tmp_path):
    root = make_repo(tmp_path)
    tree = mg.scan_tree(root)
    md = mg.render_markdown(tree)
    assert md.startswith(f"# {root.name}")
    assert "\n## views" in md
    assert "\n### page_router.py" in md


def test_count_nodes_counts_dirs_and_files(tmp_path):
    root = make_repo(tmp_path)
    tree = mg.scan_tree(root)
    assert mg.count_nodes(tree) == 6  # root + views + app.py + README.md + Dockerfile + page_router.py


def test_write_outputs_and_run_produce_artifacts(tmp_path):
    out_dir = tmp_path / "out"
    md, meta = "content", {"generated_at": "t"}
    mg.write_outputs(out_dir, md, meta)
    assert (out_dir / "project_map.md").read_text(encoding="utf-8") == "content"
    assert json.loads((out_dir / "meta.json").read_text(encoding="utf-8")) == meta
    # run 端到端:产物齐全且 meta 含生成时间(annot_path 传不存在路径,隔离真实注解文件)
    result = mg.run(tmp_path, out_dir, annot_path=tmp_path / "nope.json")
    assert result.startswith("rebuilt")
    meta2 = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta2["generated_at"] and meta2["node_count"] >= 1


def test_scan_tree_excludes_nested_superpowers(tmp_path):
    root = make_repo(tmp_path)
    (root / "docs" / "superpowers" / "specs" / "x.md").mkdir(parents=True)
    tree = mg.scan_tree(root)
    names = {c["name"] for c in tree["children"]}
    assert "docs" not in names  # docs 下只有被排除的 superpowers,整目录无收录文件


def test_scan_tree_excludes_superpowers_path_with_file(tmp_path):
    """superpowers 目录内存在真实收录文件时,相对路径排除仍生效。"""
    root = make_repo(tmp_path)
    (root / "docs" / "superpowers" / "specs").mkdir(parents=True)
    (root / "docs" / "superpowers" / "specs" / "x.md").write_text("# x")
    tree = mg.scan_tree(root)
    assert "docs" not in {c["name"] for c in tree["children"]}


def test_run_errors_return_error_line(tmp_path, monkeypatch):
    def boom(root):
        raise OSError("disk on fire")
    monkeypatch.setattr(mg, "scan_tree", boom)
    result = mg.run(tmp_path, tmp_path / "out", annot_path=tmp_path / "nope.json")
    assert result.startswith("error:")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd /home/tdxback/aiagents-stock && /home/tdxback/venv-data/bin/python -m pytest tests/test_mindmap_generator.py -v`
Expected: FAIL(ImportError: no module named 'tools.mindmap_generator';若 tools/ 无 `__init__.py` 需在测试头加 `sys.path` 处理,实现时校正)

- [ ] **Step 3: 写最小实现**

`tools/mindmap_generator.py`(完整内容):

```python
#!/usr/bin/env python3
"""项目思维导图生成器。

宿主机 cron 每分钟运行:扫描仓库结构,与上次快照对比,有变更才重建产物
(data/mindmap/project_map.md + meta.json),挂载进容器供 Streamlit 页读取。
纯 stdlib,无第三方依赖。"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "mindmap"
SYNC_LOG_PATH = OUT_DIR / "sync.log"
DEFAULT_ANNOT_PATH = ROOT / "tools" / "mindmap_annotations.json"

EXCLUDE_DIRS = {
    ".git", "__pycache__", "data", "tdx-data", "pgdata", "venv",
    ".pytest_cache", "docs/superpowers", ".streamlit",
}
INCLUDE_SUFFIXES = {".py", ".md", ".sh", ".yml", ".yaml", ".json", ".txt", ".js", ".go"}
INCLUDE_NAMES = {"Dockerfile", ".gitignore", ".dockerignore", "Makefile", "LICENSE", "requirements.txt"}
MAX_DEPTH = 6  # 超过 6 层不再展开(项目实际深度 ≤5)


def _included_file(p: Path) -> bool:
    return p.suffix in INCLUDE_SUFFIXES or p.name in INCLUDE_NAMES


def scan_tree(root: Path) -> dict:
    """扫描 root,返回仅含收录文件及其祖先目录的树。"""
    def walk(dirpath: Path, rel: str, depth: int):
        node = {"name": dirpath.name, "path": rel or ".", "type": "dir", "children": []}
        try:
            entries = sorted(dirpath.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return node
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                rel_entry = f"{rel}/{entry.name}" if rel else entry.name
                if rel_entry in EXCLUDE_DIRS or entry.name.startswith("."):
                    continue
                if depth >= MAX_DEPTH:
                    continue
                child = walk(entry, f"{rel}/{entry.name}" if rel else entry.name, depth + 1)
                if child["children"]:
                    node["children"].append(child)
            elif _included_file(entry):
                node["children"].append({
                    "name": entry.name,
                    "path": f"{rel}/{entry.name}" if rel else entry.name,
                    "type": "file",
                    "children": [],
                })
        return node

    return walk(root, "", 0)


def render_markdown(tree: dict, depth: int = 0) -> str:
    """标题层级=树层级;节点带 note 时以 ` — note` 作后缀。"""
    heading = "#" * min(depth + 1, 6) + " " + tree["name"]
    if tree.get("note"):
        heading += " — " + tree["note"]
    lines = [heading]
    for child in tree.get("children", []):
        lines.append(render_markdown(child, depth + 1))
    return "\n".join(lines)


def count_nodes(tree: dict) -> int:
    return 1 + sum(count_nodes(c) for c in tree.get("children", []))


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_outputs(out_dir: Path, md: str, meta: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(out_dir / "project_map.md", md)
    _atomic_write(out_dir / "meta.json", json.dumps(meta, ensure_ascii=False, indent=2))


def run(root: Path, out_dir: Path, force: bool = False, annot_path: Path | None = None) -> str:
    """执行一轮:扫描→(Task 2: 快照对比;Task 3: 注解合并)→重建。返回日志行。"""
    try:
        tree = scan_tree(root)
        md = render_markdown(tree)
        try:
            git_head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, timeout=10
            ).stdout.decode().strip()
        except Exception:
            git_head = ""
        meta = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "node_count": count_nodes(tree),
            "changed_files": [],
            "git_head": git_head,
        }
        write_outputs(out_dir, md, meta)
        return "rebuilt"
    except Exception as e:
        return f"error: {e!r}"


def main() -> None:
    force = "--force" in sys.argv[1:]
    line = run(ROOT, OUT_DIR, force)
    try:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(SYNC_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except OSError:
        pass
    print(line)
    if line.startswith("error"):
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `/home/tdxback/venv-data/bin/python -m pytest tests/test_mindmap_generator.py -v`
Expected: PASS(若 `import tools.mindmap_generator` 因 `tools/` 缺 `__init__.py` 失败,在测试文件顶部加:
```python
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mindmap_generator as mg
```
并把 `tools.mindmap_generator` 换成 `mindmap_generator`,同步改测试。若 test_count_nodes 期望数与树不符,按实际树节点数校正该断言。)

- [ ] **Step 5: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add tools/mindmap_generator.py tests/test_mindmap_generator.py
git commit -m "feat: 思维导图生成器核心(扫描/markdown渲染/产物写入)

纯 stdlib;产物 data/mindmap/ 挂载进容器供页面读取。

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: 快照对比与变更检测(有变更才重建)

**Files:**
- Modify: `tools/mindmap_generator.py`(`run()` 加快照逻辑;新增两个函数)
- Test: `tests/test_mindmap_generator.py`(追加)

**Interfaces:**
- Consumes: `scan_tree`、`_atomic_write`(Task 1)
- Produces:
  - `build_snapshot(root: Path, tree: dict) -> dict` — `{"paths": {relpath: [mtime, size]}, "generated_at": str}`(只跟踪 file 节点)
  - `diff_snapshot(old: dict, new: dict) -> list[str]` — 新增/删除/修改的相对路径,排序返回
  - `run()` 新版行为:快照无变化且非 force → 返回 `"unchanged"`,不写产物;有变化 → 重建并把 `changed_files` 写进 meta;快照经 `_atomic_write` 写入 `out_dir/.snapshot.json`

- [ ] **Step 1: 写失败测试(追加到 tests/test_mindmap_generator.py)**

```python
def test_snapshot_diff_and_rebuild_on_change(tmp_path):
    root = make_repo(tmp_path)
    out_dir = tmp_path / "out"
    no_annot = root / "nope.json"  # 不存在的注解路径,隔离真实注解文件
    # 第一轮:重建
    assert mg.run(root, out_dir, annot_path=no_annot).startswith("rebuilt")
    md_mtime_1 = (out_dir / "project_map.md").stat().st_mtime
    snapshot = json.loads((out_dir / ".snapshot.json").read_text(encoding="utf-8"))
    assert snapshot["paths"]
    # 第二轮:无变化 → unchanged,产物 mtime 不变
    assert mg.run(root, out_dir, annot_path=no_annot) == "unchanged"
    assert (out_dir / "project_map.md").stat().st_mtime == md_mtime_1
    # 第三轮:改一个文件 → 重建,changed_files 含该文件
    (root / "app.py").write_text("print('changed')")
    time.sleep(0.05)  # 保证 mtime 变化
    assert mg.run(root, out_dir, annot_path=no_annot).startswith("rebuilt")
    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    assert "app.py" in meta["changed_files"]
    # 第四轮:force 参数无条件重建
    assert mg.run(root, out_dir, force=True, annot_path=no_annot).startswith("rebuilt")
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/tdxback/venv-data/bin/python -m pytest tests/test_mindmap_generator.py::test_snapshot_diff_and_rebuild_on_change -v`
Expected: FAIL(`unchanged` 断言失败,当前实现每次 rebuilt)

- [ ] **Step 3: 实现快照对比**

在 `tools/mindmap_generator.py` 的 `write_outputs` 之后追加:

```python
def build_snapshot(root: Path, tree: dict) -> dict:
    """只跟踪 file 节点:relpath -> [mtime, size]。目录增删由文件路径体现。"""
    paths = {}

    def collect(node):
        if node["type"] == "file":
            try:
                st = (root / node["path"]).stat()
                paths[node["path"]] = [int(st.st_mtime), st.st_size]
            except OSError:
                pass
        for c in node.get("children", []):
            collect(c)

    collect(tree)
    return {"paths": paths, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def diff_snapshot(old: dict, new: dict) -> list[str]:
    old_paths = old.get("paths", {})
    new_paths = new.get("paths", {})
    changed = []
    for p, meta in new_paths.items():
        if p not in old_paths or old_paths[p] != meta:
            changed.append(p)
    for p in old_paths:
        if p not in new_paths:
            changed.append(p)
    return sorted(changed)
```

并把 `run()` 改为:

```python
def run(root: Path, out_dir: Path, force: bool = False, annot_path: Path | None = None) -> str:
    """执行一轮:扫描→快照对比→(Task 3: 注解合并)→重建。返回日志行。"""
    try:
        tree = scan_tree(root)
        new_snapshot = build_snapshot(root, tree)
        old_snapshot = {}
        snapshot_path = out_dir / ".snapshot.json"
        if snapshot_path.exists():
            try:
                old_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                old_snapshot = {}
        changed = diff_snapshot(old_snapshot, new_snapshot)
        if not force and old_snapshot.get("paths") and not changed:
            return "unchanged"
        md = render_markdown(tree)
        try:
            git_head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, timeout=10
            ).stdout.decode().strip()
        except Exception:
            git_head = ""
        meta = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "node_count": count_nodes(tree),
            "changed_files": changed,
            "git_head": git_head,
        }
        write_outputs(out_dir, md, meta)
        _atomic_write(snapshot_path, json.dumps(new_snapshot, ensure_ascii=False, indent=2))
        return f"rebuilt ({len(changed)} changed)"
    except Exception as e:
        return f"error: {e!r}"
```

- [ ] **Step 4: 运行确认通过**

Run: `/home/tdxback/venv-data/bin/python -m pytest tests/test_mindmap_generator.py -v`
Expected: 全部 PASS(Task 1 的 run 端到端测试首轮 rebuilt 不受影响)

- [ ] **Step 5: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add tools/mindmap_generator.py tests/test_mindmap_generator.py
git commit -m "feat: 思维导图快照对比,有变更才重建

cron 每分钟空跑开销最小化;changed_files 写入 meta 供页面展示。

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: 注解合并(JSON)+ 容错

**Files:**
- Modify: `tools/mindmap_generator.py`(`run()` 接入注解;新增两个函数)
- Test: `tests/test_mindmap_generator.py`(追加)

**Interfaces:**
- Consumes: `scan_tree`、`render_markdown`(Task 1/2)
- Produces:
  - `load_annotations(annot_path: Path) -> tuple[dict, dict, list[str]]` — `(file_notes: {relpath: note}, groups: {组名: [relpath]}, errors)`,文件不存在/格式错时返回空结构 + errors 而非抛异常
  - `apply_annotations(tree: dict, file_notes: dict, groups: dict) -> tuple[dict, list[str]]` — 文件节点写 `note`;groups 把根级文件归入分组节点(`type: "group"`);成员路径不存在记 warnings。返回(新树, warnings)
  - `run()` 新版:`annot_path` 默认 `DEFAULT_ANNOT_PATH`;日志行追加注解错误/警告

- [ ] **Step 1: 写失败测试(追加)**

```python
def _write_annotations(root: Path) -> Path:
    annot = root / "mindmap_annotations.json"
    annot.write_text(json.dumps({
        "files": {"app.py": "入口文件"},
        "groups": {"我的模块": ["app.py", "不存在的.py"]},
    }, ensure_ascii=False), encoding="utf-8")
    return annot


def test_annotations_merge_notes_and_groups(tmp_path):
    root = make_repo(tmp_path)
    annot = _write_annotations(root)
    out_dir = tmp_path / "out"
    result = mg.run(root, out_dir, annot_path=annot)
    assert result.startswith("rebuilt")
    md = (out_dir / "project_map.md").read_text(encoding="utf-8")
    assert "# 我的模块" in md
    assert "app.py — 入口文件" in md
    assert "不存在的.py" not in md  # 分组成员缺失 → 跳过
    assert "警告: 分组成员不存在: 我的模块 -> 不存在的.py" in result  # 警告并入日志行,不阻塞


def test_annotations_invalid_json_falls_back(tmp_path):
    root = make_repo(tmp_path)
    annot = root / "mindmap_annotations.json"
    annot.write_text("{not json", encoding="utf-8")
    out_dir = tmp_path / "out"
    result = mg.run(root, out_dir, annot_path=annot)
    assert result.startswith("rebuilt")  # 注解失败不阻塞结构生成
    md = (out_dir / "project_map.md").read_text(encoding="utf-8")
    assert "app.py" in md


def test_annotations_file_missing_ok(tmp_path):
    out_dir = tmp_path / "out"
    result = mg.run(tmp_path, out_dir, annot_path=tmp_path / "nope.json")
    assert result.startswith("rebuilt")
```

- [ ] **Step 2: 运行确认失败**

Run: `/home/tdxback/venv-data/bin/python -m pytest tests/test_mindmap_generator.py::test_annotations_merge_notes_and_groups -v`
Expected: FAIL(md 中无 "# 我的模块")

- [ ] **Step 3: 实现注解合并**

在 `diff_snapshot` 之后追加:

```python
def load_annotations(annot_path: Path):
    """返回 (file_notes, groups, errors)。注解文件缺失/损坏不抛异常。"""
    if annot_path is None or not annot_path.exists():
        return {}, {}, []
    try:
        data = json.loads(annot_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {}, {}, [f"注解解析失败: {e!r}"]
    if not isinstance(data, dict):
        return {}, {}, ["注解根必须是 JSON 对象"]
    file_notes, groups, errors = {}, {}, []
    raw_files = data.get("files", {})
    if not isinstance(raw_files, dict):
        errors.append("files 区必须是对象")
        raw_files = {}
    for path, note in raw_files.items():
        if isinstance(path, str) and isinstance(note, str):
            file_notes[path] = note
    raw_groups = data.get("groups", {})
    if not isinstance(raw_groups, dict):
        errors.append("groups 区必须是对象")
        raw_groups = {}
    for name, members in raw_groups.items():
        if isinstance(name, str) and isinstance(members, list) and all(isinstance(m, str) for m in members):
            groups[name] = members
    return file_notes, groups, errors


def apply_annotations(tree: dict, file_notes: dict, groups: dict):
    """文件注解写 node['note'];groups 把根级文件归入分组节点。返回 (tree, warnings)。"""
    warnings = []

    def walk(node):
        if node["type"] == "file" and node["path"] in file_notes:
            node["note"] = file_notes[node["path"]]
        for c in node.get("children", []):
            walk(c)

    walk(tree)
    by_path = {c["path"]: c for c in tree["children"] if c["type"] == "file"}
    group_nodes = []
    for gname, members in groups.items():
        group_children = []
        for m in members:
            node = by_path.pop(m, None)
            if node is None:
                warnings.append(f"分组成员不存在: {gname} -> {m}")
            else:
                group_children.append(node)
        if group_children:
            group_nodes.append({
                "name": gname, "path": f"__group__:{gname}",
                "type": "group", "children": group_children,
            })
    tree["children"] = [
        c for c in tree["children"] if c["type"] != "file" or c["path"] in by_path
    ] + group_nodes
    tree["children"].sort(key=lambda n: (n["type"] != "dir", n["name"].lower()))
    return tree, warnings
```

并把 `run()` 中 `md = render_markdown(tree)` 一行替换为:

```python
    annot_path = annot_path or DEFAULT_ANNOT_PATH
    file_notes, groups, ann_errors = load_annotations(annot_path)
    tree, ann_warnings = apply_annotations(tree, file_notes, groups)
    md = render_markdown(tree)
```

以及 `run()` 末尾 return 改为:

```python
    detail = "; ".join([f"注解错误: {e}" for e in ann_errors] + [f"警告: {w}" for w in ann_warnings])
    return f"rebuilt ({len(changed)} changed)" + (f" | {detail}" if detail else "")
```

- [ ] **Step 4: 运行确认通过**

Run: `/home/tdxback/venv-data/bin/python -m pytest tests/test_mindmap_generator.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add tools/mindmap_generator.py tests/test_mindmap_generator.py
git commit -m "feat: 思维导图注解合并(文件说明+逻辑分组)

JSON 格式纯 stdlib 解析;注解缺失/损坏/成员不存在均降级不阻塞。

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: 初版注解内容 + 真实仓库试跑 + 修订 spec(yaml→json)

**Files:**
- Create: `tools/mindmap_annotations.json`
- Modify: `docs/superpowers/specs/2026-09-29-project-mindmap-design.md`(yaml→json 修订)

**Interfaces:**
- Consumes: `run()`(Task 3)
- Produces: 真实注解文件(以下内容全部为 2026-09-29 仓库实况文件名)

- [ ] **Step 1: 写入 tools/mindmap_annotations.json**

```json
{
  "files": {
    "app.py": "Streamlit 入口:主题注入→导航→路由分派",
    "akshare_gateway.py": "数据网关核心:五级降级链+熔断+限流+缓存",
    "data_source_manager.py": "业务侧数据门面(历史K线/财务/实时)",
    "database.py": "StockAnalysisDatabase(分析结果 JSON 存储)",
    "base_db.py": "SQLite 连接工厂(WAL/busy_timeout)",
    "base_scheduler.py": "后台线程调度基类",
    "config.py": "环境配置读取",
    "config_manager.py": "配置 UI 读写 .env",
    "deepseek_client.py": "OpenAI SDK 封装(超时/退避/各分析师 prompt)",
    "ai_agents.py": "5 分析师并行+首席汇总",
    "model_config.py": "17 个预置模型",
    "stock_analysis_engine.py": "个股东分析引擎(经 analysis_runner 统一入口)",
    "strategy_catalog.py": "全部策略清单的事实来源",
    "notification_service.py": "通知统一出口(邮件/Webhook/钉钉/飞书)",
    "logger_config.py": "日志配置(print→logger)",
    "ui_theme.py": "页面主题注入",
    "run.py": "应用启动脚本",
    "ds.sh": "启动/重启容器脚本",
    "ds_auto.sh": "容器自动化脚本",
    "look_log.sh": "日志查看脚本",
    "install_stock_cn.sh": "国内源依赖安装脚本",
    "install_stock_local.sh": "本地依赖安装脚本",
    "views/nav_model.py": "导航单一数据源 NAV(5 大类)",
    "views/page_router.py": "路由:show_* 标志分派",
    "views/analysis_runner.py": "个股东分析统一函数(禁直接调 ai_agents)",
    "indicators/registry.py": "指标注册表(partial/unsupported 语义)",
    "backtest/engine.py": "统一回测引擎",
    "interfaces/analyze.py": "统一分析接口",
    "automation/cli.py": "收盘后任务链入口 post_market",
    "pg_warehouse/sync_daily.py": "每日增量同步 PG(按 max(id)/TRUNCATE)",
    "tdx-api/README.md": "Go 通达信行情服务说明",
    "docs/项目记忆.md": "项目全貌文档(架构/模块/坑/速查)",
    "CLAUDE.md": "项目规则(分支策略/结构/约定)"
  },
  "groups": {
    "缠论选股": [
      "chanlun_engine.py", "chanlun_batch.py", "chanlun_selector.py",
      "chanlun_universe.py", "chanlun_signal_db.py", "chanlun_single.py",
      "chanlun_ui.py", "chanlun_chart_ui.py", "chanlun_schedule.sh"
    ],
    "六脉神剑": [
      "liumai_engine.py", "liumai_batch.py", "liumai_selector.py",
      "liumai_signal_db.py", "liumai_ui.py"
    ],
    "缠论×六脉组合": [
      "combo_batch.py", "combo_selector.py", "combo_signal_db.py", "combo_ui.py"
    ],
    "起涨预测": [
      "qizhang_batch.py", "qizhang_picks_db.py", "qizhang_predict_ui.py", "qizhang_schedule.sh"
    ],
    "新闻流量监测": [
      "news_fetch.py", "news_flow_agents.py", "news_flow_alert.py",
      "news_flow_data.py", "news_flow_db.py", "news_flow_engine.py",
      "news_flow_model.py", "news_flow_pdf.py", "news_flow_scheduler.py",
      "news_flow_sentiment.py", "news_flow_ui.py", "news_announcement_data.py",
      "qstock_news_data.py"
    ],
    "智策板块": [
      "sector_strategy_agents.py", "sector_strategy_data.py", "sector_strategy_db.py",
      "sector_strategy_engine.py", "sector_strategy_pdf.py", "sector_strategy_scheduler.py",
      "sector_strategy_ui.py"
    ],
    "智瞰龙虎": [
      "longhubang_agents.py", "longhubang_data.py", "longhubang_db.py",
      "longhubang_engine.py", "longhubang_pdf.py", "longhubang_scoring.py",
      "longhubang_ui.py"
    ],
    "主力选股": [
      "main_force_analysis.py", "main_force_batch_db.py", "main_force_history_ui.py",
      "main_force_pdf_generator.py", "main_force_selector.py", "main_force_ui.py"
    ],
    "智能盯盘": [
      "smart_monitor_data.py", "smart_monitor_db.py", "smart_monitor_deepseek.py",
      "smart_monitor_engine.py", "smart_monitor_kline.py", "smart_monitor_qmt.py",
      "smart_monitor_tdx_data.py", "smart_monitor_ui.py", "miniqmt_interface.py",
      "monitor_db.py", "monitor_manager.py", "monitor_scheduler.py",
      "monitor_service.py", "monitor_ui.py"
    ],
    "持仓分析": [
      "portfolio_db.py", "portfolio_manager.py", "portfolio_scheduler.py", "portfolio_ui.py"
    ],
    "宏观分析": [
      "macro_analysis_agents.py", "macro_analysis_data.py", "macro_analysis_engine.py",
      "macro_analysis_ui.py"
    ],
    "宏观周期": [
      "macro_cycle_agents.py", "macro_cycle_data.py", "macro_cycle_engine.py",
      "macro_cycle_pdf.py", "macro_cycle_ui.py"
    ],
    "产业链": [
      "industry_chain_data.py", "industry_chain_ui.py"
    ],
    "低价擒牛": [
      "low_price_bull_monitor.py", "low_price_bull_monitor_ui.py", "low_price_bull_selector.py",
      "low_price_bull_service.py", "low_price_bull_strategy.py", "low_price_bull_ui.py"
    ],
    "小市值": ["small_cap_selector.py", "small_cap_ui.py"],
    "净利增长": ["profit_growth_monitor.py", "profit_growth_selector.py", "profit_growth_ui.py"],
    "价值选股": ["value_stock_selector.py", "value_stock_strategy.py", "value_stock_ui.py"],
    "稳定选股": ["stable_ui.py"],
    "基础数据与网关": [
      "fund_flow_akshare.py", "risk_data_fetcher.py", "quarterly_report_data.py",
      "market_sentiment_data.py", "stock_data.py", "update_env_example.py",
      "pdf_generator.py", "current_strategy_ui.py", "sector_detail_ui.py"
    ]
  }
}
```

- [ ] **Step 2: 真实仓库试跑**

Run: `cd /home/tdxback/aiagents-stock && /home/tdxback/venv-data/bin/python tools/mindmap_generator.py --force`
Expected: 输出 `rebuilt (N changed)`;随后:
```bash
ls -la data/mindmap/
head -30 data/mindmap/project_map.md
python3 -c "import json; print(json.load(open('data/mindmap/meta.json'))['node_count'])"
```
Expected: project_map.md / meta.json / .snapshot.json / sync.log 存在;首行为 `# aiagents-stock`;node_count > 100。若日志行含"警告: 分组成员不存在",把注解里对应文件名改成实际存在的(拼写校正)后重跑,直到无警告。

- [ ] **Step 3: 修订 spec(yaml→json)**

对 `docs/superpowers/specs/2026-09-29-project-mindmap-design.md` 做 5 处替换:
1. §2 表格「导图内容」行:`tools/mindmap_annotations.yaml` → `tools/mindmap_annotations.json`
2. §3.1 组件表注解行:`.yaml` → `.json`
3. §3.4 标题与示例:`### 3.4 注解合并(tools/mindmap_annotations.yaml)` → `.json`;示例 yaml 块改为:
   ```json
   {"files": {"chanlun_engine.py": "缠论引擎(简化缠论:分型→笔→线段→中枢→MACD背驰)"},
    "groups": {"缠论选股": ["chanlun_engine.py", "chanlun_batch.py"]}}
   ```
   并加一句:格式为 JSON 而非 yaml,保持生成器纯 stdlib(宿主 venv-data 无 PyYAML)
4. §3.7 表格「注解 yaml 格式错」行 → 「注解 JSON 格式错」
5. §5.1:`.yaml` → `.json`

- [ ] **Step 4: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add tools/mindmap_annotations.json docs/superpowers/specs/2026-09-29-project-mindmap-design.md
git commit -m "feat: 思维导图初版注解(20 逻辑分组+40 文件说明);spec 注解格式 yaml→json

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: Streamlit 页面 + 导航/路由 + smoke 测试

**Files:**
- Create: `mindmap_ui.py`
- Modify: `views/nav_model.py`(文档大类加一行)、`views/page_router.py`(docs 分支后加一段)、`tests/test_ui_pages_smoke.py`(PAGE_FLAGS + 新测试)

**Interfaces:**
- Consumes: 产物 `data/mindmap/project_map.md` + `meta.json`(容器内路径 `/app/data/mindmap/`,与 `Path(__file__).parent / "data"` 一致)
- Produces: `display_mindmap()` 页面入口;`show_mindmap` 路由标志

- [ ] **Step 1: 写失败测试(tests/test_ui_pages_smoke.py)**

PAGE_FLAGS 列表加 `"show_mindmap"`,并追加:

```python
def test_mindmap_page_renders():
    at = AppTest.from_file("app.py", default_timeout=180)
    at.session_state["show_mindmap"] = True
    at.run()
    assert not at.exception, at.exception
    text = "\n".join(str(el.value) for el in at.markdown)
    assert "项目思维导图" in text
```

- [ ] **Step 2: 失败验证说明(容器约束)**

TDD 失败验证在此省略,原因:容器内测试文件同样烤进镜像,重建前容器跑不到新增测试;宿主机 venv-data 无 streamlit(AppTest 不可用)。替代:宿主机语法检查:
`cd /home/tdxback/aiagents-stock && /home/tdxback/venv-data/bin/python -m py_compile mindmap_ui.py views/nav_model.py views/page_router.py tests/test_ui_pages_smoke.py`
Expected: 无输出(编译通过);门禁为 Step 5 重建后的容器测试通过。

- [ ] **Step 3: 创建 mindmap_ui.py**

```python
"""项目思维导图页:读取 data/mindmap 产物,markmap 渲染,60 秒定时刷新。

产物由宿主机 crontab 每分钟运行 tools/mindmap_generator.py 生成(挂载即时可见)。
"""
import html
import json
from pathlib import Path

import streamlit as st

MINDMAP_DIR = Path(__file__).resolve().parent / "data" / "mindmap"
MD_PATH = MINDMAP_DIR / "project_map.md"
META_PATH = MINDMAP_DIR / "meta.json"

_MARKMAP_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  html, body {{ margin: 0; padding: 6px 10px; height: 100%; background: transparent; }}
  #fallback {{ display: none; color: #e06c75; font-size: 14px; padding: 12px; }}
  .markmap svg {{ background: transparent; }}
</style></head><body>
<div class="markmap"><script type="text/template">
{md}
</script></div>
<div id="fallback">脑图 JS 加载失败(CDN 不可达),请检查浏览器网络/代理后刷新本页。</div>
<script>
  setTimeout(function () {{
    if (!document.querySelector('.markmap svg')) {{
      document.getElementById('fallback').style.display = 'block';
    }}
  }}, 4000);
</script>
<script src="https://cdn.jsdelivr.net/npm/markmap-autoloader@0.18"></script>
</body></html>
"""


def _load():
    """读取产物;缺失返回 (None, None)。"""
    if not MD_PATH.exists():
        return None, None
    md = MD_PATH.read_text(encoding="utf-8")
    meta = {}
    if META_PATH.exists():
        try:
            meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
    return md, meta


def display_mindmap():
    st.markdown("## 🧠 项目思维导图")
    st.caption("宿主机每分钟检测项目变更并自动重建导图;本页每 60 秒自动刷新。")

    @st.fragment(run_every=60)
    def _render():
        md, meta = _load()
        if md is None:
            st.info("导图尚未生成。宿主机 crontab 每分钟扫描项目,首次使用请等待 ≤2 分钟,"
                    "或手动执行 `tools/mindmap_generator.py --force`。")
            return
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("生成时间", meta.get("generated_at", "—"))
        c2.metric("节点数", meta.get("node_count", "—"))
        c3.metric("最近变更文件", len(meta.get("changed_files", [])))
        c4.metric("Git HEAD", (meta.get("git_head") or "—")[:8])
        st.components.v1.html(
            _MARKMAP_TEMPLATE.format(md=html.escape(md)), height=720, scrolling=True
        )

    _render()
    if st.button("🔄 立即刷新", use_container_width=True):
        st.rerun()
```

- [ ] **Step 4: 修改导航与路由**

`views/nav_model.py` 文档大类「🗂️ 目录说明」之后加一行:

```python
        ("🧠 项目思维导图", "show_mindmap", "项目结构实时思维导图(宿主机每分钟自动重建)"),
```

`views/page_router.py` 在 `show_docs_scan` 分支之后、`return False` 之前加:

```python
    if st.session_state.get('show_mindmap'):
        from mindmap_ui import display_mindmap
        display_mindmap()
        return True
```

- [ ] **Step 5: 重建镜像并容器内验证通过**

Run: `cd /home/tdxback/aiagents-stock && docker compose build agentsstock && docker compose up -d agentsstock1 && docker exec agentsstock1 python3 -m pytest tests/test_ui_pages_smoke.py -v`
Expected: 构建成功;容器 healthy(约 1-2 分钟);smoke 全部 PASS(含 test_mindmap_page_renders)

- [ ] **Step 6: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add mindmap_ui.py views/nav_model.py views/page_router.py tests/test_ui_pages_smoke.py
git commit -m "feat: 项目思维导图页面(markmap 渲染+60s 自动刷新)

文档大类新增「🧠 项目思维导图」;产物缺失时降级提示不报错。

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: 部署配套(.gitignore + 项目文档)

**Files:**
- Modify: `.gitignore`、`docs/项目记忆.md`、`CLAUDE.md`

- [ ] **Step 1: .gitignore 补产物目录**

`.gitignore` 的 `data/*.db` 行后加:

```
# 思维导图产物(宿主机 cron 生成,不入库)
data/mindmap/
```

- [ ] **Step 2: 更新 docs/项目记忆.md**

1. §3 代码地图「入口/UI 层」末尾加一行:
   `- mindmap_ui.py — 「🧠 项目思维导图」页(markmap 渲染,60s 自动刷新,读 data/mindmap 产物)`
2. §3 代码地图「数据层」之前新增一小节:

   ```markdown
   **运维工具**
   - `tools/mindmap_generator.py` — 项目思维导图生成器(纯 stdlib):宿主机 cron 每分钟扫描仓库,快照对比有变更才重建,产物 `data/mindmap/project_map.md`+`meta.json` 挂载进容器
   - `tools/mindmap_annotations.json` — 导图注解(文件说明+逻辑分组),手工维护
   ```

3. §7 调度体系 crontab 表加一行:
   `| 每分钟 | tools/mindmap_generator.py | 快照对比,有变更才重建思维导图产物 data/mindmap/(页面 60s 刷新) |`
4. §11 坑清单加一条:
   `9. 思维导图产物在 data/mindmap/(不入库);改 tools/mindmap_annotations.json 后下分钟自动生效;改 mindmap_ui.py 需重建镜像`

- [ ] **Step 3: 更新 CLAUDE.md 项目结构小节**

「顶层四个自建包」列表之后加一行:

```markdown
- **`tools/`** 运维脚本:`mindmap_generator.py`(项目思维导图:宿主 cron 每分钟快照检测重建,产物 `data/mindmap/`,页面 `mindmap_ui.py` 60s 刷新)。
```

- [ ] **Step 4: 提交**

```bash
cd /home/tdxback/aiagents-stock
git add .gitignore docs/项目记忆.md CLAUDE.md
git commit -m "docs: 思维导图子系统入项目记忆与规则文档

Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: 重建镜像 + 全量验证

**Files:**
- 无(部署操作)

- [ ] **Step 1: 确认容器状态**

Run: `cd /home/tdxback/aiagents-stock && docker compose ps`
Expected: agentsstock1 healthy(Task 5 Step 5 已重建镜像;若此前未执行重建,先跑 `docker compose build agentsstock && docker compose up -d agentsstock1`)

- [ ] **Step 2: 宿主机侧生成器全量测试**

Run: `cd /home/tdxback/aiagents-stock && /home/tdxback/venv-data/bin/python -m pytest tests/test_mindmap_generator.py -v`
Expected: 全部 PASS

- [ ] **Step 3: 容器内 UI smoke 全量测试**

Run: `docker exec agentsstock1 python3 -m pytest tests/test_ui_pages_smoke.py -v`
Expected: 全部 PASS(含 test_mindmap_page_renders)

- [ ] **Step 4: 真实产物验证**

```bash
cd /home/tdxback/aiagents-stock
/home/tdxback/venv-data/bin/python tools/mindmap_generator.py --force
docker exec agentsstock1 ls -la /app/data/mindmap/
docker exec agentsstock1 head -5 /app/data/mindmap/project_map.md
curl -sf http://localhost:8503/_stcore/health && echo " app healthy"
```
Expected: 容器内可见 project_map.md/meta.json/.snapshot.json/sync.log;首行 `# aiagents-stock`;health 返回 ok

- [ ] **Step 5: 无变更空跑验证(实时更新链路)**

```bash
cd /home/tdxback/aiagents-stock
/home/tdxback/venv-data/bin/python tools/mindmap_generator.py   # 应输出 unchanged
touch tools/mindmap_generator.py && sleep 1
/home/tdxback/venv-data/bin/python tools/mindmap_generator.py   # 应输出 rebuilt (1 changed)
git checkout tools/mindmap_generator.py 2>/dev/null || true
```
Expected: 第一次 `unchanged`,改 mtime 后 `rebuilt (1 changed)`

- [ ] **Step 6: 告知用户浏览器验证**

在浏览器打开 `http://localhost:8503` → 文档 → 🧠 项目思维导图,确认:脑图渲染(辐射状)、折叠/缩放可用、顶部 4 个指标有值、无红色 fallback 提示。

---

### Task 8: crontab 第 5 条 + 持久记忆(用户确认后执行)

**Files:**
- Modify: 宿主机 crontab(第 5 条)
- Create: `/home/tdxback/.claude/projects/-home-tdxback/memory/project-mindmap.md`、`MEMORY.md` 索引行

- [ ] **Step 1: 给用户看 crontab 行并确认**

展示:
```
* * * * * /home/tdxback/venv-data/bin/python /home/tdxback/aiagents-stock/tools/mindmap_generator.py
```
用户确认后执行:
```bash
( crontab -l 2>/dev/null | grep -v 'mindmap_generator' ; echo "* * * * * /home/tdxback/venv-data/bin/python /home/tdxback/aiagents-stock/tools/mindmap_generator.py" ) | crontab -
crontab -l | tail -6
```
Expected: 共 5 条,新增一条 mindmap_generator

- [ ] **Step 2: 等待一个 cron 周期验证自愈**

Run: `sleep 70 && tail -3 /home/tdxback/aiagents-stock/data/mindmap/sync.log`
Expected: 出现一条 `unchanged` 记录(说明 cron 每分钟在跑)

- [ ] **Step 3: 写 Claude 持久记忆**

`/home/tdxback/.claude/projects/-home-tdxback/memory/project-mindmap.md`:

```markdown
---
name: project-mindmap
description: aiagents-stock 项目思维导图子系统:要求「项目改动实时更新思维导图」,组件/产物/cron 位置
metadata:
  type: project
---

用户要求(2026-09-29):整个项目思维导图在前台页面展示,项目代码有改动要实时更新。

实现(与 [[aiagents-stock-project]] 相关):
- 生成器 `/home/tdxback/aiagents-stock/tools/mindmap_generator.py`(纯 stdlib),宿主机 crontab **每分钟**第 5 条运行,快照对比有变更才重建
- 注解 `tools/mindmap_annotations.json`(文件说明+逻辑分组,手工维护,改后下分钟生效)
- 产物 `data/mindmap/project_map.md`+`meta.json`(不入库,挂载进容器即时可见)
- 页面 `mindmap_ui.py`「🧠 项目思维导图」(show_mindmap,markmap 渲染,st.fragment 60s 自动刷新);改页面代码需重建 agentsstock 镜像
- 设计文档 docs/superpowers/specs/2026-09-29-project-mindmap-design.md
```

`MEMORY.md` 追加一行:
```markdown
- [Project mindmap](project-mindmap.md) — 项目改动实时更新思维导图:生成器/注解/产物/页面/cron 位置
```

- [ ] **Step 4: 汇报完成**

向用户汇报:页面入口、cron 条目、产物位置、延迟上界(≤2 分钟),并提醒推送由用户自行执行。
