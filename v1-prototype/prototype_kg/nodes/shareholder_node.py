"""
prototype_kg/nodes/shareholder_node.py
Extract all named shareholder entities and create :Shareholder nodes in Neo4j.

Resolution strategy (via GlobalEntityRegistry):
  - Entity resolves to "Bank"    → skip :Shareholder creation; edge builders
                                    will use the existing :Bank node directly.
  - Entity resolves to "Company" → skip :Shareholder creation; edge builders
                                    will use the existing :Company node (by CIN).
  - Unresolved                   → create a :Shareholder node (stub).

This replaces the old KNOWN_SUBSIDIARIES hardcoded lookup.

Returns a list of ExtractedShareholder / ExtractedCompanyShareholder dicts
for downstream edge builders.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from neo4j import Driver
from resolution.entity_resolver import GlobalEntityRegistry


# ---------------------------------------------------------------------------
# Data classes shared with relationship builders
# ---------------------------------------------------------------------------

@dataclass
class ExtractedShareholder:
    raw_name: str                       # exactly as it appears in SHP XBRL
    normalized_name: str                # lowercase, stripped
    shareholderCategory: str
    # Resolution outcome — exactly one of the three below will be set
    bank_symbol: str | None             # set if entity resolved to a :Bank
    resolved_company_cin: str | None    # set if entity resolved to a :Company
    # (if both above are None, entity becomes a :Shareholder stub)
    numberOfShares: int
    shareholdingPercentage: float
    source_bank_symbol: str             # which bank's SHP this came from


@dataclass
class ExtractedCompanyShareholder:
    """A shareholder entity extracted from a company's shareholdingPattern."""
    raw_name: str
    normalized_name: str
    shareholderCategory: str
    bank_symbol: str | None
    resolved_company_cin: str | None
    numberOfShares: int
    shareholdingPercentage: float
    source_company_cin: str             # CIN of the company whose SHP this came from


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize(name: str) -> str:
    return name.lower().strip()


def _safe_int(val) -> int:
    if isinstance(val, dict) and "$numberLong" in val:
        return int(val["$numberLong"])
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _safe_float(val) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Arelle format support
# ---------------------------------------------------------------------------

# Ordered hints: first matching substring wins.
# Arelle axis names follow "DetailsOfSharesHeldBy<Category>[Axis]" convention.
_AXIS_HINTS: list[tuple[str, str]] = [
    ("MutualFund",                        "MutualFund"),
    ("InsuranceCompan",                   "InsuranceCompany"),
    ("ProvidentFund",                     "ProvidentFund"),
    ("PensionFund",                       "ProvidentFund"),
    ("ForeignPortfolioInvestorOne",       "FPI_Cat1"),
    ("ForeignPortfolioInvestorTwo",       "FPI_Cat2"),
    ("CustodianOrDRHolder",               "Custodian"),
    ("CentralGovernment",                 "GovernmentPromoter"),
    ("StateGovernment",                   "GovernmentPromoter"),
    ("OtherInstitutionsForeign",          "OtherInstitutionForeign"),
    ("OtherInstitutionForeign",           "OtherInstitutionForeign"),
    ("OtherInstitutionsDomestic",         "OtherInstitutionDomestic"),
    ("ResidentIndividual",                "ResidentIndividual"),
    ("NonResidentIndian",                 "NonResidentIndian"),
    ("BodiesCorporate",                   "BodyCorporate"),
    ("BodyCorporate",                     "BodyCorporate"),
    ("OtherNonInstitution",               "OtherNonInstitution"),
    ("Banks",                             "Bank"),
]


def _axis_to_category(axis: str) -> str:
    """Derive a shareholder category label from an Arelle axis name."""
    for hint, cat in _AXIS_HINTS:
        if hint in axis:
            return cat
    return "Unknown"


def _norm_arelle_entity(e: dict) -> dict:
    """
    Normalise an Arelle-format entity dict to the same field names used by
    the ElementTree path so downstream code is format-agnostic.

    Arelle keys                                         → normalised keys
    NameOfTheShareholder (camelCase)                    → name
    ShareholdingAsAPercentageOfTotalNumberOfShares      → shareholdingPercentage
    NumberOfShares                                      → numberOfShares  (unchanged)
    """
    return {
        "name": e.get("name") or e.get("nameOfTheShareholder", ""),
        "numberOfShares": e.get("numberOfShares", 0),
        "shareholdingPercentage": (
            e.get("shareholdingPercentage")
            or e.get("shareholdingAsAPercentageOfTotalNumberOfShares", 0.0)
        ),
    }


