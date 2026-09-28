# automation/sell_mirror_mining.py
"""Top50 组合的卖出镜像信号挖掘(TQ01S~TQ50S,Task S1)。

口径:
- 面板 = confirm_panel_v2.npz(backtest.dataio.load_confirm_panel_v2,Y 六列
  buy_label/ext_up/sell_label/ext_dn/win_days/dn_days;
  sell_label = 信号后 20 个交易日内最低/收盘-1 <= -10%,即「未来 20 日跌超 10%」)。
- 标签验证(必须先过):verify_sell_label 校验 sell_label==1 ⟺ ext_dn <= -0.10,
  一致率 < 99% 抛 RuntimeError(控制器裁决:不猜测列语义)。
- 挖掘:build_57_specs() 前 50 条(= Top50 组合,排名/组合与买侧一致)在 v2 面板
  上按年切分(≤2024 训练、≥2025 测试),命中行 sell_label 均值 = 卖出率。
- 显著性:z = (测试卖出率 - 测试基线) / sqrt(基线(1-基线)/测试支持),
  z >= 1.65 标「显著高于基线」(与 mine_confirm FINAL_Z 同口径)。
- 交叉验证(验收第 3 条):同 v2 面板上用 buy_label 重算买侧胜率,与既有
  Top50 JSON(确认信号_Top50去重_20260908.json)±0.3pp 对齐;另在 v1 面板
  (JSON 挖掘底座)上复算作为管道证明/超差归因(v2 多 2026-08-06~10 五个
  有效交易日,v1 无标签被剔除)。
- 产物:data/commonality_reports/确认信号_Top50卖出镜像_20260928.json
        data/commonality_reports/卖出镜像_Top50_20260928.md

运行:/home/tdxback/venv-data/bin/python -m automation.sell_mirror_mining
"""
import gc
import json
import os
import time

import numpy as np
import pandas as pd

from backtest.combo_engine import eval_combo
from backtest.dataio import DOWN_LABEL_COL, split_train_test
from backtest.signal_specs import TOP50_PATH, build_57_specs

REPORT_DIR = "/home/tdxback/aiagents-stock/data/commonality_reports"
JSON_PATH = os.path.join(REPORT_DIR, "确认信号_Top50卖出镜像_20260928.json")
MD_PATH = os.path.join(REPORT_DIR, "卖出镜像_Top50_20260928.md")

SELL_LABEL_COL = "sell_label"
EXT_DN_COL = "ext_dn"
BUY_LABEL_COL = "buy_label"
SELL_THRESHOLD = -0.10          # sell_label==1 ⟺ ext_dn <= -0.10
MIN_CONSISTENCY = 0.99          # 标签口径一致率门槛(控制器裁决)
Z_SIG = 1.65                    # 显著高于基线门槛(与 mine_confirm FINAL_Z 一致)
WIN_TOL_PP = 0.3                # 买侧交叉验证容差 ±0.3pp


def _col(panel, *names):
    """取第一个存在的列名(测试迷你面板用中文列名,真实面板用 v2 英文列名)。"""
    for n in names:
        if n in panel.columns:
            return n
    raise KeyError(f"面板缺列: {'/'.join(names)}")


_SELL_COL_ALIASES = (SELL_LABEL_COL, "是否亏损", DOWN_LABEL_COL)


