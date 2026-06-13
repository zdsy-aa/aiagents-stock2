# 「📋 当前策略」页 设计规格

- 日期：2026-06-13
- 状态：待评审
- 类型：前台新增功能页（只读策略目录）

## 1. 背景与目标

当前选股、买卖、测试盈利、找共同点等策略分散在十几个脚本里，看不到全貌，想改某条策略时要先翻代码找到承载文件。

本功能在「🔍 功能导航」中**新增一个只读页「📋 当前策略」**，把全部策略按四大类集中展示：每条给出**脚本名 + 中文解释 + 关键可调参数（指明改哪个文件/哪个 json 键）**，方便用户一眼识别"谁干什么、想改去改哪"。

**交付定位（C 方案）**：以静态目录为主，对已是机器可读的配置（如 `star_thresholds.json`）实时读出真实数值显示。**前台不提供在线编辑**——用户读懂后自行决定修改，再由 Claude 改代码并重跑验证。

### 非目标（YAGNI）
- 不在前台编辑/写回任何策略参数。
- 不触碰、不重构任何现有策略逻辑。
- 不做策略间的对比/回测仪表盘（只做"目录+说明"）。

## 2. 集成方式（与现有 17 页一致）

1. **导航按钮**：`app.py` 功能导航中，于「🛡️ 稳定选股」按钮之后、同一选股 expander 内，新增
   `📋 当前策略`（`key="nav_current_strategy"`，`help="集中查看全部选股/买卖/测试盈利/找共同点策略的脚本与中文说明（只读）"`）。
2. **session 标志**：新增 `show_current_strategy`。
   - 点击本按钮时：`st.session_state.show_current_strategy = True`，并清掉其它所有 `show_*`（沿用现有 for-key del 写法）。
   - **反向同步**：把 `'show_current_strategy'` 追加进**所有现有导航按钮**的 clear-key 列表，保证切到别的页时本标志被清掉，不抢占。
3. **dispatch**：`app.py` 派发区（约 line 438「稳定选股」之后、`show_intraday` 之前）新增：
   ```python
   if 'show_current_strategy' in st.session_state and st.session_state.show_current_strategy:
       from current_strategy_ui import display_current_strategy
       display_current_strategy()
       return
   ```

## 3. 模块与数据结构（两个新文件，仓库根目录，入库）

> 注：根目录代码改动需重建镜像才在容器生效（与项目惯例一致）。

### 3.1 `strategy_catalog.py`（纯数据，事实来源文档）
一个 `CATALOG: list[dict]`，每条策略一个 dict。以后改策略时顺手维护这里。字段：

```python
{
  "类别": "选股",                       # 选股 / 买入卖出 / 测试盈利 / 找共同点
  "名称": "🌀 缠论选股",
  "脚本": ["chanlun_selector.py", "chanlun_batch.py", "chanlun_engine.py"],
  "解释": "多级别缠论买点筛选：日线本级别 + 30分钟次级别确认……",
  "关键参数": [
      ("次级别确认", "chanlun_selector.py", "30分钟级别，改 timeframe 参数"),
      ("买点类型", "chanlun_engine.py", "1买/2买/3买判定逻辑"),
  ],
  "实时": None,                         # 或字符串键，标记需读实时数值（见 §4）
}
```

- `类别` 取四个固定值之一，UI 据此分组。
- `脚本` 可多个；UI 以代码样式列出，方便用户复制告诉 Claude 改哪个。
- `关键参数` 每项 `(参数名, 所在文件, 现值/说明)`；指明"改哪"。
- `实时` 为 `None` 或一个回调标识键，UI 据此调用对应实时读取函数。

### 3.2 `current_strategy_ui.py`（渲染）
`display_current_strategy()`：

