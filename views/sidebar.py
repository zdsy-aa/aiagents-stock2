"""侧边栏渲染：功能导航 + 系统配置/状态 + 分析参数。

从 app.main() 抽出(行为不变)。返回主界面需要的 (api_key_status, period)。
"""
import logging

import streamlit as st

import config
from database import db
from monitor_service import monitor_service
from views.analysis_runner import check_api_key

logger = logging.getLogger(__name__)


def show_current_model_info():
    """显示当前使用的AI模型信息"""
    st.sidebar.markdown("---")
    st.sidebar.subheader("🤖 AI模型")
    st.sidebar.info(f"当前模型: **{config.DEFAULT_MODEL_NAME}**")
    st.sidebar.caption("可在「环境配置」中修改模型名称")


def render_sidebar():
    """渲染侧边栏；返回 (api_key_status, period)。"""
    api_key_status = False
    period = "1y"
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

            if st.button("📈 起涨预测(观察中)", width='stretch', key="nav_qizhang", help="起涨模型 C4 策略 paper-tracking 观察页(只读,不下单)"):
                st.session_state.show_qizhang = True
                for key in ['show_history', 'show_monitor', 'show_config', 'show_main_force',
                           'show_sector_strategy', 'show_longhubang', 'show_portfolio', 'show_low_price_bull',
                           'show_small_cap', 'show_profit_growth', 'show_value_stock', 'show_news_flow',
                           'show_macro_analysis', 'show_macro_cycle', 'show_smart_monitor', 'show_intraday',
                           'show_chanlun', 'show_liumai', 'show_combo', 'show_stable']:
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
    return api_key_status, period
