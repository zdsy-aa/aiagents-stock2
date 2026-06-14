import logging

import streamlit as st

from logger_config import setup_logging
from ui_theme import inject_theme

# 初始化统一日志配置
setup_logging()
logger = logging.getLogger(__name__)

# 页面三大块(侧栏/路由/主界面)已抽到 views/;app.py 仅做装配
from views.sidebar import render_sidebar
from views.page_router import route_page
from views.analysis_home import render_analysis_home

# 页面配置
st.set_page_config(
    page_title="复合多AI智能体股票团队分析系统",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 注入深色 Fintech 全局设计系统（全站 16 页同一次 run 内继承）
inject_theme()


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

    # 侧边栏(返回主界面所需的 api_key_status / period)
    api_key_status, period = render_sidebar()

    # 功能页面路由：命中任一 show_* 即渲染该页并结束
    if route_page():
        return

    # 默认日线主分析界面
    render_analysis_home(period, api_key_status)


if __name__ == "__main__":
    main()
