# eval_indicator_strength.py
# 评估"缠论副图"指标里的"买入强度星级"是否有参考价值。
# 复刻指标逻辑(缠论副图.txt 第225-238行):
#   量能确认 ≈ 放量(信号日±2窗口,V>MA(V,5)且>MA(V,20))   —— 指标原式 V>MA(V,5)*1.2 + COUNT(.,3)
#   背驰加分 ≈ MACD底背离(信号日±2窗口)                   —— 指标原式 L新低&MACD不新低 + COUNT(.,5)
#   星级 = 5(量&背驰共振) / 4(满足其一) / 3(都不满足) = 3 + 放量 + 底背离
# 标签: 是否盈利 = 区间涨跌幅≥4%。基线 = 全样本盈利率。
# 提升度(lift) = P(盈利|该层) / 基线 ;  >1 才说明该层比"随机买缠论买点"强。
import pandas as pd, numpy as np

df = pd.read_csv('signal_features.csv')
df['信号日期'] = df['信号日期'].astype(str)
df['年'] = df['信号日期'].str[:4]

# --- 复刻指标星级 ---
df['量能确认'] = df['放量'].astype(int)
df['背驰加分'] = df['MACD底背离'].astype(int)
df['星级'] = 3 + df['量能确认'] + df['背驰加分']     # 3/4/5

base = df['是否盈利'].mean()
N = len(df)

def lift_table(sub, label):
    base_s = sub['是否盈利'].mean()
    rows = []
    for s in [5, 4, 3]:
        g = sub[sub['星级'] == s]
        if len(g) == 0:
            continue
        wr = g['是否盈利'].mean()
        rows.append((s, len(g), len(g)/len(sub)*100, wr*100, wr/base_s))
    t = pd.DataFrame(rows, columns=['星级','样本数','占比%','盈利率%','提升度'])
    print(f"\n### {label}  (样本={len(sub)}, 基线盈利率={base_s*100:.1f}%)")
    print(t.to_string(index=False, float_format=lambda x: f'{x:.2f}'))
    return t

print(f"=== 全样本 N={N}, 基线盈利率={base*100:.2f}% ===")
print("星级分布:", df['星级'].value_counts().sort_index().to_dict())

tot = lift_table(df, "全样本")

# 单因子各自的提升度(看两个原料各自值多少)
print("\n### 两个原料因子单独的提升度")
for col in ['量能确认','背驰加分']:
    for v in [1,0]:
        g = df[df[col]==v]
        wr = g['是否盈利'].mean()
        print(f"  {col}={v}: 样本{len(g):6d} 盈利率{wr*100:5.1f}% 提升度{wr/base:.3f}")

# 按买点类型(项目已证买点类型是第一精选轴)
for bt in ['1买','2买','3买']:
    lift_table(df[df['买点类型']==bt], f"买点类型={bt}")

# 按年份看稳健性(项目口径:2024有beta/2025中性最可信)
for y in ['2023','2024','2025']:
    sub = df[df['年']==y]
    if len(sub) > 200:
        lift_table(sub, f"年份={y}")

# 5星 vs 3星 的实际差距(回答用户原问题:强度高低到底差多少)
w5 = df[df['星级']==5]['是否盈利'].mean()
w3 = df[df['星级']==3]['是否盈利'].mean()
print(f"\n=== 结论数字 ===")
print(f"5星盈利率 {w5*100:.1f}%  vs  3星盈利率 {w3*100:.1f}%  差 {(w5-w3)*100:+.1f}pt")
print(f"5星占全样本 {len(df[df['星级']==5])/N*100:.1f}%  (越高说明星级越虚)")
print(f"4星及以上占比 {len(df[df['星级']>=4])/N*100:.1f}%")
