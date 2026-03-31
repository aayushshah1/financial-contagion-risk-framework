"""
prototype_kg/relationships/lends_to.py
Build LENDS_TO edges.

Two entry points:
  build_lends_to(driver, bank_docs)
      Bank-side: (:Bank)-[:LENDS_TO]->(:Company)
      Source: bank doc advances.companies (pre-resolved by CIN)

  build_lends_to_from_companies(driver, company_docs, registry)
      Company-side: polymorphic; reads each company's bankFacilities list.
      Resolves each lenderName via the GlobalEntityRegistry:
        Bank   → (:Bank)-[:LENDS_TO]->(:Company)
        Company→ (:Company)-[:LENDS_TO]->(:Company)
        None   → creates a :Company stub (isStub=true) then
                 (:Company:stub)-[:LENDS_TO]->(:Company)

This enables multi-hop chains, e.g.
  Bank X → LENDS_TO → Company B → LENDS_TO → Company A
"""

from __future__ import annotations
import json
import re
from collections import defaultdict
from pathlib import Path

from neo4j import Driver


# Map from bankFacilityMapping canonical keys → short labels stored on edge
FACILITY_LABEL_MAP = {
    "Bills Purchased & Discounted": "Bills Discounting",
    "Cash Credits, Overdrafts & Loans": "Working Capital",
    "Term Loans": "Term Loan",
}

LGD_MULTIPLIER_MAP = {
    "Secured": 0.4,
    "Unsecured": 0.6,
    "Senior": 0.3,
    "Subordinated": 0.8,
}

T_MULTIPLIER_MAP = {
    "TermLoan": 0.9,
    "WC": 0.7,
    "CP": 1.2,
    "Guarantee": 0.3,
    "ECB": 0.8,
}

DEFAULT_LGD_CATEGORY = "Unknown"
DEFAULT_T_CATEGORY = "Unknown"

_TRAILING_NOISE_RE = re.compile(r"[\s#%&@*^~!$<>|`+={}\[\](),:;._-]+$")
_WHITESPACE_RE = re.compile(r"\s+")

_CANONICAL_T_BY_BUCKET = {
    "Bills Purchased & Discounted": "CP",
    "Cash Credits, Overdrafts & Loans": "WC",
    "Term Loans": "TermLoan",
}

_DEFAULT_RISK_MAPPING = {
    "canonicalDefaults": {
        "Bills Purchased & Discounted": {"tCategory": "CP", "lgdCategory": "Senior"},
        "Cash Credits, Overdrafts & Loans": {"tCategory": "WC", "lgdCategory": "Secured"},
        "Term Loans": {"tCategory": "TermLoan", "lgdCategory": "Secured"},
    },
    "keywordOverrides": [
        {"containsAny": ["subordinated", "tier ii", "tier 2", "lower tier"], "lgdCategory": "Subordinated"},
        {"containsAny": ["senior"], "lgdCategory": "Senior"},
        {"containsAny": ["unsecured", "clean"], "lgdCategory": "Unsecured"},
        {"containsAny": ["secured", "hypothecation", "mortgage", "pledge"], "lgdCategory": "Secured"},
        {"containsAny": ["external commercial", "ecb"], "tCategory": "ECB"},
        {"containsAny": ["guarantee", "letter of credit", "standby", "non fund"], "tCategory": "Guarantee"},
        {"containsAny": ["bill", "discount", "factoring", "forfaiting", "cheque purchase"], "tCategory": "CP"},
        {
            "containsAny": [
                "working capital",
                "cash credit",
                "overdraft",
                "packing credit",
                "pre shipment",
                "post shipment",
            ],
            "tCategory": "WC",
        },
        {"containsAny": ["term loan", "rupee term", "long term"], "tCategory": "TermLoan"},
    ],
}

_ROOT_DIR = Path(__file__).resolve().parents[2]
_BANK_FACILITY_MAPPING_PATH = _ROOT_DIR / "data" / "bank" / "bankFacilityMapping.json"
_FACILITY_RISK_MAPPING_PATH = _ROOT_DIR / "data" / "bank" / "facilityRiskMapping.json"


def _normalize_facility_key(raw_value: str) -> str:
    key = _WHITESPACE_RE.sub(" ", str(raw_value or "").strip().lower())
    key = _TRAILING_NOISE_RE.sub("", key)
    return key.strip()