- 顶部 `ftc-section` 标题「📋 当前策略」+ 一句 `st.caption` 说明（只读、用于识别与决定修改、改完让 Claude 重跑）。
- 按四大类顺序（选股 → 买入卖出 → 测试盈利 → 找共同点）渲染，每类一个小节标题 + 若干 `st.expander` 卡片。
- 卡片内容：脚本路径（代码样式）、中文解释、关键参数表（`st.table`/markdown 列表）、若有 `实时` 则附实时数值区块。
- 复用 `stable_ui.PLANS` 渲染"稳定选股买卖方案"那条（不复制粘贴方案文本，直接 import 引用，避免双份漂移）。

## 4. 收录内容（四类，全部选股策略都收）

### 选股策略
- **量化研究栈**：缠论选股、六脉神剑、缠论×六脉、稳定选股。
- **AI 智能体栈**：主力选股、低价擒牛、小市值、净利增长、低估值、龙虎榜。

### 买入卖出策略
- 稳定选股买卖方案（抄底/抢筹/过热顶/强势顶）——引用 `stable_ui.PLANS` + `NOTES`。
- `mine_sell.py`：卖点共性挖掘。
- `daily_watchlist.py`：可入状态 / 止盈止损 / 实时价判定逻辑。

### 测试盈利策略
- `star_calibrate.py`：星级分档 = 样本外验证胜率差；阈值固化在 `star_thresholds.json`。
- `walk_forward.py`：滚动样本外验证（避免样本内过拟合）。

### 找共同点策略
- `mine_commonality.py`：盈利买卖点共同特征挖掘（提升度排序）。
- `mine_combos.py` / `mine_combos_v2.py`：信号组合挖掘。
- `build_features.py` / `build_features_v2.py`：特征/信号库构建（防泄漏）。
- 分维度挖掘：`test_group_dims.py`（波动率/市值/行业/板块分组找 uplift），`mine_regime.py`、`surface_l3.py`、`calibrate_buckets.py`。

> 说明：`data/profit_mining/` 下脚本刻意 untracked，但本目录仅以**字符串路径**引用它们，不依赖其入库。

## 5. 实时数值（C 方案增量，容错读取）

所有实时读取**必须 try/except 容错**，失败时显示「—（读取失败）」而非抛异常。容器内路径沿用 `stable_ui` 的 `/app/data/...` 绝对路径约定。

| 来源 | 展示内容 | 失败回退 |
|------|----------|----------|
| `data/profit_mining/star_thresholds.json` | 实际星级阈值 + 各档样本外胜率/大涨率 | 「—」 |
| `data/profit_mining/每日自选股清单.csv` | 最新候选数 + 文件更新时间 | 「暂无清单」 |
| `data/commonality_reports/` 目录 | 最近一次产物文件名与时间戳（结论新鲜度） | 「暂无产物」 |

## 6. 测试

- 沿用项目 `AppTest` 无头冒烟法，在 `tests/test_ui_pages_smoke.py` 增用例：
  - 设 `show_current_strategy=True` 运行，断言 `not at.exception`。
  - 断言页面文本含四大类标题关键字（「选股」「买入卖出」「测试盈利」「找共同点」）。
- `strategy_catalog.py` 可加一个极简校验单测：每条目含必需字段、`类别` 取值合法。

## 7. 风险与回归

- 纯新增页 + 两个新文件，不改任何现有策略逻辑 → 零回归风险。
- 唯一对现有文件的改动是 `app.py`（加按钮 / 加标志到 clear 列表 / 加 dispatch 分支），改动模式与现有 17 页完全一致。
- 部署：根目录代码改动需**重建镜像**才在容器对用户可见（项目惯例）。

## 8. 实施步骤概览

1. 新建 `strategy_catalog.py`，填四类全部策略条目（解释需逐个读源码核对，确保准确）。
2. 新建 `current_strategy_ui.py`，实现 `display_current_strategy()` + 三个容错实时读取函数。
3. 改 `app.py`：加导航按钮、加 `show_current_strategy` 到各 clear 列表、加 dispatch 分支。
4. 加 `AppTest` 冒烟用例 + `strategy_catalog` 字段校验单测。
5. 本地跑测试 → 提交 main → 重建镜像生效。
