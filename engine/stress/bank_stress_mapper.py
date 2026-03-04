"""
FUNDAMENTAL STRESS PIPELINE
=============================
Goal: Compute a single stress score per bank (latest year) from raw financial ratios,
incorporating multi-year trends so trajectory is reflected alongside current position.

A bank with NPA=5% trending toward 8% scores worse than one stable at 5%.

PIPELINE:
  Step 1  → Connect to MongoDB, fetch all bank documents
  Step 2  → Flatten into a (bank × year) DataFrame  [2023, 2024, 2025]
  Step 3  → Select key metrics across 4 categories
  Step 4  → Handle missing values
  Step 5  → Winsorize  (clip outliers at 5th / 95th percentile)
  Step 6  → Z-score    (makes all ratios scale-free and comparable)
  Step 7  → Flip sign  (for "lower is better" metrics so high z = high stress)
  Step 8  → Trend features  (per-metric slope across years; positive = worsening)
  Step 9  → PCA on [latest-year z-scores + trend slopes]  (16 features)
  Step 10 → Output fundamental stress score S(bank) in [0, 1] for LATEST_YEAR
"""

import os
import pandas as pd
import numpy as np
from pymongo import MongoClient
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.impute import SimpleImputer
from dotenv import load_dotenv
import warnings
warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────
# CONFIGURATION — loaded from .env file
# ─────────────────────────────────────────────
# Expected .env variables:
#   MONGO_URI   = mongodb+srv://...   (or mongodb://localhost:27017/)
#   DB_NAME     = financial_kg
#   COLLECTION  = performance_metrics


