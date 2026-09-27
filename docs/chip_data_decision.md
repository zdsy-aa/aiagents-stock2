# 筹码数据源选型结论(Phase5 Task5.5)

- 日期: 2026-09-27
- 代码: `automation/chip_data.py`(结论 + 可运行探测 + fetch 接口)
- 结论: **source=unavailable** —— 三个候选源在本机均不可用;首选 akshare(东财解封即用),备选 tdx_file(需补齐股本/换手率数据)
- 测试: `tests/test_chip_data.py`(6 用例全绿,不依赖真实网络)

---

## 1. 结论摘要

```python
chip_decision() -> {
    "source": "unavailable",
    "status": "unavailable",
    "notes": "…三源探测过程与结论…(见模块 _DECISION)"
}
```

`fetch_chip(code)` 在当前结论下抛 `NotImplementedError`,附「解封后改 `_DECISION`
source 为 akshare 即可启用」的指引;akshare 取数映射 `_fetch_via_akshare`
已实现并有单测覆盖,不落全市场、单票按需。

---

## 2. 候选 1:akshare(探测日志)

### 2.1 安装探测

| 步骤 | 命令 | 结果 |
|---|---|---|
| venv-data 是否已装 | `python -c "import akshare"` | ModuleNotFoundError(未装) |
| 系统 python3 | `/usr/bin/python3 -c "import akshare"` | ModuleNotFoundError(未装) |
| pypi 直连安装 | `pip install akshare` | SSL EOF 失败(pypi.org 被墙/断) |
| 清华镜像安装 | `pip install -i https://pypi.tuna.tsinghua.edu.cn/simple akshare` | **成功: akshare-1.18.97 + 依赖(py-mini-racer 等)** |
| 接口存在性 | `hasattr(ak, "stock_cyq_em")` | 存在 |

### 2.2 源码核对(链路与算法)

`akshare/stock_feature/stock_cyq_em.py`:
- 数据上游 = `https://push2his.eastmoney.com/api/qt/stock/kline/get`
  (secid、klt=101 日K、lmt=210,fields2=f51..f61 含 **f58 换手率**);
- 算法 = 东财页面的 JS `CYQCalculator`(三角分布筹码衰减,窗口 120 日,
  150 档价格桶),经 `py_mini_racer` 执行;本地计算,非服务端下发;
- 输出列: `日期/获利比例/平均成本/90成本-低/90成本-高/90集中度/70成本-低/70成本-高/70集中度`(最近 90 行)。

→ 所需字段(获利盘/平均成本/90%集中度)全部可由该接口输出,**算法与字段核实通过**。

### 2.3 运行时探测(失败日志)

```
$ python -c "import akshare as ak; print(ak.stock_cyq_em(symbol='000001'))"
FAIL ProxyError HTTPSConnectionPool(host='push2his.eastmoney.com', port=443):
  Max retries exceeded with url: /api/qt/stock/kline/get?secid=0.000001&...&klt=101&fqt=0&end=20260927&lmt=210
  (Caused by ProxyError('Un...'))
```

- 走代理(env `HTTPS_PROXY=http://127.0.0.1:7890`):requests → ProxyError;
  显式 proxies 同失败;
- 直连(NO_PROXY):`RemoteDisconnected('Remote end closed connection without response')`;
- docker 容器 aktools 内直连:同样 RemoteDisconnected;
- curl 经代理连发 10 次(间隔 6s):**ok=0 fail=10**(HTTP 000);
- 唯一 1 次成功(探测早期,代理出口轮换偶发)返回了数据,证明接口本身可用、
  封禁发生在网络出口层;
- 项目已有记录:`akshare_gateway.py` 的 `BLOCKED_EM_FUNCS` 明确注明
  「走 push2his.eastmoney.com 的接口,当前服务器 IP 被封」。

**结论: akshare 包可用、链路与算法验证通过,但本机 IP 被东财 push2his
封禁,当前环境不可用。更换出口 IP/解封后即是最优源。**

---

## 3. 候选 2:东财筹码 HTTP 接口(探测日志)

逐一探测东财各域名(2026-09-27,curl + python requests):

| 端点 | 结果 |
|---|---|
| `push2his.eastmoney.com/api/qt/stock/kline/get`(筹码唯一上游日K) | 早期 1 次 200(数据正常),随后全部 000/连接重置;burst 10 连发 0 成功 |
| `push2.eastmoney.com/api/qt/stock/get`(实时行情) | 空响应(000) |
| `push2delay.eastmoney.com/api/qt/stock/kline/get` | 早期 1 次 200(klines 为空),随后全部 000 |
| `hsmarketwg.eastmoney.com/api/qt/stock/kline/get` | 404(该域名无此路由) |
| `quote.eastmoney.com/`(筹码分布页所在站) | 200(HTML 页,数据由 push2his 支撑) |
| `data.eastmoney.com/` | 200 |
| `emweb.securities.eastmoney.com/PC_HSF10/...`(F10 财务/股东研究) | 200(JSON 正常,但 F10 **无筹码分布数据**) |
| `datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_HOLDERNUM_DET` | 200(股东户数 HOLDER_NUM=450712 等,**可作筹码集中度近似**,非获利盘/平均成本/集中度三指标) |