# ---------------------------------------------------------------------------
# SHP tree walkers
# ---------------------------------------------------------------------------

def _get_entities(
    node: dict | None,
    category: str,
    bank_symbol: str,
    registry: GlobalEntityRegistry,
) -> list[ExtractedShareholder]:
    if not node:
        return []
    results = []
    for entity in node.get("entities", []):
        name = entity.get("name", "").strip()
        if not name:
            continue

        node_type, canonical_id, _ = registry.resolve(name)

        # Self-loop guard: a bank cannot be its own shareholder
        if node_type == "Bank" and canonical_id == bank_symbol:
            continue

        bank_sym    = canonical_id if node_type == "Bank"    else None
        company_cin = canonical_id if node_type == "Company" else None

        results.append(
            ExtractedShareholder(
                raw_name=name,
                normalized_name=_normalize(name),
                shareholderCategory=category,
                bank_symbol=bank_sym,
                resolved_company_cin=company_cin,
                numberOfShares=_safe_int(entity.get("numberOfShares", 0)),
                shareholdingPercentage=_safe_float(entity.get("shareholdingPercentage", 0.0)),
                source_bank_symbol=bank_symbol,
            )
        )
    return results


def extract_shareholders(
    bank_doc: dict,
    registry: GlobalEntityRegistry,
) -> list[ExtractedShareholder]:
    """
    Walk the full shareholdingPattern tree of one bank document and return
    all named entities as ExtractedShareholder objects.
    """
    bank_symbol = bank_doc.get("bankSymbol", "UNKNOWN")
    shp = bank_doc.get("shareholdingPattern", {}).get("shareholdingPattern", {})
    results: list[ExtractedShareholder] = []

    def _g(node, cat):
        return _get_entities(node, cat, bank_symbol, registry)

    # ---- Arelle flat format: {periodEnd, aggregates, entities: {axis: [...]}} ----
    arelle_entities = shp.get("entities")
    if isinstance(arelle_entities, dict) and not shp.get("promoterHolding"):
        for axis, entity_list in arelle_entities.items():
            cat = _axis_to_category(axis)
            for raw_entity in (entity_list or []):
                entity = _norm_arelle_entity(raw_entity)
                name = entity["name"]
                if not name:
                    continue
                node_type, canonical_id, _ = registry.resolve(name)
                if node_type == "Bank" and canonical_id == bank_symbol:
                    continue  # self-loop guard
                results.append(
                    ExtractedShareholder(
                        raw_name=name,
                        normalized_name=_normalize(name),
                        shareholderCategory=cat,
                        bank_symbol=canonical_id if node_type == "Bank" else None,
                        resolved_company_cin=canonical_id if node_type == "Company" else None,
                        numberOfShares=_safe_int(entity.get("numberOfShares", 0)),
                        shareholdingPercentage=_safe_float(entity.get("shareholdingPercentage", 0.0)),
                        source_bank_symbol=bank_symbol,
                    )
                )
        return results

    # ---- ET nested format: {promoterHolding, publicHolding, ...} ----
    promoter = shp.get("promoterHolding", {})
    results += _g(promoter, "Promoter")
    results += _g(promoter.get("government", {}), "GovernmentPromoter")

    # Public holding — Institutions
    institutions = shp.get("publicHolding", {}).get("institutions", {})
    results += _g(institutions.get("mutualFunds", {}),               "MutualFund")
    results += _g(institutions.get("insuranceCompanies", {}),         "InsuranceCompany")
    results += _g(institutions.get("banks", {}),                      "Bank")
    results += _g(institutions.get("providentFunds", {}),             "ProvidentFund")
    results += _g(institutions.get("otherInstitutionsDomestic", {}),  "OtherInstitutionDomestic")
    results += _g(institutions.get("otherInstitutionsForeign", {}),   "OtherInstitutionForeign")

    fpi = institutions.get("foreignPortfolioInvestors", {})
    results += _g(fpi.get("category1", {}), "FPI_Cat1")
    results += _g(fpi.get("category2", {}), "FPI_Cat2")

    # Public holding — Non-Institutions
    non_inst = shp.get("publicHolding", {}).get("nonInstitutions", {})
    results += _g(non_inst.get("residentIndividuals", {}),   "ResidentIndividual")
    results += _g(non_inst.get("nonResidentIndians", {}),    "NonResidentIndian")
    results += _g(non_inst.get("bodiesCorporate", {}),       "BodyCorporate")
    results += _g(non_inst.get("otherNonInstitutions", {}),  "OtherNonInstitution")

    # Non-Promoter Non-Public
    np_np = shp.get("nonPromoterNonPublicHolding", {})
    results += _g(np_np.get("custodian", {}), "Custodian")

    return results