def _load_json(path: Path):
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _build_facility_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    raw_mapping = _load_json(_BANK_FACILITY_MAPPING_PATH)
    if not isinstance(raw_mapping, dict):
        return lookup

    for canonical_bucket, raw_values in raw_mapping.items():
        normalized_canonical = _normalize_facility_key(canonical_bucket)
        if normalized_canonical:
            lookup[normalized_canonical] = canonical_bucket

        if not isinstance(raw_values, list):
            continue
        for raw_value in raw_values:
            normalized = _normalize_facility_key(str(raw_value))
            if normalized:
                lookup[normalized] = canonical_bucket
    return lookup


def _load_risk_mapping() -> dict:
    raw_mapping = _load_json(_FACILITY_RISK_MAPPING_PATH)
    if isinstance(raw_mapping, dict):
        return raw_mapping
    return _DEFAULT_RISK_MAPPING


_FACILITY_LOOKUP = _build_facility_lookup()
_RISK_MAPPING = _load_risk_mapping()


def _dominant_category(amount_by_category: dict[str, float], default_value: str) -> str:
    if not amount_by_category:
        return default_value
    return max(amount_by_category.items(), key=lambda item: (item[1], item[0]))[0]


def _new_risk_stats() -> dict:
    return {
        "riskAmountBasis": 0.0,
        "lgdWeightedSum": 0.0,
        "tWeightedSum": 0.0,
        "lgdAmountByCategory": defaultdict(float),
        "tAmountByCategory": defaultdict(float),
    }


def _find_keyword_override(normalized_facility: str, field_name: str) -> str | None:
    for rule in _RISK_MAPPING.get("keywordOverrides", []):
        if not isinstance(rule, dict):
            continue
        category = rule.get(field_name)
        if not category:
            continue

        for token in rule.get("containsAny", []):
            normalized_token = _normalize_facility_key(str(token))
            if normalized_token and normalized_token in normalized_facility:
                return str(category)
    return None


def _resolve_facility_risk(raw_facility_type: str) -> tuple[str, float, str, float]:
    normalized_facility = _normalize_facility_key(raw_facility_type)
    canonical_bucket = _FACILITY_LOOKUP.get(normalized_facility)

    canonical_defaults = _RISK_MAPPING.get("canonicalDefaults", {})
    default_for_bucket = canonical_defaults.get(canonical_bucket, {}) if isinstance(canonical_defaults, dict) else {}

    t_category = str(default_for_bucket.get("tCategory") or "")
    lgd_category = str(default_for_bucket.get("lgdCategory") or "")

    override_t = _find_keyword_override(normalized_facility, "tCategory")
    if override_t:
        t_category = override_t

    override_lgd = _find_keyword_override(normalized_facility, "lgdCategory")
    if override_lgd:
        lgd_category = override_lgd

    if not t_category and canonical_bucket:
        t_category = _CANONICAL_T_BY_BUCKET.get(canonical_bucket, "")

    if not lgd_category:
        if t_category in {"TermLoan", "ECB", "WC"}:
            lgd_category = "Secured"
        elif t_category in {"CP", "Guarantee"}:
            lgd_category = "Senior"

    if not t_category:
        t_category = DEFAULT_T_CATEGORY
    if not lgd_category:
        lgd_category = DEFAULT_LGD_CATEGORY

    return (
        lgd_category,
        LGD_MULTIPLIER_MAP.get(lgd_category, 1.0),
        t_category,
        T_MULTIPLIER_MAP.get(t_category, 1.0),
    )


def _accumulate_risk_stats(stats: dict, raw_facility_type: str, amount: float) -> None:
    if amount <= 0.0:
        return

    lgd_category, lgd_multiplier, t_category, t_multiplier = _resolve_facility_risk(raw_facility_type)
    stats["riskAmountBasis"] += amount
    stats["lgdWeightedSum"] += amount * lgd_multiplier
    stats["tWeightedSum"] += amount * t_multiplier
    stats["lgdAmountByCategory"][lgd_category] += amount
    stats["tAmountByCategory"][t_category] += amount