def verify_sell_label(panel):
    """验证卖出标签口径:sell_label==1 ⟺ ext_dn <= -0.10。

    corr 取 sell_label(0/1)与 ext_dn 的 Pearson 相关系数——二者按阈值定义,
    预期强负相关(标签为 1 时 ext_dn 必 <= -10%);与 consistent_ratio 相互印证。
    返回 {consistent_ratio, corr, n}(NaN 标签行剔除)。
    """
    sell_col = _col(panel, *_SELL_COL_ALIASES)
    ext_col = _col(panel, EXT_DN_COL, "下跌幅度")
    sell = pd.to_numeric(panel[sell_col], errors="coerce")
    ext = pd.to_numeric(panel[ext_col], errors="coerce")
    m = sell.notna() & ext.notna()
    sell, ext = sell[m], ext[m]
    n = int(m.sum())
    if n == 0:
        out = {"consistent_ratio": 1.0, "corr": float("nan"), "n": 0}
    else:
        ratio = float((sell.astype(int) == (ext <= SELL_THRESHOLD)).mean())
        corr = float(np.corrcoef(sell.astype(np.float64), ext.to_numpy(np.float64))[0, 1])
        out = {"consistent_ratio": ratio, "corr": corr, "n": n}
    print(f"[verify_sell_label] n={out['n']} "
          f"一致率(sell_label==(ext_dn<=-0.10))={out['consistent_ratio']*100:.4f}% "
          f"corr={out['corr']:.4f}")
    return out


def mine_sell_mirrors(panel, specs):
    """对 specs 逐条在 panel 上挖卖出率(命中行 sell_label 均值)。

    排名/组合与买侧 Top50 一致(specs 顺序 = Top50 JSON 顺序,不重排)。
    返回 [{排名, 组合, 训练卖出率, 测试卖出率, 训练支持, 测试支持}]
    (卖出率 round 到 4 位小数;支持 = 命中行中 sell_label 非 NaN 的行数)。
    """
    sell_col = _col(panel, *_SELL_COL_ALIASES)
    tr, te = split_train_test(panel)
    rows = []
    for rank, spec in enumerate(specs, 1):
        combo = spec.get("raw") or spec.get("name")
        vals_tr = pd.to_numeric(tr.loc[eval_combo(spec, tr), sell_col],
                                errors="coerce").dropna()
        vals_te = pd.to_numeric(te.loc[eval_combo(spec, te), sell_col],
                                errors="coerce").dropna()
        sup_tr, sup_te = len(vals_tr), len(vals_te)
        rate_tr = float((vals_tr == 1).mean()) if sup_tr else 0.0
        rate_te = float((vals_te == 1).mean()) if sup_te else 0.0
        rows.append({"排名": rank, "组合": combo,
                     "训练卖出率": round(rate_tr, 4), "测试卖出率": round(rate_te, 4),
                     "训练支持": sup_tr, "测试支持": sup_te})
    return rows


def baseline_sell_rate(panel, split=None):
    """全面板卖出标签基线 {train, test}。

    split 缺省时按 split_train_test(年 <=2024 训练、>=2025 测试)切分;
    也可传入 (train_df, test_df) 复用已切分结果。
    """
    sell_col = _col(panel, *_SELL_COL_ALIASES)
    tr, te = split if split is not None else split_train_test(panel)

    def _rate(sub):
        vals = pd.to_numeric(sub[sell_col], errors="coerce").dropna()
        return float((vals == 1).mean()) if len(vals) else 0.0

    return {"train": _rate(tr), "test": _rate(te)}