# ---------------------------------------------------------------------------
# Neo4j node builder — bank SHP
# ---------------------------------------------------------------------------

def build_shareholder_nodes(
    driver: Driver,
    bank_docs: list[dict],
    registry: GlobalEntityRegistry,
) -> list[ExtractedShareholder]:
    """
    Extract all shareholders from bank docs and MERGE :Shareholder nodes for
    entities that could not be resolved to an existing :Bank or :Company node.

    Returns the full list of ExtractedShareholder for edge builders.
    """
    all_shareholders: list[ExtractedShareholder] = []
    for doc in bank_docs:
        all_shareholders += extract_shareholders(doc, registry)

    # Deduplicate for node creation; skip resolved entities
    seen: set[str] = set()
    to_create: list[ExtractedShareholder] = []
    resolved_bank    = 0
    resolved_company = 0

    for sh in all_shareholders:
        if sh.raw_name in seen:
            continue
        seen.add(sh.raw_name)

        if sh.bank_symbol:
            resolved_bank += 1
            continue    # :Bank node already exists
        if sh.resolved_company_cin:
            resolved_company += 1
            continue    # :Company node already exists
        to_create.append(sh)

    BATCH_SIZE = 500
    records = [
        {"shareholderName": sh.raw_name, "shareholderCategory": sh.shareholderCategory}
        for sh in to_create
    ]
    with driver.session() as session:
        for i in range(0, len(records), BATCH_SIZE):
            session.run(
                """
                UNWIND $batch AS row
                MERGE (s:Shareholder {shareholderName: row.shareholderName})
                SET s.shareholderCategory = row.shareholderCategory
                """,
                batch=records[i : i + BATCH_SIZE],
            )

    print(f"[shareholder_node] Extracted {len(all_shareholders)} raw entries from bank SHP.")
    print(f"[shareholder_node]   → {resolved_bank} resolved to :Bank, "
          f"{resolved_company} resolved to :Company, "
          f"{len(to_create)} new :Shareholder stub(s).")
    return all_shareholders


# ===========================================================================
# Company-level shareholding (financial_kg/company)
# ===========================================================================

