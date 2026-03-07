"""
Task 11: RBI-Anchored Kernel Manifold Stress Score (RKMSS)
===========================================================
Computes a novel bank stress score in [0, 1] for all Indian SCBs in the
ratios dataset, combining:

  1. RBI-Threshold-Anchored Non-Linear Feature Transforms
     — Each ratio is mapped through a monotone non-linear function calibrated
       to RBI's Prompt Corrective Action (PCA) thresholds. This encodes
       regime-like, non-linear risk behaviour (e.g., NPA cliff at 6/9/12%)
       before any dimensionality reduction.

  2. Kernel PCA (RBF kernel) on Transformed Features
     — Captures non-linear inter-ratio correlations and finds the low-
       dimensional manifold of the 41-bank ratio space. Works robustly at N=41.

  3. Merton DTD Soft-Label Orientation (Ridge Regression)
     — Uses Merton Distance-to-Default ranks (from task10) as ordinal soft
       labels to identify the direction in PC space that best correlates
       with market-implied stress. Rotates the manifold so PC1 ≈ "stress axis".

  4. RBI Danger Boundary Projection
     — The RBI PCA threshold vector is projected into the KPCA manifold via
       kernel out-of-sample transform. Distance to this danger point in
       manifold space gives a boundary-relative stress measure.

  5. CAMELS-Informed Weighted Aggregation
     — Final stress score is a weighted blend of:
         (a) manifold distance to danger boundary  (structural)
         (b) Merton-oriented PC1 stress direction  (market-calibrated)
         (c) Raw CAMELS composite score            (interpretable baseline)
     — Weights can be tuned via BLEND_WEIGHTS.

Architecture reference: See docs/stress_score_architecture.md for full diagram.

RBI PCA Triggers (post-Jan 2022 revision, Master Direction effective 2022-01-01):
  Capital:      CRAR < 11.5% (RT1), < 9.0% (RT2), < 7.5% (RT3)  [anchored to 2.5% CCB]
                Tier1 < 9.5% (RT1), < 8.0% (RT2), < 6.5% (RT3)
  Asset Quality: Net NPA > 6% (RT1), > 9% (RT2), > 12% (RT3)
  Leverage:     Tier1 Leverage < 3.5% (RT1), < 3.0% (RT2), < 2.5% (RT3)
  Note: ROA was REMOVED from PCA framework in 2022 revision.
        CDR, NIM, cost metrics are CAMELS supervisory benchmarks, NOT PCA triggers.

Output:
  - Saved to: data_consolidation/data/outputs/stress_scores.json
  - MongoDB update (optional): adds stressScore field to each bank document
  - Returns dict: { bank_excel_name: StressResult }
"""

import os
import sys
import json
import warnings
import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.stats import rankdata
from scipy.spatial.distance import mahalanobis
from sklearn.decomposition import KernelPCA
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge

# ── Path setup ────────────────────────────────────────────────────────────────
_BANK_SCRIPTS_DIR = os.path.dirname(__file__)
if _BANK_SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _BANK_SCRIPTS_DIR)

from config import DATA_PATHS, MONGODB_URI, DB_NAME, COLLECTION_NAME, \
    SCB_NSE_TICKER_MAP, is_scb_bank, _normalize_bank_name

# ── Output paths ──────────────────────────────────────────────────────────────
_DATA_CONSOLIDATION_DIR = os.path.dirname(os.path.dirname(os.path.dirname(_BANK_SCRIPTS_DIR)))
OUTPUT_DIR = os.path.join(_DATA_CONSOLIDATION_DIR, "data", "outputs")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "stress_scores.json")
MERTON_FILE = os.path.join(OUTPUT_DIR, "merton_soft_labels.json")


# ─────────────────────────────────────────────────────────────────────────────
# OFFICIAL RBI PCA Triggers (post-Jan 2022 revision)
# Source: RBI Master Direction on Prompt Corrective Action, effective 2022-01-01
#
# USED ONLY for: build_danger_vector() → the regulatory danger boundary point
# in KPCA space. Only these three pillars (Capital, Asset Quality, Leverage)
# are used to define where "stress = 1.0" in the regulatory sense.
#
# All other ratios (CDR, NIM, ROA, cost metrics) are CAMELS supervisory
# benchmarks below — they carry signal for KPCA but do NOT anchor the
# danger boundary.
# ─────────────────────────────────────────────────────────────────────────────

