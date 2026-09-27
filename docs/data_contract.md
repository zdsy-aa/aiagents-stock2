# 数据契约:统一字段约定与指标映射(Phase5 Task5.6)

本文件固化 Phase 5 数据层的统一字段约定,并交付 Phase 4 遗留的
**registry 输出名 ↔ 面板列名映射表**(Phase 5 计划前置项 P5-5,Task 4.5 遗留)。

- 生成依据(映射表):Phase 2 指标注册表 `indicators/registry.json` + 确认面板
  列名清单(`backtest.dataio.confirm_panel_columns()`,读 `data/profit_mining/
  confirm_panel.npz` 的 bool_cols/cont_cols)+ 列名定义源 `data/profit_mining/
  features.py` + Phase 4 Task4.5 结论(bridge.py 引用 task-4.5-report.md:
  「输出名与确认面板列名的映射核对:两套命名口径不一致,映射表留 Phase 5
  数据层统一时解决」)。
- 日期:2026-09-27(Phase5 Task5.6)。

---

## 1. 统一字段约定

### 1.1 代码与交易所

- **代码:6 位数字字符串,前导零保留**(如 `"000001"`、`"600000"`),
  不携带交易所后缀。
- **交易所**:需要区分市场时用独立列「交易所」(取值 `SH`/`SZ`/`BJ`),
  或代码后缀写法 `600000.SH` / `000001.SZ` / `8xxxxx.BJ`(tq 脚本口径)。
- 面板(`股票代码`/`代码`)、信号追踪表(`code`)、选股输出(`代码`)统一
  6 位纯数字;跨模块比较前先做字符串归一(去空格/去后缀)。
- 指数代码:上证指数 = `000001.SH`(tq 脚本 `999999.SH` 同标的)/
  akshare sina 记法 `sh000001`。

### 1.2 时间

- **日期统一 `YYYYMMDD` 字符串**(如 `"20250101"`),面板「信号日期」为
  同语义的 int32,消费方以字符串比较。
- 日内时间:`HH:MM:SS`。
- 时间戳(落库/编译):ISO8601 本地时间,如 `2026-09-27T09:06:18`
  (registry `compiled_at` 口径)。
- 交易日历以交易所为准;非交易日取数返回空/降级时必须记录 notes
  (全局约束:失败不静默)。

### 1.3 复权

- **统一不复权(未复权价)**。依据:
  - `tq_confirm_top10.py` 取数 `dividend_type="none"`;
  - profit_mining 面板日K = `akshare_gateway` 本地K线(未复权);
  - `automation.market_env` 指数日K = 新浪源(不复权)/本地
    `index_sh000001.csv`(不复权)。
- 任何前复权数据**必须显式标注**:列名或文件名加 `_qfq` 后缀,并在
  文档/注释注明复权基准日;禁止混用复权口径。

### 1.4 字段名

| 场景 | 约定 | 示例 |
|---|---|---|
| 中文业务列(面板/选股/追踪) | 中文名 | 代码、名称、日期、股票代码、信号日期、是否盈利、区间涨跌幅、是否下跌、年 |
| 归一化日K英文列 | Open/High/Low/Close/Volume | profit_mining 的 `_RENAME` 口径(confirm_panel.py) |
| 面板布尔信号列 | 中文描述名,168 列 | 六脉6红首发、大盘空头、放量 |
| 面板连续特征列 | 中文名,17 列 | 量比、相对强弱、六脉红灯数、主力强度 |
| registry 输出名 | Phase2 `compute` 输出名(中文) | 六脉6红首发、涨停、DIFF |
| 市场环境快照键 | 英文 snake_case(automation.market_env) | index_close、limit_up_count、sentiment |

- **主键约定**:买点/确认面板 `(股票代码, 信号日期)`;信号追踪表
  `UNIQUE(combo, code, date)`;分析记录去重键 `(代码, analysis_id)`
  (ai_trace Task5.3 口径)。
- sentiment 枚举:`亢奋`/`冰点`/`中性`/`None`(缺失);trend 枚举:
  `多头`/`空头`/`震荡`/`None`。

---

