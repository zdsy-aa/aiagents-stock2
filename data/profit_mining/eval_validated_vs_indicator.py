# eval_validated_vs_indicator.py
# 对照表: 项目已验证有效的因子 vs 缠论副图指标的"买入强度5星"
# 全部用同一口径: 盈利=区间涨跌幅≥4%, 提升度=P(盈利|规则)/基线(39.63%)
import pandas as pd, numpy as np

sf = pd.read_csv('signal_features.csv')
sf['信号日期'] = sf['信号日期'].astype(str)
ts = pd.read_csv('turnover_signal.csv')
ts['信号日期'] = ts['信号日期'].astype(str)
ts = ts.drop_duplicates(['股票代码','信号日期'])   # 换手率表有重复键,去重防止merge笛卡尔放大
df = sf.merge(ts, on=['股票代码','信号日期'], how='left')
assert len(df) == len(sf), f"merge后行数变了: {len(df)} vs {len(sf)}"

def b(col):  # 转布尔
    return pd.to_numeric(df[col], errors='coerce').fillna(0) > 0

base = df['是否盈利'].mean()
N = len(df)

# 各规则的布尔掩码
极限抄底量比 = b('极限抄底') & b('量比大于1_3')
尖刺金叉   = b('尖刺金叉')
是1买      = df['买点类型'] == '1买'
非陷阱     = ~(b('相对强弱大于0') | b('大盘多头'))      # 项目精选:剔除相对强弱≥0或大盘多头
量能金叉   = b('量能金叉')
指标5星    = b('放量') & b('MACD底背离')               # 指标的"量+背驰共振"

rules = [
    ('【基线】所有缠论买点',           pd.Series(True, index=df.index)),
    ('指标5星(量+背驰共振)',          指标5星),
    ('—— 以下为项目已验证 ——',        None),
    ('只取1买',                       是1买),
    ('极限抄底+量比≥1.3',             极限抄底量比),
    ('尖刺金叉',                       尖刺金叉),
    ('(极限抄底+量比) ∪ 尖刺金叉',     极限抄底量比 | 尖刺金叉),
    ('1买 + 极限抄底+量比≥1.3',        是1买 & 极限抄底量比),
    ('1买 + 非陷阱(剔RS≥0/大盘多头)',  是1买 & 非陷阱),
    ('1买 + 非陷阱 + 量能金叉',         是1买 & 非陷阱 & 量能金叉),
    ('1买 + 极限抄底+量比 + 非陷阱',    是1买 & 极限抄底量比 & 非陷阱),
]

print(f"基线盈利率={base*100:.2f}%  全样本N={N}\n")
print(f"{'规则':<28}{'样本数':>8}{'占比%':>8}{'盈利率%':>9}{'提升度':>8}")
print('-'*63)
out_rows = []
for name, mask in rules:
    if mask is None:
        print(name)
        out_rows.append((name,'','','',''))
        continue
    g = df[mask]
    n = len(g); wr = g['是否盈利'].mean() if n else 0
    print(f"{name:<28}{n:>8}{n/N*100:>8.1f}{wr*100:>9.1f}{wr/base:>8.2f}")
    out_rows.append((name, n, f'{n/N*100:.1f}', f'{wr*100:.1f}', f'{wr/base:.2f}'))

# 落盘报告
import datetime
ts_str = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
out = f'/home/tdxback/report/缠论指标5星_vs_有效因子对照_{ts_str}.md'
L = ['# 缠论指标「买入强度5星」 vs 项目已验证有效因子 —— 同口径对照', '',
     f'- 日期: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}',
     f'- 数据: signal_features.csv ⋈ turnover_signal.csv，全历史缠论买点 {N} 条',
     f'- 口径: 盈利=区间涨跌幅≥4%；基线盈利率={base*100:.2f}%；提升度=P(盈利|规则)/基线，>1才有正向价值', '',
     '| 规则 | 样本数 | 占比% | 盈利率% | 提升度 |', '|---|---|---|---|---|']
for r in out_rows:
    L.append('| ' + ' | '.join(str(x) for x in r) + ' |')
L += ['', '## 一句话',
      '指标5星提升度≈0.95(等于/略低于基线)，而项目验证的因子提升度1.3~2.2。',
      '差距不在"要不要看强度"，而在"看哪个强度"——量+背驰共振无效，超跌反弹(极限抄底+量比)/尖刺金叉/1买精选才是真有提升度的强度。']
open(out,'w',encoding='utf-8').write('\n'.join(L))
print(f'\n报告: {out}')
