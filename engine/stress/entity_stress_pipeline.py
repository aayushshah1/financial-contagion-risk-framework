"""
entity_stress_pipeline.py  (v3)
================================
Calculates Fundamental Entity Stress for every company in
financial_kg.companies MongoDB collection.

Grounded in: CRISIL Default & Ratings Transition Study FY2025

FIXES IN v3 (on top of v2):
  ── Fix 1: INC / Withdrawn rating parsing ──────────────────────────────────
  Strings like "Crisil BB+/Stable/Issuer Not Cooperating* (Withdrawn)"
  previously returned pd=None and were silently skipped. Now:
    • The base rating (e.g. BB+) is extracted from the INC string.
    • An INC_MULT = 1.50 penalty is applied to the PD (same severity
      as "watch negative" — non-cooperation strongly precedes default).
    • "Withdrawn" alone (no base rating) is skipped — genuinely unknown.

  ── Fix 2: Flat Excel-friendly output ──────────────────────────────────────
  Instead of array columns, the CSV now has:
    facility_1_lender, facility_1_name, facility_1_amount, facility_1_rating,
    facility_2_lender, ...  (up to max facilities found across all docs)
    instrument_1_name, instrument_1_issueSize, instrument_1_rating,
    instrument_2_name, ...  (up to max instruments found, header rows skipped)
  followed by the stress score columns.

  This requires a two-pass approach over the cursor.

Usage:
    pip install pymongo python-dotenv
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
from datetime import datetime
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env'),
    override=True)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 ── CRISIL FY2025 DATA TABLES
# ═══════════════════════════════════════════════════════════════════════════════

LT_RATING_PD: dict[str, float] = {
    "AAA":  0.0000, "AA+":  0.0003, "AA":   0.0005, "AA-":  0.0008,
    "A+":   0.0006, "A":    0.0007, "A-":   0.0012,
    "BBB+": 0.0025, "BBB":  0.0046, "BBB-": 0.0110,
    "BB+":  0.0190, "BB":   0.0286, "BB-":  0.0460,
    "B+":   0.0610, "B":    0.0840, "B-":   0.1200,
    "C":    0.2498, "D":    1.0000,
}

ST_RATING_PD: dict[str, float] = {
    "A1+":  0.0002, "A1":   0.0001, "A2+":  0.0010, "A2":   0.0023,
    "A2-":  0.0030, "A3+":  0.0030, "A3":   0.0043, "A3-":  0.0055,
    "A4+":  0.0300, "A4":   0.0472, "A4-":  0.0600,
}

LT_DOWNGRADE_PROB: dict[str, float] = {
    "AAA":  0.0000, "AA+":  0.0050, "AA":   0.0175, "AA-":  0.0200,
    "A+":   0.0250, "A":    0.0304, "A-":   0.0380,
    "BBB+": 0.0420, "BBB":  0.0464, "BBB-": 0.0550,
    "BB+":  0.0600, "BB":   0.0657, "BB-":  0.0750,
    "B+":   0.0820, "B":    0.0880, "B-":   0.1200,
    "C":    0.4677, "D":    1.0000,
}

LT_GRADE: dict[str, int] = {
    "AAA": 1,  "AA+": 2,  "AA":  3,  "AA-": 4,
    "A+":  5,  "A":   6,  "A-":  7,
    "BBB+": 8, "BBB": 9,  "BBB-": 10,
    "BB+": 11, "BB":  12, "BB-": 13,
    "B+":  14, "B":   15, "B-":  16,
    "C":   17, "D":   18,
}

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

# INC penalty: non-cooperation is a strong negative signal
INC_MULT: float = 1.50

# Staleness thresholds
STALE_THRESHOLD_DAYS = 365
STALE_MAX_DAYS       = 730

# Header/placeholder values to skip inside instruments[]
INSTRUMENT_SKIP_VALUES = {
    "RATING OUTSTANDINGWITH OUTLOOK", "RATING OUTSTANDING WITH OUTLOOK",
    "RATING OUTSTANDING", "RATING", "ISIN", "NAME OF INSTRUMENT",
    "DATE OFALLOTMENT", "COUPONRATE (%)", "MATURITYDATE", "COMPLEXITYLEVELS",
}

BASE_WEIGHTS: dict[str, float] = {
    "c1": 0.25,   # primary PD
    "c2": 0.20,   # unified EW-PD
    "c3": 0.15,   # downgrade risk
    "c4": 0.10,   # heterogeneity
    "c5": 0.10,   # exposure size
    "c6": 0.10,   # coverage gap
    "c7": 0.05,   # staleness
    "c8": 0.03,   # concentration (HHI)
    "c9": 0.02,   # ST-only penalty
}


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 ── PARSING HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

# Regex: extract base rating from INC / Withdrawn strings
# e.g. "Crisil BB+/Stable/Issuer Not Cooperating* (Withdrawn)" → "BB+"
_INC_PATTERN = re.compile(
    r"issuer\s+not\s+co.?operating|issuer\s*not\s*co-?operating|"
    r"\(withdrawn\)|withdrawn",
    re.IGNORECASE
)

# All known rating tokens (LT + ST) — used to extract base from INC strings
_ALL_RATINGS = set(LT_RATING_PD) | set(ST_RATING_PD)


def is_inc_or_withdrawn(raw: str) -> bool:
    return bool(_INC_PATTERN.search(str(raw)))


def extract_base_rating(raw: str) -> str:
    """
    From a string like "Crisil BB+/Stable/Issuer Not Cooperating* (Withdrawn)"
    extract the base rating token "BB+" by trying each known rating token
    against the cleaned prefix of the string.
    """
    r = str(raw).strip()
    # Strip "Crisil " / "CRISIL " prefix
    for prefix in ["CRISIL ", "Crisil ", "crisil "]:
        if r.startswith(prefix):
            r = r[len(prefix):]
            break
    # The base rating is the first "/" segment
    base = r.split("/")[0].strip().upper().rstrip("*").strip()
    if base in _ALL_RATINGS:
        return base
    return ""


def clean_rating(raw) -> str:
    """Standard clean for non-INC ratings."""
    if not raw:
        return ""
    r = str(raw).strip()
    for prefix in ["CRISIL ", "Crisil ", "crisil "]:
        if r.startswith(prefix):
            r = r[len(prefix):]
            break
    for suffix in ["/stable", "/positive", "/negative", "/watch",
                   "/developing", "(stable)", "(positive)", "(negative)"]:
        r = r.lower().replace(suffix, "")
    return r.upper().strip().rstrip("&").strip()


def parse_outlook(raw) -> str:
    if not raw:
        return "stable"
    key = str(raw).strip().lower()
    for k in OUTLOOK_MULT:
        if k in key:
            return k
    return "stable"


def rating_type(token: str) -> str:
    """token should already be the clean base rating."""
    if token in LT_RATING_PD:
        return "LT"
    if token in ST_RATING_PD:
        return "ST"
    return "UNKNOWN"


def safe_amount(val) -> float | None:
    try:
        v = float(val)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def parse_date(raw) -> datetime | None:
    if not raw:
        return None
    fmts = ["%b %d, %Y", "%d %b %Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"]
    for fmt in fmts:
        try:
            return datetime.strptime(str(raw).strip(), fmt)
        except ValueError:
            continue
    return None


def resolve_rating(raw_rating: str) -> tuple[str, float]:
    """
    Returns (base_token, pd_multiplier).
    Handles normal ratings AND INC/Withdrawn strings.
    Returns ("", 1.0) if unresolvable.
    """
    if not raw_rating:
        return "", 1.0

    if is_inc_or_withdrawn(raw_rating):
        base = extract_base_rating(raw_rating)
        if base:
            return base, INC_MULT   # known base + INC penalty
        return "", 1.0              # "Withdrawn" alone — skip

    # Normal rating
    base = clean_rating(raw_rating)
    return base, 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 ── NORMALISATION FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def normalise_pd(pd: float) -> float:
    pd = max(min(pd, 1.0), 0.0)
    if pd == 0.0:
        return 0.0
    return math.log(1 + 99 * pd) / math.log(100)


def normalise_exposure(exp_cr: float) -> float:
    if exp_cr <= 0:
        return 0.0
    return min(math.log10(1 + exp_cr) / 4.0, 1.0)


def normalise_staleness(rating_date_str) -> float | None:
    dt = parse_date(rating_date_str)
    if dt is None:
        return None
    age_days = (datetime.now() - dt).days
    if age_days <= STALE_THRESHOLD_DAYS:
        return 0.0
    return min(
        (age_days - STALE_THRESHOLD_DAYS) / (STALE_MAX_DAYS - STALE_THRESHOLD_DAYS),
        1.0,
    )


def herfindahl(amounts: list[float]) -> float | None:
    if not amounts:
        return None
    total = sum(amounts)
    if total <= 0:
        return None
    return sum((a / total) ** 2 for a in amounts)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 ── DYNAMIC WEIGHT ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

def dynamic_score(components: dict[str, float | None]) -> float:
    """
    Active (non-None) components contribute their base weight, renormalised
    so all active weights sum to 1.0. Score ∈ [0, 1].
    """
    active = {k: v for k, v in components.items() if v is not None}
    if not active:
        return 0.30
    total_w = sum(BASE_WEIGHTS[k] for k in active)
    return sum((BASE_WEIGHTS[k] / total_w) * v for k, v in active.items())


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 ── UNIFIED RATING POOL BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def build_rating_pool(doc: dict) -> dict:
    """
    Unified pool from crisilRatings[], bankFacilities[], instruments[].
    INC/Withdrawn strings are now properly parsed with INC_MULT penalty.
    """

    pool = dict(
        lt_pd=None, lt_rating=None, lt_outlook_key="stable",
        lt_outlook_mult=1.0, lt_downgrade_p=None,
        st_pd=None, st_rating=None,
        ew_pd=None, ew_grade=None,
        total_exp=0.0, fac_amounts=[],
        all_pds=[],
        n_items_total=0, n_items_rated=0,
        has_lt=False, has_st=False,
        inc_flag=False,   # True if any INC string was found
    )

    wpd_sum    = 0.0
    wgrade_sum = 0.0
    w_total    = 0.0

    # ── (A) crisilRatings[] ───────────────────────────────────────────────────
    for cr in (doc.get("crisilRatings") or []):
        pool["n_items_total"] += 1
        raw_rating = cr.get("rating", "")
        outlook    = cr.get("outlook", "")

        base, mult = resolve_rating(raw_rating)
        if not base:
            continue   # "Withdrawn" alone or unrecognised — skip

        if mult > 1.0:
            pool["inc_flag"] = True

        rtype = rating_type(base)

        if rtype == "LT" and not pool["has_lt"]:
            pd = LT_RATING_PD.get(base)
            if pd is not None:
                pd_adj = min(pd * mult, 1.0)
                pool["n_items_rated"]   += 1
                pool["lt_pd"]            = pd_adj
                pool["lt_rating"]        = base
                pool["lt_outlook_key"]   = parse_outlook(outlook)
                pool["lt_outlook_mult"]  = OUTLOOK_MULT.get(pool["lt_outlook_key"], 1.0)
                pool["lt_downgrade_p"]   = LT_DOWNGRADE_PROB.get(base)
                pool["has_lt"]           = True
                pool["all_pds"].append(pd_adj)

        elif rtype == "ST" and not pool["has_st"]:
            pd = ST_RATING_PD.get(base)
            if pd is not None:
                pd_adj = min(pd * mult, 1.0)
                pool["n_items_rated"] += 1
                pool["st_pd"]          = pd_adj
                pool["st_rating"]      = base
                pool["has_st"]         = True
                pool["all_pds"].append(pd_adj)

    # ── Shared absorber for bankFacilities[] and instruments[] ────────────────
    def absorb(raw_rating, amount_val):
        nonlocal wpd_sum, wgrade_sum, w_total

        base, mult = resolve_rating(raw_rating)
        if not base:
            return   # unresolvable — skip

        if mult > 1.0:
            pool["inc_flag"] = True

        rtype = rating_type(base)
        amt   = safe_amount(amount_val)

        pd = g = None
        if rtype == "LT":
            pd = LT_RATING_PD.get(base)
            g  = LT_GRADE.get(base)
        elif rtype == "ST":
            pd = ST_RATING_PD.get(base)

        if pd is None:
            return

        pd_adj = min(pd * mult, 1.0)
        pool["n_items_rated"] += 1
        pool["all_pds"].append(pd_adj)

        if amt is not None:
            wpd_sum           += pd_adj * amt
            w_total           += amt
            pool["total_exp"] += amt
            pool["fac_amounts"].append(amt)
            if g is not None:
                wgrade_sum += g * amt

    # ── (B) bankFacilities[] ─────────────────────────────────────────────────
    for fac in (doc.get("bankFacilities") or []):
        pool["n_items_total"] += 1
        absorb(fac.get("rating", ""), fac.get("amount"))

    # ── (C) instruments[] ────────────────────────────────────────────────────
    for inst in (doc.get("instruments") or []):
        r_raw = inst.get("rating", "")
        r_cl  = clean_rating(r_raw).upper()
        # Skip header/placeholder rows
        if not r_cl or r_cl in INSTRUMENT_SKIP_VALUES:
            continue
        pool["n_items_total"] += 1
        absorb(r_raw, inst.get("issueSize"))

    # ── Finalise EW-PD ────────────────────────────────────────────────────────
    if w_total > 0:
        pool["ew_pd"]    = wpd_sum    / w_total
        pool["ew_grade"] = wgrade_sum / w_total if wgrade_sum > 0 else None

    return pool


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6 ── STRESS COMPUTATION
# ═══════════════════════════════════════════════════════════════════════════════

def compute_stress(doc: dict) -> dict:

    company_code  = doc.get("companyCode", "")
    crisil_name   = doc.get("crisilName") or doc.get("mcaName", "")
    nse_symbol    = doc.get("nseSymbol", "")
    industry_code = doc.get("industryCode", "")
    industry_name = doc.get("industryName", "")
    listing       = doc.get("listingStatus", "")
    rating_date   = doc.get("ratingDate", "")

    pool = build_rating_pool(doc)

    lt_pd           = pool["lt_pd"]
    lt_rating       = pool["lt_rating"]
    lt_outlook_key  = pool["lt_outlook_key"]
    lt_outlook_mult = pool["lt_outlook_mult"]
    lt_downgrade_p  = pool["lt_downgrade_p"]
    st_pd           = pool["st_pd"]
    st_rating       = pool["st_rating"]
    ew_pd           = pool["ew_pd"]
    ew_grade        = pool["ew_grade"]
    total_exp       = pool["total_exp"]
    fac_amounts     = pool["fac_amounts"]
    all_pds         = pool["all_pds"]
    n_items_total   = pool["n_items_total"]
    n_items_rated   = pool["n_items_rated"]

    # Outlook adjustment (only for non-INC ratings; INC already has mult baked in)
    adj_lt_pd = min(lt_pd * lt_outlook_mult, 1.0) if lt_pd is not None else None
    adj_ew_pd = min(ew_pd * lt_outlook_mult, 1.0) if ew_pd is not None else None

    primary_pd = (
        adj_lt_pd if adj_lt_pd is not None else
        adj_ew_pd if adj_ew_pd is not None else
        st_pd
    )

    # ── Components ────────────────────────────────────────────────────────────

    c1: float | None = normalise_pd(primary_pd) if primary_pd is not None else None
    c2: float | None = normalise_pd(adj_ew_pd)  if adj_ew_pd  is not None else None
    c3: float | None = (
        min(lt_downgrade_p / 0.25, 1.0) if lt_downgrade_p is not None else None
    )
    c4: float | None = (
        min(statistics.stdev(all_pds) / 0.50, 1.0) if len(all_pds) > 1 else None
    )
    c5: float | None = normalise_exposure(total_exp) if total_exp > 0 else None
    c6: float | None = (
        1.0 - (n_items_rated / n_items_total) if n_items_total > 0 else None
    )
    c7: float | None = normalise_staleness(rating_date)
    c8: float | None = herfindahl(fac_amounts)
    c9: float | None = (
        0.0 if pool["has_lt"] else
        1.0 if pool["has_st"] else
        None
    )

    components = dict(c1=c1, c2=c2, c3=c3, c4=c4,
                      c5=c5, c6=c6, c7=c7, c8=c8, c9=c9)

    has_any_rating = any(x is not None for x in [lt_pd, st_pd, ew_pd])

    if not has_any_rating:
        unrated = {k: components[k] for k in ("c5", "c6", "c7", "c8")}
        base   = dynamic_score(unrated)
        stress = round(40.0 + base * 30.0, 2)
    else:
        stress = round(dynamic_score(components) * 100, 2)

    label = _label(stress)
    active_keys  = [k for k, v in components.items() if v is not None]
    skipped_keys = [k for k, v in components.items() if v is None]

    return {
        # ── Identity ─────────────────────────────────────────────────────────
        "companyCode":            company_code,
        "crisilName":             crisil_name,
        "nseSymbol":              nse_symbol,
        "industryCode":           industry_code,
        "industryName":           industry_name,
        "listingStatus":          listing,
        "ratingDate":             rating_date,

        # ── Summary rating signals ────────────────────────────────────────────
        "primaryLT_Rating":       lt_rating or "",
        "primaryLT_Outlook":      lt_outlook_key or "",
        "primaryST_Rating":       st_rating or "",
        "adjustedLT_PD_%":        _pct(adj_lt_pd),
        "adjustedEW_PD_%":        _pct(adj_ew_pd),
        "ewGrade":                round(ew_grade, 2) if ew_grade is not None else "",
        "incFlag":                "Yes" if pool["inc_flag"] else "No",
        "totalExposure_Cr":       round(total_exp, 2),
        "n_items_total":          n_items_total,
        "n_items_rated":          n_items_rated,
        "ratingHeterogeneity":    (
            round(statistics.stdev(all_pds) * 100, 4) if len(all_pds) > 1 else ""
        ),
        "1yr_DowngradeProbab_%":  (
            round(lt_downgrade_p * 100, 3) if lt_downgrade_p is not None else ""
        ),

        # ── Component scores (0–100 pre-weighting, blank = skipped) ──────────
        "comp_PrimaryPD":         _comp(c1),
        "comp_EW_PD":             _comp(c2),
        "comp_DowngradeRisk":     _comp(c3),
        "comp_Heterogeneity":     _comp(c4),
        "comp_ExposureSize":      _comp(c5),
        "comp_CoverageGap":       _comp(c6),
        "comp_Staleness":         _comp(c7),
        "comp_Concentration":     _comp(c8),
        "comp_STOnlyPenalty":     _comp(c9),

        # ── Audit ─────────────────────────────────────────────────────────────
        "activeComponents":       ",".join(active_keys),
        "skippedComponents":      ",".join(skipped_keys),

        # ── Final ─────────────────────────────────────────────────────────────
        "stressScore":            stress,
        "stressLabel":            label,
        "riskTier":               _tier(lt_rating or st_rating or ""),

        # ── Raw arrays (kept for flat-column expansion below) ─────────────────
        "_bankFacilities":        doc.get("bankFacilities") or [],
        "_instruments":           [
            i for i in (doc.get("instruments") or [])
            if clean_rating(i.get("rating", "")).upper() not in INSTRUMENT_SKIP_VALUES
            and i.get("rating", "").upper() not in INSTRUMENT_SKIP_VALUES
            and i.get("instrumentName", "").upper() not in INSTRUMENT_SKIP_VALUES
            and i.get("isin", "").upper() != "ISIN"   # skip header rows
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7 ── FLAT COLUMN BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def flatten_row(row: dict, max_fac: int, max_inst: int) -> dict:
    """
    Expand _bankFacilities and _instruments into numbered flat columns,
    then remove the raw array keys.
    """
    out = {k: v for k, v in row.items()
           if k not in ("_bankFacilities", "_instruments")}

    facs  = row["_bankFacilities"]
    insts = row["_instruments"]

    for i in range(1, max_fac + 1):
        fac = facs[i - 1] if i <= len(facs) else {}
        out[f"facility_{i}_lender"]  = fac.get("lenderName", "")
        out[f"facility_{i}_name"]    = fac.get("facility", "")
        out[f"facility_{i}_amount"]  = fac.get("amount", "")
        out[f"facility_{i}_rating"]  = fac.get("rating", "")

    for i in range(1, max_inst + 1):
        inst = insts[i - 1] if i <= len(insts) else {}
        out[f"instrument_{i}_name"]      = inst.get("instrumentName", "")
        out[f"instrument_{i}_issueSize"] = inst.get("issueSize", "")
        out[f"instrument_{i}_rating"]    = inst.get("rating", "")

    return out


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8 ── OUTPUT FORMATTERS
# ═══════════════════════════════════════════════════════════════════════════════

def _pct(v) -> str:
    return str(round(v * 100, 4)) if v is not None else ""

def _comp(v) -> str:
    return str(round(v * 100, 2)) if v is not None else ""

def _label(s: float) -> str:
    if s < 5:   return "Minimal"
    if s < 15:  return "Low"
    if s < 30:  return "Moderate"
    if s < 50:  return "Elevated"
    if s < 70:  return "High"
    return "Severe"

def _tier(r: str) -> str:
    ig  = {"AAA","AA+","AA","AA-","A+","A","A-","BBB+","BBB","BBB-",
           "A1+","A1","A2+","A2","A2-"}
    sig = {"BB+","BB","BB-","B+","B","B-","A3+","A3","A3-","A4+","A4","A4-"}
    r = r.upper()
    if r in ig:    return "Investment Grade"
    if r in sig:   return "Sub-Investment Grade"
    if r == "C":   return "Near Default"
    if r == "D":   return "Default"
    return "Unrated"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 9 ── MAIN PIPELINE (two-pass for flat columns)
# ═══════════════════════════════════════════════════════════════════════════════

def run(mongo_uri, db_name, col_name, out_csv, limit=0):
    print(f"[INFO] Connecting -> {mongo_uri}  db={db_name}  col={col_name}")
    client = MongoClient(mongo_uri)

    def get_cursor():
        c = client[db_name][col_name].find({})
        return c.limit(limit) if limit else c

    # Pass 1: compute stress + find max array lengths
    print("[INFO] Pass 1 - computing stress scores...")
    rows, errors = [], 0
    max_fac  = 0
    max_inst = 0

    for doc in get_cursor():
        try:
            row = compute_stress(doc)
            max_fac  = max(max_fac,  len(row["_bankFacilities"]))
            max_inst = max(max_inst, len(row["_instruments"]))
            rows.append(row)
        except Exception as e:
            errors += 1
            print(f"  [WARN] {doc.get('companyCode', '?')}: {e}")

    print(f"[INFO] Max facilities: {max_fac}   Max instruments: {max_inst}")

    rows.sort(
        key=lambda x: float(x["stressScore"]) if x["stressScore"] != "" else 0,
        reverse=True,
    )

    if not rows:
        print("[WARN] No rows produced.")
        return

    # Pass 2: flatten and write
    print("[INFO] Pass 2 - writing flat CSV...")
    flat_rows = [flatten_row(r, max_fac, max_inst) for r in rows]

    os.makedirs(os.path.dirname(out_csv) or ".", exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(flat_rows[0].keys()))
        w.writeheader()
        w.writerows(flat_rows)

    print(f"\n[OK] {len(rows)} entities written -> {out_csv}  (errors: {errors})\n")

    from collections import Counter
    for title, key in [("Stress Label", "stressLabel"), ("Risk Tier", "riskTier")]:
        dist = Counter(r[key] for r in rows)
        print(f"{title} Distribution:")
        for k, v in sorted(dist.items(), key=lambda x: -x[1]):
            print(f"  {k:<28} {v:>5}  {'#' * min(v, 40)}")
        print()

    scores = [float(r["stressScore"]) for r in rows if r["stressScore"] != ""]
    if scores:
        print(
            f"Score stats -> min={min(scores):.1f}  max={max(scores):.1f}  "
            f"mean={statistics.mean(scores):.1f}  "
            f"median={statistics.median(scores):.1f}"
        )

    inc_count = sum(1 for r in rows if r.get("incFlag") == "Yes")
    print(f"\nINC/Withdrawn entities: {inc_count} of {len(rows)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="CRISIL Entity Stress Pipeline v3")
    ap.add_argument("--uri",   default=os.environ.get("MONGO_URI",  "mongodb://localhost:27017"))
    ap.add_argument("--db",    default=os.environ.get("MONGO_DB",   "financial_kg"))
    ap.add_argument("--col",   default=os.environ.get("MONGO_COL",  "companies"))
    ap.add_argument("--out",   default=os.environ.get("ENTITY_STRESS_OUT",
                                                       "data/outputs/entity_stress_scores.csv"))
    ap.add_argument("--limit", type=int,
                    default=int(os.environ.get("ENTITY_STRESS_LIMIT", 0)),
                    help="0 = all documents")
    a = ap.parse_args()
    run(a.uri, a.db, a.col, a.out, a.limit)