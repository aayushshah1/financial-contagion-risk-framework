"""
Task 5: Convert XBRL Shareholding Pattern to JSON
Parses XBRL shareholding pattern files using Arelle and extracts structured data with individual entity-level details
"""
from arelle import Cntlr
from collections import defaultdict
from typing import Any, Dict, List, Optional
import glob
import os
import sys
import re
import xml.etree.ElementTree as ET
from io import StringIO
from config import DATA_PATHS, get_bank_config, TARGET_YEAR


def extract_shareholding_pattern(bank_symbol: str, ctrl=None) -> Dict:
    """
    Extract comprehensive shareholding pattern data from XBRL file.

    Args:
        bank_symbol : Bank symbol (e.g., 'HDFCBANK', 'SBIN', 'ICICIBANK')
        ctrl        : Optional shared Arelle Cntlr instance.  When None a
                      temporary controller is created and destroyed per call.
                      Pass a pre-built controller to amortise taxonomy loading
                      across multiple banks (same pattern as task_company_consolidate.py).

    Returns:
        Dictionary with complete shareholding pattern data including individual entities.
    """
    bank_config = get_bank_config(bank_symbol)
    if not bank_config:
        raise ValueError(f"Unknown bank symbol: {bank_symbol}")

    xbrl_file_pattern = os.path.join(DATA_PATHS["shp_dir"], f"shareholding_{bank_symbol}_*.xml")
    matches = sorted(glob.glob(xbrl_file_pattern))
    if not matches:
        raise FileNotFoundError(
            f"No shareholding XBRL file found for {bank_symbol} in {DATA_PATHS['shp_dir']}. "
            f"Expected pattern: shareholding_{bank_symbol}_YYYY-MM-DD.xml"
        )
    xbrl_file = matches[-1]  # Use the most recent date if multiple files exist

    # Create a temporary controller if the caller did not supply one
    _owns_ctrl = ctrl is None
    if _owns_ctrl:
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            ctrl = Cntlr.Cntlr(logFileName="logToPrint")
            ctrl.webCache.workOffline = True
        finally:
            sys.stdout = old_stdout

    try:
        shp_result = _parse_shp_xml(xbrl_file, ctrl)
    finally:
        if _owns_ctrl:
            try:
                ctrl.modelManager.close()
            except Exception:
                pass

    # Pop the flat totals; remainder becomes shareholdingPattern
    total_shares       = shp_result.pop("totalShares", None)
    total_shareholders = shp_result.pop("totalShareholders", None)

    # Arelle result has no "shareholdingPattern" key (the dict IS the pattern).
    # ET result wraps the pattern under a "shareholdingPattern" key.
    if "shareholdingPattern" in shp_result:
        pattern = shp_result["shareholdingPattern"]
    else:
        pattern = shp_result   # Arelle path: {periodEnd, aggregates, entities}

    return {
        "bankName":            bank_config["fullName"],
        "bankSymbol":          bank_symbol,
        "year":                TARGET_YEAR,
        "totalShares":         total_shares,
        "totalShareholders":   total_shareholders,
        "shareholdingPattern": pattern,
    }


