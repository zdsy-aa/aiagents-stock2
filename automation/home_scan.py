# -*- coding: utf-8 -*-
"""Task 6.1: 全目录扫描器(Phase6 收官)。

扫描根目录(默认 /home/tdxback)顶层,输出分类快照 dict,落盘
docs/home_scan.json(含 generated_at 时间戳),供 6.2 资产说明与
6.4 变动检测(automation/asset_watch.py)消费。只依赖标准库。

接口:
    scan_home(root="/home/tdxback", top_only=False) -> dict
        {
          "generated_at": "2026-09-28T09:00:00",
          "entries": [{path, kind, size_mb, mtime, category,
                       顶层条目数?, 展开条目?, 大目录?}, ...],  # size_mb 降序
          "summary": {root, dirs, files, total_mb, top_dirs, top_files, categories}
        }

条目字段说明:
- 文件: path(绝对路径)/kind("file")/size_mb(3 位小数)/mtime/category;
- 符号链接: kind("link"),size_mb 记链接自身,不跟随(防环);
- 普通目录: 另带「顶层条目数」(直接子项个数)与「展开条目」(递归子条目,
  size_mb 降序);
- 大目录(自身大小 > LARGE_DIR_MB,默认 1000MB): 只记 size_mb 与顶层条目数,
  带「大目录: true」,无「展开条目」,内部不进入 entries(但计入 summary 的
  dirs/files/total_mb 统计——统计走完整 os.scandir 遍历,只按尺寸/数量聚合)。

category 判定规则(目录按直接子项与名字判定,优先级从上到下):
- 目录:
  1. 临时: 名字命中临时特征(log/tmp/cache/lock/__pycache__ 等,见
     _TEMP_DIR_TOKENS);缓存/日志目录内的杂散文件不改变其性质;
  2. 项目: 直接子项含 *.py,或含 README*/CLAUDE* 名字前缀(「代码目录簇」);
  3. 数据: 自身大小 > LARGE_DIR_MB,或名字含 backup(backups 归数据),
     或直接子文件含数据扩展名(.db/.npz/.csv/.dat/.parquet/.feather/.h5/
     .sqlite/.sqlite3/.bak/.backup/.orig);
  4. 文档: 有直接子文件且其中 ≥50% 为文档文件(.md/.xlsx/.docx/.pdf/.txt/
     .html/.pptx);
  5. 配置: 有直接子文件且全部为配置文件(.env/.yaml/.yml/.json/.toml/.ini/
     .cfg/.conf),且配置文件数不少于直接子目录数;
  6. 其他: 以上皆不满足。
  注: 简报「项目(含 .py/.json/README/CLAUDE 的目录簇)」中 .json 未作为独立
  项目标记——纯 .json 目录(如 .docker/.streamlit)按规则 5 归「配置」更符合
  实际,避免把 .claude/.config 之类误判为项目簇(见 task-6.1-report.md 疑点)。
- 文件(按扩展名,README*/CLAUDE* 前缀无扩展名时归文档):
  - 文档: .md/.xlsx/.docx/.pdf/.txt/.html/.pptx
  - 配置: .env/.yaml/.yml/.json/.toml/.ini/.cfg/.conf
  - 脚本: .sh/.py(散落的脚本)
  - 临时: .tmp/.log/.lock/.cache/.pyc/.pid/.swp
  - 数据: .db/.npz/.csv/.dat/.parquet/.feather/.h5/.sqlite/.sqlite3/.bak/.backup/.orig
  - 其他: 其余

summary 口径:
- dirs/files: 整个扫描树(含大目录内部)的目录数/文件数(符号链接计入 files);
- total_mb: 全树文件大小合计(MB,2 位小数);
- categories: 各 category 的 entries 条目数(大目录内部条目不展开,故不计数);
- top_dirs/top_files: 根目录直接子项中的目录数/文件数。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path

LARGE_DIR_MB = 1000.0  # 大目录阈值:目录自身大小超过该值(MB)只统计不展开

DEFAULT_ROOT = "/home/tdxback"

_MB = 1024 * 1024

_DOC_EXTS = {".md", ".xlsx", ".docx", ".pdf", ".txt", ".html", ".pptx"}
_CFG_EXTS = {".env", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".conf"}
_SCRIPT_EXTS = {".sh", ".py"}
_TEMP_EXTS = {".tmp", ".log", ".lock", ".cache", ".pyc", ".pid", ".swp"}
_DATA_EXTS = {".db", ".npz", ".csv", ".dat", ".parquet", ".feather", ".h5",
              ".sqlite", ".sqlite3", ".bak", ".backup", ".orig"}
_PROJECT_NAME_PREFIXES = ("readme", "claude")  # 目录簇项目标记(名字前缀)
# 目录名临时特征:全等(去点)或后缀命中即归临时
_TEMP_DIR_NAMES = {"log", "logs", "tmp", "temp", ".cache", ".pytest_cache",
                   ".mypy_cache", "__pycache__", ".ruff_cache"}
_TEMP_DIR_SUFFIXES = (".log", ".lock", ".tmp", ".cache", "cache")


def _fmt_mtime(ts):
    if not ts:
        return ""
    return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")


def _file_category(name: str) -> str:
    lower = name.lower()
    if lower.startswith(_PROJECT_NAME_PREFIXES):  # README/CLAUDE(无扩展名)归文档
        return "文档"
    ext = os.path.splitext(lower)[1]
    if ext in _DOC_EXTS:
        return "文档"
    if ext in _CFG_EXTS:
        return "配置"
    if ext in _SCRIPT_EXTS:
        return "脚本"
    if ext in _TEMP_EXTS:
        return "临时"
    if ext in _DATA_EXTS:
        return "数据"
    return "其他"


def _dir_category(name: str, child_names, child_exts, size_mb: float,
                  large: bool) -> str:
    base = name.lower()
    if base in _TEMP_DIR_NAMES or base.endswith(_TEMP_DIR_SUFFIXES):
        return "临时"
    if any(ext == ".py" for ext in child_exts) or \
            any(n.lower().startswith(_PROJECT_NAME_PREFIXES) for n in child_names):
        return "项目"
    if large or "backup" in base or any(ext in _DATA_EXTS for ext in child_exts):
        return "数据"
    if child_exts:
        doc_n = sum(1 for ext in child_exts if ext in _DOC_EXTS)
        if doc_n * 2 >= len(child_exts):
            return "文档"
        # 配置文件数须不少于直接子目录数:避免仅一个 pyvenv.cfg 的 venv
        # 之类被误判为配置目录
        if all(ext in _CFG_EXTS for ext in child_exts) and \
                2 * len(child_exts) >= len(child_names):
            return "配置"
    return "其他"


def _scan_dir(path: Path, expand: bool):
    """递归统计并(可选)展开一个目录。

    返回内部结构:
      {size_b, n_dirs, n_files, top, mtime, category, entry}
    entry 为 None 当且仅当 expand=False;expand=True 时 entry 为
    目录条目 dict(大目录无「展开条目」,带「大目录: true」)。
    """
    size_b = 0
    n_dirs = 0
    n_files = 0
    child_names = []
    child_exts = []
    sub_entries = []
    try:
        with os.scandir(path) as it:
            for de in it:
                child_names.append(de.name)
                if de.is_dir(follow_symlinks=False):
                    n_dirs += 1
                    sub = _scan_dir(Path(de.path), expand)
                    size_b += sub["size_b"]
                    n_dirs += sub["n_dirs"]
                    n_files += sub["n_files"]
                    if expand and sub["entry"] is not None:
                        sub_entries.append(sub["entry"])
                elif de.is_symlink():
                    n_files += 1
                    if expand:
                        try:
                            st = de.stat(follow_symlinks=False)
                        except OSError:
                            st = None
                        sub_entries.append({
                            "path": de.path,
                            "kind": "link",
                            "size_mb": round(st.st_size / _MB, 3) if st else 0.0,
                            "mtime": _fmt_mtime(st.st_mtime) if st else "",
                            "category": _file_category(de.name),
                        })
                else:
                    n_files += 1
                    child_exts.append(os.path.splitext(de.name.lower())[1])
                    fsize = 0
                    mtime = None
                    try:
                        st = de.stat(follow_symlinks=False)
                        fsize = st.st_size
                        mtime = st.st_mtime
                    except OSError:
                        pass
                    size_b += fsize
                    if expand:
                        sub_entries.append({
                            "path": de.path,
                            "kind": "file",
                            "size_mb": round(fsize / _MB, 3),
                            "mtime": _fmt_mtime(mtime),
                            "category": _file_category(de.name),
                        })
    except OSError:
        pass  # 无权限/已删除:该目录统计为 0,名字照旧参与父级类别判定

    size_mb = size_b / _MB
    large = size_mb > LARGE_DIR_MB
    category = _dir_category(path.name, child_names, child_exts, size_mb, large)
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        mtime = None
    entry = None
    if expand:
        entry = {
            "path": str(path),
            "kind": "dir",
            "size_mb": round(size_mb, 3),
            "mtime": _fmt_mtime(mtime),
            "category": category,
            "顶层条目数": len(child_names),
        }
        if large:
            entry["大目录"] = True
        else:
            sub_entries.sort(key=lambda e: (-e["size_mb"], e["path"]))
            entry["展开条目"] = sub_entries
    return {"size_b": size_b, "n_dirs": n_dirs, "n_files": n_files,
            "top": len(child_names), "mtime": mtime, "category": category,
            "entry": entry}


def _summarize_dir(path: Path, sub: dict, large: bool) -> dict:
    """top_only 模式下的目录条目:只统计不展开。"""
    entry = {
        "path": str(path),
        "kind": "dir",
        "size_mb": round(sub["size_b"] / _MB, 3),
        "mtime": _fmt_mtime(sub["mtime"]),
        "category": sub["category"],
        "顶层条目数": sub["top"],
    }
    if large:
        entry["大目录"] = True
    return entry


def _count_categories(entries) -> dict:
    counts = {}
    for e in entries:
        counts[e["category"]] = counts.get(e["category"], 0) + 1
        for sub in e.get("展开条目", []):
            if sub["kind"] == "dir":
                for c, n in _count_categories([sub]).items():
                    counts[c] = counts.get(c, 0) + n
            else:
                counts[sub["category"]] = counts.get(sub["category"], 0) + 1
    return counts


def scan_home(root: str = DEFAULT_ROOT, top_only: bool = False) -> dict:
    """扫描 root 顶层,返回 {generated_at, entries, summary}。

    - top_only=False(默认): 非大目录递归展开(「展开条目」),大目录只统计;
    - top_only=True: 只列顶层条目,目录一律只统计不展开(「顶层条目数」)。

    entries 按 size_mb 降序(同大小按 path 升序)。
    """
    root_p = Path(root)
    size_b = 0
    n_dirs = 0
    n_files = 0
    top_dirs = 0
    top_files = 0
    entries = []
    try:
        with os.scandir(root_p) as it:
            for de in it:
                if de.is_dir(follow_symlinks=False):
                    top_dirs += 1
                    sub = _scan_dir(Path(de.path), expand=not top_only)
                    n_dirs += 1 + sub["n_dirs"]
                    n_files += sub["n_files"]
                    size_b += sub["size_b"]
                    if top_only:
                        entries.append(_summarize_dir(Path(de.path), sub,
                                                      sub["size_b"] / _MB > LARGE_DIR_MB))
                    else:
                        entries.append(sub["entry"])
                elif de.is_symlink():
                    top_files += 1
                    n_files += 1
                    try:
                        st = de.stat(follow_symlinks=False)
                    except OSError:
                        st = None
                    if st:
                        size_b += st.st_size
                    entries.append({
                        "path": de.path,
                        "kind": "link",
                        "size_mb": round(st.st_size / _MB, 3) if st else 0.0,
                        "mtime": _fmt_mtime(st.st_mtime) if st else "",
                        "category": _file_category(de.name),
                    })
                else:
                    top_files += 1
                    n_files += 1
                    fsize = 0
                    mtime = None
                    try:
                        st = de.stat(follow_symlinks=False)
                        fsize = st.st_size
                        mtime = st.st_mtime
                    except OSError:
                        pass
                    size_b += fsize
                    entries.append({
                        "path": de.path,
                        "kind": "file",
                        "size_mb": round(fsize / _MB, 3),
                        "mtime": _fmt_mtime(mtime),
                        "category": _file_category(de.name),
                    })
    except OSError:
        pass  # root 不可读:返回空结果
    entries.sort(key=lambda e: (-e["size_mb"], e["path"]))
    summary = {
        "root": str(root_p),
        "dirs": n_dirs,
        "files": n_files,
        "total_mb": round(size_b / _MB, 2),
        "top_dirs": top_dirs,
        "top_files": top_files,
        "categories": _count_categories(entries),
    }
    return {
        "generated_at": _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "entries": entries,
        "summary": summary,
    }


def main() -> int:
    """真实扫描 /home/tdxback 并落盘 docs/home_scan.json,打印 summary。"""
    result = scan_home()
    out = Path(__file__).resolve().parent.parent / "docs" / "home_scan.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    s = result["summary"]
    print(f"扫描完成 {result['generated_at']}: root={s['root']}")
    print(f"顶层目录 {s['top_dirs']} 个 / 顶层文件 {s['top_files']} 个;"
          f"全树目录 {s['dirs']} / 文件 {s['files']};总大小 {s['total_mb']} MB")
    print("类别计数:", json.dumps(s["categories"], ensure_ascii=False))
    print("entries:", len(result["entries"]), "个;已写入", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
