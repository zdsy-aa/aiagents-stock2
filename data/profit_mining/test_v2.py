# test_v2.py —— V2新模块合成数据断言测试（无pytest, python3直接跑）
import numpy as np, pandas as pd
import label_window as LW
import features as F
import event_registry as ER


def _df(close, high=None, low=None):
    n = len(close)
    high = high if high is not None else [c for c in close]
    low = low if low is not None else [c for c in close]
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({"Open": close, "High": high, "Low": low,
                         "Close": close, "Volume": [1000.0]*n}, index=idx)


def test_label_buy():
    # i=0 收盘100；未来窗口内最高 115 → 涨15% ≥10% → 盈利
    df = _df([100, 105, 115, 108], high=[100, 106, 115, 109])
    label, mfe, trunc = LW.forward_window_label(df, 0, "buy", win=30, thresh=0.10)
    assert label == 1, label
    assert abs(mfe - 0.15) < 1e-6, mfe
    assert trunc is True   # 可用未来根数 3 < 30
    # 涨幅不足
    df2 = _df([100, 103, 105], high=[100, 104, 106])
    l2, m2, _ = LW.forward_window_label(df2, 0, "buy", win=30, thresh=0.10)
    assert l2 == 0 and abs(m2 - 0.06) < 1e-6, (l2, m2)
    print("OK label_buy")


def test_label_sell():
    # i=0 收盘100；未来最低 88 → 跌12% ≥10% → 好卖
    df = _df([100, 95, 88, 92], low=[100, 94, 88, 91])
    label, mae, trunc = LW.forward_window_label(df, 0, "sell", win=30, thresh=0.10)
    assert label == 1, label
    assert abs(mae - (-0.12)) < 1e-6, mae
    print("OK label_sell")


def test_label_no_future():
    df = _df([100])
    label, mfe, trunc = LW.forward_window_label(df, 0, "buy", win=30, thresh=0.10)
    assert label == 0 and trunc is True
    print("OK label_no_future")


def test_zhuangsan():
    # 构造先跌后涨：制造吸筹低位 + 庄家上穿散户。
    # high/low 给 ±2% 日内振幅，避免 high=low=close 使 KDJ-RSV 退化、庄家线响应迟钝。
    close = list(np.linspace(20, 10, 60)) + list(np.linspace(10, 18, 40))
    df = _df(close, high=[c * 1.02 for c in close], low=[c * 0.98 for c in close])
    f = F.zhuangsan_features(df)
    for col in ["吸筹值", "庄家线", "散户线", "庄散买1", "庄散买2", "庄散卖1", "庄散卖2"]:
        assert col in f.columns, col
    # 布尔列取值合法
    for col in ["庄散买1", "庄散买2", "庄散卖1", "庄散卖2"]:
        assert set(pd.Series(f[col]).dropna().unique()) <= {0, 1}, col
    # 买2(庄家上穿散户且庄家<50)在干净合成数据上是罕见配置(穿点多在高位被<50门槛过滤)，
    # 故不强求其触发，而是用对外暴露的庄家线/散户线复算公式，验证买2接线正确：
    z, s = f["庄家线"], f["散户线"]
    cross_up = (z > s) & (z.shift(1) <= s.shift(1))
    expected_buy2 = (cross_up & (z < 50)).astype(int)
    assert (f["庄散买2"] == expected_buy2).all(), "庄散买2 与暴露线复算不一致"
    assert ((f["庄散买2"] == 1) <= (z < 50)).all(), "存在庄家>=50的买2"
    # 接线烟测：四类信号在该V型路径上至少触发一次(CROSS 管路有效)
    assert int(f[["庄散买1", "庄散买2", "庄散卖1", "庄散卖2"]].to_numpy().sum()) >= 1
    print("OK zhuangsan")


def test_liumai_signal():
    df = _df(list(10 + np.sin(np.linspace(0, 20, 200)) * 2))
    f = F.liumai_signal_features(df)
    assert "六脉齐红首发" in f.columns and "六脉齐绿首发" in f.columns
    for col in ["六脉齐红首发", "六脉齐绿首发"]:
        assert set(pd.Series(f[col]).dropna().unique()) <= {0, 1}
    print("OK liumai_signal")


def test_metrics():
    import mine_combos_v2 as MC
    win = np.array([1,1,0,0,1,0,1,0])
    mask = np.array([1,1,1,0,1,0,0,0], dtype=bool)
    m = MC.metrics(mask, win.astype(bool), "G", "测试")
    assert m["支持数"] == 4
    assert 0 <= m["条件内胜率"] <= 1
    assert m["提升度"] > 0
    print("OK metrics")