def _finalize_risk_stats(stats: dict) -> dict:
    basis = float(stats.get("riskAmountBasis", 0.0) or 0.0)
    lgd_weighted_sum = float(stats.get("lgdWeightedSum", 0.0) or 0.0)
    t_weighted_sum = float(stats.get("tWeightedSum", 0.0) or 0.0)

    if basis > 0:
        lgd_multiplier = round(lgd_weighted_sum / basis, 6)
        t_multiplier = round(t_weighted_sum / basis, 6)
    else:
        lgd_multiplier = 1.0
        t_multiplier = 1.0

    lgd_category = _dominant_category(stats.get("lgdAmountByCategory", {}), DEFAULT_LGD_CATEGORY)
    t_category = _dominant_category(stats.get("tAmountByCategory", {}), DEFAULT_T_CATEGORY)

    return {
        "riskAmountBasis": round(basis, 6),
        "lgdWeightedSum": round(lgd_weighted_sum, 6),
        "tWeightedSum": round(t_weighted_sum, 6),
        "lgdCategory": lgd_category,
        "tCategory": t_category,
        "lgdMultiplier": lgd_multiplier,
        "tMultiplier": t_multiplier,
    }


def _canonical_facility_type(raw_type: str) -> str:
    canonical_bucket = _FACILITY_LOOKUP.get(_normalize_facility_key(raw_type))
    if canonical_bucket:
        return FACILITY_LABEL_MAP.get(canonical_bucket, canonical_bucket)
    cleaned = _TRAILING_NOISE_RE.sub("", str(raw_type or "")).strip()
    return cleaned or str(raw_type or "")


MERGE_LENDS_TO = """
UNWIND $batch AS row
MATCH (b:Bank {bankSymbol: row.bankSymbol})
MATCH (c:Company {cin: row.cin})
MERGE (b)-[r:LENDS_TO]->(c)
SET r.totalAmount    = row.totalAmount,
    r.facilityCount  = row.facilityCount,
    r.facilityTypes  = row.facilityTypes,
    r.currency       = 'INR Crore',
    r.source         = 'CRISIL',
    r.dataYear       = row.dataYear,
    r.lgdCategory    = row.lgdCategory,
    r.tCategory      = row.tCategory,
    r.riskAmountBasis= row.riskAmountBasis,
    r.lgdWeightedSum = row.lgdWeightedSum,
    r.tWeightedSum   = row.tWeightedSum,
    r.lgdMultiplier  = row.lgdMultiplier,
    r.tMultiplier    = row.tMultiplier
"""


def build_lends_to(
    driver: Driver,
    bank_docs: list[dict],
) -> int:
    """
    Create LENDS_TO edges from all bank docs.
    Skips records where hasCIN is False or cin is absent/empty.
    Returns total number of edges created/merged.
    """
    records: list[dict] = []
    skipped_no_cin = 0

    for doc in bank_docs:
        bank_symbol = doc.get("bankSymbol")
        data_year   = doc.get("dataYear", 2025)

        if not bank_symbol:
            continue

        companies = doc.get("advances", {}).get("companies", [])

        for company in companies:
            # Use cin directly — hasCIN / dummyCIN are NOT checked here;
            # all records with a non-empty cin are included.
            cin = company.get("cin", "")
            if not cin:
                skipped_no_cin += 1
                continue

            facilities = company.get("facilities", [])
            total_amount   = 0.0
            facility_count = 0
            types_seen: set[str] = set()
            risk_stats = _new_risk_stats()

            for fac in facilities:
                amount = fac.get("amount")
                if amount is None:
                    continue
                try:
                    amt = float(amount)
                except (TypeError, ValueError):
                    continue
                total_amount   += amt
                facility_count += 1
                raw_type = fac.get("facilityType", "")
                _accumulate_risk_stats(risk_stats, str(raw_type or ""), amt)
                if raw_type:
                    types_seen.add(_canonical_facility_type(raw_type))

            if facility_count == 0:
                total_amount = float(company.get("totalExposure", 0) or 0)

            risk_metrics = _finalize_risk_stats(risk_stats)

            records.append({
                "bankSymbol":    bank_symbol,
                "cin":           cin,
                "totalAmount":   round(total_amount, 4),
                "facilityCount": facility_count,
                "facilityTypes": sorted(types_seen),
                "dataYear":      data_year,
                "lgdCategory":   risk_metrics["lgdCategory"],
                "tCategory":     risk_metrics["tCategory"],
                "riskAmountBasis": risk_metrics["riskAmountBasis"],
                "lgdWeightedSum": risk_metrics["lgdWeightedSum"],
                "tWeightedSum": risk_metrics["tWeightedSum"],
                "lgdMultiplier": risk_metrics["lgdMultiplier"],
                "tMultiplier":   risk_metrics["tMultiplier"],
            })

    BATCH_SIZE = 500
    total = 0

    with driver.session() as session:
        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i : i + BATCH_SIZE]
            session.run(MERGE_LENDS_TO, batch=batch)
            total += len(batch)

    if skipped_no_cin:
        print(f"[lends_to] Skipped {skipped_no_cin} advance record(s) with no CIN mapping.")
    print(f"[lends_to] Created/merged {total} LENDS_TO edge(s).")
    return total


