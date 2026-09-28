# -*- coding: utf-8 -*-
"""Task 6.4 资产变动自动更新机制测试(Phase6)。

覆盖:
- asset_diff 以 path 为键对比快照:added/removed/changed;
- changed 阈值 = size 相对差 >5%(恰好 5% 不算,6% 算);
- mtime 未提供时的保守判定(大小有差异但未超阈值 → 视为变化);
- mtime 都提供且大小差未超阈值 → 未变化;
- 快照缺失时全部视为新增;
- 嵌套「展开条目」参与对比;
- watch():有变化 print 摘要并刷新快照,无变化完全静默;
- watch(notify_on_change=False):有变化也不打印,但快照仍刷新。
"""
import json

import automation.asset_watch as aw


def _patch(tmp_path, monkeypatch, snapshot_entries, current_entries,
           summary_root=""):
    snap = tmp_path / "home_scan.json"
    snap.write_text(json.dumps({"generated_at": "2026-09-28T08:00:00",
                                "entries": snapshot_entries,
                                "summary": {"root": summary_root}}),
                    encoding="utf-8")
    monkeypatch.setattr(aw, "SNAPSHOT_PATH", snap)

    def fake_scan(root):
        return {"generated_at": "2026-09-28T09:00:00",
                "entries": current_entries, "summary": {"root": root}}

    monkeypatch.setattr(aw, "scan_home", fake_scan)
    return snap


def test_asset_diff_detects_added(tmp_path, monkeypatch):
    snap = tmp_path / "home_scan.json"
    snap.write_text('{"entries": [{"path": "/x/a", "size_mb": 1}], "summary": {}}', encoding="utf-8")
    monkeypatch.setattr(aw, "SNAPSHOT_PATH", snap)
    def fake_scan(root):
        return {"entries": [{"path": "/x/a", "size_mb": 1}, {"path": "/x/b", "size_mb": 2}], "summary": {}}
    monkeypatch.setattr(aw, "scan_home", fake_scan)
    d = aw.asset_diff()
    assert d["added"] == ["/x/b"]


def test_asset_diff_detects_removed(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch,
           snapshot_entries=[{"path": "/x/a", "size_mb": 1},
                             {"path": "/x/b", "size_mb": 2}],
           current_entries=[{"path": "/x/a", "size_mb": 1}])
    d = aw.asset_diff()
    assert d["removed"] == ["/x/b"] and d["added"] == []


def test_asset_diff_changed_over_threshold(tmp_path, monkeypatch):
    # 6% > 5% 阈值:changed
    _patch(tmp_path, monkeypatch,
           snapshot_entries=[{"path": "/x/a", "size_mb": 1.0,
                              "mtime": "2026-01-01T00:00:00"}],
           current_entries=[{"path": "/x/a", "size_mb": 1.06,
                             "mtime": "2026-01-02T00:00:00"}])
    d = aw.asset_diff()
    assert d["changed"] == ["/x/a"]


def test_asset_diff_boundary_five_percent_not_changed(tmp_path, monkeypatch):
    # 恰好 5% 不超阈值(严格大于),mtime 都提供:未变化
    _patch(tmp_path, monkeypatch,
           snapshot_entries=[{"path": "/x/a", "size_mb": 1.0,
                              "mtime": "2026-01-01T00:00:00"}],
           current_entries=[{"path": "/x/a", "size_mb": 1.05,
                             "mtime": "2026-01-02T00:00:00"}])
    d = aw.asset_diff()
    assert d["changed"] == []


def test_asset_diff_drift_within_threshold_with_mtime_not_changed(tmp_path, monkeypatch):
    # 4% 漂移未超阈值,mtime 都提供:不判变化(即使 mtime 不同)
    _patch(tmp_path, monkeypatch,
           snapshot_entries=[{"path": "/x/a", "size_mb": 1.0,
                              "mtime": "2026-01-01T00:00:00"}],
           current_entries=[{"path": "/x/a", "size_mb": 1.04,
                             "mtime": "2026-01-02T00:00:00"}])
    d = aw.asset_diff()
    assert d["changed"] == []


def test_asset_diff_missing_mtime_conservative_changed(tmp_path, monkeypatch):
    # mtime 未提供:大小有差异(即便未超阈值)保守判为变化
    _patch(tmp_path, monkeypatch,
           snapshot_entries=[{"path": "/x/a", "size_mb": 1.0}],
           current_entries=[{"path": "/x/a", "size_mb": 1.04}])
    d = aw.asset_diff()
    assert d["changed"] == ["/x/a"]


