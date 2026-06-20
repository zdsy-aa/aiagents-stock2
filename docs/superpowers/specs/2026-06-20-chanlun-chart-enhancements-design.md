# 缠论图解页 4 项增强 设计

2026-06-20。在已上线的「📐 缠论图解」页（`chanlun_chart_ui.py`）上叠加 4 项增强，让结构与买卖点依据更完整：
分型点标注、背驰段高亮、未来条件图上提示框、多级别 30m 联立。复用 `chanlun_engine` 既有产物，
不改引擎、不动现有图层（K线/笔/线段/中枢/买卖点/关键价位横线/决策区）。

## 已核对的引擎事实
- `ChanResult.fractals`：`Fractal(kind in {"top","bottom"}, i 原始行号, price)`。
- 买卖点 `TradePoint.i` = 触发该点的**线段的 i_end**；故「背驰段」= `segments` 中 `i_end == point.i` 的那段。
  仅 1买/1卖 的 note 含「背驰」（detect_trade_points：下跌段/上涨段力度背驰）。
- 30m 次级别：`akshare_gw.local.get_kline(code, kline_type="30min", limit=2000)` 可取；
  `chanlun_engine.analyze(df_day, df_30m)` 会给每个买卖点 note 追加「30m确认」或「无次级别确认」。
- `forward_conditions(result, df)` 返回 `[{signal,direction,level,text,confidence}]`（已实现）。

## 目标 / 范围
1. **分型点标注**：顶分型红色▽（画在 high 价位）、底分型绿色△（画在 low 价位），具名 trace「分型」，**默认显示**。
2. **背驰段高亮**：对 note 含「背驰」的买卖点，取 `i_end==point.i` 的线段，用金色粗线叠画，具名 trace「背驰段」。
3. **未来条件图上提示框**：在决策区内，对每条 `forward_conditions` 在其阈值价 `level` 处画一条短横线/标注，
   文本=「{signal} {方向词} {level}」（如「3买 站上 10.46」），与图下条件表一一对应。
4. **多级别 30m 联立**：`display_chanlun_chart` 改用 `analyze(df_day, df_30m)`（取 30m K线；取不到/不足则退回 `analyze_one`）。
   买卖点 hover 文本即含「30m确认/无次级别确认」；条件表下方补一行说明「本级别买卖点 30m 确认情况：X 个确认 / Y 个未确认」。

## 非目标（YAGNI）
- 不改 `chanlun_engine`（只读 fractals/segments/points + 调 analyze）。
- 不改现有图层与 `forward_conditions` 逻辑。
- 不做 30m 级别独立画图（30m 仅用于给日线买卖点加确认标记）。
- 不持久化、不接邮件/选股。

## 组件改动
**`chanlun_chart_ui.py`**：
- `build_chart(df, result, future_days, conditions=None)`：**新增可选 `conditions` 参数**（来自 forward_conditions）。
  - 加「分型」trace：`go.Scatter(mode="markers")`，顶/底分型分两组 marker（▽红 / △绿），x=df.index[f.i]，y=f.price。
  - 加「背驰段」trace：遍历 `result.points` 中 note 含「背驰」者，找 `seg.i_end==p.i` 的 segment，
    画金色粗线（x=[df.index[i_start],df.index[i_end]], y=[p_start,p_end]），统一一条具名 trace「背驰段」。
  - 若传入 `conditions` 且有 `future_days`：在决策区 x（future_days[1] 居中）对每条 condition 的 `level`
    画短横线 + `add_annotation` 文本「{signal} {站上/跌破} {level}」（买向用「站上」、卖向用「跌破」）。
- `display_chanlun_chart`：
  - 取 30m：`df_30m = _load_kline_30m(code)`（新 helper，lazy import，失败/None 返回 None）。
  - `res = analyze(dfn.reset_index(drop=True), df_30m.reset_index(drop=True) if df_30m is not None else None)`。
  - `conds = forward_conditions(res, dfn)`；`build_chart(dfn, res, fut, conditions=conds)`。
  - 条件表下补一行 30m 确认统计（统计 res.points 中 note 含「30m确认」数 vs「无次级别确认」数）。

## 错误处理 / 边界
- 30m 取数失败/不足 20 根：`analyze` 内部已容忍（df_30m=None → 退回单级别，note 标「无次级别确认」），display 不额外报错。
- 无分型/无背驰段/无条件：对应 trace/标注跳过，不报错（与现有 trace 一样按存在性添加）。
- 分型/背驰段的 i 越界（≥len(df)）跳过该项。

## 测试（tests/test_chanlun_chart.py 追加）
- `build_chart` 含「分型」trace（构造带 fractals 的 result，断言 trace 名含「分型」）。
- `build_chart` 含「背驰段」trace（构造一个 note 含「背驰」的 1买 + 对应 segment，断言含「背驰段」trace）。
- `build_chart` 传 conditions + future_days 时，decision 区有对应 annotation（断言 fig.layout.annotations 文本含某 signal）。
- 30m 取数 helper 失败回退：monkeypatch `_load_kline_30m` 返回 None，display 路径仍可分析（经端到端/容器验证；纯逻辑层断言 analyze(df, None) 不崩——已被引擎覆盖，补一条 forward 仍可用）。
- 页面渲染冒烟沿用现有 `show_chanlun_chart`（空输入分支不变）。

## 上线 / 影响面
- 仅改 `chanlun_chart_ui.py` + 测试。改 root 需 `docker compose build agentsstock` + `up -d agentsstock` recreate。
- develop on main，用户自行 push stock2。
- 免责文案不变（已含「缠论为结构判断、未来条件需确认、背驰近似」）。
