"""类型/值转换纯函数 + 表/列中文注释字典。供 import_all.py / sync_daily.py 复用。"""
import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")

def to_ts(unix_sec):
    if unix_sec is None or unix_sec == "":
        return None
    return datetime.datetime.fromtimestamp(int(unix_sec), tz=TZ)

def to_price(v):
    if v is None or v == "":
        return None
    return float(v) / 1000.0

def to_bool(v):
    if v is None or v == "":
        return None
    return bool(int(v))

def sqlite_to_pg_type(col_type):
    t = (col_type or "").upper()
    if t.startswith("INT") or t == "INTEGER":
        return "BIGINT"
    if t in ("REAL", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL"):
        return "DOUBLE PRECISION"
    if t == "BOOLEAN" or t == "BOOL":
        return "BOOLEAN"
    if t in ("TIMESTAMP", "DATETIME"):
        return "TIMESTAMPTZ"
    return "TEXT"


# 信号库表名 -> 中文注释（源 data/*.db 的各表，加来源前缀后的 PG 表名见 import_all.SIGNAL_DBS）
TABLE_COMMENTS = {
    "chanlun_signals": "缠论买点信号（源 data/chanlun_signals.db 的 signals 表）",
    "chanlun_signals_intraday": "缠论盘中买点信号（源 data/chanlun_signals_intraday.db 的 signals 表）",
    "combo_signals": "缠论+六脉组合信号（源 data/combo_signals.db 的 combo_signals 表）",
    "liumai_signals": "六脉神剑信号（源 data/liumai_signals.db 的 liumai_signals 表）",
    "longhubang_records": "龙虎榜明细（源 data/longhubang.db）",
    "longhubang_analysis": "龙虎榜分析结论",
    "stock_tracking": "龙虎榜推荐股票跟踪",
    "low_price_bull_monitored_stocks": "低价牛股监控股票池（源 low_price_bull_monitor.db 的 monitored_stocks）",
    "low_price_bull_sell_alerts": "低价牛股卖出告警（源 low_price_bull_monitor.db 的 sell_alerts）",
    "main_force_batch_analysis_history": "主力批量分析历史（源 main_force_batch.db）",
    "news_flow_snapshots": "新闻流抓取快照（源 news_flow.db）",
    "news_flow_platform_news": "平台新闻",
    "news_flow_stock_related_news": "个股关联新闻",
    "news_flow_hot_topics": "热点话题",
    "news_flow_statistics": "新闻流统计",
    "news_flow_sentiment_records": "情绪记录",
    "news_flow_alerts": "新闻流告警",
    "news_flow_ai_analysis": "AI 分析结论",
    "news_flow_scheduler_logs": "新闻流调度日志",
    "news_flow_alert_config": "告警配置",
    "news_flow_keyword_rankings": "关键词排行",
    "news_flow_keyword_history": "关键词历史",
    "portfolio_stocks": "自选组合股票（源 portfolio_stocks.db）",
    "portfolio_analysis_history": "自选组合分析历史",
    "profit_growth_monitored_stocks": "利润增长监控股票池（源 profit_growth_monitor.db）",
    "profit_growth_sell_alerts": "利润增长卖出告警",
    "qizhang_daily_picks": "起涨预测每日选股（源 qizhang_picks.db 的 daily_picks）",
    "qizhang_realized": "起涨预测已兑现记录",
    "qizhang_run_meta": "起涨预测运行元信息",
    "sector_raw_data": "板块行情原始数据（源 sector_strategy.db）",
    "sector_news_data": "板块新闻数据",
    "sector_analysis_reports": "板块分析报告",
    "sector_tracking": "板块推荐跟踪",
    "sector_data_versions": "板块数据版本",
    "smart_monitor_tasks": "智能监控任务（源 smart_monitor.db 的 monitor_tasks）",
    "smart_monitor_ai_decisions": "智能监控 AI 决策",
    "smart_monitor_trade_records": "智能监控交易记录",
    "smart_monitor_position_monitor": "智能监控持仓",
    "smart_monitor_notifications": "智能监控通知",
    "smart_monitor_system_logs": "智能监控系统日志",
    "stock_analysis_records": "个股分析记录（源 stock_analysis.db 的 analysis_records）",
    "stock_monitor_monitored_stocks": "个股监控池（源 stock_monitor.db 的 monitored_stocks）",
    "stock_monitor_price_history": "个股监控价格历史",
    "stock_monitor_notifications": "个股监控通知",
}

# 通用列名 -> 中文注释（跨表复用；未命中的列名兜底注释为列名本身）
COLUMN_COMMENTS = {
    "id": "自增主键", "code": "股票代码", "name": "名称", "symbol": "股票代码",
    "board": "板块", "level": "级别", "scan_date": "扫描日期", "signal_type": "信号类型",
    "signal_date": "信号日期", "buy_price": "买入价", "buy_reason": "买入理由",
    "stop_loss": "止损价", "sell_type": "卖出类型", "sell_date": "卖出日期",
    "sell_reason": "卖出理由", "chanlun_type": "缠论买点类型", "chanlun_date": "缠论买点日期",
    "liumai_date": "六脉信号日期", "liumai_bull_count": "六脉看多计数", "liumai_score": "六脉得分",
    "bull_count": "看多计数", "score": "得分", "state": "状态", "macd": "MACD 信号",
    "kdj": "KDJ 信号", "rsi": "RSI 信号", "lwr": "LWR 信号", "bbi": "BBI 信号", "mtm": "MTM 信号",
    "date": "日期", "stock_code": "股票代码", "stock_name": "股票名称", "youzi_name": "游资名称",
    "yingye_bu": "营业部", "list_type": "上榜类型", "buy_amount": "买入额", "sell_amount": "卖出额",
    "net_inflow": "净流入", "concepts": "概念", "created_at": "创建时间", "analysis_date": "分析日期",
    "data_date_range": "数据日期范围", "analysis_content": "分析内容", "recommended_stocks": "推荐股票",
    "summary": "摘要", "analysis_id": "分析记录ID", "recommended_date": "推荐日期",
    "recommended_price": "推荐价", "target_price": "目标价", "stop_loss_price": "止损价",
    "current_price": "现价", "profit_loss_pct": "盈亏百分比", "status": "状态", "notes": "备注",
    "updated_at": "更新时间", "buy_date": "买入日期", "holding_days": "持有天数", "add_time": "加入时间",
    "remove_time": "移除时间", "remove_reason": "移除原因", "alert_type": "告警类型",
    "alert_reason": "告警原因", "ma5": "5日均线", "ma20": "20日均线", "alert_time": "告警时间",
    "is_sent": "是否已发送", "kdj_k": "KDJ K值", "kdj_d": "KDJ D值", "kdj_j": "KDJ J值",
    "is_processed": "是否已处理", "batch_count": "批量数量", "analysis_mode": "分析模式",
    "success_count": "成功数量", "failed_count": "失败数量", "total_time": "总耗时", "results_json": "结果JSON",
    "fetch_time": "抓取时间", "total_platforms": "平台总数", "total_score": "总分",
    "flow_level": "流量级别", "social_score": "社媒得分", "news_score": "新闻得分",
    "finance_score": "财经得分", "tech_score": "科技得分", "analysis": "分析",
    "snapshot_id": "快照ID", "platform": "平台", "platform_name": "平台名称", "category": "分类",
    "weight": "权重", "title": "标题", "content": "内容", "url": "链接", "source": "来源",
    "publish_time": "发布时间", "rank": "排名", "matched_keywords": "匹配关键词",
    "keyword_count": "关键词数量", "topic": "话题", "count": "数量", "heat": "热度",
    "cross_platform": "是否跨平台", "sources": "来源列表", "avg_score": "平均得分", "max_score": "最高得分",
    "min_score": "最低得分", "snapshot_count": "快照数", "top_topics": "热门话题",
    "sentiment_index": "情绪指数", "sentiment_class": "情绪分类", "flow_stage": "流量阶段",
    "momentum": "动量", "viral_k": "病毒系数", "flow_type": "流量类型", "stage_analysis": "阶段分析",
    "alert_level": "告警级别", "related_topics": "相关话题", "trigger_value": "触发值",
    "threshold_value": "阈值", "is_notified": "是否已通知", "affected_sectors": "受影响板块",
    "risk_level": "风险等级", "risk_factors": "风险因素", "advice": "建议", "confidence": "置信度",
    "raw_response": "原始响应", "model_used": "使用模型", "analysis_time": "分析耗时",
    "task_name": "任务名", "task_type": "任务类型", "message": "消息", "duration": "耗时",
    "executed_at": "执行时间", "config_key": "配置键", "config_value": "配置值", "description": "描述",
    "keyword": "关键词", "current_rank": "当前排名", "previous_rank": "上一排名",
    "rank_change": "排名变化", "heat_score": "热度得分", "mention_count": "提及次数",
    "platforms": "平台列表", "cost_price": "成本价", "quantity": "数量", "note": "备注",
    "auto_monitor": "是否自动监控", "portfolio_stock_id": "组合股票ID", "rating": "评级",
    "entry_min": "入场区间下限", "entry_max": "入场区间上限", "take_profit": "止盈价",
    "entry_range": "入场区间", "realized_return": "已实现收益", "hit_10pct": "是否触及10%",
    "exit_reason": "退出原因", "bench_return": "基准收益", "exit_date": "退出日期",
    "model_train_rows": "模型训练行数", "train_end_date": "训练截止日期", "sh_ma20_gate": "上证MA20择时",
    "data_date": "数据日期", "sector_code": "板块代码", "sector_name": "板块名称", "price": "价格",
    "change_pct": "涨跌幅", "volume": "成交量", "turnover": "换手率", "market_cap": "市值",
    "pe_ratio": "市盈率", "pb_ratio": "市净率", "data_type": "数据类型", "data_version": "数据版本",
    "news_date": "新闻日期", "related_sectors": "相关板块", "sentiment_score": "情绪得分",
    "importance_score": "重要度得分", "investment_horizon": "投资周期", "market_outlook": "市场展望",
    "version": "版本", "error_message": "错误信息", "record_count": "记录数",
    "enabled": "是否启用", "check_interval": "检查间隔", "auto_trade": "是否自动交易",
    "position_size_pct": "仓位比例", "stop_loss_pct": "止损比例", "take_profit_pct": "止盈比例",
    "qmt_account_id": "QMT账户ID", "notify_email": "通知邮箱", "notify_webhook": "通知webhook",
    "has_position": "是否持仓", "position_cost": "持仓成本", "position_quantity": "持仓数量",
    "position_date": "建仓日期", "trading_hours_only": "仅交易时段", "decision_time": "决策时间",
    "trading_session": "交易时段", "action": "动作", "reasoning": "推理", "key_price_levels": "关键价位",
    "market_data": "行情数据", "account_info": "账户信息", "executed": "是否已执行",
    "execution_result": "执行结果", "trade_type": "交易类型", "amount": "金额", "order_id": "订单ID",
    "order_status": "订单状态", "ai_decision_id": "AI决策ID", "trade_time": "交易时间",
    "commission": "佣金", "tax": "税费", "profit_loss": "盈亏", "last_check_time": "最近检查时间",
    "notify_type": "通知类型", "notify_target": "通知目标", "subject": "主题", "error_msg": "错误信息",
    "sent_at": "发送时间", "log_level": "日志级别", "module": "模块", "details": "详情",
    "period": "周期", "stock_info": "股票信息", "agents_results": "Agent结果",
    "discussion_result": "讨论结果", "final_decision": "最终决策", "last_checked": "最近检查时间",
    "quant_enabled": "是否启用量化", "quant_config": "量化配置", "stock_id": "股票ID",
    "type": "类型", "triggered_at": "触发时间", "sent": "是否已发送", "timestamp": "时间戳",
    "multiple": "倍数", "decimal": "小数位", "last_price": "最新价", "edit_date": "编辑时间",
    "in_date": "入库时间", "exchange": "交易所", "open": "开盘价", "high": "最高价",
    "low": "最低价", "close": "收盘价", "ts": "时间戳",
}
