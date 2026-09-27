# -*- coding: utf-8 -*-
"""interfaces.screen 批量选股与信号扫描统一接口(Phase4 Task4.2)。

薄封装现有选股器与 Phase3 组合求值,不改被封装模块的既有行为:

- :func:`screen_stocks` 按 ``SELECTORS`` 注册表调用选股器,把任意 DataFrame 结果
  归一化为公共列 ``SCREEN_RESULT_COLS = [代码, 名称, 信号, 得分, 备注]``
  (interfaces.common,Task4.0)。列名按 :data:`_ALIAS` 别名表映射;映射不到的列
  填空串,不编造。选股器返回 ``(ok, df, msg)``,``ok=False`` 或结果为空按 R4-A
  抛 RuntimeError(消息含 selector 的 msg);未知 selector 抛 ValueError。
- :func:`scan_signals` 在面板 DataFrame 上按 ComboSpec 求值(复用 Phase3
  ``backtest.combo_engine.eval_combo``),返回 mask 命中行的 代码/日期/信号名列
  (保留面板原列名,不做 SCREEN_RESULT_COLS 归一化)。spec 可为 ComboSpec dict
  或 "TQ01"~"TQ57" 名称(经 ``build_57_specs`` 解析,未知名称抛 ValueError);
  ``df=None`` 时走 ``backtest.dataio.load_confirm_panel``(约 15M 行,慢,调用方
  宜自备 df)。

selector 入口映射(包装器读真实签名,薄透传 params):

============  =================================================  =================
selector      入口函数                                           返回列(映射用)
============  =================================================  =================
main_force    MainForceStockSelector.get_main_force_stocks        股票代码/股票简称/主力资金净流入...
              (start_date=None, days_ago=None, min/max_market_cap) (问财,需网络)
chanlun       ChanlunSelector.get_chanlun_picks(types=None,       code/name/board/signal_type/
              scan_date=None)                                      signal_date/buy_reason...
combo         ComboSelector.get_picks(scan_date=None)             code/name/board/chanlun_type/
                                                                  buy_reason/liumai_score...
liumai        LiumaiSelector.get_picks(min_bull=5, scan_date=..)  code/name/board/signal_date/
                                                                  bull_count/score/state...
value_stock   ValueStockSelector.get_value_stocks(top_n=10)       股票代码/股票简称...(问财)
profit_growth ProfitGrowthSelector.get_profit_growth_stocks(top_n=5) 同上(问财)
small_cap     SmallCapSelector.get_small_cap_stocks(top_n=5)      同上(问财)
low_price     LowPriceBullSelector.get_low_price_stocks(top_n=5)  同上(问财)
============  =================================================  =================

本地库类(chanlun/combo/liumai)零参数即可跑(读 data/*_signals.db 最新批次);
问财类(main_force/value_stock/profit_growth/small_cap/low_price)依赖网络。
"""
import pandas as pd

from backtest.combo_engine import build_57_specs, eval_combo
from backtest.dataio import load_confirm_panel
from interfaces.common import SCREEN_RESULT_COLS, api_error

# 列名别名映射:归一化时按别名元组顺序取第一个命中列;全部未命中填空串,不编造。
# (代码/名称/信号/得分/备注 各语义槽位收录全项目 selector 真实出现的别名)
_ALIAS = {
    "代码": ("代码", "code", "symbol", "stock_code", "股票代码"),
    "名称": ("名称", "name", "stock_name", "股票简称", "简称"),
    "信号": ("信号", "signal", "signal_type", "买点", "signal_name",
             "chanlun_type", "state", "主力资金净流入"),
    "得分": ("得分", "score", "评分", "liumai_score"),
    "备注": ("备注", "note", "reason", "buy_reason", "说明"),
}

# 面板 代码/日期 列名候选(scan_signals 输出保留面板原列名)
_CODE_COLS = ("股票代码", "代码", "code", "symbol")
_DATE_COLS = ("信号日期", "日期", "signal_date", "date")


def _main_force(params, universe):
    """主力选股(问财网络,UI 默认近 90 日):MainForceStockSelector.get_main_force_stocks。"""
    from main_force_selector import MainForceStockSelector
    if "start_date" not in params and "days_ago" not in params:
        params = {"days_ago": 90, **params}  # UI 默认档(近 90 日)
    return MainForceStockSelector().get_main_force_stocks(**params)


def _chanlun(params, universe):
    """缠论选股(本地 data/chanlun_signals.db 最新批次):ChanlunSelector.get_chanlun_picks。"""
    from chanlun_selector import ChanlunSelector
    return ChanlunSelector().get_chanlun_picks(**params)


def _combo(params, universe):
    """缠论×六脉组合选股(本地 data/combo_signals.db):ComboSelector.get_picks。"""
    from combo_selector import ComboSelector
    return ComboSelector().get_picks(**params)


def _liumai(params, universe):
    """六脉神剑选股(本地 data/liumai_signals.db):LiumaiSelector.get_picks。"""
    from liumai_selector import LiumaiSelector
    return LiumaiSelector().get_picks(**params)


def _value(params, universe):
    """低估值选股(问财网络):ValueStockSelector.get_value_stocks。"""
    from value_stock_selector import ValueStockSelector
    return ValueStockSelector().get_value_stocks(**params)


def _profit_growth(params, universe):
    """净利增长选股(问财网络):ProfitGrowthSelector.get_profit_growth_stocks。"""
    from profit_growth_selector import ProfitGrowthSelector
    return ProfitGrowthSelector().get_profit_growth_stocks(**params)


