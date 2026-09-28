# -*- coding: utf-8 -*-
"""Task 6.4: 资产变动自动更新机制(Phase6 收官)。

消费 automation.home_scan.scan_home 与 docs/home_scan.json 快照,对比
两次扫描差异,供 SessionStart hook 静默快检(有变化才输出,不阻塞会话):

- asset_diff(current=None): 以 path 为键对比快照与当前扫描(递归摊平
  「展开条目」),返回 {added, removed, changed, summary};
  changed 阈值 = size 相对差 > 5%(CHANGE_SIZE_RATIO,严格大于);
  mtime 未提供(任一侧)时保守判定——大小有任何差异即视为变化;
  快照缺失/损坏视为空快照(首次运行:全部新增)。
- watch(notify_on_change=True): 跑一次扫描 + diff,有变化时 print 摘要
  并把当前扫描写回快照(变动自动更新:基线前进),无变化完全静默。

已知盲区(2026-09-28 终审记录):仓库根 /home/tdxback/aiagents-stock 在快照中为
顶层大目录(大目录=True,无「展开条目」),只以聚合 size_mb 参与 diff,对项目内
文件级变动不敏感——本仓库 ≈23.5GB(size_mb 23543.309),需聚合体积变动超 5%
(≈1.2GB)才触发 changed;项目内新增/删除脚本、改文档等小改动不会告警。建议后续
为仓库增顶层扫描基线(展开到子目录/文件级),以提高变动检测灵敏度。

只依赖标准库 + automation.home_scan。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from automation.home_scan import DEFAULT_ROOT, scan_home

CHANGE_SIZE_RATIO = 0.05  # changed 阈值:size 相对差 >5%(以旧值为基)
_MAX_PRINT_PATHS = 10     # 摘要打印每条目类别最多列出的路径数

SNAPSHOT_PATH: Path = Path(__file__).resolve().parent.parent / "docs" / "home_scan.json"


def _read_snapshot() -> Dict[str, Any]:
    """读取快照;缺失/损坏时返回空快照(首次运行:全部视为新增)。"""
    try:
        data = json.loads(Path(SNAPSHOT_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"entries": [], "summary": {}}
    if not isinstance(data, dict):
        return {"entries": [], "summary": {}}
    if not isinstance(data.get("entries"), list):
        data["entries"] = []
    if not isinstance(data.get("summary"), dict):
        data["summary"] = {}
    return data


def _flatten_entries(entries: List[dict], out: Dict[str, dict]) -> None:
    """把 entries(含嵌套「展开条目」)摊平为 {path: entry}。"""
    for e in entries:
        path = e.get("path")
        if path:
            out[path] = e
        subs = e.get("展开条目")
        if isinstance(subs, list):
            _flatten_entries(subs, out)


def _is_changed(old: Dict[str, Any], new: Dict[str, Any]) -> bool:
    """单条目变动判定。

    - size 缺失/不可解析任一侧:保守视为变化;
    - size 相对差(以旧值为基,size 取 3 位小数)> CHANGE_SIZE_RATIO:变化;
    - size 完全一致:未变化;
    - size 有差异但未超阈值:mtime 未提供(任一侧)时保守判定为变化,
      mtime 都提供时不判变化(阈值以 size 为准)。
    """
    try:
        o_size = round(float(old.get("size_mb")), 3)
        n_size = round(float(new.get("size_mb")), 3)
    except (TypeError, ValueError):
        return True
    if n_size == o_size:
        return False
    # size_mb 为 3 位小数,相对差取 3 位精度避免浮点边界误判(如 1.0→1.05
    # 的浮点误差 0.050000000000000044 恰好落在 5% 阈值边缘)
    rel = round(abs(n_size - o_size) / o_size, 3) if o_size else 1.0
    if rel > CHANGE_SIZE_RATIO:
        return True
    o_m = (old.get("mtime") or "").strip()
    n_m = (new.get("mtime") or "").strip()
    return not (o_m and n_m)  # mtime 未提供:保守判定为变化


def _diff(snapshot: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    old_map: Dict[str, dict] = {}
    _flatten_entries(snapshot.get("entries", []), old_map)
    new_map: Dict[str, dict] = {}
    _flatten_entries(current.get("entries", []), new_map)
    added = sorted(set(new_map) - set(old_map))
    removed = sorted(set(old_map) - set(new_map))
    changed = sorted(p for p in (set(old_map) & set(new_map))
                     if _is_changed(old_map[p], new_map[p]))
    summary = {
        "added": len(added),
        "removed": len(removed),
        "changed": len(changed),
        "total": len(added) + len(removed) + len(changed),
        "snapshot_generated_at": snapshot.get("generated_at", ""),
        "current_generated_at": current.get("generated_at", ""),
    }
    return {"added": added, "removed": removed, "changed": changed,
            "summary": summary}


def asset_diff(current: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """对比快照与当前扫描(缺省现场扫描),返回 {added, removed, changed, summary}。

    扫描根目录取快照 summary.root,缺失时回退 home_scan.DEFAULT_ROOT。
    """
    snapshot = _read_snapshot()
    if current is None:
        root = (snapshot.get("summary") or {}).get("root") or DEFAULT_ROOT
        current = scan_home(root)
    return _diff(snapshot, current)


def _fmt_paths(paths: List[str]) -> str:
    if len(paths) <= _MAX_PRINT_PATHS:
        return " ".join(paths)
    return " ".join(paths[:_MAX_PRINT_PATHS]) + f" 等 {len(paths)} 项"


def _print_summary(diff: Dict[str, Any]) -> None:
    s = diff["summary"]
    print(f"[asset_watch] 资产变动(上次快照 {s['snapshot_generated_at'] or '未知'},"
          f"本次扫描 {s['current_generated_at'] or '未知'}):"
          f" 新增 {s['added']} / 删除 {s['removed']} / 变更 {s['changed']}")
    if diff["added"]:
        print("  新增: " + _fmt_paths(diff["added"]))
    if diff["removed"]:
        print("  删除: " + _fmt_paths(diff["removed"]))
    if diff["changed"]:
        print("  变更: " + _fmt_paths(diff["changed"]))
    print(f"[asset_watch] 快照已刷新: {SNAPSHOT_PATH}")


def _write_snapshot(current: Dict[str, Any]) -> None:
    path = Path(SNAPSHOT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def watch(notify_on_change: bool = True) -> None:
    """跑一次扫描 + diff:有变化时打印摘要并刷新快照,无变化完全静默。

    供 SessionStart hook 调用:async 静默快检,有变化才输出。
    notify_on_change=False 时只刷新快照不打印。
    """
    try:
        snapshot = _read_snapshot()
        root = (snapshot.get("summary") or {}).get("root") or DEFAULT_ROOT
        current = scan_home(root)
        diff = _diff(snapshot, current)
        if not (diff["added"] or diff["removed"] or diff["changed"]):
            return  # 无变化:完全静默
        if notify_on_change:
            _print_summary(diff)
        _write_snapshot(current)  # 变动自动更新:刷新快照基线
    except Exception as exc:  # hook 场景兜底:失败仅在异常时输出,不抛出
        print(f"[asset_watch] 执行失败: {exc!r}")


def main() -> int:
    watch()
    return 0


if __name__ == "__main__":
    sys.exit(main())
