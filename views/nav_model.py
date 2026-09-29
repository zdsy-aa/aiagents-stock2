# views/nav_model.py
"""导航单源：大类 → 子页(标签, show_flag, help)。驱动顶部导航与侧栏；路由仍用 show_* 标志。"""

# (category, icon, [(label, show_flag 或 None=首页, help)])
NAV = [
    ("分析", "🔬", [
        ("🏠 股票分析-日", None, "返回首页，单只股票日线深度分析"),
    ]),
    ("选股", "🎯", [
        ("💰 主力选股", "show_main_force", "主力资金流向选股"),
        ("🐂 低价擒牛", "show_low_price_bull", "低价高成长筛选"),
        ("📊 小市值", "show_small_cap", "小盘高成长筛选"),
        ("📈 净利增长", "show_profit_growth", "净利润增长稳健筛选"),
        ("💎 低估值", "show_value_stock", "低PE+低PB+高股息+低负债"),
        ("🌀 缠论选股", "show_chanlun", "多级别缠论买点筛选"),
        ("🔱 六脉神剑", "show_liumai", "六维多头共振≥5红"),
        ("🔗 缠论×六脉", "show_combo", "缠论买点±3日内六脉5红"),
        ("🛡️ 稳定选股", "show_stable", "样本外验证的稳健买卖策略"),
        ("📈 起涨预测", "show_qizhang", "起涨C4策略 paper-tracking 观察"),
        ("📋 当前策略", "show_current_strategy", "全部策略脚本与说明只读总览"),
    ]),
    ("策略", "📊", [
        ("🎯 智策板块", "show_sector_strategy", "AI板块策略分析"),
        ("🐉 智瞰龙虎", "show_longhubang", "龙虎榜深度分析"),
        ("📰 新闻流量", "show_news_flow", "新闻流量监测与短线指导"),
        ("🌏 宏观分析", "show_macro_analysis", "宏观数据×行业映射×标的"),
        ("🧭 宏观周期", "show_macro_cycle", "康波×美林时钟×政策"),
        ("🔗 产业链", "show_industry_chain", "产业链上下游分析与传导"),
        ("📊 板块分析", "show_sector_detail", "行业/概念板块深度钻取"),
    ]),
    ("配置", "⚙️", [
        ("⚙️ 环境配置", "show_config", "系统设置与API配置"),
    ]),
    ("文档", "📚", [
        ("📐 指标文档", "show_docs_indicator", "单指标与组合指标(57信号)说明"),
        ("📁 项目文档", "show_docs_project", "项目核心说明文档"),
        ("🔄 流程文档", "show_docs_flow", "实施方案与各阶段计划"),
        ("🗂️ 目录说明", "show_docs_scan", "/home/tdxback 目录与文件说明"),
        ("🧠 项目思维导图", "show_mindmap", "项目结构实时思维导图(宿主机每分钟自动重建)"),
    ]),
]


def all_flags():
    """全部非空 show_* 标志（用于清其它页）。"""
    return [flag for _, _, pages in NAV for (_, flag, _) in pages if flag]


def flag_to_category(flag):
    """标志所属大类；未知/None → '分析'。"""
    for cat, _, pages in NAV:
        for (_, f, _) in pages:
            if f == flag:
                return cat
    return "分析"


def current_category(state=None):
    """据当前 session_state 的 show_* 标志反推大类；无标志=分析。state 可注入(测试)。"""
    if state is None:
        import streamlit as st
        state = st.session_state
    for flag in all_flags():
        if state.get(flag):
            return flag_to_category(flag)
    return "分析"


def category_pages(cat):
    for c, _, pages in NAV:
        if c == cat:
            return pages
    return []


def category_default_flag(cat):
    """大类落地页 = 首个子页的 flag（分析→None=首页）。"""
    pages = category_pages(cat)
    return pages[0][1] if pages else None
