"""
entity_stress_pipeline.py
=========================
Calculates Fundamental Entity Stress for every company in
financial_kg.companies MongoDB collection.

Grounded in: CRISIL Default & Ratings Transition Study FY2025
  - Table 1: 1-yr CDRs (FY15-25 monthly static pools)
  - Table 2: 1-yr LT transition rates
  - Table 3: 1-yr ST transition rates

Output: data/outputs/entity_stress_scores.csv  (sorted highest stress first)

Usage:
    pip install pymongo
    python entity_stress_pipeline.py \
        --uri "mongodb://localhost:27017" \
        --db  financial_kg \
        --col companies \
        --out data/outputs/entity_stress_scores.csv
"""

import re
import csv
import math
import statistics
import argparse
import os
from pymongo import MongoClient

# Load environment variables from .env in root folder
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(
    os.path.dirname(os.path.dirname(__file__))), '.env'), override=True)

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 ── CRISIL FY2025 DATA TABLES
# ═══════════════════════════════════════════════════════════════════════════════

# ── Table 1: 1-Year Cumulative Default Rates, FY15-25 ─────────────────────────
# Published values: AAA=0.00%, AA=0.05%, A=0.07%, BBB=0.46%, BB=2.86%,
#                   B=8.40%, C=24.98%
# Modifier notches (+/−) linearly interpolated between published anchor points.
LT_RATING_PD: dict[str, float] = {
    "AAA":  0.0000,
    "AA+":  0.0003,
    "AA":   0.0005,
    "AA-":  0.0008,
    "A+":   0.0006,
    "A":    0.0007,
    "A-":   0.0012,
    "BBB+": 0.0025,
    "BBB":  0.0046,
    "BBB-": 0.0110,
    "BB+":  0.0190,
    "BB":   0.0286,
    "BB-":  0.0460,
    "B+":   0.0610,
    "B":    0.0840,
    "B-":   0.1200,
    "C":    0.2498,
    "D":    1.0000,
}

# ── Table 3: 1-Year ST CDRs ───────────────────────────────────────────────────
# Published: A1+=0.02%, A1=0.01%, A2=0.23%, A3=0.43%, A4=4.72%
ST_RATING_PD: dict[str, float] = {
    "A1+":  0.0002,
    "A1":   0.0001,
    "A2+":  0.0010,
    "A2":   0.0023,
    "A2-":  0.0030,
    "A3+":  0.0030,
    "A3":   0.0043,
    "A3-":  0.0055,
    "A4+":  0.0300,
    "A4":   0.0472,
    "A4-":  0.0600,
}

# ── Table 2: 1-year downgrade probability = P(grade worsens ≥1 notch) ─────────
# = 1 − stability_rate − upgrade_rate  (from transition matrix Table 2)
# AAA:  1−98.89%−0%     = 1.11%  (but can't really downgrade AAA in same way)
# AA:   1−95.96%−2.28%  = 1.76%
# A:    1−93.14%−3.82%  = 3.04%
# BBB:  1−91.73%−0.06%  = 4.64% (≈ sum of BB+B+C+D columns = 4.64%)
# BB:   1−89.05%−0.01%  = 6.57%
# B:    1−82.04%−0.04%  = 8.80%  (B→D is 8.40%, B→C is 0.40%)
# C:    1−53.23%−0%     = 46.77%
LT_DOWNGRADE_PROB: dict[str, float] = {
    "AAA":  0.0000,
    "AA+":  0.0050,
    "AA":   0.0175,
    "AA-":  0.0200,
    "A+":   0.0250,
    "A":    0.0304,
    "A-":   0.0380,
    "BBB+": 0.0420,
    "BBB":  0.0464,
    "BBB-": 0.0550,
    "BB+":  0.0600,
    "BB":   0.0657,
    "BB-":  0.0750,
    "B+":   0.0820,
    "B":    0.0880,
    "B-":   0.1200,
    "C":    0.4677,
    "D":    1.0000,
}

