"""
数据源管理器
实现akshare、tushare、TDX三级自动切换机制
优先级: akshare > tushare > TDX
"""

import os
import pandas as pd
import requests
import time
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from akshare_gateway import akshare_gw

# 加载环境变量
load_dotenv()

logger = logging.getLogger(__name__)

class DataSourceManager:
    """数据源管理器 - 实现akshare、tushare、TDX三级自动切换"""
    
    def __init__(self):
        # P1 整改四: DataSourceManager 直接复用 akshare_gw.tushare
        self.tushare_api = akshare_gw.tushare.api if akshare_gw.tushare else None
        self.tushare_available = akshare_gw.tushare.available if akshare_gw.tushare else False
        
        if self.tushare_available:
            logger.info("✅ Tushare数据源初始化成功 (复用网关实例)")
        else:
            logger.info("ℹ️ Tushare数据源不可用")
        
        # 初始化TDX
        self.tdx_enabled = os.getenv('TDX_ENABLED', 'false').lower() == 'true'
        self.tdx_base_url = os.getenv('TDX_BASE_URL', 'http://127.0.0.1:8080')
        if self.tdx_enabled:
            logger.info(f"✅ TDX数据源已就绪: {self.tdx_base_url}")
        else:
            logger.info("ℹ️ TDX数据源未启用")

    # ==================== 历史K线数据 ====================
    
    def get_stock_hist_data(self, symbol, start_date=None, end_date=None, adjust='qfq'):
        """获取股票历史数据（直接代理给 akshare 网关，P1 整改五）"""
        clean_symbol = symbol.split('.')[0]
        if start_date: start_date = start_date.replace('-', '')
        if end_date: end_date = end_date.replace('-', '')
        else: end_date = datetime.now().strftime('%Y%m%d')
        
        # P1 整改五: 直接代理给 akshare_gw.call，它已经实现了 TDX -> AKTools -> akshare -> Tushare 的四级降级链
        df = akshare_gw.call(
            'stock_zh_a_hist',
            cache_category='daily',
            symbol=clean_symbol,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust=adjust
        )
        
        if df is not None and not df.empty:
            df = df.rename(columns={
                '日期': 'date', '开盘': 'open', '收盘': 'close', 
                '最高': 'high', '最低': 'low', '成交量': 'volume', 
                '成交额': 'amount', '振幅': 'amplitude', 
                '涨跌幅': 'pct_change', '涨跌额': 'change', 
                '换手率': 'turnover'
            })
            df['date'] = pd.to_datetime(df['date'])
            return df
        
        logger.error(f"❌ 所有数据源均获取 {clean_symbol} 历史数据失败")
        return None

    # ==================== 股票基本信息 ====================
    
    def get_stock_basic_info(self, symbol):
        """获取股票基本信息（TDX优先 → 网关 → tushare）"""
        clean_symbol = symbol.split('.')[0]
        info = {
            "symbol": clean_symbol,
            "name": "未知",
            "industry": "未知",
            "market": "未知"
        }
        
        # 1. TDX 优先（从最近K线+行情获取基本信息）
        if self.tdx_enabled:
            try:
                prefix = "SH" if clean_symbol.startswith(('6', '9', '5')) else "SZ"
                tdx_code = f"{prefix}{clean_symbol}"
                res = requests.get(
                    f"{self.tdx_base_url}/api/quote",
                    params={"code": tdx_code},
                    timeout=5
                )
                if res.status_code == 200:
                    data = res.json()
                    if data.get('code') == 0 and data.get('data'):
                        quote = data['data']
                        name = quote.get('Name') or quote.get('name', '')
                        if name:
                            info['name'] = name
                            info['market'] = 'SH' if clean_symbol.startswith(('6', '9')) else 'SZ'
                            logger.info(f"[TDX] ✅ 成功获取 {clean_symbol} 基本信息")
                            # TDX 没有行业信息，继续尝试其他源补充
                            if info['name'] != '未知':
                                # 尝试补充行业信息（不影响返回）
                                self._fill_industry_info(info, clean_symbol)
                                return info
            except Exception as e:
                logger.debug(f"[TDX] 获取基本信息失败: {e}")
        
        # 2. 通过网关获取（akshare stock_individual_info_em）
        try:
            df = akshare_gw.call(
                'stock_individual_info_em',
                cache_category='daily',
                symbol=clean_symbol
            )
            if df is not None and not df.empty and {'item', 'value'}.issubset(df.columns):
                for _, row in df.iterrows():
                    key = row['item']
                    value = row['value']
                    if key == '股票简称':
                        info['name'] = value
                    elif key == '所处行业':
                        info['industry'] = value
                    elif key == '上市时间':
                        info['list_date'] = value
                    elif key == '总市值':
                        info['market_cap'] = value
                    elif key == '流通市值':
                        info['circulating_market_cap'] = value

                logger.info(f"[网关] ✅ 成功获取 {clean_symbol} 基本信息")
                return info
            else:
                # 东财接口被封/降级后返回的表无 item/value 列，优雅跳到下一数据源
                logger.debug(f"[网关] stock_individual_info_em 无 item/value 列，跳过补充")
        except Exception as e:
            logger.warning(f"[网关] ⚠️ 获取基本信息失败: {e}")
        
        # 3. tushare 兜底
        if self.tushare_available:
            try:
                ts_code = self._convert_to_ts_code(clean_symbol)
                df = self.tushare_api.stock_basic(
                    ts_code=ts_code,
                    fields='ts_code,name,area,industry,market,list_date'
                )
                if df is not None and not df.empty:
                    info['name'] = df.iloc[0]['name']
                    info['industry'] = df.iloc[0]['industry']
                    info['market'] = df.iloc[0]['market']
                    info['list_date'] = df.iloc[0]['list_date']
                    logger.info(f"[Tushare] ✅ 成功获取 {clean_symbol} 基本信息")
                    return info
            except Exception as e:
                logger.warning(f"[Tushare] ⚠️ 获取基本信息失败: {e}")
        
        return info

    def _fill_industry_info(self, info, symbol):
        """补充行业信息（TDX没有行业字段，尝试从其他源获取）"""
        # 尝试网关
        try:
            df = akshare_gw.call(
                'stock_individual_info_em',
                cache_category='daily',
                symbol=symbol
            )
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    if row['item'] == '所处行业':
                        info['industry'] = row['value']
                    elif row['item'] == '总市值':
                        info['market_cap'] = row['value']
                    elif row['item'] == '上市时间':
                        info['list_date'] = row['value']
        except Exception:
            pass
        
        # 尝试 tushare
        if info.get('industry', '未知') == '未知' and self.tushare_available:
            try:
                ts_code = self._convert_to_ts_code(symbol)
                df = self.tushare_api.stock_basic(
                    ts_code=ts_code, fields='industry,list_date'
                )
                if df is not None and not df.empty:
                    info['industry'] = df.iloc[0].get('industry', '未知')
                    if 'list_date' not in info:
                        info['list_date'] = df.iloc[0].get('list_date', '')
            except Exception:
                pass

    # ==================== 财务数据 ====================
    
    def get_financial_data(self, symbol, report_type='income'):
        """
        获取财务数据（网关 → tushare）
        
        Args:
            symbol: 股票代码
            report_type: 'income'利润表 / 'balance'资产负债表 / 'cashflow'现金流量表
        """
        clean_symbol = symbol.split('.')[0]
        
        # 1. 通过网关获取（akshare 新浪财务报表，未被封）
        report_map = {
            'income': '利润表',
            'balance': '资产负债表',
            'cashflow': '现金流量表'
        }
        ak_symbol = report_map.get(report_type)
        if ak_symbol:
            df = akshare_gw.call(
                'stock_financial_report_sina',
                cache_category='financial',
                stock=clean_symbol,
                symbol=ak_symbol
            )
            if df is not None and not df.empty:
                logger.info(f"[网关] ✅ 成功获取 {clean_symbol} {ak_symbol}")
                return df
        
        # 2. tushare 兜底
        if self.tushare_available:
            try:
                ts_code = self._convert_to_ts_code(clean_symbol)
                if report_type == 'income':
                    df = self.tushare_api.income(ts_code=ts_code)
                elif report_type == 'balance':
                    df = self.tushare_api.balancesheet(ts_code=ts_code)
                elif report_type == 'cashflow':
                    df = self.tushare_api.cashflow(ts_code=ts_code)
                else:
                    df = None
                
                if df is not None and not df.empty:
                    logger.info(f"[Tushare] ✅ 成功获取 {clean_symbol} 财务数据")
                    return df
            except Exception as e:
                logger.warning(f"[Tushare] ⚠️ 获取财务数据失败: {e}")
        
        return None

    # ==================== 实时行情 ====================
    
    def get_realtime_quotes(self, symbol):
        """获取实时行情数据（经网关限流+缓存）"""
        clean_symbol = symbol.split('.')[0]
        quotes = None
        
        # 1. 尝试 Akshare (通过网关)
        try:
            df = akshare_gw.call(
                'stock_individual_info_em',
                cache_category='realtime',
                symbol=clean_symbol
            )
            if df is not None and not df.empty:
                # 转置或提取 key-value
                info = dict(zip(df['item'], df['value']))
                quotes = {
                    'symbol': clean_symbol, 
                    'name': info.get('股票简称'), 
                    'price': float(info.get('最新', 0)),
                    'high': None, 'low': None, 'open': None, 'pre_close': None # info 接口字段较少
                }
        except Exception as e:
            logger.error(f"[Akshare] ❌ 获取实时行情失败: {e}")
        
        # 2. TDX 兜底
        if quotes is None and self.tdx_enabled:
            df = self._get_hist_tdx(clean_symbol)
            if df is not None and not df.empty:
                last = df.iloc[-1]
                quotes = {
                    'symbol': clean_symbol, 'price': last['close'], 
                    'high': last['high'], 'low': last['low'], 
                    'open': last['open'], 'volume': last['volume']
                }

        return quotes

    def _convert_to_ts_code(self, symbol):
        """将6位代码转换为tushare代码格式"""
        if '.' in symbol: return symbol
        if symbol.startswith('6') or symbol.startswith('9'):
            return f"{symbol}.SH"
        elif symbol.startswith('8') or symbol.startswith('4'):
            return f"{symbol}.BJ"
        else:
            return f"{symbol}.SZ"

# 全局实例
data_source_manager = DataSourceManager()