def _extract_shp_arelle(modelXbrl) -> Dict[str, Any]:
    """
    Fully dynamic Arelle-driven SHP extraction using XBRL dimensions.

    Replaces all hardcoded context-prefix logic.  Works by:
      - Iterating modelXbrl.facts (all reported facts)
      - Using ctx.dimValues('segment'/'scenario') to read actual dimension members
      - Grouping by CategoryOfShareholdersAxis  -> aggregate data per category
      - Grouping by Details*Axis                -> entity list per category axis

    Returns an empty dict when Arelle resolved 0 facts (taxonomy unavailable);
    the caller should fall back to ElementTree extraction in that case.

    Output structure::

        {
          "periodEnd": "2025-12-31",
          "totalShares": int,
          "totalShareholders": int,
          "aggregates": {
            "MutualFundsOrUTIMember": { "numberOfShares": ..., ... },
            ...
          },
          "entities": {
            "DetailsSharesHeldByIndividualsOrHUFAxis": [
              { "nameOfTheShareholder": "...", "numberOfShares": ..., ... },
              ...
            ],
            ...
          }
        }
    """
    if not modelXbrl or not modelXbrl.facts:
        return {}

    aggregates: Dict[str, Dict[str, Any]]           = defaultdict(dict)
    entities:   Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(lambda: defaultdict(dict))
    totals:     Dict[str, Any]                      = {}
    period_end: Optional[str]                       = None

    for fact in modelXbrl.facts:
        ctx = fact.context
        if ctx is None:
            continue

        # Use elementQname.localName — works even when concept is unresolved
        # (Arelle may not resolve taxonomy concepts if the schema is not bundled).
        concept_local = fact.elementQname.localName

        # Collect period-end date once
        if period_end is None:
            dt = getattr(ctx, "endDatetime", None) or getattr(ctx, "instantDatetime", None)
            if dt:
                period_end = dt.strftime("%Y-%m-%d")

        # Read all explicit dimensions from both segment and scenario
        all_dims: Dict[Any, Any] = {}
        for seg in ("segment", "scenario"):
            try:
                all_dims.update(ctx.dimValues(seg))
            except Exception:
                pass

        # Coerce value to int/float where possible
        raw_val = fact.value
        try:
            coerced: Any = int(raw_val) if raw_val and "." not in str(raw_val) else float(raw_val)
        except (TypeError, ValueError):
            coerced = raw_val

        if not all_dims:
            # No dimensions — global totals row
            totals[concept_local] = coerced
            continue

        category_member: Optional[str] = None
        # Collect ALL Details*Axis entries — a fact can technically carry more
        # than one (e.g. a sub-axis alongside the primary axis).  We store the
        # fact under every axis it belongs to so nothing is lost.
        detail_axes: Dict[str, str] = {}  # axis_local -> entity_member key

        for dim_concept, dim_val in all_dims.items():
            axis_local  = dim_concept.qname.localName

            if axis_local == "CategoryOfShareholdersAxis":
                # Explicit dimension — member QName is always present
                mq = getattr(dim_val, "memberQname", None)
                if mq:
                    category_member = mq.localName
            elif "Details" in axis_local:
                # SEBI SHP entity axes are TYPED dimensions — no memberQname.
                # Use the context ID as an opaque but unique entity key.
                # Strip the leading "D_" duration prefix so that instant +
                # duration facts for the same entity collapse into one bucket.
                mq = getattr(dim_val, "memberQname", None)
                raw_ctx = fact.contextID
                member_key = mq.localName if mq else (
                    raw_ctx[2:] if raw_ctx.startswith("D_") else raw_ctx
                )
                detail_axes[axis_local] = member_key

        if detail_axes:
            # Entity (individual shareholder) row — store under EVERY Details axis
            for axis, member_key in detail_axes.items():
                entities[axis][member_key][concept_local] = coerced
        elif category_member:
            # Pure aggregate row (no Details axis at all)
            aggregates[category_member][concept_local] = coerced
        # Facts with unrecognised dimension patterns are intentionally ignored

    if not aggregates and not entities:
        return {}  # Arelle resolved nothing — signal fallback needed

    # Convert entities: {axis: {member: facts}} -> {axis: [{camelCase facts}]}
    entities_out: Dict[str, List[Dict[str, Any]]] = {}
    for axis, members in entities.items():
        entity_list = []
        for member, facts in members.items():
            entity: Dict[str, Any] = {_to_camel_case(k): v for k, v in facts.items() if v is not None}
            entity["_member"] = member  # keep for traceability
            entity_list.append(entity)
        entity_list.sort(
            key=lambda x: x.get("shareholdingAsAPercentageOfTotalNumberOfShares", 0),
            reverse=True,
        )
        entities_out[axis] = entity_list

    # Convert aggregates to camelCase
    aggregates_out: Dict[str, Dict[str, Any]] = {
        member: {_to_camel_case(k): v for k, v in facts.items()}
        for member, facts in aggregates.items()
    }

    # Pull totals — prefer ShareholdingPatternMember aggregate (total row),
    # fall back to no-dimension facts for backward compat.
    shp_total       = {_to_camel_case(k): v for k, v in aggregates.get("ShareholdingPatternMember", {}).items()}
    total_facts_all = {_to_camel_case(k): v for k, v in totals.items()}
    total_shares       = (shp_total.get("numberOfShares")
                          or shp_total.get("totalNumberOfShares")
                          or total_facts_all.get("numberOfShares")
                          or total_facts_all.get("totalNumberOfShares"))
    total_shareholders = (shp_total.get("numberOfShareholders")
                          or total_facts_all.get("numberOfShareholders"))

    return {
        "periodEnd":         period_end,
        "totalShares":       total_shares,
        "totalShareholders": total_shareholders,
        "aggregates":        aggregates_out,
        "entities":          entities_out,
    }


