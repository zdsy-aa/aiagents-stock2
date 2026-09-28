"""Task S1: 卖出镜像信号挖掘(TQ01S~TQ50S)测试。

合成迷你面板(不加载 15M 真实数据),验证:
- verify_sell_label: sell_label==1 ⟺ ext_dn <= -0.10 的一致率;
- mine_sell_mirrors: 行字典键集合(排名/组合/训练卖出率/测试卖出率/训练支持/测试支持);
- baseline_sell_rate: 训练/测试基线均在 [0, 1]。
"""
import pandas as pd
import numpy as np
import automation.sell_mirror_mining as sm

def _mini_panel(n=1000):
    rng = np.random.default_rng(0)
    sell = rng.integers(0, 2, n).astype(float)
    ext_dn = np.where(sell == 1, -0.15, -0.02).astype(float)
    df = pd.DataFrame({"是否亏损": sell, "下跌幅度": ext_dn,
                       "年": np.where(np.arange(n) < 500, "2024", "2025"),
                       "信号日期": [f"2024010{i%9+1}" for i in range(n)]})
    # 两个布尔组合列
    df["极限抄底"] = rng.integers(0, 2, n).astype(float)
    df["主力参与"] = rng.integers(0, 2, n).astype(float)
    return df

def test_verify_sell_label_consistency():
    df = _mini_panel()
    r = sm.verify_sell_label(df)
    assert r["consistent_ratio"] == 1.0

def test_mine_sell_mirrors_shape():
    df = _mini_panel()
    spec = {"name": "TQ01", "conds": [{"col": "极限抄底", "op": ">", "value": 0},
                                       {"col": "主力参与", "op": ">", "value": 0}], "join": "AND"}
    out = sm.mine_sell_mirrors(df, [spec])
    assert len(out) == 1
    r = out[0]
    assert set(r) == {"排名", "组合", "训练卖出率", "测试卖出率", "训练支持", "测试支持"}

def test_baseline_sell_rate_in_range():
    df = _mini_panel()
    b = sm.baseline_sell_rate(df)
    assert 0 <= b["train"] <= 1 and 0 <= b["test"] <= 1