# Numeric grade (1=best, 18=worst) used for weighted avg and heterogeneity
LT_GRADE: dict[str, int] = {
    "AAA": 1,  "AA+": 2,  "AA":  3,  "AA-": 4,
    "A+":  5,  "A":   6,  "A-":  7,
    "BBB+": 8,  "BBB": 9,  "BBB-": 10,
    "BB+": 11,  "BB": 12,  "BB-": 13,
    "B+": 14,  "B":  15,  "B-":  16,
    "C":  17,  "D":  18,
}

# Outlook multiplier applied to base PD
# Negative outlook → higher stress; Positive → lower
OUTLOOK_MULT: dict[str, float] = {
    "positive":        0.80,
    "watch positive":  0.75,
    "improving":       0.80,
    "stable":          1.00,
    "developing":      1.15,
    "under watch":     1.20,
    "credit watch":    1.25,
    "rating watch":    1.25,
    "negative":        1.30,
    "watch negative":  1.50,
    "creditwatch neg": 1.50,
}


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 ── PARSING HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def clean_rating(raw: str) -> str:
    """Normalise rating string: remove 'Crisil ' prefix, outlook suffixes, etc."""
    if not raw:
        return ""
    r = str(raw).strip()
    for prefix in ["CRISIL ", "Crisil ", "crisil "]:
        if r.startswith(prefix):
            r = r[len(prefix):]
    # Remove trailing outlook annotation
    for suffix in ["/stable", "/positive", "/negative", "/watch",
                   "/developing", "(stable)", "(positive)", "(negative)"]:
        r = r.lower().replace(suffix, "")
    r = r.upper().strip().rstrip("&").strip()
    return r


def parse_outlook(raw: str) -> str:
    if not raw:
        return "stable"
    key = raw.strip().lower()
    for k in OUTLOOK_MULT:
        if k in key:
            return k
    return "stable"


def rating_type(raw: str) -> str:
    """Return 'LT', 'ST', or 'UNKNOWN'."""
    r = clean_rating(raw)
    if r in LT_RATING_PD:
        return "LT"
    if r in ST_RATING_PD:
        return "ST"
    if re.match(r"^A[1-4]", r):
        return "ST"
    return "UNKNOWN"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 ── STRESS COMPUTATION
# ═══════════════════════════════════════════════════════════════════════════════

def normalise_pd(pd: float | None) -> float:
    """Log-linear map: PD=0 → 0.0, PD=1 → 1.0, smooth in between."""
    if pd is None:
        return 0.30      # unknown entity assigned neutral-high default
    pd = max(min(pd, 1.0), 0.0)
    if pd == 0.0:
        return 0.0
    return math.log(1 + 99 * pd) / math.log(100)


