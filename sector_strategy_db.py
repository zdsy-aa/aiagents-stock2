"""
智策板块数据库模块
用于存储板块分析数据和报告
"""

import json
import sqlite3
from datetime import datetime
import pandas as pd
import logging
from base_db import BaseDatabase

class SectorStrategyDatabase(BaseDatabase):
    """板块策略数据库管理类"""
    
    def __init__(self, db_path='sector_strategy.db'):
        self.logger = logging.getLogger(__name__)
        if not self.logger.handlers:
            logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s')
        super().__init__(db_path)
    
    def init_tables(self):
        """初始化数据库表"""
        with self.conn() as conn:
            cursor = conn.cursor()
            
            # 板块原始数据表 (行情/资金等)
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS sector_raw_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data_type TEXT NOT NULL, -- quote, fund_flow, overview, north_flow
                data_date TEXT NOT NULL,
                sector_name TEXT,
                price REAL,
                change_pct REAL,
                volume REAL,
                turnover REAL,
                market_cap REAL,
                pe_ratio REAL,
                pb_ratio REAL,
                raw_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            ''')
            
            # 板块新闻数据表
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS sector_news_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT,
                source TEXT,
                url TEXT,
                news_date TEXT,
                related_sectors TEXT,
                sentiment_score REAL,
                importance_score REAL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            ''')
            
            # AI分析报告表（与线上库/引擎/UI 对齐的列结构）
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS sector_analysis_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_date TEXT NOT NULL,
                data_date_range TEXT,
                analysis_content TEXT,
                recommended_sectors TEXT,
                summary TEXT,
                confidence_score REAL,
                risk_level TEXT,
                investment_horizon TEXT,
                market_outlook TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            ''')
            
            conn.commit()
            self.logger.info("[智策板块] 数据库初始化完成")

    def save_raw_data(self, data_type, data_list):
        """保存板块原始数据"""
        if not data_list: return 0
        data_date = datetime.now().strftime('%Y-%m-%d')

        # 先构建批量参数（坏数据按条跳过），再 executemany 一次性写入
        rows = []
        for item in data_list:
            try:
                rows.append((
                    data_type, data_date, item.get('名称') or item.get('sector'),
                    float(item.get('最新价') or item.get('price') or 0),
                    float(item.get('涨跌幅') or item.get('change_pct') or 0),
                    float(item.get('成交量') or item.get('volume') or 0),
                    float(item.get('成交额') or item.get('turnover') or 0),
                    float(item.get('总市值') or item.get('market_cap') or 0),
                    float(item.get('市盈率') or item.get('pe_ratio') or 0),
                    float(item.get('市净率') or item.get('pb_ratio') or 0),
                    json.dumps(item, ensure_ascii=False)
                ))
            except Exception:
                self.logger.error("构建板块原始数据失败，跳过该条", exc_info=True)

        if not rows:
            return 0

        with self.conn() as conn:
            cursor = conn.cursor()
            cursor.executemany('''
            INSERT INTO sector_raw_data
            (data_type, data_date, sector_name, price, change_pct, volume, turnover, market_cap, pe_ratio, pb_ratio, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', rows)

        return len(rows)

    def get_latest_raw_data(self, data_type, limit=100):
        """获取最近的原始数据"""
        with self.conn() as conn:
            query = '''
                SELECT id, data_type, data_date, sector_name, price, change_pct, volume, turnover, market_cap, pe_ratio, pb_ratio, raw_json, created_at 
                FROM sector_raw_data WHERE data_type = ? ORDER BY created_at DESC LIMIT ?
            '''
            df = pd.read_sql_query(query, conn, params=[data_type, limit])
            return df

    def save_analysis_report(self, data_date_range, analysis_content,
                             recommended_sectors, summary, confidence_score=None,
                             risk_level=None, investment_horizon=None, market_outlook=None):
        """保存AI分析报告（签名与 sector_strategy_engine 调用对齐）

        Args:
            data_date_range: 数据日期范围
            analysis_content: 分析内容（字典或 JSON 字符串）
            recommended_sectors: 推荐板块列表
            summary: 摘要
            confidence_score / risk_level / investment_horizon / market_outlook: 其他元信息
        Returns:
            int: 报告ID
        """
        # 字典统一序列化为 JSON 字符串
        if isinstance(analysis_content, dict):
            analysis_content = json.dumps(analysis_content, ensure_ascii=False, indent=2)
        with self.conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO sector_analysis_reports
            (analysis_date, data_date_range, analysis_content, recommended_sectors,
             summary, confidence_score, risk_level, investment_horizon, market_outlook)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                data_date_range,
                analysis_content,
                json.dumps(recommended_sectors, ensure_ascii=False),
                summary,
                confidence_score,
                risk_level,
                investment_horizon,
                market_outlook
            ))
            report_id = cursor.lastrowid
            self.logger.info(f"[智策板块] 分析报告已保存 (ID: {report_id})")
            return report_id

    def get_analysis_reports(self, limit=10):
        """获取历史分析报告列表"""
        with self.conn() as conn:
            query = '''
                SELECT id, analysis_date, data_date_range, analysis_content, recommended_sectors,
                       summary, confidence_score, risk_level, investment_horizon, market_outlook, created_at
                FROM sector_analysis_reports ORDER BY created_at DESC LIMIT ?
            '''
            df = pd.read_sql_query(query, conn, params=[limit])
            return df

    def get_analysis_report(self, report_id):
        """获取单条分析报告详情（含解析后的 analysis_content_parsed / recommended_sectors）"""
        with self.conn() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, analysis_date, data_date_range, analysis_content, recommended_sectors,
                       summary, confidence_score, risk_level, investment_horizon, market_outlook, created_at
                FROM sector_analysis_reports WHERE id = ?
            ''', (report_id,))
            row = cursor.fetchone()
            if not row:
                return None
            report = dict(row)
            # 解析 JSON 字段，供 UI 直接渲染
            try:
                report['analysis_content_parsed'] = json.loads(report['analysis_content']) if report.get('analysis_content') else None
            except (json.JSONDecodeError, TypeError):
                report['analysis_content_parsed'] = None
            try:
                report['recommended_sectors'] = json.loads(report['recommended_sectors']) if report.get('recommended_sectors') else []
            except (json.JSONDecodeError, TypeError):
                report['recommended_sectors'] = []
            return report

    def delete_analysis_report(self, report_id):
        """删除指定分析报告"""
        with self.conn() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM sector_analysis_reports WHERE id = ?', (report_id,))
            deleted = cursor.rowcount
            self.logger.info(f"[智策板块] 删除分析报告 (ID: {report_id})，影响 {deleted} 行")
            return deleted

# 全局实例
sector_db = SectorStrategyDatabase()
