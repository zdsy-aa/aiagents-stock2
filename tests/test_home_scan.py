# -*- coding: utf-8 -*-
"""Task 6.1 全目录扫描器测试(Phase6)。

覆盖:
- 小目录夹具的类别判定(项目/数据/文档);
- 大目录只统计不展开(monkeypatch 调低 LARGE_DIR_MB 触发);
- entries 按 size_mb 降序;
- top_only 模式只列顶层、不产生递归展开。
"""
import automation.home_scan as hs


def test_scan_small_fixture(tmp_path):
    (tmp_path / "proj").mkdir(); (tmp_path / "proj" / "a.py").write_text("x")
    (tmp_path / "data").mkdir(); (tmp_path / "data" / "big.db").write_bytes(b"0" * 100)
    (tmp_path / "note.md").write_text("# 标题")
    r = hs.scan_home(root=str(tmp_path))
    assert set(r["summary"]["categories"]) >= {"项目", "数据", "文档"}
    assert any(e["category"] == "项目" for e in r["entries"])


def test_large_dir_not_expanded(tmp_path, monkeypatch):
    big = tmp_path / "big"; big.mkdir()
    for i in range(50):
        (big / f"f{i}.dat").write_bytes(b"0" * 1000)
    monkeypatch.setattr(hs, "LARGE_DIR_MB", 0.001)     # 阈值调低触发
    r = hs.scan_home(root=str(tmp_path))
    entry = [e for e in r["entries"] if e["path"].endswith("big")][0]
    assert entry["category"] == "数据" and "展开条目" not in entry


def test_entries_sorted_by_size_desc(tmp_path):
    (tmp_path / "small.txt").write_text("x")
    (tmp_path / "large.txt").write_text("x" * 1000)
    (tmp_path / "mid").mkdir()
    (tmp_path / "mid" / "f.txt").write_text("x" * 5000)
    r = hs.scan_home(root=str(tmp_path))
    sizes = [e["size_mb"] for e in r["entries"]]
    assert sizes == sorted(sizes, reverse=True)
    assert [e["path"].rsplit("/", 1)[-1] for e in r["entries"] if e["size_mb"] > 0] \
        == ["mid", "large.txt"]


def test_top_only_lists_single_level(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "inner").mkdir()
    (tmp_path / "d" / "inner" / "f.py").write_text("x" * 5000)
    r = hs.scan_home(root=str(tmp_path), top_only=True)
    assert [e["kind"] for e in r["entries"]] == ["dir"]
    assert all("展开条目" not in e for e in r["entries"])
    # top_only 仍统计目录总大小与顶层条目数
    d = r["entries"][0]
    assert d["顶层条目数"] == 1 and d["size_mb"] > 0
