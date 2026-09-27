# -*- coding: utf-8 -*-
"""Phase4 统一回测接口:run_backtest_api(薄包装 Phase3 backtest 包,不改行为)。

- run_backtest_api(spec_or_name, df=None) -> dict:
    spec_or_name 可为 ComboSpec dict(backtest.combo_engine)或 "TQ01"~"TQ57"
    信号名(经 build_57_specs 解析,未知名称抛 ValueError);df=None 时自动
    load_confirm_panel()(v1,15,115,796 行,解包 ~60s,真实调用允许,测试必须传
    合成 df)并按 split_train_test 切分(训练 年<=2024 / 测试 年>=2025),返回
    {"name", "train": <引擎12键>, "test": <引擎12键>} 两段合并 dict。
- 错误约定(R4-A):输入非法(未知名称/非 dict spec)抛 ValueError;取数/依赖
  缺失(面板缺列/无「年」列等)经 interfaces.common.api_error 包装为
  RuntimeError,消息含接口名,原异常挂 __cause__。
- 依赖:backtest.engine.run_backtest / backtest.dataio /
  backtest.combo_engine / interfaces.common。
"""
from backtest.combo_engine import build_57_specs
from backtest.dataio import load_confirm_panel, split_train_test
from backtest.engine import run_backtest
from interfaces.common import api_error

__all__ = ["run_backtest_api"]


def _resolve_spec(spec_or_name):
    """spec_or_name -> ComboSpec dict;未知名称/非法类型抛 ValueError(R4-A)。"""
    if isinstance(spec_or_name, dict):
        if not spec_or_name.get("name"):
            raise ValueError(f"spec 缺 name 字段: {spec_or_name!r}")
        return spec_or_name
    if not isinstance(spec_or_name, str) or not spec_or_name.strip():
        raise ValueError(
            f"spec_or_name 非法: {spec_or_name!r},应为 ComboSpec dict 或"
            f" TQ01~TQ57 信号名")
    name = spec_or_name.strip()
    specs = {s["name"]: s for s in build_57_specs()}
    if name not in specs:
        raise ValueError(f"未知信号名: {name!r}(57 规格中不存在)")
    return specs[name]


def run_backtest_api(spec_or_name, df=None):
    """统一回测入口:返回 train/test 两段引擎结果合并 dict(见模块 docstring)。

    df=None 走真面板路径(load_confirm_panel,15M 行,慢);测试与批处理调用方
    宜自备 df。
    """
    spec = _resolve_spec(spec_or_name)
    try:
        if df is None:
            df = load_confirm_panel()
        train, test = split_train_test(df)
        r_train = run_backtest(spec, train)
        r_test = run_backtest(spec, test)
    except Exception as exc:
        raise api_error("run_backtest_api", exc) from exc
    return {"name": spec["name"], "train": r_train, "test": r_test}