**结论: 东财所有筹码/日K相关的 push2 系域名对本机不可达(IP 封禁);
可达的 emweb/datacenter 不提供筹码分布接口。无可用东财筹码 HTTP 通道。**

---

## 4. 候选 3:TDX 本地筹码数据文件(探测日志)

1. **通达信客户端安装目录**: 全盘搜索 `vipdoc/T0002/*.day/new_tdx*`(
   `/home/tdxback、/opt、/mnt、/srv、/root` 递归)— **0 命中**;无 wine、
   无 Windows 挂载盘。本机为 Linux,无通达信客户端。
2. **项目 tdx-api 本地数据**(`tdx-data/database/kline/*.db`,Go 服务
   `tdx-stock-web` 容器在 127.0.0.1:8080 运行,数据新至 2026-09-24):
   ```
   DayKline 列: Code, Date, Open, High, Low, Close, Volume, Amount, InDate
   000001.db: DayKline 8461 行 / MinuteKline 24000 行 …
   ```
   **无换手率(hsl)、无流通股本字段** → 筹码衰减算法无法计算。
3. **tdx-api 服务路由核对**(`tdx-api/web/server.go` 全部 HandleFunc):
   quote/kline/minute/trade/search/stock-info/codes/batch-quote/kline-history/
   index/market-*/etf-*/workday/income/tasks — **无筹码、无股本结构接口**;
   `protocol/model_kline.go` 的 Kline 结构体亦只有 OHLCV+Amount。
4. 顺带核对: 通达信客户端本身**不落盘筹码分布数据**(筹码图是客户端用日K+
   换手率实时计算),故「TDX 本地筹码文件」在通达信安装目录中本就不存在,
   只能走「本地日K + 流通股本」自算路线。

**结论: tdx_file 不可用。补齐路线: 引入流通股本(如东财解封后 F10 股本结构
或 TDX 协议 finance 接口)+ 本地日K,即可用与东财相同的 CYQ 算法自算。**

---

## 5. 附加探测(记录备查)

- **tushare**: `.env` 有 TUSHARE_TOKEN,`pip install tushare` 成功,但调用
  `pro.daily` / `pro.daily_basic` 均返回「您没有接口访问权限」(积分不足)
  → 不可用。
- **aktools 容器**(akshare HTTP 工具,127.0.0.1:8088):
  `/api/public/stock_cyq_em` 存在但返回 500(容器直连 push2his 同样被重置)。

---

## 6. 各源对比与最终决策

| 候选 | 链路 | 本机可用性 | 备注 |
|---|---|---|---|
| akshare `stock_cyq_em` | 东财 push2his 日K + 本地 CYQ 算法 | ✗(IP 封禁) | 算法/字段已核实;解封即用 |
| 东财 HTTP 直连 | 同上 | ✗(IP 封禁) | emweb/datacenter 可达但无筹码接口 |
| TDX 本地文件 | 本地日K + 需流通股本 | ✗(缺换手率/流通股本) | 客户端未安装、K线库字段不足 |

**决策: source=unavailable**(如实记录,宁缺毋假)。理由:
1. 三候选均无法在本机产出「获利盘/平均成本/90%集中度」三指标;
2. 不伪造「可用」状态——`fetch_chip` 明确抛 `NotImplementedError` 并附指引,
   下游任务(Task 5.6 市场环境数据层)不应依赖筹码字段兜底;
3. 把可用的计算能力留好: akshare 取数映射已实现并单测覆盖,东财解封后只改
   `_DECISION` 一处即可上线;tdx_file 自算路线亦已在文档给出补齐路径。

**启用路径(解封后)**: 修改 `automation/chip_data.py` 中 `_DECISION["source"]`
为 `"akshare"` → `fetch_chip(code)` 即返回
`{date, 获利盘, 平均成本, 90%集中度区间}`;复评探测:
`python -m automation.chip_data --probe`。

**测试口径**: `chip_decision()` 为记录型实现,不发网络请求;`fetch_chip`
映射经 monkeypatch 注入假 akshare 返回验证;探测函数(akshare/em_http 含
网络)不在单测中断言其结果,仅保证结构存在。