# ---------------------------------------------------------------------------
# Company-side: polymorphic LENDS_TO from bankFacilities
# ---------------------------------------------------------------------------

# Upsert a stub :Company for lenders that don't resolve to a known node.
# ON CREATE only — never overwrite a real node that shares the same CIN.
_MERGE_LENDER_STUB = """
UNWIND $batch AS row
MERGE (c:Company {cin: row.cin})
ON CREATE SET
    c.name          = row.crisilName,
    c.crisilName    = row.crisilName,
    c.isStub        = true,
    c.resolved      = false,
    c.nodeSource    = 'LenderStub'
"""

# Bank → Company  (resolved lender is a target bank)
_MERGE_LENDS_TO_BANK_CO = """
UNWIND $batch AS row
MATCH (b:Bank {bankSymbol: row.lenderBankSymbol})
MATCH (c:Company {cin: row.borrowerCin})
MERGE (b)-[r:LENDS_TO]->(c)
SET r.totalAmount    = coalesce(r.totalAmount, 0.0) + row.totalAmount,
    r.facilityCount  = coalesce(r.facilityCount, 0) + row.facilityCount,
    r.facilityTypes  = row.facilityTypes,
    r.currency       = 'INR Crore',
    r.source         = 'CRISIL_CO',
    r.dataYear       = row.dataYear,
    r.lenderRawName  = row.lenderRawName,
    r.resolutionConf = row.resolutionConf,
    r.absorption     = row.absorption,
    r.lgdWeightedSum = coalesce(r.lgdWeightedSum, 0.0) + row.lgdWeightedSum,
    r.tWeightedSum   = coalesce(r.tWeightedSum, 0.0) + row.tWeightedSum,
    r.riskAmountBasis= coalesce(r.riskAmountBasis, 0.0) + row.riskAmountBasis,
    r.lgdMultiplier  = CASE
        WHEN (coalesce(r.riskAmountBasis, 0.0) + row.riskAmountBasis) > 0.0 THEN
            round((coalesce(r.lgdWeightedSum, 0.0) + row.lgdWeightedSum) / (coalesce(r.riskAmountBasis, 0.0) + row.riskAmountBasis), 6)
        ELSE 1.0
    END,
    r.tMultiplier    = CASE
        WHEN (coalesce(r.riskAmountBasis, 0.0) + row.riskAmountBasis) > 0.0 THEN
            round((coalesce(r.tWeightedSum, 0.0) + row.tWeightedSum) / (coalesce(r.riskAmountBasis, 0.0) + row.riskAmountBasis), 6)
        ELSE 1.0
    END,
    r.lgdCategory    = CASE
        WHEN coalesce(r.lgdCategory, 'Unknown') IN ['Unknown', row.lgdCategory] THEN row.lgdCategory
        WHEN row.lgdCategory = 'Unknown' THEN coalesce(r.lgdCategory, 'Unknown')
        ELSE 'Mixed'
    END,
    r.tCategory      = CASE
        WHEN coalesce(r.tCategory, 'Unknown') IN ['Unknown', row.tCategory] THEN row.tCategory
        WHEN row.tCategory = 'Unknown' THEN coalesce(r.tCategory, 'Unknown')
        ELSE 'Mixed'
    END
"""

