"""
智能盯盘 - 数据库模块
记录AI决策、交易记录、监控配置等
"""

import json
from datetime import datetime
from typing import Dict, List, Optional
from base_db import BaseDatabase
import logging


class SmartMonitorDB(BaseDatabase):
    """智能盯盘数据库"""
    
    def __init__(self, db_file: str = 'smart_monitor.db'):
        self.logger = logging.getLogger(__name__)
        super().__init__(db_file)
    
    def init_tables(self):
        """初始化数据库表结构"""
        with self.conn() as conn:
            cursor = conn.cursor()
            
            # 1. 监控任务表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS monitor_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_name TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT,
                    enabled INTEGER DEFAULT 1,
                    check_interval INTEGER DEFAULT 300,
                    auto_trade INTEGER DEFAULT 0,
                    position_size_pct REAL DEFAULT 20,
                    stop_loss_pct REAL DEFAULT 5,
                    take_profit_pct REAL DEFAULT 10,
                    qmt_account_id TEXT,
                    notify_email TEXT,
                    notify_webhook TEXT,
                    has_position INTEGER DEFAULT 0,
                    position_cost REAL DEFAULT 0,
                    position_quantity INTEGER DEFAULT 0,
                    position_date TEXT,
                    trading_hours_only INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stock_code)
                )
            ''')
            
            # 2. AI决策记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ai_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT,
                    decision_time TEXT NOT NULL,
                    trading_session TEXT,
                    action TEXT NOT NULL,
                    confidence INTEGER,
                    reasoning TEXT,
                    position_size_pct REAL,
                    stop_loss_pct REAL,
                    take_profit_pct REAL,
                    risk_level TEXT,
                    key_price_levels TEXT,
                    market_data TEXT,
                    account_info TEXT,
                    executed INTEGER DEFAULT 0,
                    execution_result TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 3. 交易记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trade_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT,
                    trade_type TEXT NOT NULL,
                    quantity INTEGER,
                    price REAL,
                    amount REAL,
                    order_id TEXT,
                    order_status TEXT,
                    ai_decision_id INTEGER,
                    trade_time TEXT NOT NULL,
                    commission REAL DEFAULT 0,
                    tax REAL DEFAULT 0,
                    profit_loss REAL DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(ai_decision_id) REFERENCES ai_decisions(id)
                )
            ''')
            
            # 4. 持仓监控表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS position_monitor (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT,
                    quantity INTEGER,
                    cost_price REAL,
                    current_price REAL,
                    profit_loss REAL,
                    profit_loss_pct REAL,
                    holding_days INTEGER,
                    buy_date TEXT,
                    stop_loss_price REAL,
                    take_profit_price REAL,
                    last_check_time TEXT,
                    status TEXT DEFAULT 'holding',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(stock_code)
                )
            ''')
            
            # 5. 通知记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT,
                    notify_type TEXT NOT NULL,
                    notify_target TEXT,
                    subject TEXT,
                    content TEXT,
                    status TEXT DEFAULT 'pending',
                    error_msg TEXT,
                    sent_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 6. 系统日志表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    log_level TEXT,
                    module TEXT,
                    message TEXT,
                    details TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
            self.logger.info(f"数据库初始化完成: {self.db_path}")

    def add_monitor_task(self, task_data: Dict) -> int:
        """添加监控任务"""
        with self.conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO monitor_tasks 
                (task_name, stock_code, stock_name, enabled, check_interval, 
                 auto_trade, trading_hours_only, position_size_pct, stop_loss_pct, take_profit_pct,
                 qmt_account_id, notify_email, notify_webhook,
                 has_position, position_cost, position_quantity, position_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                task_data.get('task_name'), task_data.get('stock_code'), task_data.get('stock_name'),
                task_data.get('enabled', 1), task_data.get('check_interval', 300), task_data.get('auto_trade', 0),
                task_data.get('trading_hours_only', 1), task_data.get('position_size_pct', 20),
                task_data.get('stop_loss_pct', 5), task_data.get('take_profit_pct', 10),
                task_data.get('qmt_account_id'), task_data.get('notify_email'), task_data.get('notify_webhook'),
                task_data.get('has_position', 0), task_data.get('position_cost', 0),
                task_data.get('position_quantity', 0), task_data.get('position_date')
            ))
            task_id = cursor.lastrowid
            conn.commit()
            return task_id

    def get_monitor_tasks(self, enabled_only: bool = True) -> List[Dict]:
        """获取监控任务列表"""
        with self.conn() as conn:
            cursor = conn.cursor()
            query = 'SELECT id, task_name, stock_code, stock_name, enabled, check_interval, auto_trade, position_size_pct, stop_loss_pct, take_profit_pct, qmt_account_id, notify_email, notify_webhook, has_position, position_cost, position_quantity, position_date, trading_hours_only, created_at, updated_at FROM monitor_tasks'
            if enabled_only:
                query += ' WHERE enabled = 1'
            query += ' ORDER BY id DESC'
            cursor.execute(query)
            rows = cursor.fetchall()
            return [{
                'id': r[0], 'task_name': r[1], 'stock_code': r[2], 'stock_name': r[3], 'enabled': r[4],
                'check_interval': r[5], 'auto_trade': r[6], 'position_size_pct': r[7], 'stop_loss_pct': r[8],
                'take_profit_pct': r[9], 'qmt_account_id': r[10], 'notify_email': r[11], 'notify_webhook': r[12],
                'has_position': r[13], 'position_cost': r[14], 'position_quantity': r[15], 'position_date': r[16],
                'trading_hours_only': r[17], 'created_at': r[18], 'updated_at': r[19]
            } for r in rows]

    def save_ai_decision(self, decision_data: Dict) -> int:
        """保存AI决策"""
        with self.conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO ai_decisions
                (stock_code, stock_name, decision_time, trading_session,
                 action, confidence, reasoning, position_size_pct,
                 stop_loss_pct, take_profit_pct, risk_level,
                 key_price_levels, market_data, account_info)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                decision_data.get('stock_code'), decision_data.get('stock_name'),
                decision_data.get('decision_time', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                decision_data.get('trading_session'), decision_data.get('action'),
                decision_data.get('confidence'), decision_data.get('reasoning'),
                decision_data.get('position_size_pct'), decision_data.get('stop_loss_pct'),
                decision_data.get('take_profit_pct'), decision_data.get('risk_level'),
                json.dumps(decision_data.get('key_price_levels', {})),
                json.dumps(decision_data.get('market_data', {})),
                json.dumps(decision_data.get('account_info', {}))
            ))
            decision_id = cursor.lastrowid
            conn.commit()
            return decision_id

# 全局实例
smart_monitor_db = SmartMonitorDB()
