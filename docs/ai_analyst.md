# AI 分析师机制说明(ai_analyst.md)

> 盘点日期:2026-09-26(Task 1.2,全部结论基于当日工作树代码实读,行号以当日为准)
> 代码基线:main 分支工作树 — `ai_agents.py`、`deepseek_client.py`、`views/analysis_runner.py`、`stock_analysis_engine.py`、`stock_data.py` 及各数据取数模块
> 上游:思维导图「信息获取 · 当前项目 AI Stock 中存在的分析师进行分析」4 问,与「AI可验证性」5 项
> 阅读约定:每项结论标注代码出处(文件:行号);与旧文档(如 `docs/分析师团队选择功能说明.md`)描述不一致处,以本文档实读代码为准(旧文档部分数据源描述已过时)

## 结论摘要(4 问)

| 问题 | 一句话答案 | 关键出处 |
|---|---|---|
| 1. 分析师怎么分析? | 每个「分析师」是 `StockAnalysisAgents` 的一个方法:拼 prompt(3 个来自 `deepseek_client.py` 模板 + 2 个内联)→ 调 DeepSeek API → 返回 `{角色, 报告, 关注领域, 时间}`;5 个分析师 6 线程并行 | `ai_agents.py:17-151`、`deepseek_client.py:26-49` |
| 2. 根据什么数据? | 7 类输入:行情(基本信息+K线)、规则指标、财务、季报、资金流向、市场情绪、风险;新闻已取数但**未接入任何智能体**;行业**未接入** | `stock_data.py:24/39/545/611/854`、`views/analysis_runner.py:272-411` |
| 3. 分析流程? | 按勾选门控取数 → 并行多智能体 → 首席分析师综合讨论 → 投资决策专家输出 JSON 决策 → 落库 | `views/analysis_runner.py:260-494`、`stock_analysis_engine.py:18-137` |
| 4. 哪些规则/哪些 AI? | 规则=指标计算、ARBR 解读、市场路由/数据源切换、风险数据格式化、JSON 提取;AI=DeepSeek 调用与 prompt 模板、5 个分析师+首席+决策专家角色 | `stock_data.py:545-609`、`deepseek_client.py:51-160`、`ai_agents.py:65-107` |

## 一、入口与调用链

- 页面入口:`app.py:57-61` 路由失败时渲染首页 `views/analysis_home.py:17`(render_analysis_home)
- 分析师勾选 UI:`views/analysis_home.py:91-106`(6 个复选框,默认全选),写入 session_state `:129-134`
- 单股分析:`views/analysis_home.py:164` → `views/analysis_runner.py:260`(run_stock_analysis,内联编排)
- 批量分析:`views/analysis_home.py:200` → `views/analysis_runner.py:129`(run_batch_analysis)→ 每只票走 `:75`(analyze_single_stock_for_batch)→ 委托 `stock_analysis_engine.py:18`(run_full_analysis,纯业务编排,与单股同源)
- 分时分析:`views/analysis_views.py:370-410`(display_intraday_analysis,直接调 run_full_analysis,仅技术面)
- 单股/批量两路径的取数顺序与多智能体调用一致;差别在 UI 渲染与批量线程池(见「三、分析流程」)

## 二、问 1:分析师怎么分析?

### 2.1 分析师集合(`ai_agents.py:10-116`)

| 分析师 | 方法(行号) | prompt 来源 | 输出结构 |
|---|---|---|---|
| 技术分析师 | `technical_analyst_agent` `ai_agents.py:17-27` | `deepseek_client.py:51` technical_analysis | agent_name/agent_role/analysis/focus_areas/timestamp |
| 基本面分析师 | `fundamental_analyst_agent` `ai_agents.py:29-40` | `deepseek_client.py:65` fundamental_analysis | 同上 + quarterly_data 原样嵌入(`:38`) |
| 资金面分析师 | `fund_flow_analyst_agent` `ai_agents.py:42-53` | `deepseek_client.py:80` fund_flow_analysis | 同上 + fund_flow_data 原样嵌入(`:51`) |
| 风险管理师 | `risk_management_agent` `ai_agents.py:55-85` | **内联 prompt** `ai_agents.py:65-71` | 同上 + risk_data 原样嵌入(`:83`) |
| 市场情绪分析师 | `market_sentiment_agent` `ai_agents.py:87-116` | **内联 prompt** `ai_agents.py:97-102` | 同上 + sentiment_data 原样嵌入(`:114`) |
| 新闻分析师 | **不存在** | 无 | `ai_agents.py:143` 注释:「news_data 智能体逻辑若有需要可在此扩展」 |

