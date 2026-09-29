"""页面路由：按 session_state 的 show_* 标志分派到对应页面。

从 app.main() 抽出(行为不变)：命中任一标志即渲染该页并返回 True，
调用方据此 return(不再渲染主分析界面);无命中返回 False。
"""
import streamlit as st

from main_force_ui import display_main_force_selector
from sector_strategy_ui import display_sector_strategy
from longhubang_ui import display_longhubang
from news_flow_ui import display_news_flow_monitor
from views.config_manager import display_config_manager


def route_page() -> bool:
    """命中并渲染某页则返回 True；否则 False。"""
    # 检查是否显示主力选股
    if 'show_main_force' in st.session_state and st.session_state.show_main_force:
        display_main_force_selector()
        return True
    
    # 检查是否显示低价擒牛
    if 'show_low_price_bull' in st.session_state and st.session_state.show_low_price_bull:
        from low_price_bull_ui import display_low_price_bull
        display_low_price_bull()
        return True
    
    # 检查是否显示小市值策略
    if 'show_small_cap' in st.session_state and st.session_state.show_small_cap:
        from small_cap_ui import display_small_cap
        display_small_cap()
        return True
    
    # 检查是否显示净利增长策略
    if 'show_profit_growth' in st.session_state and st.session_state.show_profit_growth:
        from profit_growth_ui import display_profit_growth
        display_profit_growth()
        return True

    # 检查是否显示低估值策略
    if 'show_value_stock' in st.session_state and st.session_state.show_value_stock:
        from value_stock_ui import display_value_stock
        display_value_stock()
        return True

    # 检查是否显示智策板块
    if 'show_sector_strategy' in st.session_state and st.session_state.show_sector_strategy:
        display_sector_strategy()
        return True

    # 检查是否显示智瞰龙虎
    if 'show_longhubang' in st.session_state and st.session_state.show_longhubang:
        display_longhubang()
        return True

    # 检查是否显示新闻流量监测
    if 'show_news_flow' in st.session_state and st.session_state.show_news_flow:
        display_news_flow_monitor()
        return True

    # 检查是否显示宏观分析
    if 'show_macro_analysis' in st.session_state and st.session_state.show_macro_analysis:
        from macro_analysis_ui import display_macro_analysis
        display_macro_analysis()
        return True

    # 检查是否显示宏观周期分析
    if 'show_macro_cycle' in st.session_state and st.session_state.show_macro_cycle:
        from macro_cycle_ui import display_macro_cycle
        display_macro_cycle()
        return True

    # 检查是否显示板块分析
    if 'show_sector_detail' in st.session_state and st.session_state.show_sector_detail:
        from sector_detail_ui import display_sector_detail
        display_sector_detail()
        return True

    # 检查是否显示产业链分析
    if 'show_industry_chain' in st.session_state and st.session_state.show_industry_chain:
        from industry_chain_ui import display_industry_chain
        display_industry_chain()
        return True

    # 检查是否显示环境配置
    if 'show_config' in st.session_state and st.session_state.show_config:
        display_config_manager()
        return True

    # 检查是否显示缠论选股（放在所有其它 show_* 之后，残留标志不会抢占其它页面）
    if 'show_chanlun' in st.session_state and st.session_state.show_chanlun:
        from chanlun_ui import display_chanlun_selector
        display_chanlun_selector()
        return True

    # 检查是否显示六脉神剑选股
    if 'show_liumai' in st.session_state and st.session_state.show_liumai:
        from liumai_ui import display_liumai_selector
        display_liumai_selector()
        return True

    # 检查是否显示缠论×六脉组合策略
    if 'show_combo' in st.session_state and st.session_state.show_combo:
        from combo_ui import display_combo_selector
        display_combo_selector()
        return True

    # 检查是否显示稳定选股（经样本外验证的买卖策略）
    if 'show_stable' in st.session_state and st.session_state.show_stable:
        from stable_ui import display_stable_selector
        display_stable_selector()
        return True

    if st.session_state.get('show_qizhang'):
        from qizhang_predict_ui import display_qizhang_predict
        display_qizhang_predict()
        return True

    # 检查是否显示「当前策略」只读总览页
    if 'show_current_strategy' in st.session_state and st.session_state.show_current_strategy:
        from current_strategy_ui import display_current_strategy
        display_current_strategy()
        return True

    # 检查是否显示「文档」子页(指标/项目/流程/目录说明)
    if st.session_state.get('show_docs_indicator'):
        from views.docs_page import render_indicator_docs
        render_indicator_docs()
        return True
    if st.session_state.get('show_docs_project'):
        from views.docs_page import render_project_docs
        render_project_docs()
        return True
    if st.session_state.get('show_docs_flow'):
        from views.docs_page import render_flow_docs
        render_flow_docs()
        return True
    if st.session_state.get('show_docs_scan'):
        from views.docs_page import render_scan_docs
        render_scan_docs()
        return True
    if st.session_state.get('show_mindmap'):
        from mindmap_ui import display_mindmap
        display_mindmap()
        return True
    return False