def compute_stress(doc: dict) -> dict:
    """Compute full stress vector for a single MongoDB document."""

    company_code = doc.get("companyCode", "")
    crisil_name = doc.get("crisilName") or doc.get("mcaName", "")
    nse_symbol = doc.get("nseSymbol", "")
    industry_code = doc.get("industryCode", "")
    industry_name = doc.get("industryName", "")
    listing = doc.get("listingStatus", "")
    rating_date = doc.get("ratingDate", "")

    # ── A. Primary ratings from crisilRatings[] ──────────────────────────────
    lt_pd = lt_rating = lt_outlook_key = None
    st_pd = st_rating = None
    lt_outlook_mult = 1.0
    lt_downgrade_p = 0.05    # fallback 5%

    for cr in (doc.get("crisilRatings") or []):
        r_raw = cr.get("rating", "")
        outlook = cr.get("outlook", "")
        r_clean = clean_rating(r_raw)
        rtype = rating_type(r_raw)

        if rtype == "LT" and lt_pd is None:
            pd = LT_RATING_PD.get(r_clean)
            if pd is not None:
                lt_pd = pd
                lt_rating = r_clean
                lt_outlook_key = parse_outlook(outlook)
                lt_outlook_mult = OUTLOOK_MULT.get(lt_outlook_key, 1.0)
                lt_downgrade_p = LT_DOWNGRADE_PROB.get(r_clean, 0.05)

        if rtype == "ST" and st_pd is None:
            pd = ST_RATING_PD.get(r_clean)
            if pd is not None:
                st_pd = pd
                st_rating = r_clean

    adjusted_lt_pd = min(lt_pd * lt_outlook_mult,
                         1.0) if lt_pd is not None else None

    # ── B. bankFacilities[] → exposure-weighted PD ───────────────────────────
    total_exp = 0.0
    wpd_sum = 0.0
    wgrade_sum = 0.0
    fac_pds: list[float] = []
    n_fac = len(doc.get("bankFacilities") or [])
    n_rated = 0

    for fac in (doc.get("bankFacilities") or []):
        amt = float(fac.get("amount") or 0)
        r_raw = fac.get("rating", "")
        r_cl = clean_rating(r_raw)
        rtype = rating_type(r_raw)

        if rtype == "LT":
            pd = LT_RATING_PD.get(r_cl)
            g = LT_GRADE.get(r_cl)
            if pd is not None and amt > 0:
                total_exp += amt
                wpd_sum += pd * amt
                fac_pds.append(pd)
                n_rated += 1
                if g:
                    wgrade_sum += g * amt

    ew_pd = (wpd_sum / total_exp) if total_exp > 0 else None
    ew_grade = (wgrade_sum / total_exp) if total_exp > 0 else None
    adj_ew_pd = min(ew_pd * lt_outlook_mult,
                    1.0) if ew_pd is not None else None

    # ── C. Rating heterogeneity ───────────────────────────────────────────────
    het = statistics.stdev(fac_pds) if len(fac_pds) > 1 else 0.0

    # ── D. Composite stress score ─────────────────────────────────────────────
    #
    #  Best available PD for primary signal:
    #    1st choice → adjusted LT PD (crisil ratings)
    #    2nd choice → adjusted EW PD (from bank facilities)
    #    3rd choice → ST PD (short-term proxy)
    #    fallback   → None → normalise_pd(None) = 0.30
    #
    primary_pd = (
        adjusted_lt_pd
        if adjusted_lt_pd is not None
        else (adj_ew_pd if adj_ew_pd is not None
              else (st_pd if st_pd is not None else None))
    )

    # Primary credit quality  35%
    c1 = normalise_pd(primary_pd)
    # Exposure-weighted PD    30%
    c2 = normalise_pd(adj_ew_pd)
    # Downgrade risk          20%
    c3 = min(lt_downgrade_p / 0.25, 1.0)
    # Heterogeneity           15%
    c4 = min(het / 0.50, 1.0)

    has_rating = any(x is not None for x in [lt_pd, st_pd, ew_pd])
    if not has_rating:
        stress = 50.0          # unrated → neutral/cautious
        label = "Unknown"
    else:
        raw = 0.35 * c1 + 0.30 * c2 + 0.20 * c3 + 0.15 * c4
        stress = round(raw * 100, 2)
        label = _label(stress)

    return {
        # ── Identity
        "companyCode":           company_code,
        "crisilName":            crisil_name,
        "nseSymbol":             nse_symbol,
        "industryCode":          industry_code,
        "industryName":          industry_name,
        "listingStatus":         listing,
        "ratingDate":            rating_date,

        # ── Primary rating
        "primaryLT_Rating":      lt_rating or "",
        "primaryLT_Outlook":     lt_outlook_key or "",
        "primaryST_Rating":      st_rating or "",
        "primaryLT_PD_%":        _p(lt_pd),
        "primaryST_PD_%":        _p(st_pd),
        "outlookMultiplier":     round(lt_outlook_mult, 2),
        "adjustedLT_PD_%":      _p(adjusted_lt_pd),

        # ── Facility analysis
        "numBankFacilities":     n_fac,
        "numRatedFacilities":    n_rated,
        "totalExposure_Cr":      round(total_exp, 2),
        "ewPD_%":                _p(ew_pd),
        "adjustedEW_PD_%":       _p(adj_ew_pd),
        "ewGrade":               round(ew_grade, 2) if ew_grade else "",
        "ratingHeterogeneity":   round(het * 100, 4),

        # ── Transition / downgrade risk
        "1yr_DowngradeProbab_%": round(lt_downgrade_p * 100, 3),

        # ── Score components (0–100 each, pre-weighting)
        "comp_PrimaryPD":        round(c1 * 100, 2),
        "comp_ExposureWeightedPD": round(c2 * 100, 2),
        "comp_DowngradeRisk":    round(c3 * 100, 2),
        "comp_Heterogeneity":    round(c4 * 100, 2),

        # ── Final output
        "stressScore":           stress,
        "stressLabel":           label,
        "riskTier":              _tier(lt_rating or st_rating or ""),
    }


