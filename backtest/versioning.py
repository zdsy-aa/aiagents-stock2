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

完整性保障(终审裁决):
- 原子写:先写同目录临时文件 .strategy_versions.json.tmp,再 os.replace
  (同文件系统原子替换);写盘中断不会损坏原文件。
- 损坏保护:文件存在但 JSON 损坏 / 顶层非 dict / 不可读时抛 RuntimeError
  (消息含文件路径),绝不静默当 {} 读、也不覆盖 —— 防止 bump 清空全部历史。
- 畸形条目防御:策略条目缺 "versions" 键按 [] 处理(entry.get)。
- 落盘 JSON 安全化:非有限 float(inf/nan)转 None,numpy 标量转 Python 标量
  (引擎输出 profit_loss_ratio 可为 inf、ret_std 可为 nan)。
"""
import json
import math
import os
from datetime import datetime
from pathlib import Path

VERSIONS_PATH = Path(__file__).resolve().parent / "strategy_versions.json"


def _tmp_path():
    """原子写的同目录临时文件路径(随 VERSIONS_PATH monkeypatch 联动)。"""
    return VERSIONS_PATH.with_name(f".{VERSIONS_PATH.name}.tmp")


def _read_versions():
    """读现有 JSON。文件不存在 -> {};JSON 损坏 / 顶层非 dict / 不可读 ->
    RuntimeError(消息含路径,防 bump 静默覆盖全部历史)。"""
    if not VERSIONS_PATH.exists():
        return {}
    try:
        with open(VERSIONS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise RuntimeError(
            f"strategy_versions.json 损坏或不可读,拒绝读取以避免覆盖历史: "
            f"{VERSIONS_PATH}({e})") from e
    if not isinstance(data, dict):
        raise RuntimeError(
            f"strategy_versions.json 顶层结构非 dict,拒绝读取以避免覆盖历史: "
            f"{VERSIONS_PATH}")
    return data


def _write_versions(data):
    """原子写:同目录 tmp + os.replace,写盘中断不产生损坏中间态。"""
    VERSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, VERSIONS_PATH)


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


def _versions_of(entry):
    """策略条目的 versions 列表(畸形条目按空历史防御处理)。"""
    return entry.get("versions", []) if isinstance(entry, dict) else []


def bump_version(strategy, params, backtest_result):
    """推进版本:读-改-写 strategy_versions.json,返回新版本号(V+1)。

    文件损坏时 _read_versions 抛 RuntimeError,不覆盖原文件。
    """
    data = _read_versions()
    versions = _versions_of(data.get(strategy))
    version = f"V{len(versions) + 1}"
    versions.append({
        "version": version,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "params": _jsonable(params),
        "backtest": _jsonable(backtest_result),
    })
    data[strategy] = {"versions": versions}
    _write_versions(data)
    return version


def param_history(strategy):
    """策略的参数变更历史(全部版本记录,按 bump 先后排序)。"""
    return list(_versions_of(_read_versions().get(strategy)))


__all__ = ["VERSIONS_PATH", "bump_version", "param_history"]
