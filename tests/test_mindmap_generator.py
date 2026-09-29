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