def test_asset_diff_missing_mtime_equal_size_not_changed(tmp_path, monkeypatch):
    # mtime 未提供但大小完全一致:未变化
    _patch(tmp_path, monkeypatch,
           snapshot_entries=[{"path": "/x/a", "size_mb": 1.0}],
           current_entries=[{"path": "/x/a", "size_mb": 1.0}])
    d = aw.asset_diff()
    assert d["changed"] == [] and d["added"] == [] and d["removed"] == []


def test_asset_diff_missing_snapshot_all_added(tmp_path, monkeypatch):
    # 快照文件不存在:全部视为新增(首次运行)
    monkeypatch.setattr(aw, "SNAPSHOT_PATH", tmp_path / "home_scan.json")
    def fake_scan(root):
        return {"entries": [{"path": "/x/a", "size_mb": 1}], "summary": {}}
    monkeypatch.setattr(aw, "scan_home", fake_scan)
    d = aw.asset_diff()
    assert d["added"] == ["/x/a"]


def test_asset_diff_covers_nested_expanded_entries(tmp_path, monkeypatch):
    # 嵌套「展开条目」也参与 path 对比
    _patch(tmp_path, monkeypatch,
           snapshot_entries=[{"path": "/x/d", "kind": "dir", "size_mb": 1,
                              "展开条目": [{"path": "/x/d/f.txt", "size_mb": 1}]}],
           current_entries=[{"path": "/x/d", "kind": "dir", "size_mb": 1}])
    d = aw.asset_diff()
    assert d["removed"] == ["/x/d/f.txt"]


def test_asset_diff_summary_counts(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch,
           snapshot_entries=[{"path": "/x/a", "size_mb": 1},
                             {"path": "/x/gone", "size_mb": 1},
                             {"path": "/x/ch", "size_mb": 1.0}],
           current_entries=[{"path": "/x/a", "size_mb": 1},
                            {"path": "/x/new", "size_mb": 1},
                            {"path": "/x/ch", "size_mb": 1.1}])
    d = aw.asset_diff()
    s = d["summary"]
    assert (s["added"], s["removed"], s["changed"], s["total"]) == (1, 1, 1, 3)


def test_watch_prints_summary_and_refreshes_on_change(tmp_path, monkeypatch, capsys):
    snap = _patch(tmp_path, monkeypatch,
                  snapshot_entries=[{"path": "/x/a", "size_mb": 1}],
                  current_entries=[{"path": "/x/a", "size_mb": 1},
                                   {"path": "/x/b", "size_mb": 2}],
                  summary_root="/x")
    aw.watch()
    out = capsys.readouterr().out
    assert "新增" in out and "/x/b" in out
    # 变动自动更新:快照已刷新为当前扫描
    refreshed = json.loads(snap.read_text(encoding="utf-8"))
    assert [e["path"] for e in refreshed["entries"]] == ["/x/a", "/x/b"]


def test_watch_silent_and_keeps_snapshot_when_unchanged(tmp_path, monkeypatch, capsys):
    original = '{"entries": [{"path": "/x/a", "size_mb": 1}], "summary": {}}'
    snap = _patch(tmp_path, monkeypatch,
                  snapshot_entries=[{"path": "/x/a", "size_mb": 1}],
                  current_entries=[{"path": "/x/a", "size_mb": 1}])
    # 还原为原始文本以验证「无变化不写盘」
    snap.write_text(original, encoding="utf-8")
    aw.watch()
    assert capsys.readouterr().out == ""
    assert snap.read_text(encoding="utf-8") == original


def test_watch_notify_off_silent_but_refreshes(tmp_path, monkeypatch, capsys):
    snap = _patch(tmp_path, monkeypatch,
                  snapshot_entries=[{"path": "/x/a", "size_mb": 1}],
                  current_entries=[{"path": "/x/a", "size_mb": 1},
                                   {"path": "/x/b", "size_mb": 2}],
                  summary_root="/x")
    aw.watch(notify_on_change=False)
    assert capsys.readouterr().out == ""
    refreshed = json.loads(snap.read_text(encoding="utf-8"))
    assert [e["path"] for e in refreshed["entries"]] == ["/x/a", "/x/b"]