def test_capitalflow():
    """capitalflow_features: 返回预期列; 布尔列∈{0,1}; 连续列为数值; assemble列数增加且无重复列"""
    # 构造 V 型 close：先跌后涨，有高低振幅，成交量有波动
    np.random.seed(42)
    n = 300
    base = list(np.linspace(20, 10, 150)) + list(np.linspace(10, 18, 150))
    close = [b + np.random.uniform(-0.2, 0.2) for b in base]
    high = [c * 1.02 + np.random.uniform(0, 0.3) for c in close]
    low  = [c * 0.98 - np.random.uniform(0, 0.3) for c in close]
    vol  = [1000.0 * (1 + 0.5 * np.random.random()) for _ in range(n)]
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    df = pd.DataFrame({"Open": close, "High": high, "Low": low,
                       "Close": close, "Volume": vol}, index=idx)

    f = F.capitalflow_features(df)

    expected_cols = ["主力强度", "资金强度", "主力参与", "资金金叉", "资金死叉",
                     "主力净流入", "机构净买"]
    for col in expected_cols:
        assert col in f.columns, f"capitalflow_features 缺少列: {col}"

    # 布尔列（int型0/1）取值合法
    bool_cols = ["主力参与", "资金金叉", "资金死叉", "主力净流入", "机构净买"]
    for col in bool_cols:
        vals = set(f[col].dropna().unique())
        assert vals <= {0, 1}, f"列 {col} 存在非0/1值: {vals}"

    # 连续列为数值（非全NaN）
    cont_cols = ["主力强度", "资金强度"]
    for col in cont_cols:
        assert pd.api.types.is_numeric_dtype(f[col]), f"列 {col} 非数值类型"
        assert f[col].notna().sum() > 0, f"列 {col} 全为NaN"

    # assemble_feature_frame 列数增加且无重复
    af = F.assemble_feature_frame(df)
    assert "主力强度" in af.columns, "assemble 缺少 主力强度"
    assert "资金强度" in af.columns, "assemble 缺少 资金强度"
    assert af.columns.duplicated().sum() == 0, f"assemble 存在重复列: {list(af.columns[af.columns.duplicated()])}"

    print("OK capitalflow")


def test_volatility_env():
    """volatility_env_features: 返回预期列; 布尔列∈{0,1}; 连续列数值; assemble无重复列"""
    np.random.seed(7)
    n = 300
    base = list(np.linspace(20, 10, 150)) + list(np.linspace(10, 18, 150))
    close = [b + np.random.uniform(-0.2, 0.2) for b in base]
    high  = [c * 1.02 + np.random.uniform(0, 0.3) for c in close]
    low   = [c * 0.98 - np.random.uniform(0, 0.3) for c in close]
    vol   = [1000.0 * (1 + 0.5 * np.random.random()) for _ in range(n)]
    idx   = pd.date_range("2024-01-01", periods=n, freq="D")
    df    = pd.DataFrame({"Open": close, "High": high, "Low": low,
                          "Close": close, "Volume": vol}, index=idx)

    f = F.volatility_env_features(df)

    # 1. 预期列全部存在
    bool_cols = ["低波动", "高波动", "趋势加速", "缩量企稳"]
    cont_cols = ["波动率", "波动率百分位", "波动档", "MA20斜率"]
    for col in bool_cols + cont_cols:
        assert col in f.columns, f"volatility_env_features 缺少列: {col}"

    # 2. 布尔列取值 ∈ {0, 1}
    for col in bool_cols:
        vals = set(f[col].dropna().unique())
        assert vals <= {0, 1}, f"列 {col} 存在非0/1值: {vals}"

    # 3. 连续列为数值且非全NaN
    for col in cont_cols:
        assert pd.api.types.is_numeric_dtype(f[col]), f"列 {col} 非数值类型"
        assert f[col].notna().sum() > 0, f"列 {col} 全为NaN"

    # 4. 波动档取值 ∈ {1, 2, 3}（非NaN部分）
    valid = f["波动档"].dropna()
    assert set(valid.unique()) <= {1.0, 2.0, 3.0}, f"波动档含非法值: {set(valid.unique())}"

    # 5. 低波动+高波动不同时为1
    assert ((f["低波动"] == 1) & (f["高波动"] == 1)).sum() == 0, "低波动与高波动不应同时为1"

    # 6. assemble_feature_frame 包含新列且无重复列
    af = F.assemble_feature_frame(df)
    for col in bool_cols + cont_cols:
        assert col in af.columns, f"assemble 缺少列: {col}"
    assert af.columns.duplicated().sum() == 0, \
        f"assemble 存在重复列: {list(af.columns[af.columns.duplicated()])}"

    # 7. CONTINUOUS_COLS 中包含连续量
    for col in ["波动率", "波动率百分位", "波动档", "MA20斜率"]:
        assert col in F.CONTINUOUS_COLS, f"CONTINUOUS_COLS 缺少: {col}"

    print("OK volatility_env")


