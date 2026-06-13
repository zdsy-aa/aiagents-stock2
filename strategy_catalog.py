# strategy_catalog.py —— 「当前策略」页的事实来源：四类全部策略的脚本名+中文解释+关键可调参数。
# 只读文档；改某条策略时顺手维护这里。关键参数=(参数名, 所在文件, 现值/说明)，指明"改哪"。
# 实时字段：None / "plans"(引stable_ui.PLANS) / "star"(读star_thresholds.json) /
#           "watchlist"(读每日清单) / "commonality"(读共性挖掘最近产物)。

CATEGORIES = ["选股", "买入卖出", "测试盈利", "找共同点"]

CATALOG = [
    # ───────────── 选股策略 · 量化研究栈 ─────────────
    {
        "类别": "选股", "名称": "🌀 缠论选股",
        "脚本": ["chanlun_selector.py", "chanlun_batch.py", "chanlun_engine.py", "chanlun_ui.py"],
        "解释": "多级别缠论买点筛选：日线本级别 + 30分钟次级别确认。读 chanlun_signals.db 最新批次"
                "（每日收盘后 chanlun_batch 预计算），识别 1买/2买/3买，给买入参考价、止损位与缠论卖点。",
        "关键参数": [
            ("买点类型判定", "chanlun_engine.py", "笔/线段/中枢→1买/2买/3买逻辑"),
            ("次级别确认级别", "chanlun_engine.py", "30分钟"),
            ("批量范围与调度", "chanlun_batch.py", "扫描股票池、近N交易日窗口、每日20:00"),
        ],
        "实时": None,
    },
    {
        "类别": "选股", "名称": "🔱 六脉神剑",
        "脚本": ["liumai_selector.py", "liumai_engine.py", "liumai_batch.py"],
        "解释": "六维指标(MACD/KDJ/RSI/LWR/BBI/MTM)多头共振，选最新多头数≥5(5红以上)。读 liumai_signals.db 最新批次。",
        "关键参数": [
            ("多头数门槛 min_bull", "liumai_selector.py get_picks", "默认 5(5红以上)"),
            ("六维多空判定", "liumai_engine.py", "各维指标公式与红绿灯"),
        ],
        "实时": None,
    },
    {
        "类别": "选股", "名称": "🔗 缠论×六脉",
        "脚本": ["combo_selector.py", "combo_batch.py", "combo_signal_db.py"],
        "解释": "组合策略——缠论买点 ±3 交易日内出现六脉神剑 5红以上。读 combo_signals.db，取两套各自优势的交集。",
        "关键参数": [
            ("时间窗 ±N交易日", "combo_batch.py", "默认 ±3"),
            ("六脉红灯门槛", "combo_batch.py", "≥5红"),
        ],
        "实时": None,
    },
    {
        "类别": "选股", "名称": "🛡️ 稳定选股",
        "脚本": ["stable_ui.py", "daily_watchlist.py"],
        "解释": "经 walk-forward 样本外验证的稳健买卖规则(抄底/抢筹/过热顶/强势顶)，融入全量信号库共性结论。"
                "每日20:00缠论批量后自动生成当日清单；买卖方案详见『买入卖出』类。",
        "关键参数": [
            ("买卖方案文本", "stable_ui.py PLANS/NOTES", "三方案+纪律"),
            ("选股规则 A∪B", "daily_watchlist.py", "A 极限抄底+量比≥1.3 / B 尖刺金叉"),
        ],
        "实时": "watchlist",
    },
    # ───────────── 选股策略 · AI智能体栈 ─────────────
    {
        "类别": "选股", "名称": "💰 主力选股",
        "脚本": ["main_force_selector.py", "main_force_ui.py"],
        "解释": "用 pywencai(同花顺问财)取主力资金净流入前100名，再按市值/资金等做智能筛选。",
        "关键参数": [
            ("市值区间", "main_force_selector.py get_main_force_stocks", "min_market_cap / max_market_cap"),
            ("回溯天数", "main_force_selector.py get_main_force_stocks", "days_ago / start_date"),
        ],
        "实时": None,
    },
    {
        "类别": "选股", "名称": "🐂 低价擒牛",
        "脚本": ["low_price_bull_strategy.py", "low_price_bull_selector.py"],
        "解释": "低价高成长股，基于 MA 均线择时的量化买卖策略。",
        "关键参数": [
            ("最大持股数 max_stocks", "low_price_bull_strategy.py", "默认 4"),
            ("个股最大仓位 max_position_per_stock", "low_price_bull_strategy.py", "0.4(4成)"),
            ("持股周期 holding_period", "low_price_bull_strategy.py", "5 天"),
            ("单日最大买入 max_daily_buy", "low_price_bull_strategy.py", "2"),
        ],
        "实时": None,
    },
    {
        "类别": "选股", "名称": "📊 小市值策略",
        "脚本": ["small_cap_selector.py", "small_cap_ui.py"],
        "解释": "pywencai 问财筛选：总市值≤50亿、营收增速≥10%、净利增速≥100%、沪深A股、非ST/非创业板/非科创板，按总市值由小到大。",
        "关键参数": [
            ("筛选 query", "small_cap_selector.py get_small_cap_stocks", "市值/增速门槛"),
            ("返回数 top_n", "small_cap_selector.py get_small_cap_stocks", "默认 5"),
        ],
        "实时": None,
    },
    {
        "类别": "选股", "名称": "📈 净利增长",
        "脚本": ["profit_growth_selector.py", "profit_growth_ui.py"],
        "解释": "pywencai 问财：净利润同比增速≥10%、深圳A股、非科创/非创业、非ST，按成交额由小到大。",
        "关键参数": [
            ("筛选 query", "profit_growth_selector.py get_profit_growth_stocks", "净利增速门槛/市场"),
            ("返回数 top_n", "profit_growth_selector.py get_profit_growth_stocks", "默认 5"),
        ],
        "实时": None,
    },
    {
        "类别": "选股", "名称": "💎 低估值策略",
        "脚本": ["value_stock_selector.py", "value_stock_strategy.py", "value_stock_ui.py"],
        "解释": "价值投资筛选——PE≤20、PB≤1.5、股息率≥1%、资产负债率≤30%、非ST/非科创/非创业，按流通市值由小到大；"
                "配套 RSI 超买 + 持股周期择时策略。",
        "关键参数": [
            ("选股 query", "value_stock_selector.py get_value_stocks", "PE/PB/股息/负债门槛"),
            ("择时参数", "value_stock_strategy.py", "holding_period=30 / rsi_overbought=70"),
        ],
        "实时": None,
    },
    {
        "类别": "选股", "名称": "🐉 智瞰龙虎(龙虎榜)",
        "脚本": ["longhubang_data.py", "longhubang_scoring.py", "longhubang_engine.py", "longhubang_agents.py"],
        "解释": "龙虎榜深度分析与 AI 评分：抓龙虎榜数据→多维评分→AI智能体解读生成报告。偏分析型而非纯量化选股。",
        "关键参数": [
            ("评分维度/权重", "longhubang_scoring.py", "席位/资金/连板等"),
            ("数据抓取", "longhubang_data.py", "龙虎榜数据源"),
        ],
        "实时": None,
    },
    # ───────────── 买入卖出策略 ─────────────
    {
        "类别": "买入卖出", "名称": "🛒 稳定选股买卖方案",
        "脚本": ["stable_ui.py"],
        "解释": "抄底(核心A：缠论买点+极限抄底+量比≥1.3+机构净买) / 抢筹(核心B：1买+尖刺金叉) / 稳定组合(A∪B)；"
                "卖点=过热顶(均线全多头/连板)或强势顶(相对强弱≥5+六脉红灯+MA20上行)/+25~30%移动止盈。均经样本外验证。",
        "关键参数": [
            ("三方案与买卖说明", "stable_ui.py PLANS", "买点/卖点/胜率口径"),
            ("纪律/适用条件", "stable_ui.py NOTES", "适用市场/反向过滤/仓位预期"),
        ],
        "实时": "plans",
    },
    {
        "类别": "买入卖出", "名称": "📉 卖点共性挖掘",
        "脚本": ["mine_sell.py"],
        "解释": "缠论卖点共同特征挖掘(复用 mine_combos 评分器)，标签=好卖点(卖后跌≥4%)，找最能预示该卖的信号组合；结论反哺稳定选股『强势顶』卖点。",
        "关键参数": [
            ("好卖点阈值", "mine_sell.py", "卖后跌≥4%"),
            ("卖点分组", "mine_sell.py", "全部/1卖/2卖/3卖"),
        ],
        "实时": None,
    },
    {
        "类别": "买入卖出", "名称": "🟢 每日清单·可入与止盈损",
        "脚本": ["daily_watchlist.py"],
        "解释": "工程化每日选股：对最近缠论买点应用稳定组合 A∪B 规则输出当日清单；含可入状态(可入/尾窗/已过窗/已涨过/已破止损/已止盈)、实时价判定与星级排序。",
        "关键参数": [
            ("入选规则", "daily_watchlist.py", "A∪B + 大盘SID≤2 + 剔除获利盘>70%"),
            ("可入/止盈损判定", "daily_watchlist.py", "价格类优先于窗口类"),
        ],
        "实时": "watchlist",
    },
    # ───────────── 测试盈利策略 ─────────────
    {
        "类别": "测试盈利", "名称": "⭐ 星级分档(样本外胜率)",
        "脚本": ["star_calibrate.py", "star_thresholds.json"],
        "解释": "全历史1买信号回测『合成分→样本外胜率』，给核心(5★)/精选两层各定固定星级阈值(诚实降档)，星级=样本外验证胜率差。产出 star_thresholds.json，纯标准库。",
        "关键参数": [
            ("胜率/大涨阈值", "star_thresholds.json win_thresh/bigrise_thresh", "4% / 10%"),
            ("训练-测试切分", "star_thresholds.json train_end/oos", "2023末 / 2024~2025.10"),
            ("特征权重与 cuts", "star_calibrate.py + json tiers", "各档星级阈值"),
        ],
        "实时": "star",
    },
    {
        "类别": "测试盈利", "名称": "🔁 滚动样本外检验",
        "脚本": ["walk_forward.py"],
        "解释": "训练段挖规则、测试段纯验证，量化样本内偏差；规则=L1/L2/L3 条件组合，训练段内胜率最高(满足支持度)→测试未来段，防过拟合。",
        "关键参数": [
            ("训练/测试最小支持", "walk_forward.py", "SUP_TRAIN=200 / SUP_TEST=30"),
            ("三联 TopK", "walk_forward.py", "TOPK_TRIPLE=16"),
        ],
        "实时": None,
    },
    # ───────────── 找共同点策略 ─────────────
    {
        "类别": "找共同点", "名称": "🔍 共性挖掘(方案A/B)",
        "脚本": ["mine_commonality.py"],
        "解释": "涨跌前期共性挖掘——逐股累加每个信号在 ±窗口 内的命中→覆盖率/提升度/精确度→报告；找盈利买卖点的共同特征(按提升度排序)。",
        "关键参数": [
            ("窗口 W / offset", "build_features.py / mine_commonality.py", "±2 窗口"),
            ("排序口径", "mine_commonality.py", "覆盖率/提升度/精确度"),
        ],
        "实时": "commonality",
    },
    {
        "类别": "找共同点", "名称": "🧩 信号组合挖掘",
        "脚本": ["mine_combos.py", "mine_combos_v2.py"],
        "解释": "在 signal_features.csv 上生成 L1单/L2两两/L3三联/L5 测试方案，向量化算覆盖率/提升度/胜率并排序出榜。",
        "关键参数": [
            ("盈利覆盖门槛 COVER_MIN", "mine_combos.py", "0.70"),
            ("进榜最小支持 SUPPORT_MIN", "mine_combos.py", "50"),
            ("三联 TopK", "mine_combos.py", "TOPK_TRIPLE=18"),
        ],
        "实时": None,
    },
    {
        "类别": "找共同点", "名称": "🏗️ 特征/信号库构建",
        "脚本": ["build_features.py", "build_features_v2.py", "features.py"],
        "解释": "逐股加载日K+大盘，对每信号 ±2 窗口算布尔特征→signal_features.csv(防泄漏)，是挖掘的输入。",
        "关键参数": [
            ("盈利标签阈值 WIN_THRESH", "build_features.py", "4.0%"),
            ("窗口偏移 OFFSET", "build_features.py", "±2"),
            ("原子信号定义", "features.py", "信号库集合"),
        ],
        "实时": None,
    },
    {
        "类别": "找共同点", "名称": "📐 分维度参数挖掘",
        "脚本": ["group_dims.py", "test_group_dims.py", "mine_regime.py", "surface_l3.py", "calibrate_buckets.py"],
        "解释": "按波动率/市值/行业/板块把样本分桶，找各子组起涨前 uplift 最强的信号(达标榜>50%共性)。已知结论：低波动起涨 lift 最强。",
        "关键参数": [
            ("分桶维度与 cuts", "group_dims.py / calibrate_buckets.py", "波动率/市值/行业/板块"),
            ("达标共性阈值", "mine_regime.py / 分维度脚本", ">50%"),
        ],
        "实时": None,
    },
]