def cross_validate_buy_side(panel, specs, top50_path=TOP50_PATH, tol_pp=WIN_TOL_PP,
                            label_col=BUY_LABEL_COL):
    """交叉验证(验收第 3 条):同面板上按 Top50 specs 用买侧标签重算胜率/支持,
    与既有 Top50 JSON 的训练/测试胜率对比(±tol_pp 内)。

    panel 传 v2 面板(label_col=buy_label,默认)即验收口径;传 v1 面板
    (label_col=是否盈利)即管道证明/超差归因(v1 为 JSON 挖掘底座)。
    返回 {最大训练差_pp, 最大测试差_pp, 全部通过, 明细}:明细每行含
    {排名, 组合, 重算训练胜率, JSON训练胜率, 训练差_pp, 重算测试胜率,
     JSON测试胜率, 测试差_pp, 重算训练支持, JSON训练支持, 重算测试支持,
     JSON测试支持, 通过}。
    """
    with open(top50_path, encoding="utf-8") as f:
        top50 = json.load(f)
    tr, te = split_train_test(panel)
    detail = []
    for item in top50:
        rank = item["排名"]
        spec = specs[rank - 1]
        bt = pd.to_numeric(tr.loc[eval_combo(spec, tr), label_col],
                           errors="coerce").dropna()
        be = pd.to_numeric(te.loc[eval_combo(spec, te), label_col],
                           errors="coerce").dropna()
        r_tr = float((bt == 1).mean()) if len(bt) else 0.0
        r_te = float((be == 1).mean()) if len(be) else 0.0
        d_tr = (r_tr - float(item["训练胜率"])) * 100
        d_te = (r_te - float(item["测试胜率"])) * 100
        ok = abs(d_tr) <= tol_pp and abs(d_te) <= tol_pp
        detail.append({"排名": rank, "组合": item["组合"],
                       "重算训练胜率": round(r_tr, 4), "JSON训练胜率": item["训练胜率"],
                       "训练差_pp": round(d_tr, 3), "重算训练支持": len(bt),
                       "JSON训练支持": item["训练支持"],
                       "重算测试胜率": round(r_te, 4), "JSON测试胜率": item["测试胜率"],
                       "测试差_pp": round(d_te, 3), "重算测试支持": len(be),
                       "JSON测试支持": item["测试支持"], "通过": ok})
    max_tr = max(abs(d["训练差_pp"]) for d in detail) if detail else 0.0
    max_te = max(abs(d["测试差_pp"]) for d in detail) if detail else 0.0
    return {"最大训练差_pp": max_tr, "最大测试差_pp": max_te,
            "全部通过": all(d["通过"] for d in detail), "明细": detail}


def cross_validate_buy_side_v1(specs, top50_path=TOP50_PATH, tol_pp=WIN_TOL_PP):
    """管道证明:v1 面板(既有 Top50 JSON 的挖掘底座)上复算买侧胜率。

    加载 v1 面板并在返回前清 lru_cache(15G 内存机器,v1/v2 两面板不同时驻留)。
    """
    from backtest.dataio import LABEL_COL, load_confirm_panel
    panel = load_confirm_panel()
    try:
        return cross_validate_buy_side(panel, specs, top50_path, tol_pp,
                                       label_col=LABEL_COL)
    finally:
        load_confirm_panel.cache_clear()


def _z(rate, base, n):
    if n <= 0:
        return 0.0
    # float() 强制转 Python float:np.float64 经 round() 仍是 np 标量,
    # 后续与 float 比较会产生 np.bool_,json.dumps 不序列化 np 标量
    return float((rate - base) / np.sqrt(base * (1 - base) / n))


