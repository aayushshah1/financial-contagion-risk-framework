import sys, os, json, math
sys.path.insert(0, os.path.dirname(__file__))
from task11_stress_score import load_ratios_dataframe
from config import _normalize_bank_name

with open(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'outputs', 'stress_scores.json')) as f:
    scores = json.load(f)

danger = [0.3433, 0.1724, 0.1568]

all_dists = [
    math.sqrt(sum((v['kpcaEmbedding'][i] - danger[i])**2 for i in range(3)))
    for k, v in scores.items() if k != '_meta'
]
max_dist = max(all_dists)

df = load_ratios_dataframe('2025')

focus = [
    'STATE BANK OF INDIA',
    'HDFC BANK LTD.',
    'ICICI BANK LIMITED',
    'ESAF SMALL FINANCE BANK LIMITED',
    'UTKARSH SMALL FINANCE BANK LIMITED',
    'DHANLAXMI BANK LIMITED',
    'YES BANK LTD.',
    'CANARA BANK',
    'PUNJAB NATIONAL BANK',
]

print(f"Danger point (KPCA): {danger}")
print(f"Max distance (normalizer): {max_dist:.4f}\n")
header = f"{'Bank':<42} {'PC1':>6} {'PC2':>6} {'PC3':>6}  {'Dist':>6}  {'BndStr':>6}  {'tier1':>6}  {'totCAR':>6}  {'NPA':>5}"
print(header)
print('-' * len(header))

for bank in focus:
    if bank not in scores:
        continue
    data = scores[bank]
    emb = data['kpcaEmbedding']
    d = math.sqrt(sum((emb[i] - danger[i])**2 for i in range(3)))
    bs = 1.0 - d / max_dist

    t1 = tc = npa = 'N/A'
    for idx in df.index:
        if _normalize_bank_name(idx) == _normalize_bank_name(bank):
            row = df.loc[idx]
            t1  = f"{row['tier1CAR']:.1f}"  if row.get('tier1CAR')  is not None else 'N/A'
            tc  = f"{row['totalCAR']:.1f}"  if row.get('totalCAR')  is not None else 'N/A'
            npa = f"{row['netNPAToNetAdvances']:.2f}" if row.get('netNPAToNetAdvances') is not None else 'N/A'
            break

    print(f"{bank:<42} {emb[0]:>6.3f} {emb[1]:>6.3f} {emb[2]:>6.3f}  {d:>6.4f}  {bs:>6.4f}  {t1:>6}  {tc:>6}  {npa:>5}")