RBI_PCA_TRIGGERS = {
    # ── PILLAR 1: CAPITAL ADEQUACY ────────────────────────────────────────────
    # Anchored to fully-phased CCB of 2.5% (effective since March 2020).
    # CRAR minimum = 9.0% + 2.5% CCB = 11.5%
    # RT1: up to 250 bps below 11.5% → CRAR in [9.0%, 11.5%)
    # RT2: 250–400 bps below       → CRAR in [7.5%, 9.0%)
    # RT3: > 400 bps below         → CRAR < 7.5%
    "totalCAR": {
        "RT1": 11.5, "RT2": 9.0, "RT3": 7.5,
        "optimal": 16.0, "direction": "higher_better",
    },
    # Tier 1 CAR (prescribed minimum = 7.0% + 2.5% CCB = 9.5% required):
    # RT1: up to 250 bps below 9.5% → Tier1 in [7.0%, 9.5%)  → RT2 boundary = 7.0%
    # RT2: 250–400 bps below 9.5% → Tier1 in [5.5%, 7.0%)   → RT3 boundary = 5.5%
    # RT3: > 400 bps below 9.5%   → Tier1 < 5.5%
    # (Note: CET1 is separately tracked at 8.0% required, but our dataset
    #  only has Tier1 CAR, so we use the Tier1 minimum as the anchor.)
    "tier1CAR": {
        "RT1": 9.5, "RT2": 7.0, "RT3": 5.5,
        "optimal": 14.0, "direction": "higher_better",
    },

    # ── PILLAR 2: ASSET QUALITY ───────────────────────────────────────────────
    # Retained unchanged in 2022 revision. Piecewise logic in transform_ratio()
    # handles the cliff correctly.
    "netNPAToNetAdvances": {
        "RT1": 6.0, "RT2": 9.0, "RT3": 12.0,
        "optimal": 0.5, "direction": "lower_better",
    },

    # ── PILLAR 3: LEVERAGE ────────────────────────────────────────────────────
    # Added in 2022 revision. Minimum Tier 1 Leverage = 3.5%
    # (4.0% for D-SIBs: SBI, HDFC Bank, ICICI Bank)
    # NOTE: This column does NOT exist in ratios_all_banks.xlsx.
    # It is declared here for completeness but will be gracefully skipped
    # in build_transformed_matrix() (60% coverage threshold will exclude it).
    "tier1Leverage": {
        "RT1": 3.5, "RT2": 3.0, "RT3": 2.5,
        "optimal": 6.0, "direction": "higher_better",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# CAMELS Supervisory Heuristic Thresholds (NON-PCA)
#
# These are used by transform_ratio() to produce [0,1] health scores for
# the KPCA feature matrix and CAMELS composite score.
# They are NOT used to anchor the danger boundary in KPCA space.
#
# Sources: RBI Handbook of Statistics, SEBI CAMELS guidance, industry norms.
# ROA is here (not in PCA triggers) because the 2022 RBI revision explicitly
# removed it from the PCA framework to avoid disincentivising provisioning.
# ─────────────────────────────────────────────────────────────────────────────

CAMELS_HEURISTIC_THRESHOLDS = {
    # EARNINGS
    "returnOnAssets":               {"floor": 0.0,   "optimal": 1.5,  "direction": "higher_better"},
    "returnOnEquity":               {"floor": 0.0,   "optimal": 18.0, "direction": "higher_better"},
    "operatingProfitsToTotalAssets":{"floor": 0.0,   "optimal": 2.5,  "direction": "higher_better"},
    "netInterestMargin":            {"floor": 1.5,   "optimal": 3.5,  "direction": "higher_better"},
    "returnOnAdvances":             {"floor": 4.0,   "optimal": 9.0,  "direction": "higher_better"},
    "returnOnInvestments":          {"floor": 4.0,   "optimal": 8.0,  "direction": "higher_better"},
    "interestIncomeToTotalAssets":  {"floor": 4.0,   "optimal": 8.0,  "direction": "higher_better"},
    "nonInterestIncomeToTotalAssets":{"floor": 0.0,  "optimal": 1.5,  "direction": "higher_better"},
    # LIQUIDITY
    "cashDepositRatio":             {"floor": 3.0,   "optimal": 6.0,  "direction": "higher_better"},
    "creditDepositRatio":           {"floor": 55.0,  "ceiling": 85.0, "optimal": 72.0, "direction": "sweet_spot"},
    "investmentDepositRatio":       {"ceiling": 45.0,"optimal": 27.0, "direction": "lower_better"},
    # COST / EFFICIENCY
    "burdenToTotalAssets":           {"ceiling": 2.5, "optimal": 0.5,  "direction": "lower_better"},
    "intermediationCostToTotalAssets":{"ceiling": 3.5,"optimal": 1.5,  "direction": "lower_better"},
    "wageBillsToTotalExpense":       {"ceiling": 55.0,"optimal": 35.0, "direction": "lower_better"},
    # COST OF FUNDS
    "costOfFunds":                   {"ceiling": 7.5, "optimal": 4.0,  "direction": "lower_better"},
    "costOfDeposits":                {"ceiling": 7.0, "optimal": 3.5,  "direction": "lower_better"},
}

# ── CAMELS Dimension Groupings & Regulatory Weights ──────────────────────────
# Keys must match ratio field names as stored in the MongoDB/Excel structure.
CAMELS_GROUPS = {
    "Capital": {
        "weight": 0.25,
        "ratios": ["totalCAR", "tier1CAR"],
    },
    "AssetQuality": {
        "weight": 0.30,  # Highest — NPA is the primary systematic risk driver
        "ratios": ["netNPAToNetAdvances"],
    },
    "Management": {
        "weight": 0.10,
        "ratios": ["wageBillsToTotalExpense", "intermediationCostToTotalAssets"],
    },
    "Earnings": {
        "weight": 0.20,
        "ratios": ["returnOnAssets", "returnOnEquity", "netInterestMargin",
                   "operatingProfitsToTotalAssets"],
    },
    "Liquidity": {
        "weight": 0.10,
        "ratios": ["cashDepositRatio", "creditDepositRatio", "investmentDepositRatio"],
    },
    "Sensitivity": {
        "weight": 0.05,
        "ratios": ["costOfFunds", "burdenToTotalAssets"],
    },
}

# ── Final Blend Weights ───────────────────────────────────────────────────────
# Blend of three complementary signals to form the final stress score.
BLEND_WEIGHTS = {
    "danger_boundary_distance": 0.40,  # RBI-anchored manifold distance (structural)
    "merton_oriented_pc1":      0.35,  # Market-calibrated stress axis
    "camels_composite":         0.25,  # Interpretable regulatory baseline
}

# KPCA Configuration
# Optimised via analysis_kpca_optimization.ipynb (grid search: nc × gamma).
# nc=10, gamma=0.0681 yielded Spearman ρ=0.535 vs nc=3/auto (ρ=0.324) —
# a +0.204 improvement in Merton-orientation quality.
KPCA_N_COMPONENTS = 10
KPCA_KERNEL = "rbf"
KPCA_GAMMA = 0.06812920690579612  # Optimal from nc×gamma grid search


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Load Ratios for ALL Banks in the Dataset
# ─────────────────────────────────────────────────────────────────────────────

# Flat mapping: field_name → Excel column name (from task3_ratios.py)
# This list defines the universe of features used in RKMSS.
RATIO_COLUMNS = {
    "cashDepositRatio":                  "1.  Cash - Deposit Ratio",
    "creditDepositRatio":                "2.  Credit - Deposit Ratio",
    "investmentDepositRatio":            "3.  Investment - Deposit Ratio",
    "interestIncomeToTotalAssets":       "11.  Ratio of interest income to total assets",
    "netInterestMargin":                 "12.  Ratio of net interest income to total assets (Net Interest Margin)",
    "nonInterestIncomeToTotalAssets":    "13.  Ratio of non-interest income to total assets",
    "intermediationCostToTotalAssets":   "14.  Ratio of intermediation cost to total assets",
    "wageBillsToTotalExpense":           "16.  Ratio of wage bills to total expense",
    "burdenToTotalAssets":               "18.  Ratio of burden to total assets",
    "operatingProfitsToTotalAssets":     "20.  Ratio of operating profits to total assets",
    "returnOnAssets":                    "21.  Return on assets",
    "returnOnEquity":                    "22.  Return on equity",
    "costOfDeposits":                    "23.  Cost of deposits",
    "costOfFunds":                       "25.  Cost of funds",
    "returnOnAdvances":                  "26.  Return on advances",
    "returnOnInvestments":               "27.  Return on investments",
    "totalCAR":                          "32.  Capital adequacy ratio",
    "tier1CAR":                          "33. Capital adequacy ratio - Tier I",
    "netNPAToNetAdvances":               "35.  Ratio of net NPA To net advances",
}

# Subset of ratios that are reliably populated across all 41 NSE-listed Indian SCBs
# (payments banks / small-finance banks may have partial coverage).
# Tightened further by missing-value handling in load_ratios_dataframe().
CORE_RATIOS = [
    "cashDepositRatio", "creditDepositRatio", "investmentDepositRatio",
    "netInterestMargin", "intermediationCostToTotalAssets",
    "wageBillsToTotalExpense", "burdenToTotalAssets",
    "operatingProfitsToTotalAssets", "returnOnAssets", "returnOnEquity",
    "costOfFunds", "returnOnAdvances", "returnOnInvestments",
    "totalCAR", "tier1CAR", "netNPAToNetAdvances",
]

# Banks are now filtered via the SCB_NSE_TICKER_MAP allowlist in config.py
# (sourced from tier1_cap.csv).  The previous exclusion blocklist below has
# been removed — only the 41 listed SCBs in SCB_NSE_TICKER_MAP are processed.


def load_ratios_dataframe(year: str = "2025") -> pd.DataFrame:
    """
    Load ratios from Excel for all banks in the given year.
    Returns a DataFrame with bank names as index and ratio fields as columns.
    Excludes foreign branches and payments banks.
    """
    df_raw = pd.read_excel(DATA_PATHS["ratios"], sheet_name="Report 1")

    # Parse header structure (matches task3_ratios.py convention)
    clean = df_raw.iloc[5:].copy()
    clean.columns = clean.iloc[0]
    clean = clean.iloc[1:].reset_index(drop=True)
    clean["Year"] = clean["Year"].ffill()
    clean["Year_str"] = clean["Year"].astype(str).str.strip()
    clean["Bank_clean"] = clean["Bank"].astype(str).str.strip()

    df_year = clean[clean["Year_str"] == year].copy()

    # Extract all ratio columns we care about
    records = []
    for _, row in df_year.iterrows():
        bank_name = row["Bank_clean"]

        # Include only banks present in the SCB_NSE_TICKER_MAP allowlist
        # (replaces the former EXCLUDE_BANKS_CONTAINING blocklist)
        if not is_scb_bank(bank_name):
            continue

        record = {"bankName": bank_name}
        for field, col_name in RATIO_COLUMNS.items():
            val = row.get(col_name)
            try:
                record[field] = float(val) if not pd.isna(val) and val not in ["-", ""] else None
            except (ValueError, TypeError):
                record[field] = None

        records.append(record)

    df = pd.DataFrame(records).set_index("bankName")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Non-Linear Feature Transforms (RBI-Anchored)
# ─────────────────────────────────────────────────────────────────────────────

def _sigmoid(x: float, center: float, scale: float) -> float:
    """Sigmoid centred at `center` with steepness `scale`. Returns [0,1]."""
    return 1.0 / (1.0 + math.exp((x - center) / scale))


def _gaussian_penalty(x: float, optimal: float, sigma: float) -> float:
    """Gaussian bowl centred at `optimal`. Returns 1 at optimal, decays outward."""
    return math.exp(-((x - optimal) ** 2) / (2 * sigma ** 2))


def _get_threshold_cfg(field: str) -> Optional[dict]:
    """
    Looks up threshold config for a ratio field.
    Checks RBI_PCA_TRIGGERS first (official), then CAMELS_HEURISTIC_THRESHOLDS.
    Returns None if the field has no defined thresholds.
    """
    return RBI_PCA_TRIGGERS.get(field) or CAMELS_HEURISTIC_THRESHOLDS.get(field)


def transform_ratio(field: str, value: Optional[float]) -> float:
    """
    Apply a monotone non-linear transform to a single ratio value.

    Returns a HEALTH score in [0, 1]:
      0.0 = maximally stressed / dangerous
      1.0 = maximally healthy

    Stress score (used downstream) = 1 - health score.
    This is kept separate to allow CAMELS decomposition.

    Threshold lookup order: RBI_PCA_TRIGGERS → CAMELS_HEURISTIC_THRESHOLDS
    Transform logic per ratio:
      - NPA (lower_better, PCA): piecewise linear across RBI RT1/RT2/RT3 thresholds
        → encodes the regulatory cliff effect
      - CAR / Leverage (higher_better, PCA): sigmoid centred on RT1 trigger
      - CDR (sweet_spot, CAMELS): Gaussian bowl centred on optimal
      - All other higher_better: sigmoid centred on floor
      - All other lower_better: sigmoid centred on ceiling
    """
    if value is None:
        return 0.5  # Unknown → neutral

    cfg = _get_threshold_cfg(field)
    if cfg is None:
        return 0.5  # No threshold defined → neutral

    direction = cfg.get("direction", "higher_better")
    optimal = cfg.get("optimal", None)

    # ── NPA: custom piecewise — encodes regulatory cliff at 6/9/12% ─────────
    if field == "netNPAToNetAdvances":
        # 0.00 → 0.50%  : 1.00 (excellent)
        # 0.50 → 6.00%  : linear decay 1.00 → 0.70   (approaching RT1)
        # 6.00 → 9.00%  : rapid decay  0.70 → 0.35   (RT1 crossed)
        # 9.00 → 12.0%  : steep decay  0.35 → 0.10   (RT2 crossed)
        # 12.0 → ∞      : cliff to ~0                 (RT3 crossed)
        if value <= 0.5:
            return 1.00
        elif value <= 6.0:
            return 1.00 - 0.30 * ((value - 0.5) / 5.5)
        elif value <= 9.0:
            return 0.70 - 0.35 * ((value - 6.0) / 3.0)
        elif value <= 12.0:
            return 0.35 - 0.25 * ((value - 9.0) / 3.0)
        else:
            return max(0.0, 0.10 - (value - 12.0) * 0.01)

    # ── Capital / Leverage (PCA pillars): sigmoid centred on RT1 ─────────────
    if field in ("totalCAR", "tier1CAR", "tier1Leverage") and direction == "higher_better":
        trigger = cfg.get("RT1", cfg.get("floor", 10.0))
        scale = (cfg.get("optimal", trigger * 1.5) - trigger) / 4.0
        scale = max(scale, 0.3)
        return 1.0 - _sigmoid(value, center=trigger, scale=scale)

    # ── Higher-is-better (CAMELS heuristics) ─────────────────────────────────
    if direction == "higher_better":
        trigger = cfg.get("RT1", cfg.get("RT2", cfg.get("floor", 0.0)))
        opt = optimal or max(trigger * 3, trigger + 1.0)
        scale = max((opt - trigger) / 4.0, 0.2)
        return 1.0 - _sigmoid(value, center=trigger, scale=scale)

    # ── CDR: Gaussian sweet-spot ──────────────────────────────────────────────
    if direction == "sweet_spot":
        opt = cfg.get("optimal", 72.0)
        floor_val = cfg.get("floor", 55.0)
        ceiling_val = cfg.get("ceiling", 85.0)
        sigma = (ceiling_val - floor_val) / 4.0
        return _gaussian_penalty(value, optimal=opt, sigma=sigma)

    # ── Lower-is-better (CAMELS heuristics) ──────────────────────────────────
    if direction == "lower_better":
        trigger = cfg.get("RT1", cfg.get("ceiling", cfg.get("RT2", None)))
        if trigger is None:
            return 0.5
        opt = optimal or 0.0
        scale = max((trigger - opt) / 4.0, 0.3)
        return _sigmoid(value, center=trigger, scale=scale)

    return 0.5  # fallback


def build_transformed_matrix(df: pd.DataFrame,
                               features: List[str]) -> Tuple[np.ndarray, List[str], List[str]]:
    """
    Apply non-linear transforms to every bank × ratio cell.

    Returns:
        X_health:  (n_banks, n_features) array of HEALTH scores in [0,1]
        bank_names: ordered list of bank names (rows)
        feat_names: ordered list of feature names (columns)
    """
    bank_names = list(df.index)

    # Filter to features that have data for ≥ 60% of banks
    valid_features = []
    for f in features:
        if f in df.columns:
            non_null = df[f].notna().sum()
            if non_null >= len(df) * 0.6:
                valid_features.append(f)

    X_health = np.zeros((len(bank_names), len(valid_features)))
    for j, feat in enumerate(valid_features):
        for i in range(len(bank_names)):
            raw = df.iloc[i][feat] if feat in df.columns else None
            # Force scalar — guard against Series returned by duplicate index
            if hasattr(raw, '__iter__') and not isinstance(raw, str):
                raw = next(iter(raw), None)
            try:
                val = float(raw) if raw is not None and not pd.isna(raw) else None
            except (TypeError, ValueError):
                val = None
            X_health[i, j] = transform_ratio(feat, val)

    return X_health, bank_names, valid_features


def build_danger_vector(features: List[str],
                         X_health: np.ndarray) -> np.ndarray:
    """
    Build the RBI official danger boundary point in transformed feature space.

    Design principle (optimal-anchor for non-PCA dimensions):
      For the 3 official RBI PCA pillars (Capital, Asset Quality, Leverage):
        → Use the RT1 threshold value transformed through transform_ratio().
          This is the exact regulatory intervention point.
      For all other CAMELS features (CDR, NIM, cost metrics, ROA, etc.):
        → Use the POPULATION MAXIMUM (best-observed health) of the transformed
          health scores.
          Rationale: "a bank exactly at the regulatory trigger, yet otherwise
          as efficient and profitable as the best bank in the sample."
          Using population mean placed the danger point inside the PSB cluster
          (PSBs dominate the sample), causing PSBs with healthy capital to
          appear falsely close to the danger boundary in KPCA space.  Using
          population max moves the danger point toward the "ideal bank" corner
          of feature space, so only banks genuinely close to the PCA thresholds
          on capital/NPA appear close to the danger point.

    Args:
        features:  ordered list of feature names (columns of X_health)
        X_health:  (n_banks, n_features) health score matrix for the population

    Returns:
        danger: (n_features,) health-score vector representing the danger boundary
    """
    # Pre-compute population max for non-PCA anchor
    pop_max = X_health.max(axis=0)  # shape (n_features,)

    danger = np.zeros(len(features))
    for j, feat in enumerate(features):
        is_pca_pillar = feat in RBI_PCA_TRIGGERS

        if is_pca_pillar:
            cfg = RBI_PCA_TRIGGERS[feat]
            direction = cfg.get("direction", "higher_better")

            # Use RT1 as the danger threshold value
            if direction == "higher_better":
                danger_val = cfg.get("RT1", cfg.get("floor", None))
            elif direction == "lower_better":
                danger_val = cfg.get("RT1", cfg.get("ceiling", None))
            elif direction == "sweet_spot":
                danger_val = cfg.get("floor", None)
            else:
                danger_val = None

            if danger_val is not None:
                danger[j] = transform_ratio(feat, danger_val)
            else:
                danger[j] = pop_max[j]  # fallback to population max
        else:
            # Non-PCA feature: anchor to best-observed health in population.
            # This ensures the danger point represents a bank that is borderline
            # on regulatory pillars but otherwise maximally efficient/profitable,
            # preventing PSB structural characteristics from artificially pulling
            # the danger boundary into the PSB cluster in KPCA space.
            danger[j] = pop_max[j]

    return danger


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Kernel PCA
# ─────────────────────────────────────────────────────────────────────────────

def fit_kpca(X: np.ndarray,
              n_components: int = KPCA_N_COMPONENTS,
              gamma: Optional[float] = KPCA_GAMMA) -> Tuple[KernelPCA, np.ndarray, float]:
    """
    Fit Kernel PCA with RBF kernel on the health-score matrix.

    The health matrix is StandardScaled before KPCA (KPCA is not scale-invariant).

    Returns:
        kpca:      fitted KernelPCA object
        Z:         (n_banks, n_components) embedding
        gamma_used: actual gamma value used
    """
    # StandardScale (KPCA with RBF needs this)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    if gamma is None:
        # Fallback heuristic (not used when KPCA_GAMMA is set explicitly)
        gamma = 1.0 / (X_scaled.shape[1] * X_scaled.var())

    kpca = KernelPCA(
        n_components=n_components,
        kernel=KPCA_KERNEL,
        gamma=gamma,
        fit_inverse_transform=True,  # enables out-of-sample projection
        random_state=42,
    )
    Z = kpca.fit_transform(X_scaled)

    # Explained variance proxy (KPCA has no eigenvalue-based explained var)
    # Use sum of squared projections as proxy
    total_var = np.sum(Z ** 2)
    pc_vars = [np.sum(Z[:, k] ** 2) / total_var for k in range(n_components)]

    print(f"\nKPCA fitted: gamma={gamma:.4f}")
    print(f"  Variance proxy per component: "
          + " | ".join([f"PC{k+1}={v:.3f}" for k, v in enumerate(pc_vars)]))

    return kpca, Z, gamma, scaler


def project_danger_boundary(kpca: KernelPCA,
                              scaler: StandardScaler,
                              danger_vec: np.ndarray) -> np.ndarray:
    """
    Project the RBI danger boundary vector into KPCA space via out-of-sample transform.
    Returns danger point coordinates in PC space: shape (1, n_components).
    """
    danger_scaled = scaler.transform(danger_vec.reshape(1, -1))
    danger_kpca = kpca.transform(danger_scaled)
    return danger_kpca  # shape (1, n_components)


# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Merton Soft-Label Orientation (Ridge Regression in PC Space)
# ─────────────────────────────────────────────────────────────────────────────

def orient_manifold_with_merton(Z: np.ndarray,
                                 bank_names: List[str],
                                 merton_data: Optional[Dict]) -> np.ndarray:
    """
    Find the direction in PC space that best predicts Merton DTD rank.
    Uses Ridge regression: dtd_rank ~ Z @ w + bias

    Since DTD is INVERSELY related to stress (lower DTD = more stressed),
    the output stress_direction is -dtd_prediction (so high value = more stressed).

    If Merton data is unavailable or covers < 50% of banks, falls back to PC1.

    Returns:
        stress_axis:  (n_banks,) array — stress score component from Merton orientation
                      High value = more stressed.
    """
    if merton_data is None:
        print("  Merton data unavailable — using PC1 as stress axis (fallback)")
        # Sign convention: more negative PC1 (lower health) = more stressed
        stress_axis = -Z[:, 0]
        # Normalise to [0,1]
        mn, mx = stress_axis.min(), stress_axis.max()
        return (stress_axis - mn) / (mx - mn + 1e-10)

    # Build a normalised Merton lookup so Excel-keyed bank_names (task11)
    # match the CSV-keyed result keys written by task10.
    merton_norm = {
        _normalize_bank_name(k): v
        for k, v in merton_data.items()
        if k != "_meta"
    }

    # Build aligned (Z, dtd_rank) pairs
    aligned_Z = []
    aligned_rank = []
    missing = []

    for i, bank in enumerate(bank_names):
        bank_data = merton_norm.get(_normalize_bank_name(bank))
        if bank_data and bank_data.get("dtdRank") is not None:
            aligned_Z.append(Z[i])
            aligned_rank.append(float(bank_data["dtdRank"]))
        else:
            missing.append(bank)

    coverage = len(aligned_Z) / len(bank_names)
    print(f"  Merton orientation coverage: {len(aligned_Z)}/{len(bank_names)} banks "
          f"({coverage:.0%})")

    if len(missing) > 0 and len(missing) <= 10:
        print(f"  Missing Merton data for: {', '.join(missing[:5])}"
              + (f" ... +{len(missing)-5} more" if len(missing) > 5 else ""))

    if coverage < 0.5:
        print("  Coverage below 50% threshold — using PC1 fallback.")
        stress_axis = -Z[:, 0]
        mn, mx = stress_axis.min(), stress_axis.max()
        return (stress_axis - mn) / (mx - mn + 1e-10)

    Z_aligned = np.array(aligned_Z)
    rank_aligned = np.array(aligned_rank)

    # Record actual rank for each bank that has Merton data (by position in bank_names)
    actual_rank_by_idx: Dict[int, float] = {}
    for i, bank in enumerate(bank_names):
        bank_data = merton_norm.get(_normalize_bank_name(bank))
        if bank_data and bank_data.get("dtdRank") is not None:
            actual_rank_by_idx[i] = float(bank_data["dtdRank"])

    # Ridge regression: dtd_rank = Z @ w + b
    # Kept solely as a fallback for the handful of banks without Merton data.
    ridge = Ridge(alpha=1.0, fit_intercept=True)
    ridge.fit(Z_aligned, rank_aligned)

    r2 = ridge.score(Z_aligned, rank_aligned)
    print(f"  Ridge R² on Merton coverage subset: {r2:.4f}")

    # Build final rank vector:
    #   • Banks WITH actual Merton data  → use true dtdRank directly
    #   • Banks WITHOUT Merton data      → fall back to Ridge prediction
    # Rationale: the Ridge projects KPCA coordinates onto a continuous rank
    # axis, but the weak R² (typically < 0.4) means predictions are noisy for
    # structural outliers (e.g. SBI whose KPCA PC1 ≈ +0.41, similar to
    # distressed SFBs, yet actual dtdRank = 32).  Using actual ranks for the
    # ~40/41 banks with data eliminates this systematic error.
    dtd_rank_final = ridge.predict(Z).copy()  # Ridge fallback for all
    for idx, actual_rank in actual_rank_by_idx.items():
        dtd_rank_final[idx] = actual_rank  # override with ground-truth

    # Diagnostic: show predicted vs actual for a few key banks
    n_show = min(5, len(bank_names))
    deltas = []
    for i, bank in enumerate(bank_names):
        if i in actual_rank_by_idx:
            predicted = ridge.predict(Z[i:i+1])[0]
            deltas.append((abs(predicted - actual_rank_by_idx[i]), bank,
                           actual_rank_by_idx[i], predicted))
    deltas.sort(reverse=True)
    if deltas:
        print(f"  Largest Ridge prediction errors (corrected to actual):")
        for _, bank, actual, pred in deltas[:n_show]:
            print(f"    {bank[:35]:<35} actual={actual:.0f}  predicted={pred:.1f}")

    # Invert: high DTD rank (low stress) → low stress score
    # We want stress_axis: high = most stressed (lowest DTD rank = rank 1)
    max_rank = float(len(bank_names))
    stress_raw = max_rank - dtd_rank_final

    # Normalise to [0,1]
    mn, mx = stress_raw.min(), stress_raw.max()
    stress_axis = (stress_raw - mn) / (mx - mn + 1e-10)

    return stress_axis


# ─────────────────────────────────────────────────────────────────────────────
# Step 5: Manifold Distance to Danger Boundary
# ─────────────────────────────────────────────────────────────────────────────

def compute_danger_boundary_distances(Z: np.ndarray,
                                       danger_kpca: np.ndarray) -> np.ndarray:
    """
    Euclidean distance from each bank's KPCA embedding to the RBI danger boundary point.
    Uses Euclidean (not Mahalanobis) because KPCA components are already decorrelated.

    Converts to stress score: closer to danger = higher stress.
      stress_boundary = 1 / (1 + distance_normalised)

    Returns: (n_banks,) stress-from-boundary score in [0,1].
    """
    danger_pt = danger_kpca.flatten()
    distances = np.linalg.norm(Z - danger_pt, axis=1)

    # Normalise: max distance in the dataset = 0 stress, 0 distance = 1.0 stress
    max_dist = distances.max()
    if max_dist < 1e-10:
        return np.full(len(Z), 0.5)

    # Sigmoid-like: closer to boundary → higher stress
    normalised_dist = distances / max_dist
    # stress = 1 - normalised_distance (closer to danger = more stressed)
    # Use softmax-style to avoid hard cliff at 0:
    stress_boundary = 1.0 - normalised_dist
    stress_boundary = np.clip(stress_boundary, 0.0, 1.0)

    return stress_boundary


# ─────────────────────────────────────────────────────────────────────────────
# Step 6: Raw CAMELS Composite Score (Interpretable Baseline)
# ─────────────────────────────────────────────────────────────────────────────

def compute_camels_scores(X_health: np.ndarray,
                           feat_names: List[str],
                           bank_names: List[str]) -> Tuple[np.ndarray, Dict]:
    """
    Compute CAMELS composite stress score from the transformed health matrix.

    For each CAMELS dimension:
      dimension_health = mean of health scores of ratios in that dimension
      dimension_stress = 1 - dimension_health

    Final CAMELS score: weighted sum of dimension stresses (weights from CAMELS_GROUPS).

    Returns:
      camels_scores:      (n_banks,) overall CAMELS stress in [0,1]
      camels_components:  { bankName → { dimension → stress_score} }
    """
    feat_idx = {f: j for j, f in enumerate(feat_names)}
    n_banks = len(bank_names)
    camels_scores = np.zeros(n_banks)
    components = {bank: {} for bank in bank_names}

    for dim, cfg in CAMELS_GROUPS.items():
        weight = cfg["weight"]
        ratios_in_dim = [r for r in cfg["ratios"] if r in feat_idx]

        if not ratios_in_dim:
            for bank in bank_names:
                components[bank][dim] = None
            continue

        for i, bank in enumerate(bank_names):
            health_vals = [X_health[i, feat_idx[r]] for r in ratios_in_dim]
            dim_health = np.mean(health_vals)
            dim_stress = 1.0 - dim_health
            components[bank][dim] = round(float(dim_stress), 4)
            camels_scores[i] += weight * dim_stress

    return camels_scores, components


# ─────────────────────────────────────────────────────────────────────────────
# Step 7: Final Blended Stress Score
# ─────────────────────────────────────────────────────────────────────────────

def blend_stress_scores(boundary_stress: np.ndarray,
                         merton_stress: np.ndarray,
                         camels_stress: np.ndarray) -> np.ndarray:
    """
    Weighted blend of three stress signals → final score in [0,1].

    Weights from BLEND_WEIGHTS constant.
    Each component is already in [0,1].
    """
    w1 = BLEND_WEIGHTS["danger_boundary_distance"]
    w2 = BLEND_WEIGHTS["merton_oriented_pc1"]
    w3 = BLEND_WEIGHTS["camels_composite"]

    blended = w1 * boundary_stress + w2 * merton_stress + w3 * camels_stress
    return np.clip(blended, 0.0, 1.0)


# ─────────────────────────────────────────────────────────────────────────────
# Main Pipeline
# ─────────────────────────────────────────────────────────────────────────────

def run_stress_analysis(year: str = "2025",
                         verbose: bool = True) -> Dict:
    """
    Full RKMSS pipeline:
      load → transform → KPCA → Merton orient → danger distance → CAMELS → blend

    Returns dict: { bankExcelName: StressResult, "_meta": {...} }
    """
    print("\n" + "=" * 70)
    print("RKMSS: RBI-Anchored Kernel Manifold Stress Score")
    print("=" * 70)

    # ── 1. Load ratios ────────────────────────────────────────────────────────
    print(f"\n[1/7] Loading ratios for year {year}...")
    df_ratios = load_ratios_dataframe(year=year)
    print(f"  Loaded {len(df_ratios)} Indian SCBs after filtering foreign branches")

    # ── 2. Non-linear transforms ──────────────────────────────────────────────
    print("\n[2/7] Applying RBI-threshold-anchored non-linear transforms...")
    X_health, bank_names, feat_names = build_transformed_matrix(df_ratios, CORE_RATIOS)
    print(f"  Feature matrix: {X_health.shape[0]} banks × {X_health.shape[1]} features")
    print(f"  Features used: {feat_names}")

    # ── 3. KPCA ───────────────────────────────────────────────────────────────
    print("\n[3/7] Fitting Kernel PCA (RBF kernel)...")
    kpca, Z, gamma_used, scaler = fit_kpca(X_health, n_components=KPCA_N_COMPONENTS)

    # ── 4. Project danger boundary ────────────────────────────────────────────
    print("\n[4/7] Projecting RBI danger boundary into KPCA space...")
    danger_vec = build_danger_vector(feat_names, X_health)
    danger_kpca = project_danger_boundary(kpca, scaler, danger_vec)
    print(f"  Danger point in PC space: {danger_kpca.flatten().round(4)}")

    # ── 5. Load Merton soft labels ────────────────────────────────────────────
    print("\n[5/7] Loading Merton DTD soft labels for manifold orientation...")
    merton_data = None
    if os.path.exists(MERTON_FILE):
        with open(MERTON_FILE, "r", encoding="utf-8") as f:
            merton_data = json.load(f)
        print(f"  Loaded Merton data for {len(merton_data) - 1} banks from {MERTON_FILE}")
    else:
        print(f"  WARNING: Merton file not found at {MERTON_FILE}")
        print(f"  Run task10_merton_soft_labels.py first to generate soft labels.")
        print(f"  Falling back to PC1 as stress axis.")

    # ── 6. Orient manifold with Merton ────────────────────────────────────────
    print("\n[6/7] Orienting manifold stress axis with Merton soft labels...")
    merton_stress = orient_manifold_with_merton(Z, bank_names, merton_data)
    boundary_stress = compute_danger_boundary_distances(Z, danger_kpca)

    # ── 7. CAMELS baseline ────────────────────────────────────────────────────
    camels_stress, camels_components = compute_camels_scores(X_health, feat_names, bank_names)

    # ── 8. Blend ──────────────────────────────────────────────────────────────
    print("\n[7/7] Blending stress components...")
    final_stress = blend_stress_scores(boundary_stress, merton_stress, camels_stress)

    # ── Build results dict ────────────────────────────────────────────────────
    # Build a normalised Merton lookup for final field population (same normalisation
    # used in orient_manifold_with_merton so lookups are consistent).
    merton_norm_final = {}
    if merton_data:
        for k, v in merton_data.items():
            if k != "_meta":
                merton_norm_final[_normalize_bank_name(k)] = v

    results = {}
    for i, bank in enumerate(bank_names):
        merton_dtd = None
        merton_rank = None
        bank_merton = merton_norm_final.get(_normalize_bank_name(bank))
        if bank_merton:
            bd = bank_merton.get("merton", {})
            merton_dtd = bd.get("distanceToDefault")
            merton_rank = bank_merton.get("dtdRank")

        results[bank] = {
            "stressScore":         round(float(final_stress[i]), 4),
            "stressRank":          None,          # assigned after loop
            "stressComponents": {
                "boundaryDistance": round(float(boundary_stress[i]), 4),
                "mertonOriented":   round(float(merton_stress[i]), 4),
                "camelsComposite":  round(float(camels_stress[i]), 4),
            },
            "camelsDimensions":    camels_components[bank],
            "merton": {
                "distanceToDefault": merton_dtd,
                "dtdRank":           merton_rank,
            },
            "kpcaEmbedding":       [round(float(v), 6) for v in Z[i]],
        }

    # Assign stress ranks (1 = most stressed)
    stress_vals = [(k, v["stressScore"]) for k, v in results.items()]
    ranked = sorted(stress_vals, key=lambda x: -x[1])  # descending stress
    for rank, (bank, _) in enumerate(ranked, 1):
        results[bank]["stressRank"] = rank

    # Meta
    results["_meta"] = {
        "pipeline":     "RKMSS v1.0",
        "year":         year,
        "nBanks":       len(bank_names),
        "featuresUsed": feat_names,
        "kpca": {
            "kernel":           KPCA_KERNEL,
            "nComponents":      KPCA_N_COMPONENTS,
            "gamma":            round(float(gamma_used), 6),
        },
        "blendWeights":         BLEND_WEIGHTS,
        "camelsWeights":        {k: v["weight"] for k, v in CAMELS_GROUPS.items()},
        "mertonFile":           MERTON_FILE,
        "mertonAvailable":      merton_data is not None,
        "computedAt":           datetime.now().isoformat(),
    }

    # Save
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=lambda x: float(x) if isinstance(x, np.floating) else x)
    print(f"\nSaved: {OUTPUT_FILE}")

    # Print summary table
    if verbose:
        _print_summary_table(results)

    return results


def _print_summary_table(results: Dict):
    """Print ranked stress score table."""
    print("\n" + "=" * 95)
    print(f"{'RK':<4} {'BANK':<45} {'STRESS':>6}  {'BOUNDARY':>8}  {'MERTON':>8}  {'CAMELS':>8}")
    print("-" * 95)
    ranked = sorted(
        [(k, v) for k, v in results.items() if k != "_meta"],
        key=lambda x: x[1]["stressRank"]
    )
    for bank, data in ranked:
        sc = data["stressComponents"]
        print(
            f"{data['stressRank']:<4} {bank[:44]:<45} "
            f"{data['stressScore']:>6.4f}  "
            f"{sc['boundaryDistance']:>8.4f}  "
            f"{sc['mertonOriented']:>8.4f}  "
            f"{sc['camelsComposite']:>8.4f}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Optional: Update MongoDB Bank Documents with Stress Scores
# ─────────────────────────────────────────────────────────────────────────────

def push_stress_scores_to_mongodb(results: Dict,
                                   bank_symbol_map: Optional[Dict[str, str]] = None):
    """
    Update MongoDB bank documents with computed stress scores.
    Adds/updates stressScore, stressRank, stressComponents, camelsDimensions fields.

    Args:
        results:         Output from run_stress_analysis()
        bank_symbol_map: Optional {excel_name → bankSymbol} override.
                         If None, uses task10's NSE_TICKER_MAP (reverse lookup).
    """
    try:
        from pymongo import MongoClient
        from task10_merton_soft_labels import NSE_TICKER_MAP
    except ImportError as e:
        print(f"MongoDB push failed: {e}")
        return

    # Build excel_name → bankSymbol mapping from task10's ticker map
    # (approximate — uses bankName matching)
    if bank_symbol_map is None:
        bank_symbol_map = {name: symbol for name, symbol in NSE_TICKER_MAP.items()}

    client = MongoClient(MONGODB_URI)
    db = client[DB_NAME]
    collection = db[COLLECTION_NAME]

    updated = 0
    for bank_excel_name, data in results.items():
        if bank_excel_name == "_meta":
            continue

        symbol = bank_symbol_map.get(bank_excel_name)
        if not symbol:
            continue

        update_doc = {
            "$set": {
                "stressScore":      data["stressScore"],
                "stressRank":       data["stressRank"],
                "stressComponents": data["stressComponents"],
                "camelsDimensions": data["camelsDimensions"],
                "stressUpdatedAt":  datetime.now().isoformat(),
            }
        }
        res = collection.update_one({"bankSymbol": symbol}, update_doc)
        if res.modified_count > 0 or res.upserted_id:
            updated += 1

    client.close()
    print(f"MongoDB: updated {updated} bank documents with stress scores.")


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="RKMSS Bank Stress Scoring")
    parser.add_argument("--year", default="2025", help="Ratio data year (default: 2025)")
    parser.add_argument("--push-mongo", action="store_true",
                        help="Push stress scores to MongoDB after computation")
    parser.add_argument("--quiet", action="store_true", help="Suppress verbose output")
    args = parser.parse_args()

    results = run_stress_analysis(year=args.year, verbose=not args.quiet)

    if args.push_mongo:
        print("\nPushing stress scores to MongoDB...")
        push_stress_scores_to_mongodb(results)