每个分析师的执行步骤:
1. 构造 prompt:3 个分析师复用 `deepseek_client.py` 的模板方法;风险/情绪 2 个在 `ai_agents.py` 内联(若数据取数成功,先经 `format_risk_data_for_ai`(`risk_data_fetcher.py:337`)或 `format_sentiment_data_for_ai`(`market_sentiment_data.py:664`)格式化为文本再插入,见 `ai_agents.py:60-63`、`92-95`)
2. 调 DeepSeek:`DeepSeekClient.call_api`(`deepseek_client.py:26-49`,OpenAI SDK 客户端 `:24`;重试 3 次、指数退避 `:44`、单次超时 60s `:37`、默认 temperature=0.7)
3. 返回统一结构 dict,附 `timestamp`(`ai_agents.py:21-27` 等)

### 2.2 并行与容错(`ai_agents.py:118-151`)

- `run_multi_agent_analysis` 用 `ThreadPoolExecutor(max_workers=6)` 并行提交勾选的分析师(`:132-142`)
- 单个分析师抛异常不拖垮整体:记录 `{"error":..., "analysis": "分析失败: ..."}` 继续(`:145-150`)
- 勾选字典默认:`ai_agents.py:124-128`(6 项全 True)

### 2.3 团队讨论与最终决策

- 综合讨论:`ai_agents.py:153-163` 收集 5 份报告 → `deepseek_client.py:95-123`(system 角色「首席投资分析师」`:120`,max_tokens=8000)
- 最终决策:`deepseek_client.py:125-160`(system 角色「投资决策专家」`:135`,temperature=0.3 `:138`,要求 JSON 字段 `rating/target_price/stop_loss/logic` `:132`;`extract_json` `:141-151` 取首个 `{` 到末个 `}` 解析,失败兜底返回 `{"decision_text": ...}` `:157`)
- 单股路径调用点:`views/analysis_runner.py:449`(讨论)、`:457`(决策);批量路径:`stock_analysis_engine.py:107`、`:110-112`

## 三、问 2:根据什么数据?(输入清单)

思维导图要求 5 类(行情/指标/新闻/资金/行业),实读代码共 7 类已接入 + 新闻已取数未接入 + 行业未接入:

