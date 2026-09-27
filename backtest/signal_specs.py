# backtest/signal_specs.py
"""57 信号规格构建:TQ01~TQ50 从 Top50 JSON 的「组合」串解析,
TQ51~TQ57 按 tq_confirm_top10.py 定义手工映射到面板列。

ComboSpec = {"name": str, "conds": [{"col": str, "op": ">", "value": float}],
             "join": "AND"}
缺列信号:conds 置空 + "unavailable": true + "reason"(含缺列清单)+
"missing_cols" 列表;eval_combo 对其返回全 False(对齐测试据此跳过)。
列存在性自检在 build_57_specs() 内对 load_panel().columns 执行,
映射决定与缺列明细见 .superpowers/sdd/.../task-3.1-report.md。
"""
import json
from functools import lru_cache

from backtest.dataio import load_panel

TOP50_PATH = ("/home/tdxback/aiagents-stock/data/commonality_reports/"
              "确认信号_Top50去重_20260908.json")

# ---------------------------------------------------------------------------
# TQ51~TQ57 手工映射(tq_confirm_top10.py compute_signals 定义)
# 组合11 = 缠论买点(一买/二买/强二买)4日内 AND 六脉六红4日内(两信号不必同日,
# 各自 rolling(4).max() 含当日)。面板近似:
#   * 缠论买点4日:load_panel 每行均为缠论买点事件(买点类型 ∈ {1买,2买,3买}),
#     故该支天然成立;3买 不在 tq 的 一买/二买/强二买 口径内,为近似多含(记录)。
#   * 六红4日:面板列「六脉红灯大于6」= 六维红灯计数 >= 6 = 六红(features.py:258
#     命名偏小,语义核对为 >=6);4日窗口面板不可表达,取同日近似(记录)。
# ---------------------------------------------------------------------------
_C11 = [{"col": "六脉红灯大于6", "op": ">", "value": 0}]

# TQ51 的「深跌承接」在 tq 口径为 OR 组(大盘空头 OR 趋势空头 OR 资金强度大于10
# OR 机构净买);ComboSpec 平铺接口无嵌套 OR,此处按 AND 平铺记录全部成员列
# (该 spec 因缺列标 unavailable,conds 仅作结构记录,不参与求值)。
_MANUAL_51_57 = [
    ("TQ51", "六脉缠论买:深跌+空头/资金承接",
     _C11 + [{"col": "20日跌幅超15", "op": ">", "value": 0},
             {"col": "大盘空头", "op": ">", "value": 0},
             {"col": "趋势空头", "op": ">", "value": 0},
             {"col": "资金强度大于10", "op": ">", "value": 0},
             {"col": "机构净买", "op": ">", "value": 0}]),
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
    """数据基座 3.0 面板列名(load_panel 读盘开销大,进程内缓存一次)。"""
    return tuple(load_panel().columns)


def _build_spec(name, raw, conds):
    cols = _panel_columns()
    missing = [c["col"] for c in conds if c["col"] not in cols]
    if missing:
        return {"name": name, "raw": raw, "join": "AND", "conds": [],
                "unavailable": True,
                "reason": f"面板缺列: {'、'.join(missing)}",
                "missing_cols": missing}
    return {"name": name, "raw": raw, "join": "AND", "conds": conds,
            "unavailable": False}


def build_57_specs():
    """构建 57 条 ComboSpec(列存在性自检:缺列标 unavailable,conds 置空)。"""
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
    print(f"[signal_specs] 57 规格构建完成:可用 {avail}/57,"
          f"缺列 {57 - avail} 条已标 unavailable")
    return specs


def audit_missing():
    """列存在性自检结果(可测):{信号名: 缺列清单},只含缺列信号。"""
    return {s["name"]: s["missing_cols"] for s in build_57_specs()
            if s.get("unavailable")}


__all__ = ["build_57_specs", "audit_missing", "TOP50_PATH"]