# Company → Company  (resolved lender is another company, or a stub)
_MERGE_LENDS_TO_CO_CO = """
UNWIND $batch AS row
MATCH (lender:Company {cin: row.lenderCin})
MATCH (borrower:Company {cin: row.borrowerCin})
MERGE (lender)-[r:LENDS_TO]->(borrower)
SET r.totalAmount    = coalesce(r.totalAmount, 0.0) + row.totalAmount,
    r.facilityCount  = coalesce(r.facilityCount, 0) + row.facilityCount,
    r.facilityTypes  = row.facilityTypes,
    r.currency       = 'INR Crore',
    r.source         = 'CRISIL_CO',
    r.dataYear       = row.dataYear,
    r.lenderRawName  = row.lenderRawName,
    r.resolutionConf = row.resolutionConf,
    r.transmittance  = row.transmittance,
    r.lgdWeightedSum = coalesce(r.lgdWeightedSum, 0.0) + row.lgdWeightedSum,
    r.tWeightedSum   = coalesce(r.tWeightedSum, 0.0) + row.tWeightedSum,
    r.riskAmountBasis= coalesce(r.riskAmountBasis, 0.0) + row.riskAmountBasis,
    r.lgdMultiplier  = CASE
        WHEN (coalesce(r.riskAmountBasis, 0.0) + row.riskAmountBasis) > 0.0 THEN
            round((coalesce(r.lgdWeightedSum, 0.0) + row.lgdWeightedSum) / (coalesce(r.riskAmountBasis, 0.0) + row.riskAmountBasis), 6)
        ELSE 1.0
    END,
    r.tMultiplier    = CASE
        WHEN (coalesce(r.riskAmountBasis, 0.0) + row.riskAmountBasis) > 0.0 THEN
            round((coalesce(r.tWeightedSum, 0.0) + row.tWeightedSum) / (coalesce(r.riskAmountBasis, 0.0) + row.riskAmountBasis), 6)
        ELSE 1.0
    END,
    r.lgdCategory    = CASE
        WHEN coalesce(r.lgdCategory, 'Unknown') IN ['Unknown', row.lgdCategory] THEN row.lgdCategory
        WHEN row.lgdCategory = 'Unknown' THEN coalesce(r.lgdCategory, 'Unknown')
        ELSE 'Mixed'
    END,
    r.tCategory      = CASE
        WHEN coalesce(r.tCategory, 'Unknown') IN ['Unknown', row.tCategory] THEN row.tCategory
        WHEN row.tCategory = 'Unknown' THEN coalesce(r.tCategory, 'Unknown')
        ELSE 'Mixed'
    END
"""

_SLUG_RE = re.compile(r"[^a-z0-9]+")

def _slugify(name: str) -> str:
    """Deterministic lowercase slug from a lender name — used as stub CIN suffix."""
    n = name.lower().strip()
    n = _SLUG_RE.sub("_", n).strip("_")
    return n[:60]   # cap length


_SKIP_LENDER_NAMES = frozenset({
    "", "not applicable", "na", "n/a", "nil", "none", "not available",
    "tbd", "to be decided", "-",
})