| 输入类别 | 取数函数(出处) | 数据源 | 门控 | 消费者 |
|---|---|---|---|---|
| 行情·基本信息 | `StockDataFetcher.get_stock_info` `stock_data.py:24`(A股 `:74`,港股 `:249`,美股 `:335`) | akshare `stock_individual_info_em`(`:97`)+ data_source_manager(`:91`)+ tushare 兜底(`:130-145`) | 无 | 所有分析师(stock_info 注入每个 prompt) |
| 行情·历史K线 | `get_stock_data` `stock_data.py:39`(A股 `:426`,前复权 `adjust='qfq'` `:441-446`);分时 `get_minute_data` `:474` | data_source_manager(akshare/tushare 自动切换);分时走 akshare_gateway(`:477-478`) | 无(纯技术面/分时模式改用分钟线,`stock_analysis_engine.py:41-44`) | 技术分析师(原始 df 传入 `technical_analyst_agent`,实际 prompt 未注入) |
| 指标(规则算) | `calculate_technical_indicators` `stock_data.py:545-583` + `get_latest_indicators` `:585-609`(最新一行 13 项) | 本地 pandas/ta 库计算(非外部数据源) | 无 | 技术/资金/风险分析师(`indicators` 注入 prompt) |
| 财务 | `get_financial_data` `stock_data.py:611`(A股 `:623-711`;港股 `:712`;美股 `:780`) | akshare(资产负债表/利润表/现金流量表/财务比率) | 单股路径无门控、恒取(`views/analysis_runner.py:293`);批量/分时路径按基本面勾选门控(`stock_analysis_engine.py:51-53`) | 基本面分析师(仅勾选时消费) |
| 季报 | `QuarterlyReportDataFetcher.get_quarterly_reports` `quarterly_report_data.py:45`(最近 8 期 `:41`) | akshare | 基本面勾选 + A股(`views/analysis_runner.py:296-317`) | 基本面分析师 |
| 资金 | `FundFlowAkshareDataFetcher.get_fund_flow_data` `fund_flow_akshare.py:46`(最近 30 交易日 `:42`) | akshare 个股资金流向 | 资金面勾选 + A股(`views/analysis_runner.py:324-342`) | 资金面分析师 |
| 情绪 | `MarketSentimentDataFetcher.get_market_sentiment_data` `market_sentiment_data.py:45` | ARBR(26 周期,本地算 `:126`)、换手率 `:334`、大盘指数 `:417`、涨跌停 `:503`、融资融券 `:552`、恐惧贪婪指数 `:608` | 情绪勾选 + A股(`views/analysis_runner.py:344-361`) | 市场情绪分析师 |
| 风险 | `RiskDataFetcher.get_risk_data` `risk_data_fetcher.py:32`(限售解禁 `:100`、大股东减持 `:163`、重要事件 `:226`;包装入口 `stock_data.py:854`) | pywencai 问财(`risk_data_fetcher.py:114/177/240`) | 风险勾选 + A股(`views/analysis_runner.py:383-411`) | 风险管理师 |
| 新闻 | `QStockNewsDataFetcher.get_stock_news` `qstock_news_data.py:45`(最多 30 条 `:41`) | 东方财富 `ak.stock_news_em`(`qstock_news_data.py:104`) | 新闻勾选 + A股(`views/analysis_runner.py:363-381`) | **无消费者**——取数后未进入任何 prompt;`format_news_for_ai`(`qstock_news_data.py:219`)在分析链路无调用方 |
| 行业 | **未接入** | 无取数函数 | — | 仅 prompt 文案提及「行业地位」维度(`deepseek_client.py:72`)、角色描述「行业研究」(`ai_agents.py:35`),无行业数据投喂;`industry_chain_data.py` 不在分析链路 import |

说明:
- 取数门控统一为「对应分析师勾选 + 是否 A 股」,单项失败仅 UI 告警不中断整体(`views/analysis_runner.py:297/315/340/359/379/409`;引擎侧同口径 `stock_analysis_engine.py:50-97`)
- 指标是规则计算结果,不是外部数据源(见「五、问 4」)

## 四、问 3:分析流程?(步骤顺序)

单股路径(`views/analysis_runner.py:260-494`,run_stock_analysis):

1. **数据获取**(按勾选门控,顺序执行)
   - 行情 + 指标:`:272`(get_stock_data,`views/analysis_views.py:19-31`)
   - 财务:`:293`;季报:`:299-317`;资金流向:`:324-342`;市场情绪:`:344-361`;新闻:`:363-381`;风险:`:383-411`
2. **初始化 AI 团队**:`:414-418`(`StockAnalysisAgents(model=selected_model)`)
3. **多智能体并行分析**:`:435-441`(技术/基本面/资金/风险/情绪并行;新闻无智能体)
4. **团队讨论**:`:448-450`(comprehensive_discussion)
5. **最终决策**:`:456-457`(final_decision)
6. **保存到数据库**:`:471-482`(db.save_analysis,失败仅告警)

