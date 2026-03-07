"""
Task 1: Filter Companies by Bank Lender
Source: MongoDB cloud — financial_kg.companies (env: db_cluster_link)

Extracts companies that hold bank facilities from one of the target banks
(SBI, HDFC Bank, ICICI Bank).  The company documents are fully consolidated
records as described in sample_company.json:

    crisilName      – primary CRISIL display name
    mcaName         – MCA registered name (may differ from crisilName)
    companyCode     – unique CRISIL company identifier
    cin             – Company Identification Number (MCA)
    nseSymbol       – NSE ticker (for listed companies)
    listingStatus   – 'Listed' / 'Unlisted'
    industryName    – CRISIL industry classification
    industryCode    – CRISIL industry code
    nicCode         – NIC sector code (from MCA)
    ratingDate      – date of most recent CRISIL rating
    bankFacilities  – list of {facility, amount, lenderName, rating}
"""
from typing import Dict, List
from pymongo import MongoClient
from config import get_bank_config, match_bank_from_crisil_name, get_mongodb_cloud_uri, get_crisil_db_config


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------

def extract_bank_loans(bank_symbol: str) -> List[Dict]:
    """
    Query financial_kg.companies and return every company that holds at least
    one bank facility from the specified bank.

    Args:
        bank_symbol: One of 'HDFCBANK', 'SBIN', 'ICICIBANK'

    Returns:
        List of dicts with keys:
            companyName, companyCode, cin, nseSymbol, listingStatus,
            industryName, industryCode, nicCode, ratingDate,
            facilities (list), totalExposure (float, Cr)
    """
    bank_config = get_bank_config(bank_symbol)
    if not bank_config:
        raise ValueError(f"Unknown bank symbol: {bank_symbol}")

    mongodb_uri = get_mongodb_cloud_uri()
    if not mongodb_uri:
        raise EnvironmentError(
            "MongoDB URI not set. Add 'db_cluster_link' to your .env file."
        )

    db_name, collection_name = get_crisil_db_config()

    client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=10000)
    try:
        collection = client[db_name][collection_name]

        # Pull only companies that have at least one bankFacility entry
        cursor = collection.find(
            {"bankFacilities": {"$exists": True, "$not": {"$size": 0}}},
            {
                "crisilName": 1, "companyCode": 1,
                "cin": 1, "dummyCIN": 1,
                "nseSymbol": 1,
                "bankFacilities": 1,
            }
        )

        results: List[Dict] = []
        for doc in cursor:
            matching_facilities = _match_facilities(doc.get("bankFacilities", []), bank_symbol)
            if not matching_facilities:
                continue

            cin = doc.get("cin") or ""
            dummy_cin = bool(doc.get("dummyCIN", False))

            results.append({
                "companyName": doc.get("crisilName") or doc.get("companyCode"),
                "companyCode": doc.get("companyCode"),
                "cin":      cin,
                "dummyCIN": dummy_cin,
                "hasCIN":   bool(cin) and not dummy_cin,
                "nseSymbol": doc.get("nseSymbol"),
                "facilities": matching_facilities,
                "totalExposure": sum(
                    f["amount"] for f in matching_facilities if f["amount"] is not None
                ),
            })

    finally:
        client.close()

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _match_facilities(bank_facilities: List[Dict], bank_symbol: str) -> List[Dict]:
    """
    Return only those bankFacility entries whose lenderName resolves to
    ``bank_symbol``.
    """
    matched = []
    for facility in bank_facilities:
        lender_name = facility.get("lenderName")
        if match_bank_from_crisil_name(lender_name) == bank_symbol:
            matched.append({
                "facilityType": facility.get("facility"),
                "amount": facility.get("amount"),
                "rating": facility.get("rating"),
                "lenderName": lender_name,
            })
    return matched


# ---------------------------------------------------------------------------
# Summary helper
# ---------------------------------------------------------------------------

def get_loan_summary(bank_symbol: str) -> Dict:
    """
    Aggregate statistics for a bank's lending exposure across all companies.

    Returns:
        Dict with totalCompanies, totalFacilities, totalExposure (Cr),
        and facilityTypeBreakdown.
    """
    companies = extract_bank_loans(bank_symbol)

    facility_types: Dict[str, Dict] = {}
    for company in companies:
        for f in company["facilities"]:
            ftype = f["facilityType"] or "Unknown"
            entry = facility_types.setdefault(ftype, {"count": 0, "totalAmount": 0.0})
            entry["count"] += 1
            if f["amount"] is not None:
                entry["totalAmount"] += f["amount"]

    return {
        "totalCompanies": len(companies),
        "totalFacilities": sum(len(c["facilities"]) for c in companies),
        "totalExposure": sum(c["totalExposure"] for c in companies),
        "facilityTypeBreakdown": facility_types,
    }


# ---------------------------------------------------------------------------
# Quick smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    for symbol in ("HDFCBANK", "SBIN", "ICICIBANK"):
        print(f"\n{'='*55}")
        print(f"Bank: {symbol}")
        loans = extract_bank_loans(symbol)
        print(f"  Companies with facilities : {len(loans)}")
        if loans:
            with_cin    = sum(1 for c in loans if c["hasCIN"])
            dummy_cin   = sum(1 for c in loans if c["dummyCIN"])
            no_cin      = sum(1 for c in loans if not c["cin"])
            print(f"  CIN coverage : {with_cin} real | {dummy_cin} dummy | {no_cin} missing")
            print("  Sample (first 3):")
            for c in loans[:3]:
                cin_tag = c["cin"] if c["hasCIN"] else (f"[dummy] {c['cin']}" if c["dummyCIN"] else "[no CIN]")
                nse_tag = f"  NSE: {c['nseSymbol']}" if c.get("nseSymbol") else ""
                print(f"    - {c['companyName']} ({c['companyCode']})  CIN: {cin_tag}{nse_tag}")
                print(f"      Exposure: {c['totalExposure']:.2f} Cr  Facilities: {len(c['facilities'])}")
        summary = get_loan_summary(symbol)
        print(f"  Total exposure            : {summary['totalExposure']:.2f} Cr")
