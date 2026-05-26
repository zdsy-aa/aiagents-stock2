from typing import Dict, Any, List
import time
import config
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from deepseek_client import DeepSeekClient

logger = logging.getLogger(__name__)

class StockAnalysisAgents:
    """股票分析AI智能体集合"""
    
    def __init__(self, model=None):
        self.model = model or config.DEFAULT_MODEL_NAME
        self.deepseek_client = DeepSeekClient(model=self.model)
        
    def technical_analyst_agent(self, stock_info: Dict, stock_data: Any, indicators: Dict) -> Dict[str, Any]:
        """技术面分析智能体"""
        logger.info("🔍 技术分析师正在分析中...")
        analysis = self.deepseek_client.technical_analysis(stock_info, stock_data, indicators)
        return {
            "agent_name": "技术分析师",
            "agent_role": "负责技术指标分析、图表形态识别、趋势判断",
            "analysis": analysis,
            "focus_areas": ["技术指标", "趋势分析", "支撑阻力", "交易信号"],
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
    
    def fundamental_analyst_agent(self, stock_info: Dict, financial_data: Dict = None, quarterly_data: Dict = None) -> Dict[str, Any]:
        """基本面分析智能体"""
        logger.info("📊 基本面分析师正在分析中...")
        analysis = self.deepseek_client.fundamental_analysis(stock_info, financial_data, quarterly_data)
        return {
            "agent_name": "基本面分析师", 
            "agent_role": "负责公司财务分析、行业研究、估值分析",
            "analysis": analysis,
            "focus_areas": ["财务指标", "行业分析", "公司价值", "成长性", "季报趋势"],
            "quarterly_data": quarterly_data,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
    
    def fund_flow_analyst_agent(self, stock_info: Dict, indicators: Dict, fund_flow_data: Dict = None) -> Dict[str, Any]:
        """资金面分析智能体"""
        logger.info("💰 资金面分析师正在分析中...")
        analysis = self.deepseek_client.fund_flow_analysis(stock_info, indicators, fund_flow_data)
        return {
            "agent_name": "资金面分析师",
            "agent_role": "负责资金流向分析、主力行为研究、市场情绪判断", 
            "analysis": analysis,
            "focus_areas": ["资金流向", "主力动向", "市场情绪", "流动性"],
            "fund_flow_data": fund_flow_data,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
    
    def risk_management_agent(self, stock_info: Dict, indicators: Dict, risk_data: Dict = None) -> Dict[str, Any]:
        """风险管理智能体 (P2 整改十三: 增强 Prompt)"""
        logger.info("⚠️ 风险管理师正在评估中...")
        
        risk_data_text = ""
        if risk_data and risk_data.get('data_success'):
            from risk_data_fetcher import RiskDataFetcher
            fetcher = RiskDataFetcher()
            risk_data_text = f"\n【实际风险数据】（来自问财）\n{fetcher.format_risk_data_for_ai(risk_data)}\n"
        
        prompt = f"""
        作为资深风险管理专家，请基于以下数据对股票进行风险评估：
        股票信息: {stock_info}
        技术指标: {indicators}
        {risk_data_text}
        请从退市风险、财务造假风险、质押风险、违规担保风险、法律诉讼风险等维度进行深度扫描，并给出风险等级评价。
        """
        messages = [
            {"role": "system", "content": "你是一名资深的风险管理专家。"},
            {"role": "user", "content": prompt}
        ]
        analysis = self.deepseek_client.call_api(messages, max_tokens=6000)
        
        return {
            "agent_name": "风险管理师",
            "agent_role": "负责风险识别、风险评估、风险控制策略制定",
            "analysis": analysis,
            "focus_areas": ["风险识别", "风险量化", "风险控制"],
            "risk_data": risk_data,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
    
    def market_sentiment_agent(self, stock_info: Dict, sentiment_data: Dict = None) -> Dict[str, Any]:
        """市场情绪分析智能体 (P2 整改十三: 增强 Prompt)"""
        logger.info("📈 市场情绪分析师正在分析中...")
        
        sentiment_data_text = ""
        if sentiment_data and sentiment_data.get('data_success'):
            from market_sentiment_data import MarketSentimentDataFetcher
            fetcher = MarketSentimentDataFetcher()
            sentiment_data_text = f"\n【市场情绪实际数据】\n{fetcher.format_sentiment_data_for_ai(sentiment_data)}\n"
            
        prompt = f"""
        作为资深市场情绪分析师，请基于以下数据分析市场情绪：
        股票信息: {stock_info}
        {sentiment_data_text}
        请从 ARBR 人气指标、多空博弈情况、市场关注度、舆论热度等维度进行分析，判断当前市场情绪处于恐慌、冷静还是贪婪状态。
        """
        messages = [
            {"role": "system", "content": "你是一名资深的市场情绪分析师。"},
            {"role": "user", "content": prompt}
        ]
        analysis = self.deepseek_client.call_api(messages, max_tokens=4000)
        
        return {
            "agent_name": "市场情绪分析师",
            "agent_role": "负责市场心理分析、情绪指标解读",
            "analysis": analysis,
            "focus_areas": ["ARBR指标", "市场人气"],
            "sentiment_data": sentiment_data,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }

    def run_multi_agent_analysis(self, stock_info, stock_data, indicators,
                               financial_data=None, fund_flow_data=None,
                               sentiment_data=None, news_data=None,
                               quarterly_data=None, risk_data=None,
                               enabled_analysts=None) -> Dict[str, Any]:
        """并行运行多个分析智能体"""
        if enabled_analysts is None:
            enabled_analysts = {
                'technical': True, 'fundamental': True, 'fund_flow': True,
                'risk': True, 'sentiment': True, 'news': True
            }
        
        tasks = {}
        results = {}
        with ThreadPoolExecutor(max_workers=6) as executor:
            if enabled_analysts.get('technical'):
                tasks['technical'] = executor.submit(self.technical_analyst_agent, stock_info, stock_data, indicators)
            if enabled_analysts.get('fundamental'):
                tasks['fundamental'] = executor.submit(self.fundamental_analyst_agent, stock_info, financial_data, quarterly_data)
            if enabled_analysts.get('fund_flow'):
                tasks['fund_flow'] = executor.submit(self.fund_flow_analyst_agent, stock_info, indicators, fund_flow_data)
            if enabled_analysts.get('risk'):
                tasks['risk'] = executor.submit(self.risk_management_agent, stock_info, indicators, risk_data)
            if enabled_analysts.get('sentiment'):
                tasks['sentiment'] = executor.submit(self.market_sentiment_agent, stock_info, sentiment_data)
            # 备注：news_data 智能体逻辑若有需要可在此扩展

            for name, future in tasks.items():
                try:
                    results[name] = future.result()
                except Exception as e:
                    logger.error(f"❌ {name} 智能体分析失败: {e}")
                    results[name] = {"error": str(e), "analysis": f"分析失败: {e}"}
        return results

    def comprehensive_discussion(self, reports: Dict[str, Any], stock_info: Dict) -> str:
        """综合讨论 (P2 整改四: 完整传递报告)"""
        tech_report = reports.get('technical', {}).get('analysis', '')
        fund_report = reports.get('fundamental', {}).get('analysis', '')
        flow_report = reports.get('fund_flow', {}).get('analysis', '')
        risk_report = reports.get('risk', {}).get('analysis', '')
        sent_report = reports.get('sentiment', {}).get('analysis', '')
        
        return self.deepseek_client.comprehensive_discussion(
            tech_report, fund_report, flow_report, risk_report, sent_report, stock_info
        )