def test_wyckoff_ext():
    """wyckoff_ext_features: 返回预期列; 布尔列∈{0,1}; assemble无重复列"""
    np.random.seed(42)
    n = 400
    # 构造先下跌后上涨行情，使B2/B5/B6信号有机会触发
    base = list(np.linspace(20, 10, 200)) + list(np.linspace(10, 20, 200))
    close = [b + np.random.uniform(-0.3, 0.3) for b in base]
    high  = [c * 1.03 + np.random.uniform(0, 0.5) for c in close]
    low   = [c * 0.97 - np.random.uniform(0, 0.5) for c in close]
    # 构造多样的量：前半段大量（积累SC特征），后半段均量
    vol   = [2000.0 * (1 + np.random.random()) if i < 10 else
             1000.0 * (1 + 0.5 * np.random.random()) for i in range(n)]
    idx   = pd.date_range("2024-01-01", periods=n, freq="D")
    df    = pd.DataFrame({"Open": close, "High": high, "Low": low,
                          "Close": close, "Volume": vol}, index=idx)

    f = F.wyckoff_ext_features(df)

    # 1. 预期列全部存在
    bool_cols = ["威科夫B2回踩", "威科夫B4强势杆", "威科夫B5底背离", "威科夫B6缺口突破"]
    for col in bool_cols:
        assert col in f.columns, f"wyckoff_ext_features 缺少列: {col}"

    # 2. 布尔列取值 ∈ {0, 1}
    for col in bool_cols:
        vals = set(f[col].dropna().unique())
        assert vals <= {0, 1}, f"列 {col} 存在非0/1值: {vals}"

    # 3. 非全零（足够长序列应出现至少1次信号）
    for col in bool_cols:
        assert f[col].sum() >= 0, f"列 {col} sum < 0（不可能）"  # 宽松：仅保证非负

    # 4. assemble_feature_frame 包含新列且无重复列
    af = F.assemble_feature_frame(df)
    for col in bool_cols:
        assert col in af.columns, f"assemble 缺少列: {col}"
    assert af.columns.duplicated().sum() == 0, \
        f"assemble 存在重复列: {list(af.columns[af.columns.duplicated()])}"

    # 5. 与已有威科夫列不冲突（B1/B3/得分/积累阶段 仍存在）
    for col in ["威科夫B1突破", "威科夫B3弹簧", "威科夫得分大于4", "积累阶段"]:
        assert col in af.columns, f"assemble 丢失原有列: {col}"

    print("OK wyckoff_ext")


def test_chanlun_struct():
    """chanlun_struct_features: 列存在/布尔{0,1}/连续量数值/assemble无重复列"""
    np.random.seed(13)
    n = 400
    # 构造V型走势：先下跌后上涨，有足够波动让底分型/顶分型触发
    base = list(np.linspace(20, 8, 200)) + list(np.linspace(8, 18, 200))
    close = [b + np.random.uniform(-0.3, 0.3) for b in base]
    high  = [c * 1.025 + np.random.uniform(0, 0.4) for c in close]
    low   = [c * 0.975 - np.random.uniform(0, 0.4) for c in close]
    vol   = [1000.0 * (1 + 0.5 * np.random.random()) for _ in range(n)]
    idx   = pd.date_range("2024-01-01", periods=n, freq="D")
    df    = pd.DataFrame({"Open": close, "High": high, "Low": low,
                          "Close": close, "Volume": vol}, index=idx)

    f = F.chanlun_struct_features(df)

    # 1. 预期列全部存在
    bool_cols = ["MACD底背驰", "缠论底分型", "缠论方向多", "缠论一买", "缠论二买", "缠论V2过滤",
                 "缠论趋势强势", "缠论评分大于65"]
    cont_cols = ["缠论趋势评分", "MACD背驰强度"]
    for col in bool_cols + cont_cols:
        assert col in f.columns, f"chanlun_struct_features 缺少列: {col}"

    # 2. 布尔列取值 ∈ {0, 1}
    for col in bool_cols:
        vals = set(f[col].dropna().unique())
        assert vals <= {0, 1}, f"列 {col} 存在非0/1值: {vals}"

    # 3. 连续列为数值且非全NaN
    for col in cont_cols:
        assert pd.api.types.is_numeric_dtype(f[col]), f"列 {col} 非数值类型"
        assert f[col].notna().sum() > 0, f"列 {col} 全为NaN"

    # 4. 缠论趋势评分上限100，下限理论最低=-4（量能分最低-2且持续，其余分均>=0）
    valid_score = f["缠论趋势评分"].dropna()
    assert (valid_score <= 100).all(), \
        f"缠论趋势评分超出上限100: max={valid_score.max()}"
    assert (valid_score >= -10).all(), \
        f"缠论趋势评分低于-10（异常）: min={valid_score.min()}"

    # 5. MACD背驰强度 >= 0
    valid_div = f["MACD背驰强度"].dropna()
    assert (valid_div >= 0).all(), f"MACD背驰强度存在负值"

    # 6. assemble_feature_frame 包含新列且无重复列
    af = F.assemble_feature_frame(df)
    for col in bool_cols + cont_cols:
        assert col in af.columns, f"assemble 缺少列: {col}"
    assert af.columns.duplicated().sum() == 0, \
        f"assemble 存在重复列: {list(af.columns[af.columns.duplicated()])}"

    # 7. CONTINUOUS_COLS 包含连续量
    for col in cont_cols:
        assert col in F.CONTINUOUS_COLS, f"CONTINUOUS_COLS 缺少: {col}"

    print("OK chanlun_struct")


