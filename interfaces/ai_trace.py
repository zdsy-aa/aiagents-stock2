# -*- coding: utf-8 -*-
"""Phase4 统一接口:AI 可验证性(Task4.4)。

- extract_direction(text):从 final_decision(文本或 dict)提取 AI 结论方向,
  含「看多/买入/上涨」→ 多,「看空/卖出/下跌」→ 空,否则 中性。
- comparison_table(symbol=None, days=(1, 3, 5, 10)) -> pd.DataFrame:
  读已保存分析记录(database 的 get_all_records + get_record_by_id),
  对每条记录按 (代码, 分析日期 + N 天) 在买点事件面板 load_panel(优先)
  与确认面板 load_confirm_panel(次选)匹配「是否盈利」标签;两个面板都没有
  该键的行标「无数据」。输出列:代码/分析日期/AI方向/{N}天后是否盈利...
  记录先按 (代码, analysis_id) 去重,版本化记录优先(P5-1 双记录收口,
  Task5.3;无 analysis_id 的老记录保持原行为)。
- trace_save(...):包装 database.save_analysis,透传 prompt_version /
  model_version / input_snapshot 版本字段(默认空,旧调用兼容),返回新记录 id。

约定(R4-A):记录/面板读取失败抛带接口名的 RuntimeError(api_error 包装);
非法 days(非正)抛 ValueError。
"""
import json
from datetime import datetime, timedelta

import pandas as pd

from backtest.dataio import LABEL_COL, load_confirm_panel, load_panel
from database import get_db
from interfaces.common import api_error

CODE_COL = "股票代码"
DATE_COL = "信号日期"
NO_DATA = "无数据"

BULLISH_WORDS = ("看多", "买入", "上涨")
BEARISH_WORDS = ("看空", "卖出", "下跌")


# ---------- 文本 -> 方向 ----------

def _decision_text(final_decision):
    """final_decision -> 方向判定文本。

    dict 时按 rating/decision/decision_text/logic 顺序取首个非空字段
    (结论文本优先于推理文本),全空时整体 JSON 兜底。
    """
    if isinstance(final_decision, str):
        return final_decision
    if isinstance(final_decision, dict):
        for key in ("rating", "decision", "decision_text", "logic"):
            value = final_decision.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return json.dumps(final_decision, ensure_ascii=False)
    return ""


def extract_direction(text):
    """从 final_decision(文本或 dict)提取 AI 结论方向:多/空/中性。"""
    text = _decision_text(text)
    if any(word in text for word in BULLISH_WORDS):
        return "多"
    if any(word in text for word in BEARISH_WORDS):
        return "空"
    return "中性"


# ---------- 键归一(代码去前导零 / 日期统一 YYYY-MM-DD) ----------

def _norm_code(x):
    """股票代码归一:纯数字去前导零(面板 '1' 与库 '000001' 可匹配)。"""
    s = str(x).strip()
    if s.isdigit():
        s = s.lstrip("0") or "0"
    return s