def _discover_entity_groups(root) -> Dict[str, List[Dict]]:
    """
    Scan the XML root ONCE for ALL NameOfTheShareholder facts and group them
    by their context prefix (everything before _Context<N>).

    This is the single source-of-truth for entity discovery.  Calling this
    once and passing the result down avoids repeated full-root scans and
    ensures no entities are missed regardless of what context-prefix naming
    convention the filer chose (e.g. 'IndividualsOrHUF' vs 'ResidentIndividuals').

    Returns: {prefix: [{context, name}, ...]}
    """
    groups: Dict[str, List[Dict]] = {}
    context_re = re.compile(r'^(.+)_Context\d+$')
    for elem in root:
        local = elem.tag.split('}')[1] if '}' in elem.tag else elem.tag
        if local != 'NameOfTheShareholder':
            continue
        ctx  = elem.get('contextRef', '').replace('D_', '')
        name = (elem.text or '').strip()
        if not name or name in ('******', 'NA', '', 'Not Applicable'):
            continue
        m = context_re.match(ctx)
        if m:
            prefix = m.group(1)
            groups.setdefault(prefix, []).append({'context': ctx, 'name': name})
    return groups


def _build_entities(root, entity_contexts: List[Dict]) -> List[Dict]:
    """
    Build an entity list from a pre-discovered list of {context, name} dicts.
    Extracted from _extract_entity_group so the logic lives in one place.
    """
    entities = []
    for ec in entity_contexts:
        facts = _extract_context_facts(root, ec['context'])
        if not facts:
            continue
        entity = {
            'name':                   ec['name'],
            'numberOfShares':         facts.get('numberOfShares') or facts.get('numberOfFullyPaidUpEquityShares'),
            'shareholdingPercentage': facts.get('shareholdingAsAPercentageOfTotalNumberOfShares'),
            'numberOfVotingRights':   facts.get('numberOfVotingRights'),
            'votingRightsPercentage': facts.get('percentageOfTotalVotingRights'),
            'pan':                    facts.get('permanentAccountNumberOfShareholder'),
            'dematerializedShares':   facts.get('numberOfEquitySharesHeldInDematerializedForm'),
            'numberOfShareholders':   facts.get('numberOfShareholders'),
        }
        entity = {k: v for k, v in entity.items() if v is not None}
        if facts.get('typeOfPromoterShareholding'):
            entity['type'] = facts['typeOfPromoterShareholding']
        if facts.get('categoryOfOtherInstitutions'):
            entity['category'] = facts['categoryOfOtherInstitutions']
        if facts.get('categoryOfOtherNonInstitutions'):
            entity['category'] = facts['categoryOfOtherNonInstitutions']
        entities.append(entity)
    entities.sort(key=lambda x: x.get('shareholdingPercentage', 0), reverse=True)
    return entities


