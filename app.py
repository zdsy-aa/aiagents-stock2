import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from ui_theme import inject_theme, style_fig, metric_card, badge, section_header
import pandas as pd
import json
from datetime import datetime
import time
import base64
import os
import config
import logging
from logger_config import setup_logging

# 初始化统一日志配置
setup_logging()
logger = logging.getLogger(__name__)

from stock_analysis_engine import analysis_engine, StockAnalysisEngine
from stock_data import StockDataFetcher
from ai_agents import StockAnalysisAgents
from pdf_generator import display_pdf_export_section
from database import db
from monitor_manager import display_monitor_manager, get_monitor_summary
from monitor_service import monitor_service
from notification_service import notification_service
from config_manager import config_manager
from main_force_ui import display_main_force_selector
from sector_strategy_ui import display_sector_strategy
from longhubang_ui import display_longhubang
from smart_monitor_ui import smart_monitor_ui
from news_flow_ui import display_news_flow_monitor
from views.config_manager import display_config_manager
from views.history import display_history_records
from views.analysis_views import (
    get_stock_data, display_stock_info, display_stock_chart,
    display_agents_analysis, display_team_discussion, display_final_decision,
    show_example_interface, display_intraday_analysis, display_batch_analysis_results,
)
from views.analysis_runner import (
    check_api_key, parse_stock_list, analyze_single_stock_for_batch,
    run_batch_analysis, run_stock_analysis,
)

