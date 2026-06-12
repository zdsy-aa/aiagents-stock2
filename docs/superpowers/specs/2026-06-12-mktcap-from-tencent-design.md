# 市值快照改从腾讯取数 设计规格

2026-06-12

## 背景与目标

分维度参数挖掘的**市值维度**当前为空：东财 IP 封锁导致 `fetch_mktcap_snapshot.py` 经 akshare `stock_zh_a_spot_em` 拉不到全市场快照 → `stock_mktcap_snapshot.csv` 缺失 → `calibrate_buckets` 市值 cuts=null → `mine_commonality` 仅出板块+波动率两维。

目标：把 `data/profit_mining/fetch_mktcap_snapshot.py` 的取数源从东财换成腾讯 `qt.gtimg.cn`，**输出 CSV 契约完全不变**，下游 `calibrate_buckets`、`mine_commonality` 零改动。

## 输出契约（不变）

`/app/data/profit_mining/stock_mktcap_snapshot.csv`，列：
- `代码`：6 位零填充字符串
- `总市值`：float，单位**元**（与旧东财口径一致）
- `采集日期`：`YYYY-MM-DD`

消费方：`calibrate_buckets._size_cuts()`（读 `总市值` 列算三分位）、`mine_commonality._group_ctx()`（`mktcap_map[代码]=float(总市值)`，按 events 池代码匹配）。

## 已实测确认的关键事实

- 接口 `http://qt.gtimg.cn/q=sh600519,sz000001,...`（GET，逗号分隔可批量）本机连通；东财封的是 push2.eastmoney，腾讯不受影响。
- 响应 **GBK** 编码，每行 `v_sh600519="字段~字段~...";`，按 `~` 切分共 88 字段。
- **总市值 = 下标 45，单位亿元**（实测 茅台 sh600519=16149.93 亿、平安 sz000001=2181.23 亿；下标 44=流通市值）。

## 设计

**股票池**：`events_labeled.csv` 股票代码列去重 ≈4415 个 6 位码（市值只服务这些股的三分位分桶，无需全市场表）。

**核心流程**：
1. 读 events 池 → 6 位代码集合。
2. 6 位 → 交易所前缀：`6→sh`、`0/3→sz`、`4/8→bj`、`9→sh`（查不到者腾讯返回空，自动跳过，不致命）。
3. 按 ~60 码/批拼 `q=` 串请求腾讯（urllib，GBK 解码）。
4. 解析每行：按 `~` 切分，取下标 45（亿元）× 1e8 → 元。
5. 写 CSV：代码 zfill6 + 总市值 + 采集日期。当天已存在则跳过（保留原行为）。

**容错**：单批请求失败重试一次仍失败则跳过该批；最终拿到 0 行则抛 ValueError（不静默写空表，沿用原则）。

**运行位置**：容器内（`/app/...` 路径与 calibrate_buckets 一致；运行前验证容器能出网到 gtimg）。直连 HTTP，不走 akshare_gateway。

## 单元函数边界（便于 TDD）

- `_prefix(code) -> "sh600519"`：6 位 → 带前缀代码。
- `_parse_line(line) -> (代码6位, 总市值元) | None`：单行 `v_xxx="..."` → (代码, 元)；非法/缺字段返回 None。
- `fetch_mktcap(codes, batch=60, fetch=urlopen_fn) -> DataFrame[代码,总市值]`：批量取+解析+组装；`fetch` 可注入便于测试。
- `main()`：当天跳过 / 读池 / fetch / 加采集日期 / 写 CSV / 0 行抛错。

## 测试（python3 合成数据，注入 fetch 桩，不联网）

1. `_prefix`：600519→sh600519、000001→sz000001、430xxx/8xxxxx→bj、900xxx→sh。
2. `_parse_line`：用真实样例串解析出 (600519, 16149.93e8)；缺字段/空串→None。
3. `fetch_mktcap`：注入桩返回两行 → DataFrame 两行、代码 zfill6、总市值为元。
4. 空响应/整批失败 → 跳过；全空 → main 抛 ValueError。

## 不做

全市场代码表、流通市值、其它字段、北交所特殊兼容（查不到即跳过）。

## 实现后收尾

容器跑 `fetch_mktcap_snapshot.py → calibrate_buckets.py（填市值 cuts）→ mine_commonality 全量重跑` → 补出 `分组uplift榜_市值_*.csv`（现仅 104 字节表头）→ 归档 `/home/tdxback/report/`。在 main 上提交并 push stock2。