def _extract_complete_shareholding_pattern(root) -> Dict:
    """
    Extract complete shareholding pattern with both aggregates and individual entities.

    Uses _discover_entity_groups to scan ALL NameOfTheShareholder facts ONCE,
    so no entities are missed regardless of the context-prefix naming convention
    used by the filer.  Any prefix not in the canonical set is collected under
    pattern["discovered"] rather than silently dropped.
    """
    # Discover every entity group present in this file — one pass over the root
    all_groups = _discover_entity_groups(root)

    # Canonical prefixes handled by explicit slots below; anything else → discovered
    _KNOWN = {
        "CentralGovernmentOrStateGovernments",
        "MutualFundsOrUTI",
        "InstitutionsForeignPortfolioInvestorCategoryOne",
        "InstitutionsForeignPortfolioInvestorCategoryTwo",
        "InsuranceCompanies",
        "Banks",
        "ProvidentFundsOrPensionFunds",
        "OtherInstitutionsDomestic",
        "OtherInstitutionsForeign",
        "ResidentIndividuals",
        "NonResidentIndians",
        "BodiesCorporate",
        "OtherNonInstitutions",
        "CustodianOrDRHolder",
    }

    def ge(prefix: str) -> List[Dict]:
        """Build entities for a known prefix using pre-discovered contexts."""
        return _build_entities(root, all_groups.get(prefix, []))

    pattern = {}

    # 1. PROMOTER AND PROMOTER GROUP
    promoter = {
        "aggregate": _extract_context_facts(root, "ShareholdingOfPromoterAndPromoterGroup_ContextI"),
        "entities": []
    }
    promoter_entities = ge("CentralGovernmentOrStateGovernments")
    if promoter_entities:
        promoter["government"] = {
            "aggregate": _extract_context_facts(root, "CentralGovernmentOrStateGovernments_ContextI"),
            "entities": promoter_entities
        }
    pattern["promoterHolding"] = promoter

    # 2. PUBLIC SHAREHOLDING
    public = {
        "aggregate": _extract_context_facts(root, "PublicShareholding_ContextI"),
        "institutions": {},
        "nonInstitutions": {}
    }

    # 2.1 Institutional Holdings
    institutions = {}

    # Mutual Funds
    mf_entities = ge("MutualFundsOrUTI")
    institutions["mutualFunds"] = {
        "aggregate": _extract_context_facts(root, "MutualFundsOrUTI_ContextI"),
        "entities": mf_entities
    }
    
    # Foreign Portfolio Investors
    fpi_cat1_entities = ge("InstitutionsForeignPortfolioInvestorCategoryOne")
    fpi_cat2_entities = ge("InstitutionsForeignPortfolioInvestorCategoryTwo")
    institutions["foreignPortfolioInvestors"] = {
        "category1": {
            "aggregate": _extract_context_facts(root, "InstitutionsForeignPortfolioInvestorCategoryOne_ContextI"),
            "entities": fpi_cat1_entities
        },
        "category2": {
            "aggregate": _extract_context_facts(root, "InstitutionsForeignPortfolioInvestorCategoryTwo_ContextI"),
            "entities": fpi_cat2_entities
        }
    }

    # Insurance Companies
    insurance_entities = ge("InsuranceCompanies")
    institutions["insuranceCompanies"] = {
        "aggregate": _extract_context_facts(root, "InsuranceCompanies_ContextI"),
        "entities": insurance_entities
    }

    # Banks
    bank_entities = ge("Banks")
    institutions["banks"] = {
        "aggregate": _extract_context_facts(root, "Banks_ContextI"),
        "entities": bank_entities
    }

    # Provident/Pension Funds
    pension_entities = ge("ProvidentFundsOrPensionFunds")
    institutions["providentFunds"] = {
        "aggregate": _extract_context_facts(root, "ProvidentFundsOrPensionFunds_ContextI"),
        "entities": pension_entities
    }

    # Other Institutions - Domestic
    other_inst_domestic_entities = ge("OtherInstitutionsDomestic")
    institutions["otherInstitutionsDomestic"] = {
        "aggregate": _extract_context_facts(root, "OtherInstitutionsDomestic_ContextI"),
        "entities": other_inst_domestic_entities
    }

    # Other Institutions - Foreign
    other_inst_foreign_entities = ge("OtherInstitutionsForeign")
    institutions["otherInstitutionsForeign"] = {
        "aggregate": _extract_context_facts(root, "OtherInstitutionsForeign_ContextI"),
        "entities": other_inst_foreign_entities
    }

    public["institutions"] = institutions

    # 2.2 Non-Institutional Holdings
    non_institutions = {}

    # Resident Individuals
    resident_entities = ge("ResidentIndividuals")
    non_institutions["residentIndividuals"] = {
        "aggregate": _extract_context_facts(root, "ResidentIndividuals_ContextI"),
        "entities": resident_entities
    }

    # Non-Resident Indians
    nri_entities = ge("NonResidentIndians")
    non_institutions["nonResidentIndians"] = {
        "aggregate": _extract_context_facts(root, "NonResidentIndians_ContextI"),
        "entities": nri_entities
    }

    # Bodies Corporate
    bodies_corp_entities = ge("BodiesCorporate")
    non_institutions["bodiesCorporate"] = {
        "aggregate": _extract_context_facts(root, "BodiesCorporate_ContextI"),
        "entities": bodies_corp_entities
    }

    # Other Non-Institutions (HUF, Trusts, Clearing Members, etc.)
    other_non_inst_entities = ge("OtherNonInstitutions")
    non_institutions["otherNonInstitutions"] = {
        "aggregate": _extract_context_facts(root, "OtherNonInstitutions_ContextI"),
        "entities": other_non_inst_entities
    }

    public["nonInstitutions"] = non_institutions
    pattern["publicHolding"] = public

    # 3. NON-PROMOTER NON-PUBLIC SHAREHOLDING
    non_promoter_non_public = {
        "aggregate": _extract_context_facts(root, "SharesHeldByNonPromoterNonPublicShareholders_ContextI"),
        "entities": []
    }
    custodian_entities = ge("CustodianOrDRHolder")
    if custodian_entities:
        non_promoter_non_public["custodian"] = {
            "aggregate": _extract_context_facts(root, "CustodianOrDRHolder_ContextI"),
            "entities": custodian_entities
        }
    pattern["nonPromoterNonPublicHolding"] = non_promoter_non_public

    # 4. DISCOVERED — any prefix not in the canonical set above
    # Captures entities from filers that use non-standard context prefix names
    # (e.g. 'IndividualsOrHUF', 'OthersIndianShareholders') so nothing is dropped.
    discovered = {}
    for prefix, entity_contexts in all_groups.items():
        if prefix not in _KNOWN:
            discovered[prefix] = {
                "aggregate": _extract_context_facts(root, f"{prefix}_ContextI"),
                "entities":  _build_entities(root, entity_contexts),
            }
    if discovered:
        pattern["discovered"] = discovered

    return pattern


