#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时监测定时调度模块
支持交易日交易时间自动启动关闭监测服务
"""

import schedule
import time
import threading
from datetime import datetime, time as dtime
from typing import Dict, Optional
import json
import os
import logging

logger = logging.getLogger(__name__)

class TradingTimeScheduler:
    """交易时间调度器"""
    
    def __init__(self, monitor_service):
        self.monitor_service = monitor_service
        self.running = False
        self.thread = None
        self.config = self._load_config()
        
    def _load_config(self) -> Dict:
        """加载调度配置"""
        config_file = "monitor_schedule_config.json"
        default_config = {
            "enabled": False,  # 默认不启用自动调度
            "market": "CN",  # CN=中国A股, US=美股, HK=港股
            "trading_hours": {
                "CN": [
                    {"start": "09:30", "end": "11:30"},  # 上午
                    {"start": "13:00", "end": "15:00"}   # 下午
                ],
                "US": [
                    {"start": "21:30", "end": "04:00"}   # 美股时间（北京时间）
                ],
                "HK": [
                    {"start": "09:30", "end": "12:00"},  # 上午
                    {"start": "13:00", "end": "16:00"}   # 下午
                ]
            },
            "trading_days": [1, 2, 3, 4, 5],  # 周一到周五
            "auto_stop": True,  # 收盘后自动停止
            "pre_market_minutes": 5,  # 提前5分钟启动
            "post_market_minutes": 5   # 延后5分钟停止
        }
        
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    # 合并配置，保留默认值
                    default_config.update(loaded_config)
            except Exception as e:
                logger.error(f"加载调度配置失败，使用默认配置: {e}")
        
        return default_config
    
    def _save_config(self):
        """保存调度配置"""
        config_file = "monitor_schedule_config.json"
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            logger.info(f"✅ 调度配置已保存")
        except Exception as e:
            logger.error(f"❌ 保存调度配置失败: {e}")
    
    def update_config(self, **kwargs):
        """更新配置"""
        self.config.update(kwargs)
        self._save_config()
    
    def is_trading_day(self) -> bool:
        """判断是否为交易日"""
        now = datetime.now()
        weekday = now.weekday() + 1  # 转换为1-7（周一到周日）
        
        # 检查是否在交易日列表中
        if weekday not in self.config['trading_days']:
            return False
        
        # TODO: 可以进一步检查是否为法定节假日
        # 这里简单判断为工作日即交易日
        return True
    
    def is_trading_time(self) -> bool:
        """判断当前是否在交易时间内"""
        if not self.is_trading_day():
            return False
        
        now = datetime.now()
        current_time = now.time()
        
        market = self.config.get('market', 'CN')
        trading_hours = self.config['trading_hours'].get(market, [])
        
        for period in trading_hours:
            start_time = datetime.strptime(period['start'], '%H:%M').time()
            end_time = datetime.strptime(period['end'], '%H:%M').time()
            
            # 处理跨天的情况（如美股）
            if start_time > end_time:
                if current_time >= start_time or current_time <= end_time:
                    return True
            else:
                if start_time <= current_time <= end_time:
                    return True
        
        return False
    
    def get_next_trading_time(self) -> Optional[str]:
        """获取下一个交易时间"""
        if not self.is_trading_day():
            return "非交易日"
        
        now = datetime.now()
        current_time = now.time()
        
        market = self.config.get('market', 'CN')
        trading_hours = self.config['trading_hours'].get(market, [])
        
        for period in trading_hours:
            start_time = datetime.strptime(period['start'], '%H:%M').time()
            if current_time < start_time:
                return period['start']
        
        return "交易时间已结束"
    
    def start_scheduler(self):
        """启动调度器"""
        if self.running:
            logger.warning("⚠️ 调度器已在运行")
            return
        
        if not self.config.get('enabled', False):
            logger.warning("⚠️ 调度器未启用")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._schedule_loop, daemon=True)
        self.thread.start()
        logger.info("✅ 调度器已启动")
    
    def stop_scheduler(self):
        """停止调度器"""
        self.running = False
        schedule.clear()
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("⏹️ 调度器已停止")
    
    def _schedule_loop(self):
        """调度循环"""
        # 清空之前的任务
        schedule.clear()
        
        # 根据市场设置定时任务
        market = self.config.get('market', 'CN')
        trading_hours = self.config['trading_hours'].get(market, [])
        
        for period in trading_hours:
            start_time = period['start']
            end_time = period['end']
            
            # 设置开盘启动任务
            schedule.every().day.at(start_time).do(self._auto_start_monitoring)
            logger.info(f"📅 已设置开盘启动任务: {start_time}")
            
            # 设置收盘停止任务
            if self.config.get('auto_stop', True):
                schedule.every().day.at(end_time).do(self._auto_stop_monitoring)
                logger.info(f"📅 已设置收盘停止任务: {end_time}")
        
        # 每分钟检查一次是否在交易时间
        logger.info("🔄 调度器循环已启动")
        while self.running:
            try:
                schedule.run_pending()
                
                # 智能检测：如果当前在交易时间但服务未运行，则启动
                if self.is_trading_time() and not self.monitor_service.running:
                    logger.info("🔔 检测到交易时间，自动启动监测服务")
                    self.monitor_service.start_monitoring()
                
                # 智能检测：如果当前不在交易时间但服务在运行，且auto_stop=True，则停止
                if not self.is_trading_time() and self.monitor_service.running and self.config.get('auto_stop', True):
                    logger.info("🔔 检测到非交易时间，自动停止监测服务")
                    self.monitor_service.stop_monitoring()
                
                time.sleep(60)  # 每分钟检查一次
            except Exception as e:
                logger.error(f"❌ 调度器错误: {e}")
                time.sleep(60)
    
    def _auto_start_monitoring(self):
        """自动启动监测"""
        if self.is_trading_day():
            logger.info(f"🔔 定时启动监测服务 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            if not self.monitor_service.running:
                self.monitor_service.start_monitoring()
        else:
            logger.warning("⏸️ 非交易日，跳过启动")
    
    def _auto_stop_monitoring(self):
        """自动停止监测"""
        logger.info(f"🔔 定时停止监测服务 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if self.monitor_service.running:
            self.monitor_service.stop_monitoring()
    
    def get_status(self) -> Dict:
        """获取调度器状态"""
        return {
            'scheduler_running': self.running,
            'scheduler_enabled': self.config.get('enabled', False),
            'is_trading_day': self.is_trading_day(),
            'is_trading_time': self.is_trading_time(),
            'market': self.config.get('market', 'CN'),
            'next_trading_time': self.get_next_trading_time(),
            'monitor_service_running': self.monitor_service.running,
            'auto_stop': self.config.get('auto_stop', True)
        }

# 全局调度器实例（延迟初始化）
_scheduler_instance = None

def get_scheduler(monitor_service=None):
    """获取调度器实例"""
    global _scheduler_instance
    if _scheduler_instance is None and monitor_service is not None:
        _scheduler_instance = TradingTimeScheduler(monitor_service)
    return _scheduler_instance