# 页面配置
st.set_page_config(
    page_title="复合多AI智能体股票团队分析系统",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 注入深色 Fintech 全局设计系统（全站 16 页同一次 run 内继承）
inject_theme()

# 在侧边栏显示当前模型信息（统一使用.env配置）
def show_current_model_info():
    """显示当前使用的AI模型信息"""
    st.sidebar.markdown("---")
    st.sidebar.subheader("🤖 AI模型")
    st.sidebar.info(f"当前模型: **{config.DEFAULT_MODEL_NAME}**")
    st.sidebar.caption("可在「环境配置」中修改模型名称")


def main():
    # 顶部标题栏
    st.markdown("""
    <div class="top-nav">
        <h1 class="nav-title">📈 复合多AI智能体股票团队分析系统</h1>
        <p class="nav-subtitle">基于DeepSeek的专业量化投资分析平台 | Multi-Agent Stock Analysis System</p>
    </div>
    """, unsafe_allow_html=True)

    # P2 整改八: 统一在入口处加载环境变量
    from dotenv import load_dotenv
    load_dotenv()
    
    # 侧边栏
    with st.sidebar:
        # 快捷导航 - 移到顶部
        st.markdown("### 🔍 功能导航")

        # 🏠 单股分析（首页，日线）
        if st.button("🏠 股票分析-日", width='stretch', key="nav_home", help="返回首页，进行单只股票的日线深度分析"):
            # 清除所有功能页面标志
            for key in ['show_history', 'show_monitor', 'show_config', 'show_main_force',
                       'show_sector_strategy', 'show_longhubang', 'show_portfolio', 'show_low_price_bull', 'show_news_flow', 'show_macro_cycle', 'show_macro_analysis', 'show_value_stock', 'show_intraday', 'show_chanlun', 'show_liumai', 'show_combo', 'show_stable', 'show_current_strategy']:
                if key in st.session_state:
                    del st.session_state[key]

        # ⏱️ 分时分析（纯短线技术面）
        if st.button("⏱️ 股票分析-分时", width='stretch', key="nav_intraday", help="仅按分钟线做纯短线技术面分析"):
            st.session_state.show_intraday = True
            for key in ['show_history', 'show_monitor', 'show_config', 'show_main_force',
                        'show_sector_strategy', 'show_longhubang', 'show_portfolio',
                        'show_low_price_bull', 'show_small_cap', 'show_profit_growth',
                        'show_value_stock', 'show_news_flow', 'show_macro_analysis',
                        'show_macro_cycle', 'show_smart_monitor', 'show_chanlun', 'show_liumai', 'show_combo', 'show_stable', 'show_current_strategy']:
                if key in st.session_state:
                    del st.session_state[key]

        st.markdown("---")

        # 🎯 选股板块
        with st.expander("🎯 选股板块", expanded=True):
            st.markdown("**根据不同策略筛选优质股票**")

            st.markdown("**单策略选股**")

            if st.button("💰 主力选股", width='stretch', key="nav_main_force", help="基于主力资金流向的选股策略"):
                st.session_state.show_main_force = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_sector_strategy',
                           'show_longhubang', 'show_portfolio', 'show_low_price_bull', 'show_news_flow', 'show_macro_analysis']:
                    if key in st.session_state:
                        del st.session_state[key]
            
            if st.button("🐂 低价擒牛", width='stretch', key="nav_low_price_bull", help="低价高成长股票筛选策略"):
                st.session_state.show_low_price_bull = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_sector_strategy',
                           'show_longhubang', 'show_portfolio', 'show_main_force', 'show_small_cap', 'show_profit_growth', 'show_news_flow', 'show_macro_analysis']:
                    if key in st.session_state:
                        del st.session_state[key]
            
            if st.button("📊 小市值策略", width='stretch', key="nav_small_cap", help="小盘高成长股票筛选策略"):
                st.session_state.show_small_cap = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_sector_strategy',
                           'show_longhubang', 'show_portfolio', 'show_main_force', 'show_low_price_bull', 'show_profit_growth', 'show_news_flow', 'show_macro_analysis']:
                    if key in st.session_state:
                        del st.session_state[key]
            
            if st.button("📈 净利增长", width='stretch', key="nav_profit_growth", help="净利润增长稳健股票筛选策略"):
                st.session_state.show_profit_growth = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_sector_strategy',
                           'show_longhubang', 'show_portfolio', 'show_main_force', 'show_low_price_bull', 'show_small_cap', 'show_news_flow', 'show_value_stock', 'show_macro_analysis']:
                    if key in st.session_state:
                        del st.session_state[key]

            if st.button("💎 低估值策略", width='stretch', key="nav_value_stock", help="低PE+低PB+高股息+低负债 价值投资筛选"):
                st.session_state.show_value_stock = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_sector_strategy',
                           'show_longhubang', 'show_portfolio', 'show_main_force', 'show_low_price_bull', 'show_small_cap', 'show_profit_growth', 'show_news_flow', 'show_macro_cycle', 'show_macro_analysis']:
                    if key in st.session_state:
                        del st.session_state[key]

            if st.button("🌀 缠论选股", width='stretch', key="nav_chanlun", help="多级别缠论买点筛选（日线本级别+30分钟次级别确认），读每日收盘后预计算结果"):
                st.session_state.show_chanlun = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_main_force',
                           'show_sector_strategy', 'show_longhubang', 'show_portfolio', 'show_low_price_bull',
                           'show_small_cap', 'show_profit_growth', 'show_value_stock', 'show_news_flow',
                           'show_macro_analysis', 'show_macro_cycle', 'show_smart_monitor', 'show_intraday',
                           'show_liumai', 'show_combo', 'show_stable']:
                    if key in st.session_state:
                        del st.session_state[key]

            if st.button("🔱 六脉神剑", width='stretch', key="nav_liumai", help="六维(MACD/KDJ/RSI/LWR/BBI/MTM)多头共振，选最新多头数≥5(5红以上)"):
                st.session_state.show_liumai = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_main_force',
                           'show_sector_strategy', 'show_longhubang', 'show_portfolio', 'show_low_price_bull',
                           'show_small_cap', 'show_profit_growth', 'show_value_stock', 'show_news_flow',
                           'show_macro_analysis', 'show_macro_cycle', 'show_smart_monitor', 'show_intraday',
                           'show_chanlun', 'show_combo', 'show_stable']:
                    if key in st.session_state:
                        del st.session_state[key]

            st.markdown("**组合策略选股**")

            if st.button("🔗 缠论×六脉", width='stretch', key="nav_combo", help="缠论买点±3交易日内六脉神剑5红以上"):
                st.session_state.show_combo = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_main_force',
                           'show_sector_strategy', 'show_longhubang', 'show_portfolio', 'show_low_price_bull',
                           'show_small_cap', 'show_profit_growth', 'show_value_stock', 'show_news_flow',
                           'show_macro_analysis', 'show_macro_cycle', 'show_smart_monitor', 'show_intraday',
                           'show_chanlun', 'show_liumai', 'show_stable']:
                    if key in st.session_state:
                        del st.session_state[key]

            if st.button("🛡️ 稳定选股", width='stretch', key="nav_stable", help="经样本外验证的稳健买卖策略(抄底/抢筹/过热顶)，含方案说明与今日候选"):
                st.session_state.show_stable = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_main_force',
                           'show_sector_strategy', 'show_longhubang', 'show_portfolio', 'show_low_price_bull',
                           'show_small_cap', 'show_profit_growth', 'show_value_stock', 'show_news_flow',
                           'show_macro_analysis', 'show_macro_cycle', 'show_smart_monitor', 'show_intraday',
                           'show_chanlun', 'show_liumai', 'show_combo']:
                    if key in st.session_state:
                        del st.session_state[key]

            if st.button("📋 当前策略", width='stretch', key="nav_current_strategy", help="集中查看全部 选股/买卖/测试盈利/找共同点 策略的脚本与中文说明（只读，便于识别后决定修改）"):
                st.session_state.show_current_strategy = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_main_force',
                           'show_sector_strategy', 'show_longhubang', 'show_portfolio', 'show_low_price_bull',
                           'show_small_cap', 'show_profit_growth', 'show_value_stock', 'show_news_flow',
                           'show_macro_analysis', 'show_macro_cycle', 'show_smart_monitor', 'show_intraday',
                           'show_chanlun', 'show_liumai', 'show_combo', 'show_stable']:
                    if key in st.session_state:
                        del st.session_state[key]

        # 📊 策略分析
        with st.expander("📊 策略分析", expanded=True):
            st.markdown("**AI驱动的板块和龙虎榜策略**")

            if st.button("🎯 智策板块", width='stretch', key="nav_sector_strategy", help="AI板块策略分析"):
                st.session_state.show_sector_strategy = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_main_force',
                           'show_longhubang', 'show_portfolio', 'show_smart_monitor', 'show_low_price_bull', 'show_news_flow', 'show_macro_analysis']:
                    if key in st.session_state:
                        del st.session_state[key]

            if st.button("🐉 智瞰龙虎", width='stretch', key="nav_longhubang", help="龙虎榜深度分析"):
                st.session_state.show_longhubang = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_main_force',
                           'show_sector_strategy', 'show_portfolio', 'show_smart_monitor', 'show_low_price_bull', 'show_news_flow', 'show_macro_analysis']:
                    if key in st.session_state:
                        del st.session_state[key]
            
            if st.button("📰 新闻流量", width='stretch', key="nav_news_flow", help="新闻流量监测与短线指导"):
                st.session_state.show_news_flow = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_main_force',
                           'show_sector_strategy', 'show_portfolio', 'show_smart_monitor', 'show_low_price_bull', 'show_longhubang', 'show_macro_cycle', 'show_macro_analysis']:
                    if key in st.session_state:
                        del st.session_state[key]

            if st.button("🌏 宏观分析", width='stretch', key="nav_macro_analysis", help="国家统计局宏观数据 × A股行业映射 × 优质标的"):
                st.session_state.show_macro_analysis = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_main_force',
                           'show_sector_strategy', 'show_portfolio', 'show_smart_monitor', 'show_low_price_bull', 'show_longhubang', 'show_news_flow', 'show_macro_cycle']:
                    if key in st.session_state:
                        del st.session_state[key]

            if st.button("🧭 宏观周期", width='stretch', key="nav_macro_cycle", help="康波周期 × 美林投资时钟 × 政策分析"):
                st.session_state.show_macro_cycle = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_main_force',
                           'show_sector_strategy', 'show_portfolio', 'show_smart_monitor', 'show_low_price_bull', 'show_longhubang', 'show_news_flow', 'show_macro_analysis']:
                    if key in st.session_state:
                        del st.session_state[key]

        # 💼 投资管理
        with st.expander("💼 投资管理", expanded=True):
            st.markdown("**持仓跟踪与实时监测**")

            if st.button("📊 持仓分析", width='stretch', key="nav_portfolio", help="投资组合分析与定时跟踪"):
                st.session_state.show_portfolio = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_main_force',
                           'show_sector_strategy', 'show_longhubang', 'show_smart_monitor', 'show_low_price_bull', 'show_news_flow', 'show_macro_analysis']:
                    if key in st.session_state:
                        del st.session_state[key]

            if st.button("🤖 AI盯盘", width='stretch', key="nav_smart_monitor", help="DeepSeek AI自动盯盘决策交易（支持A股T+1）"):
                st.session_state.show_smart_monitor = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_main_force',
                           'show_sector_strategy', 'show_longhubang', 'show_portfolio', 'show_low_price_bull', 'show_news_flow', 'show_macro_analysis']:
                    if key in st.session_state:
                        del st.session_state[key]

            if st.button("📡 实时监测", width='stretch', key="nav_monitor", help="价格监控与预警提醒"):
                st.session_state.show_monitor = True
                for key in ['show_history', 'show_main_force', 'show_longhubang', 'show_portfolio',
                           'show_config', 'show_sector_strategy', 'show_smart_monitor', 'show_low_price_bull', 'show_news_flow', 'show_macro_analysis']:
                    if key in st.session_state:
                        del st.session_state[key]

        st.markdown("---")

        # 📖 历史记录
        if st.button("📖 历史记录", width='stretch', key="nav_history", help="查看历史分析记录"):
            st.session_state.show_history = True
            for key in ['show_monitor', 'show_longhubang', 'show_portfolio', 'show_config',
                       'show_main_force', 'show_sector_strategy', 'show_low_price_bull', 'show_news_flow', 'show_macro_analysis']:
                if key in st.session_state:
                    del st.session_state[key]

        # ⚙️ 环境配置
        if st.button("⚙️ 环境配置", width='stretch', key="nav_config", help="系统设置与API配置"):
            st.session_state.show_config = True
            for key in ['show_history', 'show_monitor', 'show_main_force', 'show_sector_strategy',
                       'show_longhubang', 'show_portfolio', 'show_low_price_bull', 'show_news_flow', 'show_macro_analysis']:
                if key in st.session_state:
                    del st.session_state[key]

        st.markdown("---")

        # 系统配置
        st.markdown("### ⚙️ 系统配置")

        # API密钥检查
        api_key_status = check_api_key()
        if api_key_status:
            st.success("✅ API已连接")
        else:
            st.error("❌ API未配置")
            st.caption("请在.env中配置API密钥")

        st.markdown("---")

        # 显示当前模型信息
        show_current_model_info()
        st.session_state.selected_model = config.DEFAULT_MODEL_NAME

        st.markdown("---")

        # 系统状态面板
        st.markdown("### 📊 系统状态")

        monitor_status = "🟢 运行中" if monitor_service.running else "🔴 已停止"
        st.markdown(f"**监测服务**: {monitor_status}")

        try:
            from monitor_db import monitor_db
            stocks = monitor_db.get_monitored_stocks()
            notifications = monitor_db.get_pending_notifications()
            record_count = db.get_record_count()

            st.markdown(f"**分析记录**: {record_count}条")
            st.markdown(f"**监测股票**: {len(stocks)}只")
            st.markdown(f"**待处理**: {len(notifications)}条")
        except Exception as e:
            logger.debug("侧栏状态面板读取失败: %s", e)

        st.markdown("---")

        # 分析参数设置
        st.markdown("### 📊 分析参数")
        period = st.selectbox(
            "数据周期",
            ["1y", "6mo", "3mo", "1mo"],
            index=0,
            help="选择历史数据的时间范围"
        )

        st.markdown("---")

        # 帮助信息
        with st.expander("💡 使用帮助"):
            st.markdown("""
            **股票代码格式**
            - 🇨🇳 A股：6位数字（如600519）
            - 🇭🇰 港股：1-5位数字（如700、00700）或HK前缀（如HK00700）
            - 🇺🇸 美股：字母代码（如AAPL）
            
            **功能说明**
            - **股票分析**：AI团队深度分析个股
            - **选股板块**：主力资金选股策略
            - **策略分析**：智策板块、智瞰龙虎
            - **投资管理**：持仓分析、实时监测
            - **历史记录**：查看分析历史
            
            **AI分析流程**
            1. 数据获取 → 2. 技术分析
            3. 基本面分析 → 4. 资金分析
            5. 情绪数据(ARBR) → 6. 新闻(qstock)
            7. AI分析 → 8. 团队讨论 → 9. 决策
            """)

    # 检查是否显示历史记录
    if 'show_history' in st.session_state and st.session_state.show_history:
        display_history_records()
        return

    # 检查是否显示监测面板
    if 'show_monitor' in st.session_state and st.session_state.show_monitor:
        display_monitor_manager()
        return

    # 检查是否显示主力选股
    if 'show_main_force' in st.session_state and st.session_state.show_main_force:
        display_main_force_selector()
        return
    
    # 检查是否显示低价擒牛
    if 'show_low_price_bull' in st.session_state and st.session_state.show_low_price_bull:
        from low_price_bull_ui import display_low_price_bull
        display_low_price_bull()
        return
    
    # 检查是否显示小市值策略
    if 'show_small_cap' in st.session_state and st.session_state.show_small_cap:
        from small_cap_ui import display_small_cap
        display_small_cap()
        return
    
    # 检查是否显示净利增长策略
    if 'show_profit_growth' in st.session_state and st.session_state.show_profit_growth:
        from profit_growth_ui import display_profit_growth
        display_profit_growth()
        return

    # 检查是否显示低估值策略
    if 'show_value_stock' in st.session_state and st.session_state.show_value_stock:
        from value_stock_ui import display_value_stock
        display_value_stock()
        return

    # 检查是否显示智策板块
    if 'show_sector_strategy' in st.session_state and st.session_state.show_sector_strategy:
        display_sector_strategy()
        return

    # 检查是否显示智瞰龙虎
    if 'show_longhubang' in st.session_state and st.session_state.show_longhubang:
        display_longhubang()
        return

    # 检查是否显示AI盯盘
    if 'show_smart_monitor' in st.session_state and st.session_state.show_smart_monitor:
        smart_monitor_ui()
        return

    # 检查是否显示持仓分析
    if 'show_portfolio' in st.session_state and st.session_state.show_portfolio:
        from portfolio_ui import display_portfolio_manager
        display_portfolio_manager()
        return

    # 检查是否显示新闻流量监测
    if 'show_news_flow' in st.session_state and st.session_state.show_news_flow:
        display_news_flow_monitor()
        return

    # 检查是否显示宏观分析
    if 'show_macro_analysis' in st.session_state and st.session_state.show_macro_analysis:
        from macro_analysis_ui import display_macro_analysis
        display_macro_analysis()
        return

    # 检查是否显示宏观周期分析
    if 'show_macro_cycle' in st.session_state and st.session_state.show_macro_cycle:
        from macro_cycle_ui import display_macro_cycle
        display_macro_cycle()
        return
    
    # 检查是否显示环境配置
    if 'show_config' in st.session_state and st.session_state.show_config:
        display_config_manager()
        return

    # 检查是否显示缠论选股（放在所有其它 show_* 之后，残留标志不会抢占其它页面）
    if 'show_chanlun' in st.session_state and st.session_state.show_chanlun:
        from chanlun_ui import display_chanlun_selector
        display_chanlun_selector()
        return

    # 检查是否显示六脉神剑选股
    if 'show_liumai' in st.session_state and st.session_state.show_liumai:
        from liumai_ui import display_liumai_selector
        display_liumai_selector()
        return

    # 检查是否显示缠论×六脉组合策略
    if 'show_combo' in st.session_state and st.session_state.show_combo:
        from combo_ui import display_combo_selector
        display_combo_selector()
        return

    # 检查是否显示稳定选股（经样本外验证的买卖策略）
    if 'show_stable' in st.session_state and st.session_state.show_stable:
        from stable_ui import display_stable_selector
        display_stable_selector()
        return

    # 检查是否显示「当前策略」只读总览页
    if 'show_current_strategy' in st.session_state and st.session_state.show_current_strategy:
        from current_strategy_ui import display_current_strategy
        display_current_strategy()
        return

    # 检查是否显示分时分析（放在所有 show_* 之后、默认日线主界面之前）
    if 'show_intraday' in st.session_state and st.session_state.show_intraday:
        display_intraday_analysis()
        return

    # 主界面
    # 添加单个/批量分析切换
    col_mode1, col_mode2 = st.columns([1, 3])
    with col_mode1:
        analysis_mode = st.radio(
            "分析模式",
            ["单个分析", "批量分析"],
            horizontal=True,
            help="单个分析：分析单只股票；批量分析：同时分析多只股票"
        )

    with col_mode2:
        if analysis_mode == "批量分析":
            batch_mode = st.radio(
                "批量模式",
                ["顺序分析", "多线程并行"],
                horizontal=True,
                help="顺序分析：按次序分析，稳定但较慢；多线程并行：同时分析多只，快速但消耗资源"
            )
            st.session_state.batch_mode = batch_mode

    st.markdown("---")

    if analysis_mode == "单个分析":
        # 单个股票分析界面
        col1, col2, col3 = st.columns([2, 1, 1])

        with col1:
            stock_input = st.text_input(
                "🔍 请输入股票代码或名称",
                placeholder="例如: AAPL, 000001, 00700",
                help="支持A股(如000001)、港股(如00700)和美股(如AAPL)"
            )

        with col2:
            analyze_button = st.button("🚀 开始分析", type="primary", width='stretch')

        with col3:
            if st.button("🔄 清除缓存", width='stretch'):
                st.cache_data.clear()
                st.success("缓存已清除")

    else:
        # 批量股票分析界面
        stock_input = st.text_area(
            "🔍 请输入多个股票代码（每行一个或用逗号分隔）",
            placeholder="例如:\n000001\n600036\n00700\n\n或者: 000001, 600036, 00700, AAPL",
            height=120,
            help="支持多种格式：每行一个代码或用逗号分隔。支持A股、港股、美股"
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            analyze_button = st.button("🚀 开始批量分析", type="primary", width='stretch')
        with col2:
            if st.button("🔄 清除缓存", width='stretch'):
                st.cache_data.clear()
                st.success("缓存已清除")
        with col3:
            if st.button("🗑️ 清除结果", width='stretch'):
                if 'batch_analysis_results' in st.session_state:
                    del st.session_state.batch_analysis_results
                st.success("已清除批量分析结果")

    # 分析师团队选择
    st.markdown("---")
    st.subheader("👥 选择分析师团队")

    col1, col2, col3 = st.columns(3)

    with col1:
        enable_technical = st.checkbox("📊 技术分析师", value=True,
                                       help="负责技术指标分析、图表形态识别、趋势判断")
        enable_fundamental = st.checkbox("💼 基本面分析师", value=True,
                                        help="负责公司财务分析、行业研究、估值分析")

    with col2:
        enable_fund_flow = st.checkbox("💰 资金面分析师", value=True,
                                      help="负责资金流向分析、主力行为研究")
        enable_risk = st.checkbox("⚠️ 风险管理师", value=True,
                                 help="负责风险识别、风险评估、风险控制策略制定")

    with col3:
        enable_sentiment = st.checkbox("📈 市场情绪分析师", value=True,
                                      help="负责市场情绪研究、ARBR指标分析（仅A股）")
        enable_news = st.checkbox("📰 新闻分析师", value=True,
                                 help="负责新闻事件分析、舆情研究（仅A股，qstock数据源）")

    # 显示已选择的分析师
    selected_analysts = []
    if enable_technical:
        selected_analysts.append("技术分析师")
    if enable_fundamental:
        selected_analysts.append("基本面分析师")
    if enable_fund_flow:
        selected_analysts.append("资金面分析师")
    if enable_risk:
        selected_analysts.append("风险管理师")
    if enable_sentiment:
        selected_analysts.append("市场情绪分析师")
    if enable_news:
        selected_analysts.append("新闻分析师")

    if selected_analysts:
        st.info(f"✅ 已选择 {len(selected_analysts)} 位分析师: {', '.join(selected_analysts)}")
    else:
        st.warning("⚠️ 请至少选择一位分析师")

    # 保存选择到session_state
    st.session_state.enable_technical = enable_technical
    st.session_state.enable_fundamental = enable_fundamental
    st.session_state.enable_fund_flow = enable_fund_flow
    st.session_state.enable_risk = enable_risk
    st.session_state.enable_sentiment = enable_sentiment
    st.session_state.enable_news = enable_news

    st.markdown("---")

    if analyze_button and stock_input:
        if not api_key_status:
            st.error("❌ 请先配置 DeepSeek API Key")
            return

        # 检查是否至少选择了一位分析师
        if not selected_analysts:
            st.error("❌ 请至少选择一位分析师参与分析")
            return

        if analysis_mode == "单个分析":
            # 单个股票分析
            # 清除之前的分析结果
            if 'analysis_completed' in st.session_state:
                del st.session_state.analysis_completed
            if 'stock_info' in st.session_state:
                del st.session_state.stock_info
            if 'agents_results' in st.session_state:
                del st.session_state.agents_results
            if 'discussion_result' in st.session_state:
                del st.session_state.discussion_result
            if 'final_decision' in st.session_state:
                del st.session_state.final_decision
            if 'just_completed' in st.session_state:
                del st.session_state.just_completed

            run_stock_analysis(stock_input, period)

        else:
            # 批量股票分析
            # 解析股票代码列表
            stock_list = parse_stock_list(stock_input)

            if not stock_list:
                st.error("❌ 请输入有效的股票代码")
                return

            if len(stock_list) > 20:
                st.warning(f"⚠️ 检测到 {len(stock_list)} 只股票，建议一次分析不超过20只")

            st.info(f"📊 准备分析 {len(stock_list)} 只股票: {', '.join(stock_list)}")

            # 清除之前的分析结果（包括单个和批量）
            if 'batch_analysis_results' in st.session_state:
                del st.session_state.batch_analysis_results
            if 'analysis_completed' in st.session_state:
                del st.session_state.analysis_completed
            if 'stock_info' in st.session_state:
                del st.session_state.stock_info
            if 'agents_results' in st.session_state:
                del st.session_state.agents_results
            if 'discussion_result' in st.session_state:
                del st.session_state.discussion_result
            if 'final_decision' in st.session_state:
                del st.session_state.final_decision
            if 'just_completed' in st.session_state:
                del st.session_state.just_completed

            # 获取批量模式
            batch_mode = st.session_state.get('batch_mode', '顺序分析')

            # 运行批量分析
            run_batch_analysis(stock_list, period, batch_mode)

    # 检查是否有已完成的批量分析结果（优先显示批量结果）
    if 'batch_analysis_results' in st.session_state and st.session_state.batch_analysis_results:
        display_batch_analysis_results(st.session_state.batch_analysis_results, period)

    # 检查是否有已完成的单个分析结果（但不是刚刚完成的，避免重复显示）
    elif 'analysis_completed' in st.session_state and st.session_state.analysis_completed:
        # 如果是刚刚完成的分析，清除标志，避免重复显示
        if st.session_state.get('just_completed', False):
            st.session_state.just_completed = False
        else:
            # 重新显示之前的分析结果（页面刷新后）
            stock_info = st.session_state.stock_info
            agents_results = st.session_state.agents_results
            discussion_result = st.session_state.discussion_result
            final_decision = st.session_state.final_decision

            # 重新获取股票数据用于显示图表
            stock_info_current, stock_data, indicators = get_stock_data(stock_info['symbol'], period)

            # 显示股票基本信息
            display_stock_info(stock_info, indicators)

            # 显示股票图表
            if stock_data is not None:
                display_stock_chart(stock_data, stock_info)

            # 显示各分析师报告
            display_agents_analysis(agents_results)

            # 显示团队讨论
            display_team_discussion(discussion_result)

            # 显示最终决策
            display_final_decision(final_decision, stock_info, agents_results, discussion_result)

    # 示例和说明
    elif not stock_input:
        show_example_interface()

if __name__ == "__main__":
    main()