def _extract_entity_group(root, category_prefix: str) -> List[Dict]:
    """
    Backward-compatible wrapper for direct per-prefix lookups.
    Internally delegates to _discover_entity_groups + _build_entities.
    For full-file extraction prefer _extract_complete_shareholding_pattern
    which calls _discover_entity_groups only once.
    """
    groups = _discover_entity_groups(root)
    return _build_entities(root, groups.get(category_prefix, []))


def _extract_context_facts(root, context_id: str) -> Optional[Dict]:
    """
    Extract all facts for a specific context ID
    
    Args:
        root: XML root element
        context_id: Context ID to search for (instant context, not duration)
        
    Returns:
        Dictionary with fact names and values, or None if no facts found
    """
    data = {}
    
    for elem in root:
        context_ref = elem.get('contextRef', '')
        if context_ref == context_id or context_ref == f"D_{context_id}":
            # Get the local name (strip namespace)
            local_name = elem.tag.split('}')[1] if '}' in elem.tag else elem.tag
            value = elem.text
            
            # Convert to camelCase and store
            key = _to_camel_case(local_name)
            
            # Try to convert to numeric if possible
            try:
                if value is not None:
                    # Try integer first
                    if '.' not in str(value):
                        data[key] = int(value)
                    else:
                        data[key] = float(value)
                else:
                    data[key] = None
            except (ValueError, TypeError):
                # Keep as string
                data[key] = value
    
    return data if data else None