## 2. registry 输出名 ↔ 面板列名映射表(P5-5)

### 2.1 映射关系分类

| 关系 | 含义 |
|---|---|
| 一致 | 名称完全相同,语义同源(registry 与 profit_mining 均移植自同一 TDX 公式库) |
| 近似 | 语义同源但命名不同,消费方须按本表对照改名 |
| 无对应 | 面板无该列(未落库/中间变量/绘图辅助线/unsupported) |

面板列名全量清单:`backtest.dataio.confirm_panel_columns()` → 168 布尔列
+ 17 连续列 + 是否盈利/区间涨跌幅/是否下跌/股票代码/信号日期/年。

### 2.2 六脉神剑V5(registry `partial=false`,source=03_资金流向体系/六脉神剑V5.txt)

| registry 输出名 | 面板列名 | 关系 | 说明 |
|---|---|---|---|
| MACD多 | (无) | 无对应 | 面板 MACD 布尔为经典 MACD(12/26/9)五列:MACD_DIF大于0/MACD金叉态/MACD柱递增/MACD零轴上金叉/MACD底背离;六脉内部 MACD多 未单独落列,仅在红灯计数中体现 |
| KDJ多 | (无) | 无对应 | 面板 KDJ 布尔:KDJ金叉态/KDJ_J超卖/KDJ低位金叉/KDJ_D小于30 |
| RSI多 | (无) | 无对应 | 面板 RSI 布尔:RSI6大于50/RSI金叉/RSI6超卖/RSI底背离 |
| LWR多 | (无) | 无对应 | 面板无 LWR 列 |
| BBI多 | (无) | 无对应 | 面板 BBI 布尔:BBI站上5_10_20_40/BBI上穿5_10_20_40 |
| MTM多 | (无) | 无对应 | 面板无 MTM 列 |
| 六脉得分 | (无) | 无对应 | 面板未落(六脉信号库 110 列之外的合成值) |
| 六脉红灯 | **六脉红灯数** | 近似 | registry 为 0~6 红灯计数;面板连续列「六脉红灯数」(features.py:485)同为六分量(MACD/KDJ/RSI/LWR/BBI/MTM)之和,语义一致、命名不同 |
| 六脉6红首发 | **六脉6红首发** | 一致 | 面板 bool_cols[53](features.py:260);**bridge.registry_to_spec("六脉神剑V5") 选中的 spec col 即此列**,回测可直接对面板求值 |
| 六脉5红首发 | **六脉5红首发** | 一致 | 面板 bool_cols[54](features.py:261) |
| 得分曲线 | (无) | 无对应 | 绘图辅助线,面板未落 |
| 均线 | (无) | 无对应 | 同上 |
| 强势线 | (无) | 无对应 | 同上 |
| 中轴 | (无) | 无对应 | 同上 |
| 弱势线 | (无) | 无对应 | 同上 |

面板相关衍生列:六脉红灯大于5(bool_cols[51])/六脉红灯大于6(bool_cols[52])
为红灯计数的阈值布尔,registry 无同名输出。

### 2.3 核心_基础V3(registry `partial=true`,source=00_公共核心模块/核心_基础V3.txt)