def build_lends_to_from_companies(
    driver: Driver,
    company_docs: list[dict],
    registry,           # GlobalEntityRegistry
    *,
    bank_tier1: dict[str, float] | None = None,
    data_year: int = 2025,
    batch_size: int = 500,
) -> int:
    """
    Build polymorphic LENDS_TO edges by walking each company's bankFacilities list.

    Two-phase approach:
      Phase 1 — upsert :Company stub nodes for unresolved lenders.
      Phase 2 — upsert LENDS_TO edges (Bank→Company or Company→Company).

    Returns total number of edges created/merged.
    """
    from resolution.entity_resolver import _normalize   # local import to avoid circular

    if bank_tier1 is None:
        bank_tier1 = {}

    bank_edge_records:    list[dict] = []
    company_edge_records: list[dict] = []
    stub_records_seen:    dict[str, dict] = {}   # stub_cin → record (deduplicated)
    skipped_no_cin        = 0
    skipped_no_lender     = 0

    for doc in company_docs:
        borrower_cin = str(doc.get("cin") or "").strip()
        if not borrower_cin:
            skipped_no_cin += 1
            continue

        # Aggregate facilities per (borrowerCin, lenderName) pair
        lender_agg: dict[str, dict] = {}

        for fac in doc.get("bankFacilities", []):
            raw_lender = str(fac.get("lenderName") or "").strip()
            if _normalize(raw_lender) in _SKIP_LENDER_NAMES or not raw_lender:
                skipped_no_lender += 1
                continue

            try:
                amt = float(fac.get("amount") or 0)
            except (TypeError, ValueError):
                amt = 0.0

            facility_type = str(fac.get("facility") or "").strip()

            if raw_lender not in lender_agg:
                lender_agg[raw_lender] = {
                    "total": 0.0,
                    "count": 0,
                    "types": set(),
                    "risk": _new_risk_stats(),
                }
            lender_agg[raw_lender]["total"] += amt
            lender_agg[raw_lender]["count"] += 1
            _accumulate_risk_stats(lender_agg[raw_lender]["risk"], facility_type, amt)
            if facility_type:
                lender_agg[raw_lender]["types"].add(facility_type)

        # Total borrowing across ALL lenders for this company (denominator for transmittance)
        total_for_borrower = sum(a["total"] for a in lender_agg.values())

        # Resolve each aggregated lender
        for raw_lender, agg in lender_agg.items():
            node_type, canonical_id, confidence = registry.resolve(raw_lender)
            risk_metrics = _finalize_risk_stats(agg["risk"])

            edge_base = {
                "borrowerCin":   borrower_cin,
                "totalAmount":   round(agg["total"], 4),
                "facilityCount": agg["count"],
                "facilityTypes": sorted(agg["types"]),
                "dataYear":      data_year,
                "lenderRawName": raw_lender,
                "resolutionConf": round(confidence, 3),
                "lgdCategory":   risk_metrics["lgdCategory"],
                "tCategory":     risk_metrics["tCategory"],
                "riskAmountBasis": risk_metrics["riskAmountBasis"],
                "lgdWeightedSum": risk_metrics["lgdWeightedSum"],
                "tWeightedSum": risk_metrics["tWeightedSum"],
                "lgdMultiplier": risk_metrics["lgdMultiplier"],
                "tMultiplier": risk_metrics["tMultiplier"],
            }

            if node_type == "Bank":
                # absorption = this facility / bank's Tier 1 Capital
                t1 = bank_tier1.get(canonical_id)
                absorption = round(agg["total"] / t1, 6) if t1 else None
                bank_edge_records.append({
                    **edge_base,
                    "lenderBankSymbol": canonical_id,
                    "absorption":       absorption,
                })

            elif node_type == "Company":
                # transmittance = this lender's share of borrower's total facilities
                transmittance = round(agg["total"] / total_for_borrower, 6) if total_for_borrower > 0 else None
                company_edge_records.append({
                    **edge_base,
                    "lenderCin":     canonical_id,
                    "transmittance": transmittance,
                })

            else:
                # Unresolved → create a stable stub CIN
                stub_cin = "LSTUB_" + _slugify(raw_lender)
                if stub_cin not in stub_records_seen:
                    stub_records_seen[stub_cin] = {
                        "cin":        stub_cin,
                        "crisilName": raw_lender,
                    }
                transmittance = round(agg["total"] / total_for_borrower, 6) if total_for_borrower > 0 else None
                company_edge_records.append({
                    **edge_base,
                    "lenderCin":     stub_cin,
                    "transmittance": transmittance,
                })

    stub_records = list(stub_records_seen.values())

    with driver.session() as session:
        # Phase 1 — upsert stubs (must exist before edge MATCH)
        for i in range(0, len(stub_records), batch_size):
            session.run(_MERGE_LENDER_STUB, batch=stub_records[i : i + batch_size])

        # Phase 2 — upsert edges
        for i in range(0, len(bank_edge_records), batch_size):
            session.run(_MERGE_LENDS_TO_BANK_CO, batch=bank_edge_records[i : i + batch_size])

        for i in range(0, len(company_edge_records), batch_size):
            session.run(_MERGE_LENDS_TO_CO_CO, batch=company_edge_records[i : i + batch_size])

    total_edges = len(bank_edge_records) + len(company_edge_records)

    print(
        f"[lends_to/co] Company-side LENDS_TO complete:\n"
        f"              Bank→Company  : {len(bank_edge_records):>6}\n"
        f"              Company→Company: {len(company_edge_records):>6}  "
        f"(incl. {len(stub_records)} lender stubs)\n"
        f"              Skipped (no borrower CIN): {skipped_no_cin}\n"
        f"              Skipped (no lender name) : {skipped_no_lender}"
    )
    return total_edges
