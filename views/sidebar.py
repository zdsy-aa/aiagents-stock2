"""侧边栏渲染：功能导航 + 系统配置/状态 + 分析参数。

从 app.main() 抽出(行为不变)。返回主界面需要的 (api_key_status, period)。
"""
import logging

import streamlit as st

import config
from database import db
from monitor_service import monitor_service
from views.analysis_runner import check_api_key
from views.nav_model import current_category, category_pages, all_flags

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
        st.markdown("### 📈 智投 · 导航")
        cat = current_category()
        st.caption(f"当前分类：{cat}")
        for label, flag, help_txt in category_pages(cat):
            is_active = (st.session_state.get(flag) if flag
                         else not any(st.session_state.get(f) for f in all_flags()))
            if st.button(label, width='stretch', key=f"side_{flag or 'home'}",
                         help=help_txt, type=("primary" if is_active else "secondary")):
                for f in all_flags():
                    st.session_state.pop(f, None)
                if flag:
                    st.session_state[flag] = True
                st.rerun()

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