| registry 输出名 | 面板列名 | 关系 | 说明 |
|---|---|---|---|
| 涨停 | (无) | 无对应 | 面板无基础涨停列(有衍生:二连板/二次涨停/妖股启动);面板内涨停定义见 features.py:tdx_extra_features |
| 跌停 | (无) | 无对应 | 同上 |
| 真一字板 | (无) | 无对应 | 同上(tdx_extra_features 内部变量) |
| 涨停幅度 | (无) | 无对应 | capitalflow_features 内为常数简化(0.10) |
| 放量 | **放量** | 一致 | 面板 bool_cols[17](features.py:89);实现阈值不同(面板 V>MA5 且 V>MA20;registry V>VOL_MA_S),消费方以面板实现为准 |
| 缩量 | **缩量** | 一致 | 面板 bool_cols[18](features.py:90) |
| 量比 | **量比** | 一致 | 面板连续列 cont_cols[0](features.py:91);阈值布尔见 量比大于1/1_3/2/1_5/2_5/3 |
| 主力参与 | **主力参与** | 一致 | 面板 bool_cols[80](capitalflow_features:513,定义= (振幅>大单阈值)&放量,与 registry 同源) |
| 主力强度 | **主力强度** | 一致 | 面板连续列 cont_cols[8](capitalflow_features:531);阈值布尔见 主力强度高(bool_cols[154]) |
| K_MA5/K_MA10/K_MA20/K_MA60/K_MA120 | (无) | 无对应 | 面板均线布尔为斐波口径 站上MA5/13/34/55/89/144/233 与 MA金叉5_10 等网格列,无 K_MA* 列 |
| 净资金流/净资金累计/净资金均线/大单阈值/主力净方向/主力累计/流动规模 | (无) | 无对应 | 面板资金布尔:资金金叉/资金死叉/主力净流入/机构净买;连续列:资金强度 |
| 当前波幅/长期波幅/适应系数/N/M/VS/VL/修正量/VOL_MA_S/VOL_MA_L/价涨/价跌/振幅/多方占比/空方占比/强势上攻/加速下跌/上涨乏力/下跌衰竭 | (无) | 无对应 | registry 输出(TDX 公式中间量),面板未落(面板相关布尔为 价涨量增/价涨量缩/多空共振 等不同口径列) |

> 注:registry `unsupported` 5 名(获利盘/活跃筹码/套牢盘/筹码集中/筹码锁定)
> **不属于 outputs**,不参与映射统计;WINNER 未实现(见
> indicators/registry.json),面板亦无筹码列(与 Task5.5 筹码选型
> 「当前不可用」结论一致)。

### 2.4 MACD(registry `source=builtin:MACD`)

| registry 输出名 | 面板列名 | 关系 | 说明 |
|---|---|---|---|
| DIFF | (无) | 无对应 | 面板无 MACD 数值列(连续列「MACD背驰强度」为背驰度量,非 MACD 柱) |
| DEA | (无) | 无对应 | 同上 |
| MACD | (无) | 无对应 | 同上 |

### 2.5 映射汇总

registry 3 条目合计 **58 个输出名**(六脉神剑V5 15 + 核心_基础V3 40 +
MACD 3,程序化核对 indicators/registry.json,2026-09-27):

| 关系 | 数量 | 输出名 |
|---|---|---|
| 一致 | 7 | 六脉6红首发、六脉5红首发、放量、缩量、量比、主力参与、主力强度 |
| 近似 | 1 | 六脉红灯(面板列名:六脉红灯数) |
| 无对应 | 50 | 其余全部(面板未落/unsupported 同源未实现/绘图辅助线) |

registry `unsupported` 5 名(2.3 注)不属于 outputs,不计入上表。
本节表逐行覆盖全部 58 个输出名,无遗漏、无多余(以 registry.json 为准)。

### 2.6 回测桥接口径说明

- `interfaces.bridge.registry_to_spec(name)` 的 spec col 用 **registry 输出名**;
  当前 registry 中可产出 spec 的条目(六脉神剑V5 → 六脉6红首发)其输出名与
  面板列名**一致**,ComboSpec 可直接对确认面板求值。
- 未来若 bridge 选中「近似」关系的输出名(如某条目首个布尔输出是
  六脉红灯),消费方须先按本表映射到面板列名再求值。

---

## 3. 市场环境快照契约(automation.market_env)

`market_snapshot()` 返回键集(取值与约定见模块 docstring):

```text
date(YYYYMMDD) / index_close / ma20 / ma60 / trend(多头|空头|震荡)
/ limit_up_count / limit_down_count / limit_up_height / sentiment(亢奋|冰点|中性)
/ notes([str])
```

- trend 口径 = tq_confirm_top10._get_index_state:close<MA20 且 MA20<MA60
  空头、close>MA20 且 MA20>MA60 多头、否则震荡;日K不足 60 根不判趋势。
- sentiment 规则:涨停数>100 且连板高度≥5 → 亢奋;涨停数<30 → 冰点;
  否则中性;任一输入缺失 → None。
- 任一字段取不到标 None 并记 notes(全局约束:失败不静默、可重试)。