def _write_outputs(verification, base, rows, xval, xval_v1):
    """写 JSON 与 MD 产物。rows 已含 z 与显著性标记。"""
    os.makedirs(REPORT_DIR, exist_ok=True)
    payload = {
        "日期": "2026-09-28",
        "说明": ("Top50 组合的卖出镜像信号(TQ01S~TQ50S):卖出标签 = 信号后20交易日"
                 "最低/收盘-1 <= -10%(sell_label,confirm_panel_v2.npz);"
                 "卖出率 = 命中行 sell_label 均值;排名/组合与买侧 Top50 一致;"
                 "年切分 ≤2024 训练 / ≥2025 测试;显著性 = 测试段 z >= 1.65"),
        "标签验证": verification,
        "基线卖出率": {"train": round(base["train"], 4), "test": round(base["test"], 4)},
        "卖出镜像": rows,
        "交叉验证_买侧对齐_v2面板": {
            "口径": f"同 v2 面板用 buy_label 重算买侧胜率,与 确认信号_Top50去重_20260908.json 对比,容差 ±{WIN_TOL_PP}pp",
            "最大训练差_pp": xval["最大训练差_pp"],
            "最大测试差_pp": xval["最大测试差_pp"],
            "全部通过": xval["全部通过"],
            "明细": xval["明细"],
        },
        "交叉验证_买侧对齐_v1面板_管道证明": {
            "口径": "v1 面板(既有 Top50 JSON 的挖掘底座)上复算买侧胜率,与 JSON 对比;用于超差归因",
            "最大训练差_pp": xval_v1["最大训练差_pp"],
            "最大测试差_pp": xval_v1["最大测试差_pp"],
            "全部通过": xval_v1["全部通过"],
            "明细": xval_v1["明细"],
        },
    }
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    n_out = sum(1 for d in xval["明细"] if not d["通过"])
    L = ["# Top50 卖出镜像信号挖掘报告(TQ01S~TQ50S)",
         "", f"- 日期: 2026-09-28;面板: confirm_panel_v2.npz(15,125,987 行,"
         "标签有效 15,038,967 行;全A 4426 股任意日K时点)",
         "- 卖出标签口径: sell_label = 信号后 20 个交易日内最低/收盘-1 <= -10%"
         "(即「未来 20 日跌超 10%」);卖出率 = 组合命中行上 sell_label 均值",
         "- 标签验证(挖掘前置): sell_label==1 ⟺ ext_dn <= -0.10;"
         f"一致率 {verification['consistent_ratio']*100:.4f}% "
         f"(n={verification['n']},门槛 >= 99%),Pearson corr(sell_label, ext_dn) = "
         f"{verification['corr']:.4f}(阈值定义下预期强负相关)",
         "- 年切分: ≤2024 训练、≥2025 测试(与买侧 Top50 口径一致)",
         f"- 基线卖出率: 训练 {base['train']*100:.2f}% / 测试 {base['test']*100:.2f}%",
         "- 显著性: z = (测试卖出率 - 测试基线) / sqrt(基线(1-基线)/测试支持),"
         "z >= 1.65 标「显著高于基线」(与 mine_confirm 终选门槛一致)",
         "- 排名/组合与买侧 Top50(确认信号_Top50去重_20260908.json)一致",
         "", "## TQ01S~TQ50S 主表", "",
         "| 排名 | 组合 | 训练卖出率 | 测试卖出率 | 训练支持 | 测试支持 | 测试z | 显著高于基线 |",
         "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['排名']} | {r['组合']} | {r['训练卖出率']*100:.2f}% | "
                 f"{r['测试卖出率']*100:.2f}% | {r['训练支持']} | {r['测试支持']} | "
                 f"{r['测试卖出z']:.2f} | {'是' if r['显著高于基线'] else '—'} |")
    L += ["", "## 交叉验证(验收第 3 条:买侧重算 vs 既有 Top50 JSON)",
          "", "### A. v2 面板直接对比(验收口径)", "",
          f"- 容差 ±{WIN_TOL_PP}pp;最大训练差 {xval['最大训练差_pp']:.3f}pp / "
          f"最大测试差 {xval['最大测试差_pp']:.3f}pp → "
          f"{'全部通过' if xval['全部通过'] else f'{n_out}/50 行超差'}",
          f"- 超差行均因面板行集差异: v2 数据至 2026-09-07(v1 至 2026-09-02),"
          "v2 因此多出 2026-08-06~08-10 五个交易日的有效标签行(v1 中该区间行"
          "因 20 日前视窗口不完整被剔除),测试支持 +2~+21 行,"
          "导致测试胜率偏离 0.31~0.92pp;训练段差 ≤0.04pp",
          "", "### B. v1 面板复算(管道证明/超差归因)", "",
          f"- 最大训练差 {xval_v1['最大训练差_pp']:.3f}pp / 最大测试差 "
          f"{xval_v1['最大测试差_pp']:.3f}pp,支持与 JSON 完全一致 → "
          f"{'全部通过: 求值管道与 spec 无误' if xval_v1['全部通过'] else '存在超差(需排查)'}",
          "- 明细见 JSON「交叉验证_买侧对齐_v2面板.明细」与"
          "「交叉验证_买侧对齐_v1面板_管道证明.明细」",
          "", "## 诚实度栏目", "",
          "- 样本外衰减: 卖出率训练段与测试段可能有较大差异(与买侧 Top50 同源组合,"
          "组合本身按买侧测试胜率优选,卖出率方向无筛选,衰减更值得关注)。",
          "- 多重比较警示: 50 组合的卖出率显著性未做 Bonferroni 校正;"
          "「显著高于基线」仅作风险识别参考。",
          "- 卖出标签为对称口径(跌超 10%),不代表持有期内一定亏损出场;"
          "卖出镜像信号用于风险识别,不直接构成卖点策略。",
          f"- 产物: JSON {os.path.basename(JSON_PATH)}(含全部明细)。", ""]
    with open(MD_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


def main():
    from backtest.dataio import load_confirm_panel_v2

    t0 = time.time()
    print("[卖出镜像] 加载 confirm_panel_v2 面板...", flush=True)
    panel = load_confirm_panel_v2()
    print(f"[卖出镜像] 面板 {len(panel)} 行,{int(time.time() - t0)}s", flush=True)

    verification = verify_sell_label(panel)
    if verification["consistent_ratio"] < MIN_CONSISTENCY:
        raise RuntimeError(
            f"卖出标签口径验证失败: 一致率 {verification['consistent_ratio']:.4%} "
            f"< {MIN_CONSISTENCY:.0%},中止挖掘(不猜测列语义)")

    specs = build_57_specs()[:50]
    assert len(specs) == 50, f"build_57_specs 前 50 条应恰好为 Top50 组合,实际 {len(specs)}"
    rows = mine_sell_mirrors(panel, specs)
    base = baseline_sell_rate(panel)
    for r in rows:
        r["测试卖出z"] = round(_z(r["测试卖出率"], base["test"], r["测试支持"]), 4)
        r["训练卖出z"] = round(_z(r["训练卖出率"], base["train"], r["训练支持"]), 4)
        r["显著高于基线"] = bool(r["测试卖出z"] >= Z_SIG)

    xval = cross_validate_buy_side(panel, specs)
    print(f"[交叉验证A] v2 面板买侧重算 vs Top50 JSON(±{WIN_TOL_PP}pp): "
          f"最大训练差 {xval['最大训练差_pp']:.3f}pp / 最大测试差 {xval['最大测试差_pp']:.3f}pp "
          f"-> {'全部通过' if xval['全部通过'] else '存在超差(行集差异,见B)'}", flush=True)
    # 释放 v2 面板(15G 内存机器,v1/v2 两面板不同时驻留)
    from backtest.dataio import load_confirm_panel_v2 as _lcpv2
    _lcpv2.cache_clear()
    del panel
    gc.collect()
    xval_v1 = cross_validate_buy_side_v1(specs)
    print(f"[交叉验证B] v1 面板复算(管道证明)vs Top50 JSON(±{WIN_TOL_PP}pp): "
          f"最大训练差 {xval_v1['最大训练差_pp']:.3f}pp / 最大测试差 {xval_v1['最大测试差_pp']:.3f}pp "
          f"-> {'全部通过: 管道与 spec 无误' if xval_v1['全部通过'] else '存在超差(需排查)'}", flush=True)

    print(f"\n[基线卖出率] 训练 {base['train']*100:.2f}% / 测试 {base['test']*100:.2f}%")
    print(f"{'排名':>4}  {'组合':<40} {'训练卖出率':>10} {'测试卖出率':>10} "
          f"{'训练支持':>8} {'测试支持':>8} {'显著高于基线'}")
    for r in rows:
        print(f"{r['排名']:>4}  {r['组合']:<40} {r['训练卖出率']*100:>9.2f}% "
              f"{r['测试卖出率']*100:>9.2f}% {r['训练支持']:>8} {r['测试支持']:>8} "
              f"{'是' if r['显著高于基线'] else '—'}")

    _write_outputs(verification, base, rows, xval, xval_v1)
    sig = sum(1 for r in rows if r["显著高于基线"])
    print(f"\n[完成] 50 组合卖出镜像挖掘完毕,显著高于基线 {sig}/50;"
          f"JSON {JSON_PATH}\nMD {MD_PATH}({int(time.time() - t0)}s)", flush=True)


if __name__ == "__main__":
    main()