def _p(v): return f"{round(v * 100, 4)}" if v is not None else ""


def _label(s: float) -> str:
    if s < 5:
        return "Minimal"
    if s < 15:
        return "Low"
    if s < 30:
        return "Moderate"
    if s < 50:
        return "Elevated"
    if s < 70:
        return "High"
    return "Severe"


def _tier(r: str) -> str:
    ig = {"AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-",
          "A1+", "A1", "A2+", "A2", "A2-"}
    sig = {"BB+", "BB", "BB-", "B+", "B", "B-",
           "A3+", "A3", "A3-", "A4+", "A4", "A4-"}
    if r.upper() in ig:
        return "Investment Grade"
    if r.upper() in sig:
        return "Sub-Investment Grade"
    if r.upper() == "C":
        return "Near Default"
    if r.upper() == "D":
        return "Default"
    return "Unrated"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 ── MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

def run(mongo_uri, db_name, col_name, out_csv, limit=0):
    print(f"[INFO] Connecting → {mongo_uri}  db={db_name}  col={col_name}")
    client = MongoClient(mongo_uri)
    cursor = client[db_name][col_name].find({})
    if limit:
        cursor = cursor.limit(limit)

    rows, errors = [], 0
    for doc in cursor:
        try:
            rows.append(compute_stress(doc))
        except Exception as e:
            errors += 1
            print(f"  [WARN] {doc.get('companyCode', '?')}: {e}")

    rows.sort(key=lambda x: float(x["stressScore"]) if x["stressScore"] != "" else 0,
              reverse=True)

    if not rows:
        print("[WARN] No rows produced.")
        return

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n✅  {len(rows)} entities written → {out_csv}  (errors: {errors})\n")

    from collections import Counter
    label_dist = Counter(r["stressLabel"] for r in rows)
    tier_dist = Counter(r["riskTier"] for r in rows)

    print("Stress Label Distribution:")
    for k, v in sorted(label_dist.items(), key=lambda x: -x[1]):
        bar = "█" * min(v, 40)
        print(f"  {k:<22} {v:>5}  {bar}")

    print("\nRisk Tier Distribution:")
    for k, v in sorted(tier_dist.items(), key=lambda x: -x[1]):
        bar = "█" * min(v, 40)
        print(f"  {k:<26} {v:>5}  {bar}")

    scores = [float(r["stressScore"]) for r in rows if r["stressScore"] != ""]
    if scores:
        print(f"\nStress Score  min={min(scores):.1f}  max={max(scores):.1f}  "
              f"mean={statistics.mean(scores):.1f}  "
              f"median={statistics.median(scores):.1f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="CRISIL Entity Stress Pipeline")
    ap.add_argument(
        "--uri",
        default=os.environ.get("MONGO_URI", "ip here "))
    ap.add_argument(
        "--db",
        default=os.environ.get("MONGO_DB", "financial_kg"))
    ap.add_argument(
        "--col",
        default=os.environ.get("MONGO_COL", "companies"))
    ap.add_argument(
        "--out",
        default=os.environ.get("ENTITY_STRESS_OUT", "data/outputs/entity_stress_scores.csv"))
    ap.add_argument(
        "--limit",
        type=int,
        default=int(os.environ.get("ENTITY_STRESS_LIMIT", 0)),
        help="0=all docs")
    a = ap.parse_args()
    run(a.uri, a.db, a.col, a.out, a.limit)
