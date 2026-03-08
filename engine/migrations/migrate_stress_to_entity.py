import pandas as pd
import sys
from pymongo import MongoClient  # Uncomment for MongoDB

# ─────────────────────────────────────────────
# CONFIG — update paths as needed
# ─────────────────────────────────────────────
NEWS_STRESS_CSV       = "../../data/outputs/news_stress_scores.csv"
FUNDAMENTAL_STRESS_CSV = "../../data/outputs/entity_stress_scores.csv"
OUTPUT_CSV            = "../../data/outputs/stress_scores_mapped.csv"

# ─────────────────────────────────────────────
# LOAD CSVs
# ─────────────────────────────────────────────
try:
    df_news = pd.read_csv(NEWS_STRESS_CSV)
    print(f"[✓] Loaded news stress CSV       — {len(df_news)} rows")
except FileNotFoundError:
    print(f"[✗] File not found: {NEWS_STRESS_CSV}")
    sys.exit(1)

try:
    df_fund = pd.read_csv(FUNDAMENTAL_STRESS_CSV)
    print(f"[✓] Loaded fundamental stress CSV — {len(df_fund)} rows")
except FileNotFoundError:
    print(f"[✗] File not found: {FUNDAMENTAL_STRESS_CSV}")
    sys.exit(1)

# ─────────────────────────────────────────────
# NORMALISE COMPANY CODE COLUMNS
# ─────────────────────────────────────────────
# CSV-1 uses "company_code", CSV-2 uses "companyCode"
df_news = df_news.rename(columns={"company_code": "companyCode"})

df_news["companyCode"] = df_news["companyCode"].astype(str).str.strip().str.upper()
df_fund["companyCode"] = df_fund["companyCode"].astype(str).str.strip().str.upper()

# ─────────────────────────────────────────────
# EXTRACT ONLY WHAT WE NEED
# ─────────────────────────────────────────────
news_scores = (
    df_news[["companyCode", "stress_score"]]
    .dropna(subset=["companyCode", "stress_score"])
    .drop_duplicates(subset="companyCode")
    .rename(columns={"stress_score": "news_stress"})
)

fund_scores = (
    df_fund[["companyCode", "stressScore"]]
    .dropna(subset=["companyCode", "stressScore"])
    .drop_duplicates(subset="companyCode")
    .rename(columns={"stressScore": "entity_stress_fundamental"})
)

# ─────────────────────────────────────────────
# MERGE ON companyCode
# ─────────────────────────────────────────────
merged = pd.merge(news_scores, fund_scores, on="companyCode", how="outer")
print(f"\n[✓] Merged — {len(merged)} unique company codes with at least one stress score")

# Quick preview
print("\n──── Sample (first 10 rows) ────")
print(merged.head(10).to_string(index=False))

# Stats
n_both    = merged[["news_stress", "entity_stress_fundamental"]].notna().all(axis=1).sum()
n_news    = merged["news_stress"].notna().sum()
n_fund    = merged["entity_stress_fundamental"].notna().sum()
print(f"\n  Companies with BOTH scores      : {n_both}")
print(f"  Companies with news_stress only  : {n_news - n_both}")
print(f"  Companies with fund_stress only  : {n_fund - n_both}")

# ─────────────────────────────────────────────
# SAVE PREVIEW CSV
# ─────────────────────────────────────────────
merged.to_csv(OUTPUT_CSV, index=False)
print(f"\n[✓] Output saved → {OUTPUT_CSV}")


# ═════════════════════════════════════════════
# MONGODB UPDATE — uncomment when ready
# ═════════════════════════════════════════════

MONGO_URI = "mongodb+srv://prabirkalwani:prabirkalwani%40123@maincluster.tvef4tx.mongodb.net/"
DB_NAME   = "financial_kg"
COLL_NAME = "companies"

client = MongoClient(MONGO_URI)
coll   = client[DB_NAME][COLL_NAME]

updated_count = 0
skipped_count = 0

for _, row in merged.iterrows():
    company_code = row["companyCode"]
    update_fields = {}

    if pd.notna(row.get("news_stress")):
        update_fields["news_stress"] = float(row["news_stress"])

    if pd.notna(row.get("entity_stress_fundamental")):
        update_fields["entity_stress_fundamental"] = float(row["entity_stress_fundamental"])

    if not update_fields:
        skipped_count += 1
        continue

    result = coll.update_one(
        {"companyCode": company_code},
        {"$set": update_fields}
    )

    if result.matched_count:
        updated_count += 1
    else:
        print(f"  [!] No document found for companyCode: {company_code}")
        skipped_count += 1

print(f"\n[MongoDB] Updated : {updated_count}")
print(f"[MongoDB] Skipped : {skipped_count}")
client.close()