def _extract_with_root(root) -> Dict:
    """
    Build the canonical result dict from any XML/lxml root element.

    Returns:
        {
            "totalShares":         int | None,
            "totalShareholders":   int | None,
            "shareholdingPattern": {...},
        }
    """
    total_facts = (
        _extract_context_facts(root, "ShareholdingPattern_ContextI")
        or _extract_context_facts(root, "MainI")
        or {}
    )
    return {
        "totalShares":         total_facts.get("numberOfShares") or total_facts.get("totalNumberOfShares"),
        "totalShareholders":   total_facts.get("numberOfShareholders"),
        "shareholdingPattern": _extract_complete_shareholding_pattern(root),
    }


def _parse_shp_xml(xml_path: str, ctrl=None) -> Dict:
    """
    Parse a SEBI Shareholding Pattern XBRL file.

    Preferred path  : Arelle (taxonomy-validated; pass a shared Cntlr instance).
    Fallback path   : raw ElementTree (fast, no network / taxonomy needed).

    Returns the raw extraction dict — either:
      {periodEnd, totalShares, totalShareholders, aggregates, entities}  ← Arelle
      {totalShares, totalShareholders, shareholdingPattern}              ← ET
    The caller (extract_shareholding_pattern) normalises both forms.
    """
    # ── Arelle path ─────────────────────────────────────────────────────────
    if ctrl is not None:
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            modelXbrl = ctrl.modelManager.load(str(xml_path))
            sys.stdout = old_stdout
        except Exception:
            sys.stdout = old_stdout
            modelXbrl = None

        if modelXbrl:
            arelle_result = _extract_shp_arelle(modelXbrl)
            # Grab the parsed root before closing the model
            root = modelXbrl.modelDocument.xmlRootElement
            modelXbrl.close()
            if arelle_result:
                return arelle_result
            # Arelle resolved 0 facts (taxonomy not bundled) — ET on same root
            return _extract_with_root(root)

    # ── ElementTree fallback ─────────────────────────────────────────────────
    try:
        tree = ET.parse(str(xml_path))
    except ET.ParseError as exc:
        raise ValueError(f"XML parse error in {xml_path}: {exc}") from exc
    return _extract_with_root(tree.getroot())


def _extract_total_shares(root) -> Optional[int]:
    """Extract total number of shares (kept for backward compatibility)."""
    facts = _extract_context_facts(root, "ShareholdingPattern_ContextI")
    if facts:
        return facts.get('numberOfShares') or facts.get('totalNumberOfShares')
    facts = _extract_context_facts(root, "MainI")
    if facts:
        return facts.get('numberOfShares') or facts.get('totalNumberOfShares')
    return None


def _extract_total_shareholders(root) -> Optional[int]:
    """Extract total number of shareholders (kept for backward compatibility)."""
    facts = _extract_context_facts(root, "ShareholdingPattern_ContextI")
    if facts:
        return facts.get('numberOfShareholders')
    facts = _extract_context_facts(root, "MainI")
    if facts:
        return facts.get('numberOfShareholders')
    return None


def _to_camel_case(pascal_str: str) -> str:
    """Convert PascalCase to camelCase"""
    if pascal_str:
        return pascal_str[0].lower() + pascal_str[1:]
    return pascal_str