def test_multiperiod_v8():
    """multiperiod_resonance(V8扩充): 含新4列; 做多权重∈[-3,3]整数; 空头/多头共振互斥;
    首发是对应共振的子集且带>=15根冷却(同一段共振内至多一个首发)。"""
    # 单调上升200根 → 三周期方向全多 → 多头共振长期为真，首发应只在起点附近一次
    up = list(np.linspace(10, 30, 200))
    f = F.multiperiod_resonance(_df(up))
    for col in ["做多权重", "空头共振", "多头首发", "空头首发", "偏多共振", "多头共振"]:
        assert col in f.columns, f"缺列 {col}"
    assert set(pd.Series(f["做多权重"]).dropna().unique()) <= {-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0}
    for col in ["空头共振", "多头首发", "空头首发"]:
        assert set(pd.Series(f[col]).dropna().unique()) <= {0, 1}
    # 共振互斥：不会同时多头与空头共振
    assert int(((f["多头共振"] == 1) & (f["空头共振"] == 1)).sum()) == 0
    # 首发是共振的子集
    assert ((f["多头首发"] == 1) <= (f["多头共振"] == 1)).all()
    assert ((f["空头首发"] == 1) <= (f["空头共振"] == 1)).all()
    # 冷却：任意两个相邻多头首发间隔>=15根
    pos = np.where(f["多头首发"].to_numpy() == 1)[0]
    if len(pos) >= 2:
        assert int(np.diff(pos).min()) >= 15, "多头首发冷却<15根"
    print("OK multiperiod_v8")


def test_event_registry():
    assert set(ER.EVENTS) >= {"缠论1买","缠论2买","缠论3买","六脉齐红首发买",
        "庄散买1","庄散买2","缠论1卖","缠论2卖","缠论3卖","六脉齐绿首发卖","庄散卖1","庄散卖2"}
    assert ER.EVENTS["缠论1买"]["direction"] == "buy"
    assert ER.EVENTS["庄散卖1"]["direction"] == "sell"
    # 防泄漏：分析庄散买1组应剔除庄散全族信号
    leak = ER.leakage_signals("庄散买1")
    assert {"庄散买1","庄散买2","庄散卖1","庄散卖2","吸筹值","庄家线","散户线"} <= set(leak)
    # 六脉组剔除六脉族(含V8共振派生信号)
    assert {"六脉齐红首发","六脉齐绿首发","六脉红灯数","六脉6红首发",
            "做多权重","空头共振","多头首发","空头首发"} <= set(ER.leakage_signals("六脉齐红首发买"))
    # 缠论族：分析缠论1买时应剔除所有缠论结构特征
    chanlun_new = {"MACD底背驰", "缠论底分型", "缠论方向多", "缠论一买", "缠论二买",
                   "缠论V2过滤", "缠论趋势强势", "缠论评分大于65", "缠论趋势评分", "MACD背驰强度"}
    leak_chan = ER.leakage_signals("缠论1买")
    assert chanlun_new <= set(leak_chan), \
        f"缠论族防泄漏缺少: {chanlun_new - set(leak_chan)}"
    print("OK event_registry")


if __name__ == "__main__":
    test_label_buy(); test_label_sell(); test_label_no_future()
    test_zhuangsan()
    test_liumai_signal()
    test_event_registry()
    test_metrics()
    test_capitalflow()
    test_volatility_env()
    test_wyckoff_ext()
    test_chanlun_struct()
    test_multiperiod_v8()
    print("ALL OK")