def extract_company_shareholders(
    company_doc: dict,
    registry: GlobalEntityRegistry,
) -> list[ExtractedCompanyShareholder]:
    """
    Walk the shareholdingPattern of a company document and return all named
    entities as ExtractedCompanyShareholder objects.
    """
    company_cin = company_doc.get("cin", "UNKNOWN")
    shp = company_doc.get("shareholdingPattern", {})
    if not shp:
        return []

    results: list[ExtractedCompanyShareholder] = []

    def _get(node: dict | None, category: str) -> list[ExtractedCompanyShareholder]:
        if not node:
            return []
        out = []
        for entity in node.get("entities", []):
            name = entity.get("name", "").strip()
            if not name:
                continue
            node_type, canonical_id, _ = registry.resolve(name)

            # Self-loop guard: a company cannot be its own shareholder
            if node_type == "Company" and canonical_id == company_cin:
                continue

            bank_sym    = canonical_id if node_type == "Bank"    else None
            company_cin_resolved = canonical_id if node_type == "Company" else None
            out.append(
                ExtractedCompanyShareholder(
                    raw_name=name,
                    normalized_name=name.lower().strip(),
                    shareholderCategory=category,
                    bank_symbol=bank_sym,
                    resolved_company_cin=company_cin_resolved,
                    numberOfShares=_safe_int(entity.get("numberOfShares", 0)),
                    shareholdingPercentage=_safe_float(entity.get("shareholdingPercentage", 0.0)),
                    source_company_cin=company_cin,
                )
            )
        return out

    # ---- Arelle flat format ----
    arelle_entities = shp.get("entities")
    if isinstance(arelle_entities, dict) and not shp.get("promoterHolding"):
        for axis, entity_list in arelle_entities.items():
            cat = _axis_to_category(axis)
            for raw_entity in (entity_list or []):
                entity = _norm_arelle_entity(raw_entity)
                name = entity["name"]
                if not name:
                    continue
                node_type, canonical_id, _ = registry.resolve(name)
                if node_type == "Company" and canonical_id == company_cin:
                    continue  # self-loop guard
                results.append(
                    ExtractedCompanyShareholder(
                        raw_name=name,
                        normalized_name=name.lower().strip(),
                        shareholderCategory=cat,
                        bank_symbol=canonical_id if node_type == "Bank" else None,
                        resolved_company_cin=canonical_id if node_type == "Company" else None,
                        numberOfShares=_safe_int(entity.get("numberOfShares", 0)),
                        shareholdingPercentage=_safe_float(entity.get("shareholdingPercentage", 0.0)),
                        source_company_cin=company_cin,
                    )
                )
        return results

    # ---- ET nested format ----
    promoter = shp.get("promoterHolding", {})
    results += _get(promoter, "Promoter")
    results += _get(promoter.get("government", {}), "GovernmentPromoter")

    # Public holding — Institutions
    institutions = shp.get("publicHolding", {}).get("institutions", {})
    results += _get(institutions.get("mutualFunds", {}),              "MutualFund")
    results += _get(institutions.get("insuranceCompanies", {}),        "InsuranceCompany")
    results += _get(institutions.get("banks", {}),                     "Bank")
    results += _get(institutions.get("providentFunds", {}),            "ProvidentFund")
    results += _get(institutions.get("otherInstitutionsDomestic", {}), "OtherInstitutionDomestic")
    results += _get(institutions.get("otherInstitutionsForeign", {}),  "OtherInstitutionForeign")

    fpi = institutions.get("foreignPortfolioInvestors", {})
    results += _get(fpi.get("category1", {}), "FPI_Cat1")
    results += _get(fpi.get("category2", {}), "FPI_Cat2")

    # Public holding — Non-Institutions
    non_inst = shp.get("publicHolding", {}).get("nonInstitutions", {})
    results += _get(non_inst.get("residentIndividuals", {}),  "ResidentIndividual")
    results += _get(non_inst.get("nonResidentIndians", {}),   "NonResidentIndian")
    results += _get(non_inst.get("bodiesCorporate", {}),      "BodyCorporate")
    results += _get(non_inst.get("otherNonInstitutions", {}), "OtherNonInstitution")

    # Non-Promoter Non-Public
    np_np = shp.get("nonPromoterNonPublicHolding", {})
    results += _get(np_np.get("custodian", {}), "Custodian")

    return results


def build_company_shareholder_nodes(
    driver: Driver,
    company_docs: list[dict],
    registry: GlobalEntityRegistry,
) -> list[ExtractedCompanyShareholder]:
    """
    Extract shareholders from all company docs that have a shareholdingPattern
    and upsert :Shareholder nodes for unresolved entities only.

    Returns the full list for use by relationship builders.
    """
    all_shareholders: list[ExtractedCompanyShareholder] = []
    docs_with_shp = 0
    for doc in company_docs:
        if doc.get("shareholdingPattern") and doc.get("cin"):
            all_shareholders += extract_company_shareholders(doc, registry)
            docs_with_shp += 1

    seen: set[str] = set()
    to_create: list[ExtractedCompanyShareholder] = []
    resolved_bank    = 0
    resolved_company = 0

    for sh in all_shareholders:
        if sh.raw_name in seen:
            continue
        seen.add(sh.raw_name)
        if sh.bank_symbol:
            resolved_bank += 1
            continue
        if sh.resolved_company_cin:
            resolved_company += 1
            continue
        to_create.append(sh)

    BATCH_SIZE = 500
    records = [
        {"shareholderName": sh.raw_name, "shareholderCategory": sh.shareholderCategory}
        for sh in to_create
    ]
    with driver.session() as session:
        for i in range(0, len(records), BATCH_SIZE):
            session.run(
                """
                UNWIND $batch AS row
                MERGE (s:Shareholder {shareholderName: row.shareholderName})
                SET s.shareholderCategory = row.shareholderCategory
                """,
                batch=records[i : i + BATCH_SIZE],
            )

    print(f"[shareholder_node/company] Extracted {len(all_shareholders)} entries "
          f"from {docs_with_shp} company SHP doc(s).")
    print(f"[shareholder_node/company]   → {resolved_bank} resolved to :Bank, "
          f"{resolved_company} resolved to :Company, "
          f"{len(to_create)} new :Shareholder stub(s).")
    return all_shareholders
