"""
Task 1: Filter CRISIL Rating Reports by Bank
Extracts companies that have taken loans from specified banks
Now supports both MongoDB cloud and local JSON file
"""
import json
from typing import Dict, List
from pymongo import MongoClient
from config import DATA_PATHS, get_bank_config, match_bank_from_crisil_name, get_mongodb_cloud_uri, get_crisil_db_config


def extract_bank_loans(bank_symbol: str, use_cloud: bool = True) -> List[Dict]:
    """
    Filter CRISIL data to find companies with loans from the specified bank
    
    Args:
        bank_symbol: Bank symbol (e.g., 'HDFCBANK', 'SBIN', 'ICICIBANK')
        use_cloud: Whether to use MongoDB cloud (default) or local JSON file
        
    Returns:
        List of dictionaries containing company details and loan facilities
    """
    bank_config = get_bank_config(bank_symbol)
    if not bank_config:
        raise ValueError(f"Unknown bank symbol: {bank_symbol}")
    
    # Try to load from MongoDB cloud first if enabled
    if use_cloud:
        try:
            return extract_from_mongodb_cloud(bank_symbol, bank_config)
        except Exception as e:
            print(f"  ⚠ Cloud MongoDB unavailable ({e}), falling back to local JSON")
            use_cloud = False
    
    # Fallback to local JSON file
    if not use_cloud:
        return extract_from_json_file(bank_symbol, bank_config)


def extract_from_mongodb_cloud(bank_symbol: str, bank_config: Dict) -> List[Dict]:
    """
    Extract CRISIL data from MongoDB cloud
    
    Args:
        bank_symbol: Bank symbol
        bank_config: Bank configuration
        
    Returns:
        List of companies with loans from this bank
    """
    mongodb_uri = get_mongodb_cloud_uri()
    if not mongodb_uri:
        raise ValueError("MongoDB cloud URI not configured in .env file")
    
    # Get CRISIL database configuration
    db_name, collection_name = get_crisil_db_config()
    
    client = MongoClient(mongodb_uri, serverSelectionTimeoutMS=10000)
    db = client[db_name]
    collection = db[collection_name]
    
    companies_with_loans = []
    
    # Query companies with bankFacilities
    companies_cursor = collection.find({
        "bankFacilities": {"$exists": True, "$ne": []}
    })
    
    for company in companies_cursor:
        # Find facilities from our target bank
        matching_facilities = []
        for facility in company.get('bankFacilities', []):
            lender_name = facility.get('lenderName')
            
            # Check if this lender matches our bank
            matched_bank = match_bank_from_crisil_name(lender_name)
            if matched_bank == bank_symbol:
                matching_facilities.append({
                    "facilityType": facility.get('facility'),
                    "amount": facility.get('amount'),
                    "rating": facility.get('rating'),
                    "lenderName": lender_name
                })
        
        # If we found matching facilities, add this company
        if matching_facilities:
            company_info = {
                "companyName": company.get('companyName'),
                "companyCode": company.get('companyCode'),
                "industryName": company.get('industryName', ''),
                "companyIndustrialClassification": company.get('CompanyIndustrialClassification'),
                "nicCode": company.get('nic_code'),
                "ratingDate": company.get('ratingDate'),
                "facilities": matching_facilities,
                "totalExposure": sum(f['amount'] for f in matching_facilities if f['amount'])
            }
            companies_with_loans.append(company_info)
    
    client.close()
    return companies_with_loans


def extract_from_json_file(bank_symbol: str, bank_config: Dict) -> List[Dict]:
    """
    Extract CRISIL data from local JSON file (legacy support)
    
    Args:
        bank_symbol: Bank symbol
        bank_config: Bank configuration
        
    Returns:
        List of companies with loans from this bank
    """
    # Load CRISIL data
    try:
        with open(DATA_PATHS["crisil"], 'r', encoding='utf-8') as f:
            crisil_data = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"CRISIL data file not found at {DATA_PATHS['crisil']}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in CRISIL data file: {e}")
    
    # Filter companies with loans from this bank
    companies_with_loans = []
    
    for company in crisil_data:
        # Check if company has bankFacilities
        if not company.get('bankFacilities'):
            continue
        
        # Find facilities from our target bank
        matching_facilities = []
        for facility in company['bankFacilities']:
            lender_name = facility.get('lenderName')
            
            # Check if this lender matches our bank
            matched_bank = match_bank_from_crisil_name(lender_name)
            if matched_bank == bank_symbol:
                matching_facilities.append({
                    "facilityType": facility.get('facility'),
                    "amount": facility.get('amount'),
                    "rating": facility.get('rating'),
                    "lenderName": lender_name
                })
        
        # If we found matching facilities, add this company
        if matching_facilities:
            company_info = {
                "companyName": company.get('companyName'),
                "companyCode": company.get('companyCode'),
                "industryName": company.get('industryName', ''),
                "companyIndustrialClassification": company.get('CompanyIndustrialClassification'),
                "nicCode": company.get('nic_code'),
                "ratingDate": company.get('ratingDate'),
                "facilities": matching_facilities,
                "totalExposure": sum(f['amount'] for f in matching_facilities if f['amount'])
            }
            companies_with_loans.append(company_info)
    
    return companies_with_loans


def get_loan_summary(bank_symbol: str) -> Dict:
    """
    Get summary statistics of loans for a bank
    
    Args:
        bank_symbol: Bank symbol
        
    Returns:
        Dictionary with summary statistics
    """
    companies = extract_bank_loans(bank_symbol)
    
    total_companies = len(companies)
    total_facilities = sum(len(c['facilities']) for c in companies)
    total_exposure = sum(c['totalExposure'] for c in companies if c['totalExposure'])
    
    # Get facility type breakdown
    facility_types = {}
    for company in companies:
        for facility in company['facilities']:
            ftype = facility['facilityType']
            if ftype not in facility_types:
                facility_types[ftype] = {"count": 0, "totalAmount": 0}
            facility_types[ftype]["count"] += 1
            if facility['amount']:
                facility_types[ftype]["totalAmount"] += facility['amount']
    
    return {
        "totalCompanies": total_companies,
        "totalFacilities": total_facilities,
        "totalExposure": total_exposure,
        "facilityTypeBreakdown": facility_types
    }


if __name__ == "__main__":
    # Test with HDFC Bank
    print("Testing CRISIL Filter with HDFC Bank...")
    hdfc_loans = extract_bank_loans("HDFCBANK")
    print(f"Found {len(hdfc_loans)} companies with HDFC Bank loans")
    
    if hdfc_loans:
        print("\nFirst 3 companies:")
        for company in hdfc_loans[:3]:
            print(f"  - {company['companyName']} ({company['companyCode']})")
            print(f"    Total Exposure: {company['totalExposure']}")
            print(f"    Facilities: {len(company['facilities'])}")
    
    print("\n" + "="*50)
    summary = get_loan_summary("HDFCBANK")
    print(f"Summary for HDFC Bank:")
    print(f"  Total Companies: {summary['totalCompanies']}")
    print(f"  Total Facilities: {summary['totalFacilities']}")
    print(f"  Total Exposure: {summary['totalExposure']} Cr")
