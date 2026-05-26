import time
import threading
import logging
from datetime import datetime, timedelta
from typing import Dict, List
import os

from monitor_db import monitor_db
from stock_data import StockDataFetcher
from miniqmt_interface import miniqmt
from notification_service import notification_service

logger = logging.getLogger(__name__)

class StockMonitorService:
    """股票监测服务"""
    
    def __init__(self):
        self.fetcher = StockDataFetcher()
        self.running = False
        self.thread = None
    
    def is_trading_hours(self) -> bool:
        """判断当前是否为交易时间 (P1 整改五)"""
        now = datetime.now()
        # 周六周日不交易
        if now.weekday() >= 5:
            return False
        
        current_time = now.strftime('%H:%M:%S')
        # A股交易时间：09:30-11:30, 13:00-15:00
        if ('09:30:00' <= current_time <= '11:30:00') or \
           ('13:00:00' <= current_time <= '15:00:00'):
            return True
        return False

    def start_monitoring(self) -> str:
        """启动监测服务"""
        if self.running:
            return "already_running"
        
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        logger.info("监测服务已启动")
        return "started"
    
    def stop_monitoring(self) -> str:
        """停止监测服务"""
        if not self.running:
            return "already_stopped"
            
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("监测服务已停止")
        return "stopped"
    
    def _monitor_loop(self):
        """监测循环 (P1 整改七)"""
        while self.running:
            try:
                # P1 整改七: 循环内部不再直接跳过，而是在 _check_all_stocks 中按需跳过
                self._check_all_stocks()
                
                if self.is_trading_hours():
                    # 交易时段检查频率可以稍高，例如 1 分钟
                    time.sleep(60)
                else:
                    # 非交易时段，大幅降低检查频率，例如 15 分钟
                    logger.info("当前非交易时段，进入低频监测模式...")
                    time.sleep(900)
            except Exception as e:
                logger.error(f"监测服务循环错误: {e}")
                time.sleep(60)
    
    def _check_all_stocks(self):
        """检查所有监测股票 (P1 整改七)"""
        stocks = monitor_db.get_monitored_stocks()
        current_time = datetime.now()
        is_trading = self.is_trading_hours()
        
        updated_count = 0
        for stock in stocks:
            # P1 整改七: 尊重每只股票的 trading_hours_only 配置
            if stock.get('trading_hours_only', True) and not is_trading:
                continue

            # 检查是否需要更新价格
            last_checked = stock.get('last_checked')
            check_interval = stock.get('check_interval', 30)
            
            if last_checked:
                try:
                    last_checked_dt = datetime.fromisoformat(last_checked)
                    next_check = last_checked_dt + timedelta(minutes=check_interval)
                    if current_time < next_check:
                        continue
                except (ValueError, TypeError):
                    pass
            
            try:
                self._update_stock_price(stock)
                updated_count += 1
            except Exception as e:
                logger.error(f"❌ 更新股票 {stock['symbol']} 价格失败: {e}")
        
        if updated_count > 0:
            logger.info(f"✅ 本轮共更新了 {updated_count} 只股票")
    
    def _update_stock_price(self, stock: Dict):
        """更新股票价格并检查条件"""
        symbol = stock['symbol']
        try:
            # 统一使用 fetcher 获取价格，fetcher 内部应使用 data_source_manager
            stock_info = self.fetcher.get_stock_info(symbol)
            current_price = stock_info.get('current_price')
            
            if current_price and current_price != 'N/A':
                current_price = float(current_price)
                monitor_db.update_stock_price(stock['id'], current_price)
                self._check_trigger_conditions(stock, current_price)
            else:
                monitor_db.update_last_checked(stock['id'])
        except Exception as e:
            logger.error(f"❌ 获取股票 {symbol} 数据失败: {e}")
            try:
                monitor_db.update_last_checked(stock['id'])
            except Exception:
                pass
    
    def _check_trigger_conditions(self, stock: Dict, current_price: float):
        """检查触发条件"""
        if not stock.get('notification_enabled', True):
            return
        
        entry_range = stock.get('entry_range', {})
        take_profit = stock.get('take_profit')
        stop_loss = stock.get('stop_loss')
        
        # 检查进场区间
        if entry_range and entry_range.get('min') and entry_range.get('max'):
            if entry_range['min'] <= current_price <= entry_range['max']:
                if not monitor_db.has_recent_notification(stock['id'], 'entry', minutes=60):
                    message = f"股票 {stock['symbol']} ({stock['name']}) 价格 {current_price} 进入进场区间 [{entry_range['min']}-{entry_range['max']}]"
                    monitor_db.add_notification(stock['id'], 'entry', message)
                    notification_service.send_notifications()
        
        # 止盈止损逻辑略... (保持原有逻辑)
        if take_profit and current_price >= take_profit:
            if not monitor_db.has_recent_notification(stock['id'], 'take_profit', minutes=60):
                message = f"股票 {stock['symbol']} ({stock['name']}) 价格 {current_price} 达到止盈位 {take_profit}"
                monitor_db.add_notification(stock['id'], 'take_profit', message)
                notification_service.send_notifications()
        
        if stop_loss and current_price <= stop_loss:
            if not monitor_db.has_recent_notification(stock['id'], 'stop_loss', minutes=60):
                message = f"股票 {stock['symbol']} ({stock['name']}) 价格 {current_price} 达到止损位 {stop_loss}"
                monitor_db.add_notification(stock['id'], 'stop_loss', message)
                notification_service.send_notifications()

    def get_scheduler(self):
        """获取交易时段定时调度器单例（延迟导入避免循环依赖）"""
        from monitor_scheduler import get_scheduler as _get_scheduler
        return _get_scheduler(self)

# P3 整改十八: 延迟加载单例
_monitor_service_instance = None
def get_monitor_service():
    global _monitor_service_instance
    if _monitor_service_instance is None:
        _monitor_service_instance = StockMonitorService()
    return _monitor_service_instance

# 为了兼容旧代码，保留 monitor_service 变量，但改为动态获取
class MonitorServiceProxy:
    def __getattr__(self, name):
        return getattr(get_monitor_service(), name)

monitor_service = MonitorServiceProxy()
