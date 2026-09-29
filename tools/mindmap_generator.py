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


def _exclude_out_dir(tree: dict, root: Path, out_dir: Path) -> None:
    """把产物目录从树中移除:产物不得回流成输入,否则快照永不稳定(out_dir 位于 root 内时)。"""
    try:
        rel_out = out_dir.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return
    stack = [tree]
    while stack:
        node = stack.pop()
        node["children"] = [c for c in node.get("children", []) if c["path"] != rel_out]
        stack.extend(c for c in node["children"] if c["type"] == "dir")


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


def run(root: Path, out_dir: Path, force: bool = False, annot_path: Path | None = None) -> str:
    """执行一轮:扫描→快照对比→(Task 3: 注解合并)→重建。返回日志行。"""
    try:
        tree = scan_tree(root)
        _exclude_out_dir(tree, root, out_dir)
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