def _small_cap(params, universe):
    """小市值选股(问财网络):SmallCapSelector.get_small_cap_stocks。"""
    from small_cap_selector import SmallCapSelector
    return SmallCapSelector().get_small_cap_stocks(**params)


def _low_price(params, universe):
    """低价牛股选股(问财网络):LowPriceBullSelector.get_low_price_stocks。"""
    from low_price_bull_selector import LowPriceBullSelector
    return LowPriceBullSelector().get_low_price_stocks(**params)


# selector 注册表:名称 -> callable(params: dict, universe) -> DataFrame | (ok, df, msg)
SELECTORS = {
    "main_force": _main_force,
    "chanlun": _chanlun,
    "combo": _combo,
    "liumai": _liumai,
    "value_stock": _value,
    "profit_growth": _profit_growth,
    "small_cap": _small_cap,
    "low_price": _low_price,
}


def _cell(v):
    """归一化单元格:NaN/None -> 空串,其余转 str(数值列转文本,不改变原值)。"""
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return str(v)


def _normalize_result(df):
    """任意 DataFrame -> SCREEN_RESULT_COLS 固定列(别名映射,缺列填空串)。

    列名与 _ALIAS 零交集时五槽全为标量 "",仍按 df.index 广播构造
    N 行 × 5 列,不会触发「all scalar values」构造异常。
    """
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=SCREEN_RESULT_COLS)
    out = {}
    for std, aliases in _ALIAS.items():
        col = next((c for c in aliases if c in df.columns), None)
        out[std] = df[col].map(_cell) if col is not None else ""
    return pd.DataFrame(out, index=df.index, columns=SCREEN_RESULT_COLS)


def screen_stocks(selector, params=None, universe=None):
    """调用注册选股器并把结果归一化为 SCREEN_RESULT_COLS。

    Args:
        selector: SELECTORS 注册表键(如 "main_force"/"chanlun"/"combo"/"liumai")。
        params: 透传给选股器入口函数的参数字典(如 {"days_ago": 90}、{"top_n": 10})。
        universe: 预留的自选池参数,现有选股器不支持时忽略。

    Returns:
        DataFrame,列恒为 SCREEN_RESULT_COLS(代码/名称/信号/得分/备注)。

    Raises:
        ValueError: 未知 selector。
        RuntimeError: 选股器失败(ok=False,消息含原因)、结果为空或结果无法归一化
            (如非 DataFrame),均按 R4-A 经 api_error 包装,消息含 selector 名,
            __cause__ 保留原始异常。
    """
    if selector not in SELECTORS:
        raise ValueError(
            f"未知选股器: {selector!r}(可用: {'、'.join(SELECTORS)})")
    fn = SELECTORS[selector]
    api = f"screen_stocks({selector})"
    try:
        result = fn(dict(params or {}), universe)
        if isinstance(result, tuple):
            if len(result) >= 3:
                ok, df, msg = result[0], result[1], result[2]
            else:
                ok, df = result[0], result[1]
                msg = ""
        else:
            ok, df, msg = True, result, ""
        if not ok:
            raise RuntimeError(msg or "选股器返回失败")
        if df is None or len(df) == 0:
            raise RuntimeError(msg or "选股结果为空")
        return _normalize_result(df)
    except Exception as e:
        raise api_error(api, e)


def _spec_cond_cols(spec):
    """ComboSpec 条件涉及的信号列名(嵌套 or_group 递归展开,按出现序去重)。"""
    cols = []

    def walk(conds):
        for c in conds or []:
            if "or_group" in c:
                walk(c["or_group"])
            elif c.get("col"):
                cols.append(c["col"])

    walk(spec.get("conds") or [])
    seen, out = set(), []
    for c in cols:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def scan_signals(spec, df=None):
    """按组合规格扫描面板,返回命中行的 代码/日期/信号名列。

    Args:
        spec: ComboSpec dict({"name", "conds", "join"}),或 "TQ01"~"TQ57"
            名称字符串(经 build_57_specs 解析)。
        df: 信号面板 DataFrame;None 时走 load_confirm_panel(约 15M 行,慢,
            建议调用方自备 df)。

    Returns:
        DataFrame:mask 命中行,列 = 面板的 代码列 + 日期列 + spec 涉及的信号名列
        (保留面板原列名,不做归一化);无命中时为空表但列结构一致。

    Raises:
        ValueError: spec 类型非法或名称不在 TQ01~TQ57。
        RuntimeError: 面板缺列/加载失败(R4-A,经 api_error 包装)。
    """
    if isinstance(spec, str):
        found = [s for s in build_57_specs() if s["name"] == spec]
        if not found:
            raise ValueError(f"未知组合规格: {spec}(可用 TQ01~TQ57)")
        spec = found[0]
    if not isinstance(spec, dict):
        raise ValueError(
            f"spec 须为 ComboSpec dict 或 TQ01~TQ57 名称,got {type(spec).__name__}")
    try:
        if df is None:
            df = load_confirm_panel()
        mask = eval_combo(spec, df)
    except Exception as e:
        raise api_error("scan_signals", e)
    hits = df[mask]
    code_col = next((c for c in _CODE_COLS if c in df.columns), None)
    date_col = next((c for c in _DATE_COLS if c in df.columns), None)
    out_cols = [c for c in [code_col, date_col] + _spec_cond_cols(spec)
                if c is not None and c in df.columns]
    return hits[out_cols].reset_index(drop=True)
