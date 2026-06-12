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


def main():
    codes = M._universe()[:4]
    print(f"网格 A={len(PS.PLAN_A_GRID)} B={len(PS.PLAN_B_GRID)}；校验股票 {codes}")
    all_ok = True
    for code in codes:
        df = M._load_kline(code)
        if df is None or len(df) < 80:
            print(f"  {code} 跳过(数据不足)"); continue
        opt = M.accumulate_stock(df)
        ref = reference_accumulate(df)
        if set(opt) != set(ref):
            print(f"  {code} ❌ key集不一致 opt={len(opt)} ref={len(ref)}"); all_ok = False; continue
        bad = [k for k in ref if opt[k] != ref[k]]
        if bad:
            all_ok = False
            print(f"  {code} ❌ {len(bad)}/{len(ref)} 键计数不一致，示例:")
            for k in bad[:3]:
                print(f"     {k}\n       opt={opt[k]}\n       ref={ref[k]}")
        else:
            print(f"  {code} ✅ {len(ref)}键全一致 bars={len(df)}")
    print("==== 全部一致 ✅" if all_ok else "==== 存在差异 ❌")


if __name__ == "__main__":
    main()
