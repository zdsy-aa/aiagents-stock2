import os
import json
import time
import logging
import re
from typing import Dict, List, Any, Optional
from openai import OpenAI

logger = logging.getLogger(__name__)

class APICallError(Exception):
    """API调用异常"""
    pass

class DeepSeekClient:
    def __init__(self, api_key=None, base_url=None, model=None):
        # P0 整改三: 统一从 config.py 读取默认值，避免 /v1 缺失
        import config
        self.api_key = api_key or config.DEEPSEEK_API_KEY
        self.base_url = base_url or config.DEEPSEEK_BASE_URL
        self.model = model or config.DEFAULT_MODEL_NAME
        
        # 使用预配置的 OpenAI 客户端
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def call_api(self, messages: List[Dict], temperature=0.7, max_tokens=2000, max_retries=3) -> str:
        """调用DeepSeek API，带重试、超时和异常处理"""
        last_error = None
        for attempt in range(max_retries):
            try:
                # 设置 60 秒超时
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=60.0
                )
                return response.choices[0].message.content
            except Exception as e:
                last_error = e
                logger.warning(f"DeepSeek API call failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # 指数退避
                continue
        
        error_msg = f"DeepSeek API调用失败，已重试 {max_retries} 次: {str(last_error)}"
        logger.error(error_msg)
        raise APICallError(error_msg)

    def technical_analysis(self, stock_info: Dict, stock_data: Any, indicators: Dict) -> str:
        """技术面分析"""
        prompt = f"""
        作为资深技术分析师，请基于以下数据对股票进行深度分析：
        股票信息: {stock_info}
        技术指标: {indicators}
        请从趋势、动量、波动率、支撑阻力等维度进行分析。
        """
        messages = [
            {"role": "system", "content": "你是一名资深的技术分析师。"},
            {"role": "user", "content": prompt}
        ]
        return self.call_api(messages, max_tokens=3000)

    def fundamental_analysis(self, stock_info: Dict, financial_data: Dict = None, quarterly_data: Dict = None) -> str:
        """基本面分析"""
        prompt = f"""
        作为资深基本面分析师，请基于以下数据对股票进行深度分析：
        股票信息: {stock_info}
        财务数据: {financial_data}
        季报数据: {quarterly_data}
        请从盈利能力、偿债能力、营运能力、成长性及行业地位等维度进行分析。
        """
        messages = [
            {"role": "system", "content": "你是一名资深的基本面分析师。"},
            {"role": "user", "content": prompt}
        ]
        return self.call_api(messages, max_tokens=4000)

    def fund_flow_analysis(self, stock_info: Dict, indicators: Dict, fund_flow_data: Dict = None) -> str:
        """资金面分析"""
        prompt = f"""
        作为资深资金面分析师，请基于以下数据对股票进行深度分析：
        股票信息: {stock_info}
        技术指标: {indicators}
        资金流向数据: {fund_flow_data}
        请分析主力动向、资金净流入流出情况及其对股价的潜在影响。
        """
        messages = [
            {"role": "system", "content": "你是一名资深的资金面分析师。"},
            {"role": "user", "content": prompt}
        ]
        return self.call_api(messages, max_tokens=3000)

    def comprehensive_discussion(self, technical_report: str, fundamental_report: str, 
                               fund_flow_report: str, risk_report: str, sentiment_report: str, stock_info: Dict) -> str:
        """综合讨论 (P2 整改四: 完整传递报告)"""
        prompt = f"""
        现在需要进行一场投资决策会议，你作为首席分析师，需要综合各位分析师的报告进行讨论。
        股票信息: {stock_info}
        
        【技术面报告】
        {technical_report}
        
        【基本面报告】
        {fundamental_report}
        
        【资金面报告】
        {fund_flow_report}
        
        【风险评估报告】
        {risk_report}
        
        【市场情绪报告】
        {sentiment_report}
        
        请综合以上所有维度进行深度讨论，给出最终的投资逻辑。
        """
        messages = [
            {"role": "system", "content": "你是一名资深的首席投资分析师。"},
            {"role": "user", "content": prompt}
        ]
        return self.call_api(messages, max_tokens=8000)

    def final_decision(self, comprehensive_discussion: str, stock_info: Dict, 
                      indicators: Dict) -> Dict[str, Any]:
        """最终投资决策 (P2 整改十四: 优化 JSON 提取)"""
        prompt = f"""
        基于前期的综合分析讨论，现在需要做出最终的投资决策。
        综合讨论结果: {comprehensive_discussion}
        股票信息: {stock_info}
        请给出最终投资决策（JSON格式，必须包含 'rating', 'target_price', 'stop_loss', 'logic' 字段）。
        """
        messages = [
            {"role": "system", "content": "你是一名专业的投资决策专家。"},
            {"role": "user", "content": prompt}
        ]
        response = self.call_api(messages, temperature=0.3, max_tokens=4000)
        
        # P2 整改十四: 优化 JSON 提取，处理多层大括号
        def extract_json(text):
            try:
                # 寻找第一个 { 和最后一个 }
                start = text.find('{')
                end = text.rfind('}')
                if start != -1 and end != -1:
                    json_str = text[start:end+1]
                    return json.loads(json_str)
            except Exception:
                pass
            return None

        try:
            data = extract_json(response)
            if data:
                return data
            return {"decision_text": response}
        except Exception as e:
            logger.error(f"Failed to parse final decision JSON: {e}")
            return {"decision_text": response}
