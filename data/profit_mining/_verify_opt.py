# 临时校验：优化版 accumulate_stock 与参考实现(原信号函数+原count_for_signal)逐键比对。
import mine_commonality as M
import param_signals as PS
import swing_samples as SW
from collections import defaultdict


def reference_accumulate(df, pcts=M.DEFAULT_PCTS, fwd=4):
    out = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    high = df["High"].tolist(); low = df["Low"].tolist()
    for pct in pcts:
        up, down = SW.positive_windows(high, low, pct, fwd)
        for side, windows in (("buy", up), ("sell", down)):
            if not windows:
                continue
            for params in PS.PLAN_A_GRID:
                sig = PS.plan_a_signal(df, *params, side=side).to_numpy()
                M._merge(out[("A", side, pct, params)], M.count_for_signal(sig, windows))
            for params in PS.PLAN_B_GRID:
                sig = PS.plan_b_signal(df, *params, side=side).to_numpy()
                M._merge(out[("B", side, pct, params)], M.count_for_signal(sig, windows))
    return dict(out)


def check_conservation(code):
    """分组守恒: 板块/市值整组键==ALL同参(同一窗口复用)；波动率三桶窗口计数和==ALL前4元。"""
    df = M._load_kline(code)
    if df is None or len(df) < 80:
        return True
    groups = {"board": "板块=测试", "size": "市值=小盘", "vol_cuts": [0.01, 0.03]}
    counts = M.accumulate_stock(df, pcts=M.DEFAULT_PCTS, groups=groups)
    all_keys = [k for k in counts if k[0] == "ALL"]
    ok = True
    for ak in all_keys:
        for lab in ("板块=测试", "市值=小盘"):
            gk = (lab,) + ak[1:]
            if counts.get(gk) != counts[ak]:
                ok = False; print(f"  {code} ❌ {lab} 6元计数≠ALL {ak}")
        agg = [0, 0, 0, 0]
        for lab in ("波动率=低", "波动率=中", "波动率=高"):
            vk = (lab,) + ak[1:]
            if vk in counts:
                for i in range(4):
                    agg[i] += counts[vk][i]
        if agg != counts[ak][:4]:
            ok = False; print(f"  {code} ❌ 波动率三桶窗口计数和≠ALL {ak}")
    if ok:
        print(f"  {code} ✅ 分组守恒")
    return ok


def main():
    codes = M._universe()[:4]
    print(f"网格 A={len(PS.PLAN_A_GRID)} B={len(PS.PLAN_B_GRID)}；校验股票 {codes}")
    all_ok = True
    for code in codes:
        df = M._load_kline(code)
        if df is None or len(df) < 80:
            print(f"  {code} 跳过(数据不足)"); continue
        # 优化版(ALL组,strip前缀) vs 参考实现 逐键比对
        opt_all = {k[1:]: v for k, v in M.accumulate_stock(df).items() if k[0] == "ALL"}
        ref = reference_accumulate(df)
        if set(opt_all) != set(ref):
            print(f"  {code} ❌ key集不一致 opt={len(opt_all)} ref={len(ref)}"); all_ok = False; continue
        bad = [k for k in ref if opt_all[k] != ref[k]]
        if bad:
            all_ok = False
            print(f"  {code} ❌ {len(bad)}/{len(ref)} 键计数不一致，示例:")
            for k in bad[:3]:
                print(f"     {k}\n       opt={opt_all[k]}\n       ref={ref[k]}")
        else:
            print(f"  {code} ✅ {len(ref)}键全一致 bars={len(df)}")
        if not check_conservation(code):
            all_ok = False
    print("==== 全部一致 ✅" if all_ok else "==== 存在差异 ❌")


if __name__ == "__main__":
    main()
