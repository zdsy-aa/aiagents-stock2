# event_registry.py —— 12组买卖点定义 + 体系归属（驱动防泄漏）
# family: 该组所属指标体系；分析该组时剔除同 family 的全部信号(及其派生)防泄漏。
EVENTS = {
    "缠论1买": dict(family="缠论", direction="buy",  source="chanlun", kind="1买"),
    "缠论2买": dict(family="缠论", direction="buy",  source="chanlun", kind="2买"),
    "缠论3买": dict(family="缠论", direction="buy",  source="chanlun", kind="3买"),
    "六脉齐红首发买": dict(family="六脉", direction="buy", source="signal", kind="六脉齐红首发"),
    "庄散买1": dict(family="庄散", direction="buy", source="signal", kind="庄散买1"),
    "庄散买2": dict(family="庄散", direction="buy", source="signal", kind="庄散买2"),
    "缠论1卖": dict(family="缠论", direction="sell", source="chanlun", kind="1卖"),
    "缠论2卖": dict(family="缠论", direction="sell", source="chanlun", kind="2卖"),
    "缠论3卖": dict(family="缠论", direction="sell", source="chanlun", kind="3卖"),
    "六脉齐绿首发卖": dict(family="六脉", direction="sell", source="signal", kind="六脉齐绿首发"),
    "庄散卖1": dict(family="庄散", direction="sell", source="signal", kind="庄散卖1"),
    "庄散卖2": dict(family="庄散", direction="sell", source="signal", kind="庄散卖2"),
}

# 各体系的本族信号名（含派生），分析时整体剔除。缠论不作特征(基础事件)，故其族暂空，
# 但保留键以备将来移植缠论类特征时填入。
FAMILY_SIGNALS = {
    "庄散": {"庄散买1","庄散买2","庄散卖1","庄散卖2","吸筹值","庄家线","散户线"},
    "六脉": {"六脉齐红首发","六脉齐绿首发","六脉红灯数","六脉6红首发","六脉5红首发",
            "六脉红灯大于5","六脉红灯大于6","偏多共振","多头共振",
            "做多权重","空头共振","多头首发","空头首发"},
    "缠论": {
        "MACD底背驰", "MACD背驰强度",
        "缠论底分型", "缠论方向多",
        "缠论一买", "缠论二买", "缠论V2过滤",
        "缠论趋势评分", "缠论趋势强势", "缠论评分大于65",
    },
}


def leakage_signals(group):
    """返回分析该组时应从特征池剔除的信号名集合。"""
    fam = EVENTS[group]["family"]
    return set(FAMILY_SIGNALS.get(fam, set()))
