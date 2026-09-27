# backtest/versioning.py
"""策略版本管理(Phase3 Task3.5):strategy_versions.json 读写与版本推进。

- VERSIONS_PATH = backtest/strategy_versions.json(模块级属性,测试 monkeypatch)。
- JSON 结构:
    {"<策略名>": {"versions": [{"version": "V1", "created_at": ...,
                                "params": {...}, "backtest": {...}}, ...]}}
- bump_version(strategy, params, backtest_result) -> str:
    读-改-写(保留已有策略条目),新版本号 = "V" + (现有 versions 条数 + 1);
    params 与回测结果(引擎 12 键指标)绑定存入同一条版本记录;返回新版本号。
- param_history(strategy) -> list[dict]: 该策略全部版本记录(参数变更历史,
    按 bump 先后排序);无记录返回空列表(不创建文件)。
- 落盘 JSON 安全化:非有限 float(inf/nan)转 None,numpy 标量转 Python 标量
  (引擎输出 profit_loss_ratio 可为 inf、ret_std 可为 nan)。
"""
import json
import math
from datetime import datetime
from pathlib import Path

VERSIONS_PATH = Path(__file__).resolve().parent / "strategy_versions.json"


def _read_versions():
    """读现有 JSON(不存在/损坏 -> 空 dict,不抛错)。"""
    if not VERSIONS_PATH.exists():
        return {}
    try:
        with open(VERSIONS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _jsonable(v):
    """递归转 JSON 安全值:非有限 float -> None,numpy 标量 -> Python 标量。"""
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, (int, float)):
        if isinstance(v, float) and not math.isfinite(v):
            return None
        return v
    try:
        import numpy as np
        if isinstance(v, np.generic):
            return _jsonable(v.item())
    except Exception:
        pass
    return str(v)


def bump_version(strategy, params, backtest_result):
    """推进版本:读-改-写 strategy_versions.json,返回新版本号(V+1)。"""
    data = _read_versions()
    entry = data.get(strategy, {"versions": []})
    versions = entry["versions"] if isinstance(entry, dict) else []
    version = f"V{len(versions) + 1}"
    versions.append({
        "version": version,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "params": _jsonable(params),
        "backtest": _jsonable(backtest_result),
    })
    data[strategy] = {"versions": versions}
    VERSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(VERSIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return version


def param_history(strategy):
    """策略的参数变更历史(全部版本记录,按 bump 先后排序)。"""
    data = _read_versions()
    entry = data.get(strategy, {})
    versions = entry.get("versions", []) if isinstance(entry, dict) else []
    return list(versions)


__all__ = ["VERSIONS_PATH", "bump_version", "param_history"]
