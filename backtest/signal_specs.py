# backtest/signal_specs.py
"""57 信号规格构建:TQ01~TQ50 从 Top50 JSON 的「组合」串解析,
TQ51~TQ57 按 tq_confirm_top10.py 定义手工映射到确认面板列。

ComboSpec = {"name": str, "conds": [条件元素], "join": "AND"}
条件元素 = {"col","op","value"} 或 {"or_group": [...]}(组内 OR,见 combo_engine)。
缺列信号:conds 置空 + "unavailable": true + "reason"(含缺列清单)+
"missing_cols" 列表;eval_combo 对其返回全 False(对齐测试据此跳过)。

列存在性自检在 build_57_specs() 内对确认面板列名(confirm_panel.npz 的
bool_cols/cont_cols + 标签/日期列,数据基座 Task 3.2 勘误)执行 —— 全部 57 条
spec 均可用于对齐验收(3.1 时代基于 signal_features.csv 的 52 条 unavailable
已随基座切换消除;TQ51 深跌承接的 OR 组语义经嵌套 or_group 修复,控制器裁决)。
"""
import json
from functools import lru_cache

from backtest.dataio import confirm_panel_columns

TOP50_PATH = ("/home/tdxback/aiagents-stock/data/commonality_reports/"
              "确认信号_Top50去重_20260908.json")

# ---------------------------------------------------------------------------
# TQ51~TQ57 手工映射(tq_confirm_top10.py compute_signals 定义)
# 组合11 = 缠论买点(一买/二买/强二买)4日内 AND 六脉六红4日内(两信号不必同日,
# 各自 rolling(4).max() 含当日)。确认面板(日K × 168 布尔列)为「最新一根日K」
# 状态列,无 4 日窗口事件列,故取同日近似(与文件头涨跌占比的挖掘口径一致:
# mine_combo11.py 事件 E = (缠论一买|缠论二买) & 六脉红灯大于6 同日成立):
#   * 缠论买点支:缠论一买 OR 缠论二买(强二买无对应列;同日近似,记录)。
#   * 六红支:面板列「六脉红灯大于6」= 六维红灯计数 >= 6 = 六红(features.py:258
#     命名偏小,语义核对为 >=6);4 日窗口面板不可表达,取同日近似(记录)。
# ---------------------------------------------------------------------------
_C11 = [{"col": "六脉红灯大于6", "op": ">", "value": 0},
        {"or_group": [{"col": "缠论一买", "op": ">", "value": 0},
                      {"col": "缠论二买", "op": ">", "value": 0}]}]

_OR_承接 = [{"col": "大盘空头", "op": ">", "value": 0},
            {"col": "趋势空头", "op": ">", "value": 0},
            {"col": "资金强度大于10", "op": ">", "value": 0},
            {"col": "机构净买", "op": ">", "value": 0}]

# TQ51 的「深跌承接」在 tq 口径为 OR 组(大盘空头 OR 趋势空头 OR 资金强度大于10
# OR 机构净买);经嵌套 or_group 表达(控制器裁决:修复 3.1 的 AND 扁平化)。
_MANUAL_51_57 = [
    ("TQ51", "六脉缠论买:深跌+空头/资金承接",
     _C11 + [{"col": "20日跌幅超15", "op": ">", "value": 0},
             {"or_group": _OR_承接}]),
    ("TQ52", "六脉缠论卖:大盘多头+波动率大于5",
     _C11 + [{"col": "大盘多头", "op": ">", "value": 0},
             {"col": "波动率大于5", "op": ">", "value": 0}]),
    ("TQ53", "六脉缠论卖:MA金叉10_20+量比大于1_5",
     _C11 + [{"col": "MA金叉10_20", "op": ">", "value": 0},
             {"col": "量比大于1_5", "op": ">", "value": 0}]),
    ("TQ54", "六脉缠论卖:BOLL开口扩张+MA金叉10_20",
     _C11 + [{"col": "BOLL开口扩张", "op": ">", "value": 0},
             {"col": "MA金叉10_20", "op": ">", "value": 0}]),
    ("TQ55", "六脉缠论卖:多头排列+阳包阴",
     _C11 + [{"col": "多头排列", "op": ">", "value": 0},
             {"col": "阳包阴", "op": ">", "value": 0}]),
    ("TQ56", "六脉缠论卖:斐波全多头+量比大于1",
     _C11 + [{"col": "斐波全多头", "op": ">", "value": 0},
             {"col": "量比大于1", "op": ">", "value": 0}]),
    ("TQ57", "六脉缠论卖:斐波短中多头+20日新高",
     _C11 + [{"col": "斐波短中多头", "op": ">", "value": 0},
             {"col": "20日新高", "op": ">", "value": 0}]),
]


def _load_top50():
    with open(TOP50_PATH, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _panel_columns():
    """确认面板列名(只读 npz 头,毫秒级;进程内缓存一次)。"""
    return confirm_panel_columns()


def _iter_cond_cols(cond):
    """条件元素涉及的全部列名(嵌套 or_group 递归展开)。"""
    if "or_group" in cond:
        for sub in cond["or_group"]:
            yield from _iter_cond_cols(sub)
    else:
        yield cond["col"]


def _build_spec(name, raw, conds):
    cols = _panel_columns()
    missing = sorted({c for cond in conds for c in _iter_cond_cols(cond)
                      if c not in cols})
    if missing:
        return {"name": name, "raw": raw, "join": "AND", "conds": [],
                "unavailable": True,
                "reason": f"面板缺列: {'、'.join(missing)}",
                "missing_cols": missing}
    return {"name": name, "raw": raw, "join": "AND", "conds": conds,
            "unavailable": False}


def build_57_specs():
    """构建 57 条 ComboSpec(对确认面板列做存在性自检:缺列标 unavailable)。"""
    specs = []
    for item in _load_top50():
        name = "TQ%02d" % item["排名"]
        raw = item["组合"]
        conds = [{"col": t.strip(), "op": ">", "value": 0}
                 for t in raw.split(" AND ")]
        specs.append(_build_spec(name, raw, conds))
    for name, label, conds in _MANUAL_51_57:
        specs.append(_build_spec(name, label, conds))
    avail = sum(1 for s in specs if not s.get("unavailable"))
    print(f"[signal_specs] 57 规格构建完成(确认面板列自检):"
          f"可用 {avail}/57,缺列 {57 - avail} 条已标 unavailable")
    return specs


def audit_missing():
    """列存在性自检结果(可测):{信号名: 缺列清单},只含缺列信号。"""
    return {s["name"]: s["missing_cols"] for s in build_57_specs()
            if s.get("unavailable")}


__all__ = ["build_57_specs", "audit_missing", "TOP50_PATH"]
