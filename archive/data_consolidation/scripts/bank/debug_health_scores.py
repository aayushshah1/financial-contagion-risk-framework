import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from task11_stress_score import transform_ratio, load_ratios_dataframe
from config import _normalize_bank_name

df = load_ratios_dataframe('2025')

banks = [
    'STATE BANK OF INDIA',
    'HDFC BANK LTD.',
    'ICICI BANK LIMITED',
    'ESAF SMALL FINANCE BANK LIMITED',
    'CANARA BANK',
    'PUNJAB NATIONAL BANK',
]

FEATURES = [
    ('tier1CAR',                        'tier1'),
    ('totalCAR',                        'totCAR'),
    ('netNPAToNetAdvances',             'NPA'),
    ('returnOnAssets',                  'ROA'),
    ('returnOnEquity',                  'ROE'),
    ('netInterestMargin',               'NIM'),
    ('creditDepositRatio',              'CDR'),
    ('wageBillsToTotalExpense',         'Wages'),
    ('intermediationCostToTotalAssets', 'IntCst'),
    ('cashDepositRatio',                'CashDR'),
    ('costOfFunds',                     'CostFds'),
]

col_headers = '  '.join(f'{label:>7}' for _, label in FEATURES)
print(f"\n{'Feature health scores (0=stressed, 1=healthy)':}")
print(f"{'Bank':<42}  {col_headers}")
print('-' * (42 + 2 + len(col_headers) + 2 * len(FEATURES)))

for bank in banks:
    row = None
    for idx in df.index:
        if _normalize_bank_name(idx) == _normalize_bank_name(bank):
            row = df.loc[idx]
            break
    if row is None:
        print(f'{bank:<42}  (not found in ratios df)')
        continue

    scores = []
    for field, _ in FEATURES:
        val = None
        if field in row.index:
            try:
                val = float(row[field]) if row[field] is not None else None
            except (TypeError, ValueError):
                val = None
        scores.append(transform_ratio(field, val))

    raw_vals = []
    for field, _ in FEATURES:
        if field in row.index:
            try:
                raw_vals.append(f"{float(row[field]):.1f}" if row[field] is not None else ' N/A')
            except:
                raw_vals.append(' N/A')
        else:
            raw_vals.append(' N/A')

    score_str = '  '.join(f'{s:>7.3f}' for s in scores)
    raw_str   = '  '.join(f'{r:>7}' for r in raw_vals)
    print(f'{bank:<42}  {score_str}   <- health')
    print(f'{"(raw)":>42}  {raw_str}   <- actual %')
    print()

print("\nDanger point health scores (for reference):")
print("  tier1CAR @ RT1=9.5%:   ~0.500")
print("  totalCAR @ RT1=11.5%:  ~0.500")
print("  netNPA   @ RT1=6.0%:   ~0.700")
print("  all other features:     pop_max (~0.90-1.00)")
print()
print("Why HDFC/ICICI are far from the danger point:")
print("  Their tier1CAR (17-18%) and totalCAR (16-20%) transform to ~1.0")
print("  -> health vector is near (1.0, 1.0, 1.0, ...) in all 16 dimensions")
print("  -> In KPCA space this puts them the MAXIMUM distance from danger [0.5, 0.5, 0.7, 1.0, ...]")
print()
print("Why SBI is close to the danger point:")
print("  SBI tier1CAR=12.1% transforms to ~0.73 (only 260bps above RT1 trigger 9.5%)")
print("  -> Health vector partial match to danger's capital component (~0.5)")
print("  -> RBF kernel places SBI in the positive-PC1 cluster near the danger projection")
