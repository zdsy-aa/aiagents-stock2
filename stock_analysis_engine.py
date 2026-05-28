import logging
import pandas as pd
from datetime import datetime
from typing import Dict, Any, List, Optional
from stock_data import StockDataFetcher
from ai_agents import StockAnalysisAgents
from database import db

logger = logging.getLogger(__name__)

class StockAnalysisEngine:
    """股票分析引擎 - P2 整改十五: 解耦 UI 与业务逻辑"""
    
    def __init__(self, model_name: Optional[str] = None):
        self.fetcher = StockDataFetcher()
        self.agents = StockAnalysisAgents(model=model_name)
        
    def run_full_analysis(self, symbol: str, period: str = "1y",
                          enabled_analysts: Optional[Dict[str, bool]] = None,
                          freq: Optional[str] = None) -> Dict[str, Any]:
        """执行全套 AI 智能体分析流程（纯业务逻辑，无 UI 依赖）。

        数据获取与 app.py 的 run_stock_analysis 保持一致：可选数据按
        enabled_analysts 与 A 股判断进行门控，单项失败不影响整体流程。
        """
        logger.info(f"🚀 开始对股票 {symbol} 进行全套 AI 分析")

        if enabled_analysts is None:
            enabled_analysts = {
                'technical': True, 'fundamental': True, 'fund_flow': True,
                'risk': True, 'sentiment': True, 'news': True,
            }
        is_cn = self.fetcher._is_chinese_stock(symbol)

        # 1. 基础信息
        stock_info = self.fetcher.get_stock_info(symbol)
        if not stock_info or (isinstance(stock_info, dict) and stock_info.get('error')):
            raise ValueError(f"无法获取股票 {symbol} 的基础信息")

        # 2. 技术面：历史数据 + 最新指标（freq 非空走分钟线）
        if freq:
            stock_data = self.fetcher.get_minute_data(symbol, freq, limit=240)
        else:
            stock_data = self.fetcher.get_stock_data(symbol, period)
        indicators = {}
        if isinstance(stock_data, pd.DataFrame) and not stock_data.empty:
            enriched = self.fetcher.calculate_technical_indicators(stock_data)
            indicators = self.fetcher.get_latest_indicators(enriched)

        # 3. 基本面（受 fundamental 门控；纯技术面/分时分析跳过，亦绕开东财资金流报错）
        financial_data = None
        if enabled_analysts.get('fundamental'):
            financial_data = self.fetcher.get_financial_data(symbol)

        # 季报（A 股 + 启用基本面）
        quarterly_data = None
        if enabled_analysts.get('fundamental') and is_cn:
            try:
                from quarterly_report_data import QuarterlyReportDataFetcher
                quarterly_data = QuarterlyReportDataFetcher().get_quarterly_reports(symbol)
            except Exception:
                logger.warning(f"获取季报数据失败: {symbol}", exc_info=True)

        # 资金面（A 股 + 启用资金面）
        fund_flow_data = None
        if enabled_analysts.get('fund_flow') and is_cn:
            try:
                from fund_flow_akshare import FundFlowAkshareDataFetcher
                fund_flow_data = FundFlowAkshareDataFetcher().get_fund_flow_data(symbol)
            except Exception:
                logger.warning(f"获取资金流向数据失败: {symbol}", exc_info=True)

        # 情绪面（A 股 + 启用情绪）
        sentiment_data = None
        if enabled_analysts.get('sentiment') and is_cn:
            try:
                from market_sentiment_data import MarketSentimentDataFetcher
                sentiment_data = MarketSentimentDataFetcher().get_market_sentiment_data(symbol, stock_data)
            except Exception:
                logger.warning(f"获取市场情绪数据失败: {symbol}", exc_info=True)

        # 新闻面（A 股 + 启用新闻）
        news_data = None
        if enabled_analysts.get('news') and is_cn:
            try:
                from qstock_news_data import QStockNewsDataFetcher
                news_data = QStockNewsDataFetcher().get_stock_news(symbol)
            except Exception:
                logger.warning(f"获取新闻数据失败: {symbol}", exc_info=True)

        # 风险面（A 股 + 启用风险）
        risk_data = None
        if enabled_analysts.get('risk') and is_cn:
            try:
                risk_data = self.fetcher.get_risk_data(symbol)
            except Exception:
                logger.warning(f"获取风险数据失败: {symbol}", exc_info=True)

        # 4. 运行多智能体并行分析
        agents_results = self.agents.run_multi_agent_analysis(
            stock_info, stock_data, indicators, financial_data,
            fund_flow_data, sentiment_data, news_data, quarterly_data, risk_data,
            enabled_analysts=enabled_analysts,
        )

        # 5. 综合讨论
        discussion_result = self.agents.comprehensive_discussion(agents_results, stock_info)

        # 6. 最终投资决策
        final_decision = self.agents.deepseek_client.final_decision(
            discussion_result, stock_info, indicators
        )

        # 7. 保存结果到数据库（失败不影响返回）
        analysis_id = None
        try:
            analysis_id = db.save_analysis(
                symbol=stock_info.get('symbol', symbol),
                stock_name=stock_info.get('name', ''),
                period=period,
                stock_info=stock_info,
                agents_results=agents_results,
                discussion_result=discussion_result,
                final_decision=final_decision,
            )
        except Exception:
            logger.warning(f"保存分析结果到数据库失败: {symbol}", exc_info=True)

        return {
            "analysis_id": analysis_id,
            "stock_info": stock_info,
            "stock_data": stock_data,
            "indicators": indicators,
            "agents_results": agents_results,
            "discussion_result": discussion_result,
            "final_decision": final_decision,
        }

# 全局单例
analysis_engine = StockAnalysisEngine()