批量路径(`views/analysis_runner.py:129-258`):外层线程池 `ThreadPoolExecutor(max_workers=3)`(`:180`,避免 API 限流);每只票经 `analyze_single_stock_for_batch`(`:75-124`)委托 `stock_analysis_engine.py:18-137`,步骤顺序同单股:基础信息 `:36` → 技术(行情+指标)`:41-48` → 基本面+季报 `:51-62` → 资金 `:65-71` → 情绪 `:74-80` → 新闻 `:83-89` → 风险 `:92-97` → 多智能体 `:100-104` → 讨论 `:107` → 决策 `:110-112` → 落库 `:115-127`(落库失败不影响返回)。

分时路径(`views/analysis_views.py:370-410`):仅技术面,`freq=5min/30min` 分钟线(`:390-395`),跳过基本面/资金/新闻/情绪。

## 五、问 4:哪些是规则 / 哪些是 AI 推理?

### 5.1 规则(确定性代码,不依赖 AI)

| 规则 | 出处 |
|---|---|
| 技术指标计算:MA5/10/20/60、RSI14、MACD、BOLL、KDJ(K/D)、量比(ta 库公式,写死参数) | `stock_data.py:545-583` |
| 最新指标值提取(取最新一行 13 项) | `stock_data.py:585-609` |
| ARBR 指标计算与解读、买卖信号生成 | `market_sentiment_data.py:126`(计算)、`:254`(解读)、`:295`(信号) |
| 市场路由:A股/港股/美股代码判定与分发 | `stock_data.py:51` 等 |
| 数据源自动切换:akshare/tushare/data_source_manager | `stock_data.py:22`、`:91`、`:441` |
| 风险数据格式化(结构化 dict → AI 文本) | `risk_data_fetcher.py:337` |
| 情绪数据格式化 | `market_sentiment_data.py:664` |
| 股票代码列表解析 | `views/analysis_runner.py:32-73` |
| 分析师启用门控与线程编排、失败隔离 | `ai_agents.py:124-150` |
| 决策 JSON 提取(文本 → dict) | `deepseek_client.py:141-151` |

### 5.2 AI 推理(DeepSeek 调用)

| AI 环节 | 出处 |
|---|---|
| 技术面分析模板 | `deepseek_client.py:51-63` |
| 基本面分析模板 | `deepseek_client.py:65-78` |
| 资金面分析模板 | `deepseek_client.py:80-93` |
| 风险评估内联 prompt | `ai_agents.py:65-76` |
| 市场情绪内联 prompt | `ai_agents.py:97-107` |
| 综合讨论(首席分析师) | `deepseek_client.py:95-123` |
| 最终投资决策(投资决策专家,JSON 输出) | `deepseek_client.py:125-160` |
| 团队角色设定(system 文案与 agent_role/focus_areas) | `deepseek_client.py:60/75/90/120/135`;`ai_agents.py:22-26/34-39/47-52/79-84/110-115` |

### 5.3 边界

AI 只消费规则产出的结构化数据做推理与总结;指标计算、数据路由、格式化等确定性环节全部由代码完成,不经过 AI。与主路线图全局约束一致:「程序化分析为主,AI 作为分析与总结辅助,**不替代原始数据和规则**」。

## 六、Prompt 模板:版本与要点

### 6.1 版本现状:无显式版本号

- `deepseek_client.py` 与 `ai_agents.py` 中的 prompt 全部为 f-string 内联模板,**没有** VERSION/PROMPT_VERSION 常量或版本标记(2026-09-26 全文检索 `V[0-9]`/「版本」/`version` 无命中)
- 仅有非正式变更痕迹(代码注释中的整改记录):`deepseek_client.py:97`「P2 整改四: 完整传递报告」、`deepseek_client.py:127`「P2 整改十四: 优化 JSON 提取」、`ai_agents.py:56/88`「P2 整改十三: 增强 Prompt」——只能推断历史整改方向,无法追溯具体 prompt 内容变更

### 6.2 模板要点(7 个)