def _norm_date(x):
    """日期 -> 'YYYY-MM-DD'(兼容 'YYYY-MM-DD HH:MM:SS' / 'YYYYMMDD' / datetime);
    无法解析返回 None。"""
    if x is None:
        return None
    s = str(x).strip()
    head = s[:10] if len(s) >= 10 else s
    try:
        return datetime.strptime(head, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        pass
    if len(s) >= 8:
        try:
            return datetime.strptime(s[:8], "%Y%m%d").strftime("%Y-%m-%d")
        except ValueError:
            pass
    try:
        return pd.to_datetime(s).strftime("%Y-%m-%d")
    except Exception:
        return None


# ---------- 数据源(独立函数,便于测试 monkeypatch) ----------

def _load_analysis_records():
    """读全部已保存分析记录 -> [{id, symbol, analysis_date, final_decision,
    input_snapshot}](id/input_snapshot 供 (代码, analysis_id) 去重,Task5.3 收口)。

    经 database 既有接口:get_all_records(取 id)+ get_record_by_id(取明细)。
    """
    db = get_db()
    records = []
    for item in db.get_all_records():
        detail = db.get_record_by_id(item.get("id"))
        if not detail:
            continue
        records.append({
            "id": detail.get("id"),
            "symbol": detail.get("symbol", ""),
            "analysis_date": detail.get("analysis_date", ""),
            "final_decision": detail.get("final_decision", {}),
            "input_snapshot": detail.get("input_snapshot", {}),
        })
    return records


def _buy_index(df):
    """买点面板 -> {(norm_code, 'YYYY-MM-DD'): 是否盈利(int)};NaN 标签不建键。"""
    idx = {}
    if df is None or len(df) == 0:
        return idx
    codes = df[CODE_COL].astype(str).map(_norm_code).to_numpy()
    dates = df[DATE_COL].map(_norm_date).to_numpy()
    labels = pd.to_numeric(df[LABEL_COL], errors="coerce").to_numpy()
    for code, date, lab in zip(codes, dates, labels):
        if code and date and pd.notna(lab):
            idx[(code, date)] = int(lab)
    return idx


def _norm_code_series(codes):
    """面板代码列 -> 归一字符串列(categorical 走字典映射,向量化)。"""
    if isinstance(codes.dtype, pd.CategoricalDtype):
        return codes.map(
            {c: _norm_code(c) for c in codes.cat.categories}).astype(str)
    return codes.astype(str).map(_norm_code)


def _lookup_confirm(confirm_df, pending):
    """确认面板兜底:{(norm_code, YYYYMMDD int): 是否盈利(int)}。

    只对 pending 涉及的 (代码, 日期) 做向量化筛选与合并,避免全表 Python 循环。
    """
    found = {}
    if not pending or confirm_df is None or len(confirm_df) == 0:
        return found
    needed_codes = {c for _, c, _ in pending}
    needed_dates = {int(t.replace("-", "")) for _, _, t in pending}
    norm = _norm_code_series(confirm_df[CODE_COL])
    mask = norm.isin(needed_codes) & confirm_df[DATE_COL].isin(needed_dates)
    if not mask.any():
        return found
    sub = confirm_df.loc[mask, [CODE_COL, DATE_COL, LABEL_COL]].copy()
    sub[CODE_COL] = norm[mask].to_numpy()
    labels = pd.to_numeric(sub[LABEL_COL], errors="coerce").to_numpy()
    for code, date, lab in zip(sub[CODE_COL].to_numpy(),
                               sub[DATE_COL].to_numpy(), labels):
        if pd.notna(lab):
            found[(str(code), int(date))] = int(lab)
    return found


# ---------- (代码, analysis_id) 去重(Task5.3 收口,回应 P5-1 双记录) ----------

def _snapshot_dict(input_snapshot):
    """input_snapshot -> dict;dict 原样、JSON 文本解析、其余空 dict(不抛错)。"""
    if isinstance(input_snapshot, dict):
        return input_snapshot
    if isinstance(input_snapshot, str) and input_snapshot.strip():
        try:
            parsed = json.loads(input_snapshot)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _analysis_id_of(rec):
    """记录 input_snapshot 里的 analysis_id -> 非空字符串;无 -> None。"""
    value = _snapshot_dict(rec.get("input_snapshot")).get("analysis_id")
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return str(value).strip()


def _record_identity(rec):
    """记录身份键 (norm_code, identity) -> 供 (代码, analysis_id) 去重。

    identity = input_snapshot.analysis_id(版本化记录);缺省取记录自身 id——
    引擎落库记录的 id 与版本化记录引用的 analysis_id 同命名空间(AUTOINCREMENT
    主键),据此把「引擎原始记录 + 任务版本化记录」归入同组。id 与 analysis_id
    皆无的记录不参与去重(保持原行为)。
    """
    code = _norm_code(rec.get("symbol"))
    identity = _analysis_id_of(rec)
    if identity is None:
        rid = rec.get("id")
        if rid is None:
            return None
        identity = str(rid)
    return (code, identity)


def _is_versioned(rec):
    """是否版本化记录:input_snapshot 含非空 analysis_id。"""
    return _analysis_id_of(rec) is not None


def _dedupe_records(records):
    """按 (代码, analysis_id) 去重:版本化记录优先;同组多条版本化留最新(id 大)。

    规则(控制器裁决,P5-1 双记录收口):
    - 无身份键的记录(无 id 且无 analysis_id 的老记录)保持原行为,不去重;
    - 同组内版本化记录取代非版本化记录(引擎原始记录被其版本化孪生取代);
    - 同组多条版本化记录(重跑)只留 id 最大的一条。
    输出保持原记录顺序(只删行,不重排)。
    """
    chosen = {}
    for rec in records:
        key = _record_identity(rec)
        if key is None:
            continue
        cur = chosen.get(key)
        if cur is None:
            chosen[key] = rec
            continue
        new_v, cur_v = _is_versioned(rec), _is_versioned(cur)
        if new_v and not cur_v:
            chosen[key] = rec
        elif new_v and cur_v and (rec.get("id") or -1) > (cur.get("id") or -1):
            chosen[key] = rec
        # 新记录非版本化:保留组内既有者(版本化优先;都非版本化时先到先得)
    seen, out = set(), []
    for rec in records:
        key = _record_identity(rec)
        if key is None:
            out.append(rec)
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(chosen[key])
    return out


# ---------- 对外接口 ----------

def comparison_table(symbol=None, days=(1, 3, 5, 10)):
    """分析记录 × 面板标签对比表:AI 结论方向 vs 信号后 N 天是否盈利。

    Args:
        symbol: 仅保留该代码的记录(None = 全部);代码做前导零归一匹配。
        days: 信号后 N 天元组,默认 (1, 3, 5, 10);非正整数抛 ValueError。

    Returns:
        DataFrame,列 = 代码/分析日期/AI方向/{N}天后是否盈利...(按 days 顺序)。
        「{N}天后是否盈利」取面板中 (代码, 分析日期+N天) 行的 是否盈利 标签,
        面板两处均无该键标「无数据」。记录为空时返回仅含表头的空表。
        记录先按 (代码, analysis_id) 去重(版本化记录优先,见 _dedupe_records,
        Task5.3 收口);无 analysis_id 的老记录保持原行为。
    """
    if isinstance(days, (int, float)):
        days = (int(days),)
    days = tuple(int(d) for d in days)
    if any(d <= 0 for d in days):
        raise ValueError(f"days 必须为正整数:{days}")

    columns = ["代码", "分析日期", "AI方向"] + [f"{d}天后是否盈利" for d in days]
    try:
        records = _load_analysis_records()
    except Exception as exc:
        raise api_error("comparison_table", exc) from exc
    if symbol:
        target = _norm_code(symbol)
        records = [r for r in records if _norm_code(r.get("symbol")) == target]
    records = _dedupe_records(records)
    if not records:
        return pd.DataFrame(columns=columns)

    try:
        buy_df = load_panel()
    except Exception as exc:
        raise api_error("comparison_table", exc) from exc
    buy_idx = _buy_index(buy_df)

    # 每条记录 × 每个 N:目标日期 = 分析日期 + N 天;先查买点面板,未命中留待确认面板
    outcomes = {}
    pending = []
    for i, rec in enumerate(records):
        base = _norm_date(rec.get("analysis_date"))
        code = _norm_code(rec.get("symbol"))
        for d in days:
            key = (i, d)
            if not base or not code:
                outcomes[key] = None
                continue
            try:
                target = (datetime.strptime(base, "%Y-%m-%d")
                          + timedelta(days=d)).strftime("%Y-%m-%d")
            except ValueError:
                outcomes[key] = None
                continue
            lab = buy_idx.get((code, target))
            if lab is None:
                pending.append((key, code, target))
            else:
                outcomes[key] = lab

    if pending:
        try:
            confirm_df = load_confirm_panel()
        except Exception as exc:
            raise api_error("comparison_table", exc) from exc
        found = _lookup_confirm(confirm_df, pending)
        for key, code, target in pending:
            lab = found.get((code, int(target.replace("-", ""))))
            if lab is not None:
                outcomes[key] = lab

    rows = []
    for i, rec in enumerate(records):
        row = {
            "代码": str(rec.get("symbol", "")),  # 输出保留记录原始代码(归一仅用于匹配)
            "分析日期": rec.get("analysis_date", ""),
            "AI方向": extract_direction(rec.get("final_decision")),
        }
        for d in days:
            lab = outcomes.get((i, d))
            row[f"{d}天后是否盈利"] = lab if lab is not None else NO_DATA
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)


def trace_save(symbol, name, period, stock_info, agents_results,
               discussion_result, final_decision,
               prompt_version="", model_version="", input_snapshot=""):
    """包装 database.save_analysis,透传 AI 可验证性版本字段,返回新记录 id。

    prompt_version / model_version / input_snapshot 默认空,旧调用方(仅传
    前 7 个位置参数)完全兼容;input_snapshot 传 dict 时落库为 JSON 文本。
    """
    return get_db().save_analysis(
        symbol, name, period, stock_info, agents_results,
        discussion_result, final_decision,
        prompt_version=prompt_version or "",
        model_version=model_version or "",
        input_snapshot=input_snapshot,
    )
