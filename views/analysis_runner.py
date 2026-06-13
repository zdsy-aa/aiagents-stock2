#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""个股/批量分析的编排逻辑（从 app.py 抽离）。

app.py(main 路由) 通过 `from views.analysis_runner import (...)` 调用；本模块只做
取数+多智能体编排+落库+进度渲染,不含侧栏导航/session_state 路由逻辑。
渲染辅助来自 views.analysis_views(单向 import,无循环)。
"""
import time

import streamlit as st

import config
from stock_analysis_engine import StockAnalysisEngine
from stock_data import StockDataFetcher
from ai_agents import StockAnalysisAgents
from database import db
from views.analysis_views import (
    get_stock_data, display_stock_info, display_stock_chart,
    display_agents_analysis, display_team_discussion, display_final_decision,
)


def check_api_key():
    """检查API密钥是否配置"""
    try:
        import config
        return bool(config.DEEPSEEK_API_KEY and config.DEEPSEEK_API_KEY.strip())
    except Exception:
        return False

@st.cache_data(ttl=300)  # 缓存5分钟
def parse_stock_list(stock_input):
    """解析股票代码列表

    支持的格式：
    - 每行一个代码
    - 逗号分隔
    - 空格分隔
    """
    if not stock_input or not stock_input.strip():
        return []

    # 先按换行符分割
    lines = stock_input.strip().split('\n')

    # 处理每一行
    stock_list = []
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 检查是否包含逗号
        if ',' in line:
            codes = [code.strip() for code in line.split(',')]
            stock_list.extend([code for code in codes if code])
        # 检查是否包含空格
        elif ' ' in line:
            codes = [code.strip() for code in line.split()]
            stock_list.extend([code for code in codes if code])
        else:
            stock_list.append(line)

    # 去重并保持顺序
    seen = set()
    unique_list = []
    for code in stock_list:
        if code not in seen:
            seen.add(code)
            unique_list.append(code)

    return unique_list

def analyze_single_stock_for_batch(symbol, period, enabled_analysts_config=None, selected_model=None):
    """单个股票分析（用于批量分析）

    Args:
        symbol: 股票代码
        period: 数据周期
        enabled_analysts_config: 分析师配置字典
        selected_model: 选择的AI模型，默认从 .env 的 DEFAULT_MODEL_NAME 读取

    返回分析结果或错误信息
    """
    try:
        # 使用默认模型
        if selected_model is None:
            selected_model = config.DEFAULT_MODEL_NAME
        
        # 使用默认配置
        if enabled_analysts_config is None:
            enabled_analysts_config = {
                'technical': True,
                'fundamental': True,
                'fund_flow': True,
                'risk': True,
                'sentiment': False,
                'news': False
            }

        # 调用统一分析引擎（与 run_full_analysis 同源，消除重复的取数+多智能体编排）
        engine = StockAnalysisEngine(model_name=selected_model)
        result = engine.run_full_analysis(symbol, period, enabled_analysts_config)

        stock_info = result["stock_info"]
        indicators = result["indicators"]
        agents_results = result["agents_results"]
        discussion_result = result["discussion_result"]
        final_decision = result["final_decision"]
        saved_to_db = result.get("analysis_id") is not None
        db_error = None

        return {
            "symbol": symbol,
            "success": True,
            "stock_info": stock_info,
            "indicators": indicators,
            "agents_results": agents_results,
            "discussion_result": discussion_result,
            "final_decision": final_decision,
            "saved_to_db": saved_to_db,
            "db_error": db_error
        }

    except Exception as e:
        return {"symbol": symbol, "error": str(e), "success": False}

def run_batch_analysis(stock_list, period, batch_mode="顺序分析"):
    """运行批量股票分析"""
    import concurrent.futures
    import threading

    # 在开始分析前获取配置（从session_state）
    enabled_analysts_config = {
        'technical': st.session_state.get('enable_technical', True),
        'fundamental': st.session_state.get('enable_fundamental', True),
        'fund_flow': st.session_state.get('enable_fund_flow', True),
        'risk': st.session_state.get('enable_risk', True),
        'sentiment': st.session_state.get('enable_sentiment', False),
        'news': st.session_state.get('enable_news', False)
    }
    selected_model = st.session_state.get('selected_model', config.DEFAULT_MODEL_NAME)

    # 创建进度显示
    st.subheader(f"📊 批量分析进行中 ({batch_mode})")

    progress_bar = st.progress(0)
    status_text = st.empty()

    # 存储结果
    results = []
    total = len(stock_list)

    if batch_mode == "多线程并行":
        # 多线程并行分析
        status_text.text(f"🚀 使用多线程并行分析 {total} 只股票...")

        # 创建线程锁用于更新进度
        lock = threading.Lock()
        completed = [0]  # 使用列表以便在闭包中修改
        progress_status = [{}]  # 存储进度状态

        def analyze_with_progress(symbol):
            """包装分析函数，不在线程中访问Streamlit上下文"""
            try:
                result = analyze_single_stock_for_batch(symbol, period, enabled_analysts_config, selected_model)
                with lock:
                    completed[0] += 1
                    progress_status[0][symbol] = result
                return result
            except Exception as e:
                with lock:
                    completed[0] += 1
                    error_result = {"symbol": symbol, "error": str(e), "success": False}
                    progress_status[0][symbol] = error_result
                return error_result

        # 使用线程池执行，限制最大并发数为3以避免API限流
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_to_symbol = {executor.submit(analyze_with_progress, symbol): symbol
                              for symbol in stock_list}

            for future in concurrent.futures.as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    result = future.result(timeout=300)  # 5分钟超时
                    results.append(result)

                    # 在主线程中更新UI
                    progress = len(results) / total
                    progress_bar.progress(progress)

                    if result['success']:
                        status_text.text(f"✅ [{len(results)}/{total}] {symbol} 分析完成")
                    else:
                        status_text.text(f"❌ [{len(results)}/{total}] {symbol} 分析失败: {result.get('error', '未知错误')}")

                except concurrent.futures.TimeoutError:
                    results.append({"symbol": symbol, "error": "分析超时（5分钟）", "success": False})
                    progress_bar.progress(len(results) / total)
                    status_text.text(f"⏱️ [{len(results)}/{total}] {symbol} 分析超时")
                except Exception as e:
                    results.append({"symbol": symbol, "error": str(e), "success": False})
                    progress_bar.progress(len(results) / total)
                    status_text.text(f"❌ [{len(results)}/{total}] {symbol} 出现错误")

    else:
        # 顺序分析
        status_text.text(f"📝 按顺序分析 {total} 只股票...")

        for i, symbol in enumerate(stock_list, 1):
            status_text.text(f"🔍 [{i}/{total}] 正在分析 {symbol}...")

            try:
                result = analyze_single_stock_for_batch(symbol, period, enabled_analysts_config, selected_model)
            except Exception as e:
                result = {"symbol": symbol, "error": str(e), "success": False}

            results.append(result)

            # 更新进度
            progress = i / total
            progress_bar.progress(progress)

            if result['success']:
                status_text.text(f"✅ [{i}/{total}] {symbol} 分析完成")
            else:
                status_text.text(f"❌ [{i}/{total}] {symbol} 分析失败: {result.get('error', '未知错误')}")

    # 完成
    progress_bar.progress(1.0)

    # 统计结果
    success_count = sum(1 for r in results if r['success'])
    failed_count = total - success_count
    saved_count = sum(1 for r in results if r.get('saved_to_db', False))

    # 显示完成信息
    if success_count > 0:
        status_text.success(f"✅ 批量分析完成！成功 {success_count} 只，失败 {failed_count} 只，已保存 {saved_count} 只到历史记录")

        # 显示保存失败的股票
        save_failed = [r['symbol'] for r in results if r.get('success') and not r.get('saved_to_db', False)]
        if save_failed:
            st.warning(f"⚠️ 以下股票分析成功但保存失败: {', '.join(save_failed)}")
    else:
        status_text.error(f"❌ 批量分析完成，但所有股票都分析失败")

    # 保存结果到session_state
    st.session_state.batch_analysis_results = results
    st.session_state.batch_analysis_mode = batch_mode

    time.sleep(1)
    progress_bar.empty()

    # 自动显示结果
    st.rerun()

def run_stock_analysis(symbol, period):
    """运行股票分析"""

    # 进度条
    progress_bar = st.progress(0)
    status_text = st.empty()

    try:
        # 1. 获取股票数据
        status_text.text("📈 正在获取股票数据...")
        progress_bar.progress(10)

        stock_info, stock_data, indicators = get_stock_data(symbol, period)

        if "error" in stock_info:
            st.error(f"❌ {stock_info['error']}")
            return

        if stock_data is None:
            st.error("❌ 无法获取股票历史数据")
            return

        # 显示股票基本信息
        display_stock_info(stock_info, indicators)
        progress_bar.progress(20)

        # 显示股票图表
        display_stock_chart(stock_data, stock_info)
        progress_bar.progress(30)

        # 2. 获取财务数据
        status_text.text("📊 正在获取财务数据...")
        fetcher = StockDataFetcher()  # 创建fetcher实例
        financial_data = fetcher.get_financial_data(symbol)
        progress_bar.progress(35)

        # 2.5 获取季报数据（仅在选择了基本面分析师且为A股时）
        enable_fundamental = st.session_state.get('enable_fundamental', True)
        quarterly_data = None
        if enable_fundamental and fetcher._is_chinese_stock(symbol):
            status_text.text("📊 正在获取季报数据（akshare数据源）...")
            try:
                from quarterly_report_data import QuarterlyReportDataFetcher
                quarterly_fetcher = QuarterlyReportDataFetcher()
                quarterly_data = quarterly_fetcher.get_quarterly_reports(symbol)
                if quarterly_data and quarterly_data.get('data_success'):
                    income_count = quarterly_data.get('income_statement', {}).get('periods', 0) if quarterly_data.get('income_statement') else 0
                    balance_count = quarterly_data.get('balance_sheet', {}).get('periods', 0) if quarterly_data.get('balance_sheet') else 0
                    cash_flow_count = quarterly_data.get('cash_flow', {}).get('periods', 0) if quarterly_data.get('cash_flow') else 0
                    st.info(f"✅ 成功获取季报数据：利润表{income_count}期，资产负债表{balance_count}期，现金流量表{cash_flow_count}期")
                else:
                    st.warning("⚠️ 未能获取季报数据，将基于基本财务数据分析")
            except Exception as e:
                st.warning(f"⚠️ 获取季报数据时出错: {str(e)}")
                quarterly_data = None
        elif enable_fundamental and not fetcher._is_chinese_stock(symbol):
            st.info("ℹ️ 美股暂不支持季报数据")
        progress_bar.progress(37)

        # 获取分析师选择状态
        enable_fund_flow = st.session_state.get('enable_fund_flow', True)
        enable_sentiment = st.session_state.get('enable_sentiment', False)
        enable_news = st.session_state.get('enable_news', False)

        # 3. 获取资金流向数据（仅在选择了资金面分析师时，使用akshare数据源）
        fund_flow_data = None
        if enable_fund_flow and fetcher._is_chinese_stock(symbol):
            status_text.text("💰 正在获取资金流向数据（akshare数据源）...")
            try:
                from fund_flow_akshare import FundFlowAkshareDataFetcher
                fund_flow_fetcher = FundFlowAkshareDataFetcher()
                fund_flow_data = fund_flow_fetcher.get_fund_flow_data(symbol)
                if fund_flow_data and fund_flow_data.get('data_success'):
                    days = fund_flow_data.get('fund_flow_data', {}).get('days', 0) if fund_flow_data.get('fund_flow_data') else 0
                    st.info(f"✅ 成功获取 {days} 个交易日的资金流向数据")
                else:
                    st.warning("⚠️ 未能获取资金流向数据，将基于技术指标进行资金面分析")
            except Exception as e:
                st.warning(f"⚠️ 获取资金流向数据时出错: {str(e)}")
                fund_flow_data = None
        elif enable_fund_flow and not fetcher._is_chinese_stock(symbol):
            st.info("ℹ️ 美股暂不支持资金流向数据")
        progress_bar.progress(40)

        # 4. 获取市场情绪数据（仅在选择了市场情绪分析师时）
        sentiment_data = None
        if enable_sentiment and fetcher._is_chinese_stock(symbol):
            status_text.text("📊 正在获取市场情绪数据（ARBR等指标）...")
            try:
                from market_sentiment_data import MarketSentimentDataFetcher
                sentiment_fetcher = MarketSentimentDataFetcher()
                sentiment_data = sentiment_fetcher.get_market_sentiment_data(symbol, stock_data)
                if sentiment_data and sentiment_data.get('data_success'):
                    st.info("✅ 成功获取市场情绪数据（ARBR、换手率、涨跌停等）")
                else:
                    st.warning("⚠️ 未能获取完整的市场情绪数据，将基于基本信息进行分析")
            except Exception as e:
                st.warning(f"⚠️ 获取市场情绪数据时出错: {str(e)}")
                sentiment_data = None
        elif enable_sentiment and not fetcher._is_chinese_stock(symbol):
            st.info("ℹ️ 美股暂不支持市场情绪数据（ARBR等指标）")
        progress_bar.progress(45)

        # 5. 获取新闻数据（仅在选择了新闻分析师时，使用qstock数据源）
        news_data = None
        if enable_news and fetcher._is_chinese_stock(symbol):
            status_text.text("📰 正在获取新闻数据...")
            try:
                from qstock_news_data import QStockNewsDataFetcher
                news_fetcher = QStockNewsDataFetcher()
                news_data = news_fetcher.get_stock_news(symbol)
                if news_data and news_data.get('data_success'):
                    news_count = news_data.get('news_data', {}).get('count', 0) if news_data.get('news_data') else 0
                    st.info(f"✅ 成功从东方财富获取个股 {news_count} 条新闻")
                else:
                    st.warning("⚠️ 未能获取新闻数据，将基于基本信息进行分析")
            except Exception as e:
                st.warning(f"⚠️ 获取新闻数据时出错: {str(e)}")
                news_data = None
        elif enable_news and not fetcher._is_chinese_stock(symbol):
            st.info("ℹ️ 美股暂不支持新闻数据")
        progress_bar.progress(45)

        # 5.5 获取风险数据（仅在选择了风险管理师时，使用问财数据源）
        enable_risk = st.session_state.get('enable_risk', True)
        risk_data = None
        if enable_risk and fetcher._is_chinese_stock(symbol):
            status_text.text("⚠️ 正在获取风险数据（限售解禁、大股东减持、重要事件）...")
            try:
                risk_data = fetcher.get_risk_data(symbol)
                if risk_data and risk_data.get('data_success'):
                    # 统计获取到的风险数据类型
                    risk_types = []
                    if risk_data.get('lifting_ban') and risk_data['lifting_ban'].get('has_data'):
                        risk_types.append("限售解禁")
                    if risk_data.get('shareholder_reduction') and risk_data['shareholder_reduction'].get('has_data'):
                        risk_types.append("大股东减持")
                    if risk_data.get('important_events') and risk_data['important_events'].get('has_data'):
                        risk_types.append("重要事件")

                    if risk_types:
                        st.info(f"✅ 成功获取风险数据：{', '.join(risk_types)}")
                    else:
                        st.info("ℹ️ 暂无风险相关数据")
                else:
                    st.info("ℹ️ 暂无风险相关数据，将基于基本信息进行风险分析")
            except Exception as e:
                st.warning(f"⚠️ 获取风险数据时出错: {str(e)}")
                risk_data = None
        elif enable_risk and not fetcher._is_chinese_stock(symbol):
            st.info("ℹ️ 美股暂不支持风险数据（限售解禁、大股东减持等）")
        progress_bar.progress(50)

        # 6. 初始化AI分析系统
        status_text.text("🤖 正在初始化AI分析系统...")
        # 使用选择的模型
        selected_model = st.session_state.get('selected_model', config.DEFAULT_MODEL_NAME)
        agents = StockAnalysisAgents(model=selected_model)
        progress_bar.progress(55)

        # 获取所有分析师选择状态
        enable_technical = st.session_state.get('enable_technical', True)
        enable_fundamental = st.session_state.get('enable_fundamental', True)
        enable_risk = st.session_state.get('enable_risk', True)

        # 创建分析师启用字典
        enabled_analysts = {
            'technical': enable_technical,
            'fundamental': enable_fundamental,
            'fund_flow': enable_fund_flow,
            'risk': enable_risk,
            'sentiment': enable_sentiment,
            'news': enable_news
        }

        # 7. 运行多智能体分析（传入所有数据和分析师选择）
        status_text.text("🔍 AI分析师团队正在分析,请耐心等待几分钟...")
        agents_results = agents.run_multi_agent_analysis(
            stock_info, stock_data, indicators, financial_data,
            fund_flow_data, sentiment_data, news_data, quarterly_data, risk_data,
            enabled_analysts=enabled_analysts
        )
        progress_bar.progress(75)

        # 显示各分析师报告
        display_agents_analysis(agents_results)

        # 8. 团队讨论
        status_text.text("🤝 分析团队正在讨论...")
        discussion_result = agents.comprehensive_discussion(agents_results, stock_info)
        progress_bar.progress(88)

        # 显示团队讨论
        display_team_discussion(discussion_result)

        # 9. 最终决策
        status_text.text("📋 正在制定最终投资决策...")
        final_decision = agents.deepseek_client.final_decision(discussion_result, stock_info, indicators)
        progress_bar.progress(100)

        # 显示最终决策
        display_final_decision(final_decision, stock_info, agents_results, discussion_result)

        # 保存分析结果到session_state（用于页面刷新后显示）
        st.session_state.analysis_completed = True
        st.session_state.stock_info = stock_info
        st.session_state.agents_results = agents_results
        st.session_state.discussion_result = discussion_result
        st.session_state.final_decision = final_decision
        st.session_state.just_completed = True  # 标记刚刚完成分析

        # 保存到数据库
        try:
            db.save_analysis(
                symbol=stock_info.get('symbol', ''),
                stock_name=stock_info.get('name', ''),
                period=period,
                stock_info=stock_info,
                agents_results=agents_results,
                discussion_result=discussion_result,
                final_decision=final_decision
            )
            st.success("✅ 分析记录已保存到数据库")
        except Exception as e:
            st.warning(f"⚠️ 保存到数据库时出现错误: {str(e)}")

        status_text.text("✅ 分析完成！")
        time.sleep(1)
        status_text.empty()
        progress_bar.empty()

    except Exception as e:
        st.error(f"❌ 分析过程中出现错误: {str(e)}")
        progress_bar.empty()
        status_text.empty()

