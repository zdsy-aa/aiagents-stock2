# -*- coding: utf-8 -*-
"""automation.risk_filter: 风险前置过滤(Phase5 Task5.2)。

``build_risk_filter(rules) -> callable(df) -> df``,规则按序应用,顺序:
market_env_gate -> exclude_st -> min_amount -> exclude_events(事件取数
只对前面规则筛选后的剩余行发起,减少网络调用)。

规则:
- exclude_st: 名称/简称含 "ST"(大小写不敏感,覆盖 *ST/ST 退等)的行剔除;
- min_amount: 成交额列低于下限的行剔除(成交额缺失(NaN)视同低于下限剔除;
  无成交额列或列不可比时透传);
- exclude_events: 逐代码调用 risk_data_fetcher.RiskDataFetcher().get_risk_data,
  限售解禁/大股东减持/重要事件任一 ``has_data`` 为 True 即剔除该代码;
- market_env_gate: callable|None。非 None 时调用 gate(df),返回假值整表
  清空(市场环境不满足);None 跳过(5.6 就绪前的默认值)。

某规则因前置条件不满足(列缺失/依赖模块不可用/调用异常)时不抛错:
该规则原样透传,并记录到返回函数 ``.records`` 列表与 logger.warning
——前置过滤定位是「宁可漏滤,不阻断选股链路」。

输出列结构恒稳定:pandas 3.x 下 0 行 DataFrame 的布尔行掩码可能退化为
列选择导致整表列丢失(3.0.6 实测),入口空表早返回 + 每条规则掩码经
``_row_mask``(空表原样返回)双重防护,保证任一规则剔空全部行后输出仍
保留原列结构(screen_stocks 依赖「列恒为五槽」契约)。

风险数据模块摸底结论(本文件依据):
- 模块: 根目录 risk_data_fetcher.py,类 RiskDataFetcher;
- 入口: get_risk_data(symbol: str) -> Dict,键 symbol/data_success/
  lifting_ban/shareholder_reduction/important_events/error,三个数据子字典
  均有 has_data 布尔字段;
- 可用性: 依赖 pywencai(问财,需网络);测试通道 venv-data 未安装
  pywencai,故 exclude_events 在测试环境恒为「模块不可用透传并记录」;
  生产(应用运行)环境可用。模块在 build 时解析一次,测试可用
  monkeypatch(sys.modules) 注入假模块。

akshare ST 名单探测结论: venv-data 与系统 python3 均未安装 akshare,
无法探测 stock_zh_a_st_em,选型待定;exclude_st 现按文本规则(名称/
简称含 ST)实现,未来 akshare 就绪可增补名单式判定。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

__all__ = ["build_risk_filter", "default_risk_filter", "DEFAULT_MIN_AMOUNT"]

# 默认成交额下限(元):1000 万,低于视为流动性不足(default_risk_filter 用)。
DEFAULT_MIN_AMOUNT = 1e7

_DEFAULT_RULES: Dict[str, Any] = {
    "exclude_st": True,
    "min_amount": DEFAULT_MIN_AMOUNT,
    "exclude_events": True,
    "market_env_gate": None,
}

_NAME_COLS = ("名称", "简称", "股票简称", "name", "stock_name")
_AMOUNT_COLS = ("成交额", "amount", "turnover")
_CODE_COLS = ("代码", "code", "symbol", "stock_code", "股票代码")


def _first_col(df: pd.DataFrame, candidates) -> Optional[str]:
    return next((c for c in candidates if c in df.columns), None)


def _is_st(value) -> bool:
    """名称/简称含 ST(大小写不敏感);NaN/None/非字符串安全返回 False。"""
    try:
        return "ST" in str(value).upper()
    except Exception:
        return False


def _row_mask(df: pd.DataFrame, mask) -> pd.DataFrame:
    """按行掩码过滤 df,空表原样返回(列结构保留)。

    pandas 3.x 对 0 行 DataFrame 做布尔行掩码可能退化为列选择:掩码为非
    bool dtype(如 map/~ 产生的 object 空序列)时整表列丢失(3.0.6 实测)。
    规则管道中途被前序规则剔空后,后续规则的掩码必须经此函数,保证输出
    列恒稳定(screen_stocks 依赖「列恒为五槽」契约)。
    """
    return df if len(df) == 0 else df[mask]


def build_risk_filter(rules: Dict[str, Any]) -> Callable[[pd.DataFrame], pd.DataFrame]:
    """按 rules 构建风险过滤函数,返回 callable(df) -> df。

    Args:
        rules: 支持 {"exclude_st": bool, "min_amount": float(成交额下限),
            "exclude_events": bool, "market_env_gate": callable|None},
            键缺失或为假值/None 视为该规则不启用。

    Returns:
        callable(df) -> df:逐条应用启用的规则,返回筛选后的 DataFrame;
        附带 ``.records`` 属性(未生效规则的透传记录列表,调试/审计用)。
    """
    rules = dict(rules or {})
    records: List[str] = []

    def _record(rule: str, reason: str) -> None:
        msg = f"{rule}: {reason}(透传)"
        records.append(msg)
        logger.warning("风险过滤规则未生效: %s", msg)

    # exclude_events 依赖模块在构建期解析一次(失败则整规则透传)
    fetcher_cls = None
    if rules.get("exclude_events"):
        try:
            from risk_data_fetcher import RiskDataFetcher as _RF

            fetcher_cls = _RF
        except Exception as e:  # pywencai 缺失等
            _record("exclude_events", f"风险数据模块不可用: {e}")

    def risk_filter(df: pd.DataFrame) -> pd.DataFrame:
        # 入口空表直接返回;管道中途被前序规则剔空的情况由各掩码处的
        # _row_mask 防护(pandas 3.x 对 0 行 DataFrame 的布尔行掩码可能退化
        # 为列选择导致列全丢,详见 _row_mask 注释)。
        if df is None or len(df) == 0:
            return df
        out = df
        # 0. 市场环境门控
        gate = rules.get("market_env_gate")
        if gate is not None:
            try:
                if not bool(gate(out)):
                    return pd.DataFrame(columns=out.columns)
            except Exception as e:
                _record("market_env_gate", f"调用失败: {e}")
        # 1. ST/退市(名称/简称任一列含 ST 即剔除)
        if rules.get("exclude_st"):
            name_cols = [c for c in _NAME_COLS if c in out.columns]
            if not name_cols:
                _record("exclude_st", "无名称/简称列")
            else:
                mask = pd.Series(False, index=out.index)
                for c in name_cols:
                    mask = mask | out[c].map(_is_st)
                out = _row_mask(out, ~mask)
        # 2. 流动性
        min_amount = rules.get("min_amount")
        if min_amount is not None:
            amount_col = _first_col(out, _AMOUNT_COLS)
            if amount_col is None:
                _record("min_amount", "无成交额列")
            else:
                try:
                    out = _row_mask(out, out[amount_col] >= min_amount)
                except Exception as e:
                    _record("min_amount", f"成交额列不可比: {e}")
        # 3. 重大事件(逐代码取数,失败保留该行)
        if rules.get("exclude_events"):
            code_col = _first_col(out, _CODE_COLS)
            if code_col is None:
                _record("exclude_events", "无代码列")
            elif fetcher_cls is not None:
                try:
                    fetcher = fetcher_cls()
                except Exception as e:
                    _record("exclude_events", f"初始化失败: {e}")
                    fetcher = None
                if fetcher is not None:
                    drop_codes = set()
                    for code in out[code_col].tolist():
                        try:
                            data = fetcher.get_risk_data(str(code)) or {}
                            if any((data.get(k) or {}).get("has_data")
                                   for k in ("lifting_ban", "shareholder_reduction",
                                             "important_events")):
                                drop_codes.add(code)
                        except Exception as e:
                            _record("exclude_events", f"{code} 取数失败: {e}")
                            continue
                    if drop_codes:
                        out = _row_mask(out, ~out[code_col].isin(drop_codes))
        return out

    risk_filter.records = records
    return risk_filter


def default_risk_filter() -> Callable[[pd.DataFrame], pd.DataFrame]:
    """默认风险过滤:ST/流动性/重大事件三项默认开启,市场环境门控 None(5.6 就绪前)。"""
    return build_risk_filter(dict(_DEFAULT_RULES))
