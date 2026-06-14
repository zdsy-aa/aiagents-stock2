"""主分析界面：单/批量分析模式、分析师团队选择、运行与结果回显。

从 app.main() 抽出(行为不变)。依赖侧栏返回的 period / api_key_status。
"""
import streamlit as st

from views.analysis_runner import (
    parse_stock_list, run_batch_analysis, run_stock_analysis,
)
from views.analysis_views import (
    get_stock_data, display_stock_info, display_stock_chart,
    display_agents_analysis, display_team_discussion, display_final_decision,
    display_batch_analysis_results, show_example_interface,
)


def render_analysis_home(period, api_key_status):
    """渲染主分析界面(默认日线主页)。"""
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