| 模板 | 出处 | system 角色 | 用户输入变量 | max_tokens | 输出要求 |
|---|---|---|---|---|---|
| 技术面分析 | `deepseek_client.py:51-63` | 资深技术分析师(`:60`) | stock_info、indicators | 3000 | 趋势/动量/波动率/支撑阻力 |
| 基本面分析 | `deepseek_client.py:65-78` | 资深基本面分析师(`:75`) | stock_info、financial_data、quarterly_data | 4000 | 盈利/偿债/营运/成长/行业地位 |
| 资金面分析 | `deepseek_client.py:80-93` | 资深资金面分析师(`:90`) | stock_info、indicators、fund_flow_data | 3000 | 主力动向/净流入及对股价影响 |
| 风险评估 | `ai_agents.py:65-76` | 资深风险管理专家(`:73`) | stock_info、indicators、risk_data_text(问财) | 6000 | 退市/造假/质押/违规担保/诉讼扫描 + 风险等级 |
| 市场情绪 | `ai_agents.py:97-107` | 资深市场情绪分析师(`:104`) | stock_info、sentiment_data_text | 4000 | ARBR/多空/关注度/舆论 → 恐慌/冷静/贪婪 |
| 综合讨论 | `deepseek_client.py:95-123` | 首席投资分析师(`:120`) | 5 份分析师报告 + stock_info | 8000 | 综合投资逻辑 |
| 最终决策 | `deepseek_client.py:125-160` | 投资决策专家(`:135`) | discussion_result、stock_info | 4000 | JSON:rating/target_price/stop_loss/logic;temperature=0.3(`:138`) |

### 6.3 调用参数与模型

- 统一入口 `call_api`(`deepseek_client.py:26-49`):temperature 默认 0.7(仅最终决策 0.3),max_retries=3,指数退避,超时 60s
- 模型名:`config.py:12` `DEFAULT_MODEL_NAME`(env 可覆盖);当前 `.env` 配置为 `deepseek-v4-pro`(2026-09-26 读取);`model_config.py` 预置 17 个模型选项,但当前代码(views/ 与 app.py)无任何引用——模型选择 UI 未接入,实际恒用默认模型

## 七、AI 可验证性现状(思维导图 5 项对照)

| 思维导图要求 | 现状 | 出处 |
|---|---|---|
| 保存AI输出 | ✅ 已保存:各分析师报告(agents_results)、团队讨论(discussion_result)、最终决策(final_decision)整体 JSON 落库 | `database.py:15-28`(analysis_records 表)、`:42-45` |
| 保存时间 | ✅ 已保存:analysis_date + created_at 双时间戳 | `database.py:38-39` |
| 保存AI输入 | 🟡 部分:stock_info(基础信息)落库;风险/情绪/资金/季报原始数据随 agents_results 嵌入(`ai_agents.py:38/51/83/114`);但 **indicators 指标值、K线快照、财务数据原文、prompt 原文不落库**(save_analysis 无对应入参,`database.py:32-51`) | `database.py:32-51` |
| 保存模型/提示词版本 | ❌ 未保存:表结构无 model/prompt_version 字段;save_analysis 签名无 model 参数;prompt 本身亦无版本号 | `database.py:15-28`、`:32`;见 6.1 |
| 与实际结果对比 | ❌ 未做:全库无分析结论 vs 实际走势的对比/复盘表 | — |

## 八、待办(指向后续 Phase)

1. **AI 可验证性落地(主待办)** → Phase 4 Task 4.4「AI 可验证性落地(保存 AI 输入/输出/时间/模型与提示词版本,与实际结果对比表)」:建议扩展 `analysis_records` 表加 `model`/`prompt_version` 字段、save_analysis 记录调用参数与 prompt 原文快照,并给 prompt 模板引入显式版本号(现状见 6.1)
2. **新闻输入接入** → Phase 1.5 产出 `news_fetch.py`(每日新闻,供 AI 输入)+ 新增新闻分析师智能体(`ai_agents.py:143` 已留扩展位);现有新闻取数结果暂被丢弃
3. **行业输入接入** → Phase 4.1 `analyze_stock(code)` 统一接口(聚合趋势/K线结构/量/筹码/资金/行业上下游/新闻,行业上下游读 tdxgp 数据)
4. **(可选)模型选择 UI 重接** → `model_config.py` 预置模型列表当前无调用方,实际恒用 `.env` 默认模型