load_dotenv(dotenv_path=os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env'))

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("MONGO_DB")
COLLECTION = os.getenv("MONGO_COLLECTION")


if not all([MONGO_URI, DB_NAME, COLLECTION]):
    raise EnvironmentError(
        "Missing one or more required .env variables: MONGO_URI, DB_NAME, COLLECTION"
    )

# All years used for trend computation
YEARS = ["2023", "2024", "2025"]
# The year whose stress score is output (must be last in YEARS)
LATEST_YEAR = "2025"

METRICS = {
    # ASSET QUALITY
    # ✓ Ratio — NPA as % of advances, size-neutral
    "Net NPA as % to Net Advances": -1,   # lower is better
    # ✗ REMOVED: "Gross NPA" — absolute rupee value, large banks always score worse
    #   purely because they have more loans, not because they are more stressed.
    #   Example: Canara Bank had Gross NPA 46k crore vs IDFC 3.8k crore,
    #   making Canara look maximally stressed even though its NPA % was lower.

    # CAPITAL ADEQUACY
    # ✓ Ratio — regulatory capital buffer as % of risk-weighted assets, size-neutral
    "Capital Adequacy Ratio (Basel-III)": +1,   # higher is better
    # ✓ Ratio — how much of bad loans are already covered by provisions
    "Provision Coverage Ratio (%)": +1,   # higher is better

    # LIQUIDITY
    # ✓ Ratio — how aggressively deposits are lent out
    "Credit Deposit Ratio": -1,   # too high = overleveraged
    # ✓ Ratio — investment buffer relative to deposits
    "Investment Deposit Ratio": +1,   # higher = more buffer

    # PROFITABILITY & RETURNS
    # ✓ Ratio — return relative to total asset base, size-neutral
    "Return on Assets (%)": +1,   # higher is better
    # ✓ Ratio — net interest margin relative to assets, size-neutral
    "Spread as % of Total Assets": +1,   # higher is better
    # ✗ REMOVED: "Net Profit" — absolute rupee value, large banks always dominate.
    #   HDFC Net Profit 60k crore vs IDFC 2.4k crore → size bias, not stress signal.

    # COST EFFICIENCY
    # ✓ Ratio — operating cost as share of total expenses, size-neutral
    "Operating Expenses as % to Total Expenses": -1,   # lower is better
}


# ─────────────────────────────────────────────
# STEP 1: FETCH DATA FROM MONGODB
# ─────────────────────────────────────────────

def fetch_data():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    coll = db[COLLECTION]
    docs = list(coll.find({}, {"_id": 0}))
    print(f"✓ Fetched {len(docs)} bank documents from MongoDB")
    return docs


# ─────────────────────────────────────────────
# STEP 2: FLATTEN INTO DATAFRAME
# ─────────────────────────────────────────────

def flatten_to_dataframe(docs):
    """
    Each MongoDB doc = one bank.
    Keys inside doc = years ("2023", "2024", ...) + "Bank Name".
    We produce one row per (bank, year).
    """
    rows = []

    for doc in docs:
        bank_name = doc.get("Bank Name", "Unknown")

        for year in YEARS:
            if year not in doc:
                continue

            year_data = doc[year]
            if not isinstance(year_data, dict):
                continue

            row = {"bank": bank_name, "year": int(year)}
            for metric in METRICS:
                row[metric] = year_data.get(metric, np.nan)

            rows.append(row)

    df = pd.DataFrame(rows)
    print(f"✓ Flattened to DataFrame: {df.shape[0]} rows (bank-year pairs)")
    print(f"  Banks  : {df['bank'].nunique()}")
    print(f"  Years  : {sorted(df['year'].unique())}")
    return df


# ─────────────────────────────────────────────
# STEP 3: HANDLE MISSING VALUES
# ─────────────────────────────────────────────

def handle_missing(df):
    """
    Impute missing metrics with the cross-sectional median for that year.
    Conservative: missing = average, not stressed, not healthy.
    """
    metric_cols = list(METRICS.keys())

    missing_pct = df[metric_cols].isnull().mean() * 100
    has_missing = missing_pct[missing_pct > 0]
    if len(has_missing):
        print("\n── Missing Value Report ──────────────────────")
        for col, pct in has_missing.items():
            print(f"  {col:<50}: {pct:.1f}% missing → imputed with yearly median")

    for year in df["year"].unique():
        mask = df["year"] == year
        for col in metric_cols:
            med = df.loc[mask, col].median()
            df.loc[mask & df[col].isnull(), col] = med

    print("✓ Missing values handled")
    return df


# ─────────────────────────────────────────────
# STEP 4: WINSORIZE — CLIP OUTLIERS
# ─────────────────────────────────────────────

def winsorize(df, lower=0.05, upper=0.95):
    """
    WHY: One distressed bank with NPA=40% inflates the std for the whole year.
    After inflation, all other banks cluster near 0 → differences disappear.
    Winsorizing prevents this by capping at 5th/95th percentile within each year.
    """
    metric_cols = list(METRICS.keys())

    for year in df["year"].unique():
        mask = df["year"] == year
        for col in metric_cols:
            lo = df.loc[mask, col].quantile(lower)
            hi = df.loc[mask, col].quantile(upper)
            df.loc[mask, col] = df.loc[mask, col].clip(lower=lo, upper=hi)

    print(
        f"✓ Winsorized at [{lower*100:.0f}th–{upper*100:.0f}th] percentile per year")
    return df


# ─────────────────────────────────────────────
# STEP 5: Z-SCORE NORMALIZATION (per year)
# ─────────────────────────────────────────────

def zscore_normalize(df):
    """
    WHY per year: The "healthy" level of NPA in 2023 may differ from 2025.
    Normalizing within each year means we always compare a bank to its contemporaries.

    RESULT: Change of 0.1→0.2 on a 0-1 scale and change of 10→11 on a 10-20 scale
    are now BOTH measured in standard deviations → directly comparable.
    """
    metric_cols = list(METRICS.keys())

    for year in df["year"].unique():
        mask = df["year"] == year
        scaler = StandardScaler()
        df.loc[mask, metric_cols] = scaler.fit_transform(
            df.loc[mask, metric_cols])

    print("✓ Z-score normalization applied per year (all metrics now scale-free)")
    return df


# ─────────────────────────────────────────────
# STEP 6: FLIP SIGNS
# ─────────────────────────────────────────────

def flip_signs(df):
    """
    After z-scoring we need a consistent direction: HIGH = MORE STRESSED.

    "Higher is better" metric (e.g. CAR, ROA):
        A LOW z-score means the bank is BELOW average → STRESSED
        → multiply by -1 so low becomes high (= stressed)

    "Lower is better" metric (e.g. NPA, OpEx%):
        A HIGH z-score means the bank is ABOVE average → STRESSED
        → keep as-is (multiply by -1 of direction=-1 gives +1, no change)

    Formula: stressed_z = z * (-1 * direction)
        direction = +1 → stressed_z = -z  (flip)
        direction = -1 → stressed_z = +z  (keep)
    """
    for metric, direction in METRICS.items():
        df[metric] = df[metric] * (-1 * direction)

    print("✓ Signs aligned: HIGH value = HIGH STRESS for all metrics")
    return df


# ─────────────────────────────────────────────
# STEP 8: TREND FEATURES (slope across years)
# ─────────────────────────────────────────────

def compute_trend_features(df):
    """
    For each bank, fit a linear slope over the z-scored, sign-flipped metric values
    across all available years.

    Slope > 0  →  metric is getting more stressed over time  (worsening trend)
    Slope < 0  →  metric is improving over time              (recovery trend)
    Slope = 0  →  stable or only one year of data available

    WHY from z-scores (not raw values):
    The z-scores already account for year-level differences in what "normal" means,
    so the slope captures relative deterioration vs. peers rather than
    absolute level changes that might just reflect the industry moving together.
    """
    metric_cols = list(METRICS.keys())
    year_list = sorted(df["year"].unique())
    year_idx = {y: i for i, y in enumerate(year_list)}

    trend_rows = []
    for bank in df["bank"].unique():
        bank_data = df[df["bank"] == bank].sort_values("year")
        xs = np.array([year_idx[y]
                      for y in bank_data["year"].values], dtype=float)

        trend_row = {"bank": bank}
        for metric in metric_cols:
            vals = bank_data[metric].values.astype(float)
            valid = ~np.isnan(vals)
            if valid.sum() >= 2:
                slope = np.polyfit(xs[valid], vals[valid], 1)[0]
            else:
                slope = 0.0
            trend_row[f"trend_{metric}"] = slope

        trend_rows.append(trend_row)

    trend_df = pd.DataFrame(trend_rows)
    print(f"✓ Trend features computed for {len(trend_df)} banks "
          f"(slope of z-scores across {year_list})")
    return trend_df


# ─────────────────────────────────────────────
# STEP 9: PCA — COMPUTE STRESS SCORE
# ─────────────────────────────────────────────

def compute_pca_stress(df, trend_df):
    """
    Runs PCA on a 16-feature matrix per bank:
      - 8 current-position features: z-scored metrics for LATEST_YEAR
      - 8 trend features: per-metric slope across all YEARS

    WHY PCA instead of fixed weights:
    - Avoids arbitrary weights like "NPA=30%, CAR=20%"
    - Correlated metrics (ROA and Net Profit) get combined, not double-counted
    - PC1 = direction of maximum variance = the main "stress axis" in the data

    WHY include trends:
    - A bank at NPA=5% heading toward 8% is riskier than one stable at 5%
    - Trend features let the model penalise deterioration and reward recovery
    - Slopes are computed on z-scores so they reflect relative moves vs. peers,
      not absolute level shifts driven by industry-wide macro changes
    """
    metric_cols = list(METRICS.keys())
    trend_cols = [f"trend_{m}" for m in metric_cols]

    # ── Take only LATEST_YEAR snapshot ────────────────────────────────────────
    latest = df[df["year"] == int(LATEST_YEAR)].copy()

    # ── Merge trend features ───────────────────────────────────────────────────
    combined = latest.merge(trend_df, on="bank", how="left")
    combined[trend_cols] = combined[trend_cols].fillna(0.0)

    # ── Standardize trend features (snapshot features are already z-scored) ───
    scaler = StandardScaler()
    combined[trend_cols] = scaler.fit_transform(combined[trend_cols])

    # ── Build feature matrix ───────────────────────────────────────────────────
    all_features = metric_cols + trend_cols
    X = combined[all_features].values
    X = SimpleImputer(strategy="median").fit_transform(X)

    pca = PCA(n_components=min(len(all_features), X.shape[0]))
    pca.fit(X)

    stress_scores = pca.transform(X)[:, 0]

    # Ensure direction: NPA should load POSITIVELY (high NPA = high stress)
    npa_idx = all_features.index("Net NPA as % to Net Advances")
    if pca.components_[0][npa_idx] < 0:
        stress_scores = -stress_scores
        components_0 = -pca.components_[0]
    else:
        components_0 = pca.components_[0]

    combined["fundamental_stress"] = stress_scores

    explained = pca.explained_variance_ratio_[0] * 100
    print(f"\n✓ PCA complete  (16 features: 8 snapshot + 8 trend)")
    print(f"  PC1 explains {explained:.1f}% of total variance")

    # ── Loadings ───────────────────────────────────────────────────────────────
    loadings = pd.Series(
        components_0, index=all_features).sort_values(ascending=False)
    print("\n── PC1 Loadings (positive = stress driver) ───────────────────────────")
    for feat, loading in loadings.items():
        bar = "█" * int(abs(loading) * 20)
        sign = "+" if loading >= 0 else "-"
        label = f"[trend] {feat[6:]}" if feat.startswith("trend_") else feat
        print(f"  {sign}{bar:<22} {loading:+.3f}  {label}")

    return combined, loadings


# ─────────────────────────────────────────────
# STEP 10: NORMALIZE TO [0, 1]
# ─────────────────────────────────────────────

def normalize_stress_score(df):
    """
    Min-max across the full universe so:
        0.0 = least stressed bank
        1.0 = most stressed bank
    This is the S(bank) you plug into the contagion model as initial shock.
    """
    s = df["fundamental_stress"]
    df["fundamental_stress_normalized"] = (s - s.min()) / (s.max() - s.min())
    print("\n✓ Final stress score normalized to [0, 1]")
    return df


# ─────────────────────────────────────────────
# STEP 11: SAVE RESULTS
# ─────────────────────────────────────────────

def save_results(df):
    # ── Save to CSV ───────────────────────────────────────────────────────────
    output_cols = ["bank", "year", "fundamental_stress",
                   "fundamental_stress_normalized"]
    output_df = df[output_cols].sort_values(
        "fundamental_stress_normalized", ascending=False)

    csv_path = "fundamental_stress_scores.csv"
    output_df.to_csv(csv_path, index=False)
    print(f"✓ Saved {len(output_df)} records → {csv_path}")

    # ── Push to MongoDB (commented out — uncomment when ready) ───────────────
    # client = MongoClient(MONGO_URI)
    # db     = client[DB_NAME]
    # coll   = db["stress_scores"]
    # coll.drop()
    # records = output_df.to_dict("records")
    # coll.insert_many(records)
    # print(f"✓ Saved {len(records)} records → MongoDB collection: 'stress_scores'")

    # ── Print ranked table ────────────────────────────────────────────────────
    ranked = output_df.reset_index(drop=True)
    print(
        f"\n── Fundamental Stress Rankings  [{LATEST_YEAR}, trend-adjusted]  ─────")
    print(f"  {'Rank':<5} {'Bank':<40} {'Score':>8}  {'Bar'}")
    print(f"  {'─'*5} {'─'*40} {'─'*8}  {'─'*20}")
    for i, row in ranked.iterrows():
        bar = "▓" * int(row["fundamental_stress_normalized"] * 20)
        print(
            f"  {i+1:<5} {row['bank']:<40} {row['fundamental_stress_normalized']:>8.4f}  {bar}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def run_pipeline():
    print("=" * 65)
    print("  FUNDAMENTAL STRESS PIPELINE  (for contagion model)")
    print(f"  Training years: {YEARS}  →  scoring year: {LATEST_YEAR}")
    print("=" * 65)

    docs = fetch_data()
    df = flatten_to_dataframe(docs)
    df = handle_missing(df)
    df = winsorize(df)
    df = zscore_normalize(df)
    df = flip_signs(df)
    trend_df = compute_trend_features(df)          # new: slopes from all years
    df, loadings = compute_pca_stress(
        df, trend_df)  # new: LATEST_YEAR + trends
    df = normalize_stress_score(df)
    save_results(df)

    print("\n" + "=" * 65)
    print(f"  DONE — use df['fundamental_stress_normalized'] as")
    print(f"  your initial shock vector S(bank) in contagion.")
    print("=" * 65)

    return df, loadings


if __name__ == "__main__":
    df, loadings = run_pipeline()