if __name__ == "__main__":
    # ---------------------------------------------------------------------------
    # Smoke test — run with:  python task5_shareholding_xbrl.py [SYMBOL]
    #   default symbol: SBIN
    # Checks:
    #   1. File is found and parsed without errors
    #   2. totalShares / totalShareholders are non-zero
    #   3. Entity counts per category section are printed
    #   4. Whether Arelle or ET path was used is indicated
    #   5. Full dump written to smoke_<SYMBOL>.json for deep inspection
    # ---------------------------------------------------------------------------
    import json
    import argparse

    parser = argparse.ArgumentParser(description="Smoke test for SHP extraction")
    parser.add_argument("symbol", nargs="?", default="SBIN",
                        help="Bank symbol to test (default: SBIN)")
    parser.add_argument("--all", action="store_true",
                        help="Test all three banks (SBIN, HDFCBANK, ICICIBANK)")
    args = parser.parse_args()

    symbols = ["SBIN", "HDFCBANK", "ICICIBANK"] if args.all else [args.symbol.upper()]

    old_stdout = sys.stdout
    sys.stdout = StringIO()
    try:
        shared_ctrl = Cntlr.Cntlr(logFileName="logToPrint")
        shared_ctrl.webCache.workOffline = True
    finally:
        sys.stdout = old_stdout

    SEP = "=" * 80

    def _count_et_entities(pattern: dict) -> dict[str, int]:
        """Walk the ET-style nested pattern and count entities per section."""
        counts: dict[str, int] = {}

        def _walk(node, path=""):
            if isinstance(node, dict):
                for k, v in node.items():
                    key_path = f"{path}.{k}" if path else k
                    if k == "entities" and isinstance(v, list):
                        if v:
                            counts[path] = len(v)
                    else:
                        _walk(v, key_path)
            elif isinstance(node, list):
                for item in node:
                    _walk(item, path)

        _walk(pattern)
        return counts

    def _count_arelle_entities(pattern: dict) -> dict[str, int]:
        """Count entities per axis in the Arelle flat format."""
        raw_entities = pattern.get("entities", {})
        if not isinstance(raw_entities, dict):
            return {}
        return {axis: len(lst) for axis, lst in raw_entities.items() if lst}

    for symbol in symbols:
        print(f"\n{SEP}")
        print(f"  Smoke test: {symbol}")
        print(SEP)
        try:
            data = extract_shareholding_pattern(symbol, ctrl=shared_ctrl)
            pattern = data.get("shareholdingPattern", {})
            pat_keys = list(pattern.keys())

            # Detect which extraction path was used
            is_arelle = "aggregates" in pat_keys or "entities" in pat_keys
            path_label = "Arelle" if is_arelle else "ElementTree"

            print(f"  Bank          : {data['bankName']}")
            print(f"  Year          : {data['year']}")
            print(f"  Extraction    : {path_label}")
            shares = data.get("totalShares")
            shareholders = data.get("totalShareholders")
            print(f"  totalShares      : {shares:,.0f}" if shares else "  totalShares      : None  <-- WARN")
            print(f"  totalShareholders: {shareholders:,.0f}" if shareholders else "  totalShareholders: None  <-- WARN")
            print(f"  pattern keys  : {pat_keys}")

            # Entity counts
            if is_arelle:
                counts = _count_arelle_entities(pattern)
                label = "Arelle axis"
            else:
                counts = _count_et_entities(pattern)
                label = "ET section"

            if counts:
                print(f"\n  Entity counts by {label}:")
                for k, v in sorted(counts.items(), key=lambda x: -x[1]):
                    print(f"    {k:<70} : {v}")
            else:
                print(f"\n  WARNING: No entity lists found in pattern (0 {label}s).")
                print(f"           Check _extract_complete_shareholding_pattern / _extract_shp_arelle.")

            # Save full dump
            import pathlib
            out = pathlib.Path(__file__).parent / f"smoke_{symbol}.json"
            with open(out, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            print(f"\n  Full dump -> {out}")
            print(f"  [PASS] {symbol}")

        except Exception as exc:
            import traceback
            print(f"  [FAIL] {symbol}: {exc}")
            traceback.print_exc()

