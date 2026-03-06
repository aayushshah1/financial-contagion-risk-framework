"""
Task 8: NIC Sector Mapping and Aggregation
Maps companies by NIC code to major sectors and generates aggregate statistics
Uses data from Task 1 (CRISIL filter) instead of querying MongoDB separately
"""
from typing import Dict, List

# NIC Sector Mapping (First 3 digits of NIC code)
NIC_SECTOR_MAPPING = [
    {
        "section_letter": "A",
        "sector_name": "Agriculture, forestry and fishing",
        "group_range": {"start": "011", "end": "033"}
    },
    {
        "section_letter": "B",
        "sector_name": "Mining and quarrying",
        "group_range": {"start": "051", "end": "099"}
    },
    {
        "section_letter": "C",
        "sector_name": "Manufacturing",
        "group_range": {"start": "101", "end": "332"}
    },
    {
        "section_letter": "D",
        "sector_name": "Electricity, gas, steam and air conditioning supply",
        "group_range": {"start": "351", "end": "354"}
    },
    {
        "section_letter": "E",
        "sector_name": "Water supply; sewerage, waste management and remediation activities",
        "group_range": {"start": "360", "end": "390"}
    },
    {
        "section_letter": "F",
        "sector_name": "Construction",
        "group_range": {"start": "410", "end": "439"}
    },
    {
        "section_letter": "G",
        "sector_name": "Wholesale and retail trade",
        "group_range": {"start": "461", "end": "479"}
    },
    {
        "section_letter": "H",
        "sector_name": "Transportation and storage",
        "group_range": {"start": "491", "end": "533"}
    },
    {
        "section_letter": "I",
        "sector_name": "Accommodation and food service activities",
        "group_range": {"start": "551", "end": "564"}
    },
    {
        "section_letter": "J",
        "sector_name": "Publishing, broadcasting, and content distribution activities",
        "group_range": {"start": "581", "end": "603"}
    },
    {
        "section_letter": "K",
        "sector_name": "Telecommunications, computer programming, consultancy, computing infrastructure, and other information service activities",
        "group_range": {"start": "611", "end": "639"}
    },
    {
        "section_letter": "L",
        "sector_name": "Financial and insurance activities",
        "group_range": {"start": "641", "end": "663"}
    },
    {
        "section_letter": "M",
        "sector_name": "Real estate activities",
        "group_range": {"start": "681", "end": "682"}
    },
    {
        "section_letter": "N",
        "sector_name": "Professional, scientific and technical activities",
        "group_range": {"start": "691", "end": "750"}
    },
    {
        "section_letter": "O",
        "sector_name": "Administrative and support service activities",
        "group_range": {"start": "771", "end": "829"}
    },
    {
        "section_letter": "P",
        "sector_name": "Public administration and defence; compulsory social security",
        "group_range": {"start": "841", "end": "843"}
    },
    {
        "section_letter": "Q",
        "sector_name": "Education",
        "group_range": {"start": "851", "end": "856"}
    },
    {
        "section_letter": "R",
        "sector_name": "Human health and social work activities",
        "group_range": {"start": "861", "end": "889"}
    },
    {
        "section_letter": "S",
        "sector_name": "Arts, sports and recreation",
        "group_range": {"start": "901", "end": "932"}
    },
    {
        "section_letter": "T",
        "sector_name": "Other service activities",
        "group_range": {"start": "941", "end": "969"}
    },
    {
        "section_letter": "U",
        "sector_name": "Activities of households as employers; undifferentiated goods- and services-producing activities of households for own use",
        "group_range": {"start": "970", "end": "982"}
    },
    {
        "section_letter": "V",
        "sector_name": "Activities of extraterritorial organizations and bodies",
        "group_range": {"start": "990", "end": "990"}
    }
]


def map_nic_to_sector(nic_code: str) -> Dict:
    """
    Map NIC code to sector based on first 3 digits
    
    Args:
        nic_code: NIC code string (e.g., "24246")
        
    Returns:
        Dictionary with sector information or None if not mappable
    """
    if not nic_code or not isinstance(nic_code, str):
        return None
    
    # Extract first 3 digits
    nic_3digit = nic_code[:3]
    
    # Find matching sector
    for sector in NIC_SECTOR_MAPPING:
        start = sector["group_range"]["start"]
        end = sector["group_range"]["end"]
        
        if start <= nic_3digit <= end:
            return {
                "section": sector["section_letter"],
                "sectorName": sector["sector_name"],
                "nicCode": nic_3digit
            }
    
    return None


def aggregate_by_nic_sector(companies_with_loans: List[Dict]) -> Dict:
    """
    Aggregate companies by NIC sector using data from Task 1
    
    Args:
        companies_with_loans: List of companies with loan facilities (from Task 1)
        
    Returns:
        Dictionary with sector-wise aggregation (totals only, no individual companies)
    """
    sector_aggregation = {}
    unmapped_count = 0
    total_companies_processed = len(companies_with_loans)
    
    for company in companies_with_loans:
        nic_code = company.get('nicCode')
        total_exposure = company.get('totalExposure', 0)
        
        # Map to sector
        sector_info = map_nic_to_sector(nic_code)
        
        if sector_info:
            sector_name = f"{sector_info['section']} - {sector_info['sectorName']}"
            
            if sector_name not in sector_aggregation:
                sector_aggregation[sector_name] = {
                    "section": sector_info['section'],
                    "sectorName": sector_info['sectorName'],
                    "totalExposure": 0,
                    "numberOfCompanies": 0
                }
            
            sector_aggregation[sector_name]["totalExposure"] += total_exposure
            sector_aggregation[sector_name]["numberOfCompanies"] += 1
        else:
            # Company couldn't be mapped to sector
            unmapped_count += 1
    
    # Calculate summary statistics
    total_exposure = sum(s["totalExposure"] for s in sector_aggregation.values())
    total_mapped_companies = sum(s["numberOfCompanies"] for s in sector_aggregation.values())
    
    return {
        "summary": {
            "totalCompaniesProcessed": total_companies_processed,
            "totalMappedCompanies": total_mapped_companies,
            "totalUnmappedCompanies": unmapped_count,
            "totalExposure": total_exposure,
            "numberOfSectors": len(sector_aggregation)
        },
        "sectorWiseAggregation": sector_aggregation
    }


# Legacy function for backward compatibility (deprecated)
def extract_sector_wise_exposure(bank_symbol: str = None, companies_with_loans: List[Dict] = None) -> Dict:
    """
    DEPRECATED: Use aggregate_by_nic_sector() instead
    
    Legacy function maintained for backward compatibility
    If companies_with_loans is provided, uses it directly
    Otherwise falls back to the old MongoDB query method
    
    Args:
        bank_symbol: Bank symbol (deprecated, not used if companies_with_loans provided)
        companies_with_loans: List of companies from Task 1
        
    Returns:
        Dictionary with sector-wise aggregation
    """
    if companies_with_loans is not None:
        # Use the new efficient method
        return aggregate_by_nic_sector(companies_with_loans)
    
    # Old method - kept for backward compatibility but not recommended
    raise ValueError("Please provide companies_with_loans parameter or use aggregate_by_nic_sector() directly")


def get_sector_summary(companies_with_loans: List[Dict]) -> Dict:
    """
    Get a summary of sector-wise exposure
    
    Args:
        companies_with_loans: List of companies from Task 1
        
    Returns:
        Summary dictionary with top sectors
    """
    data = aggregate_by_nic_sector(companies_with_loans)
    
    # Sort sectors by exposure
    sorted_sectors = sorted(
        data["sectorWiseAggregation"].items(),
        key=lambda x: x[1]["totalExposure"],
        reverse=True
    )
    
    return {
        "summary": data["summary"],
        "topSectors": [
            {
                "sector": sector_name,
                "exposure": sector_data["totalExposure"],
                "companies": sector_data["numberOfCompanies"]
            }
            for sector_name, sector_data in sorted_sectors[:10]
        ]
    }


if __name__ == "__main__":
    # Test the function
    import sys
    from task1_crisil_filter import extract_bank_loans
    
    if len(sys.argv) > 1:
        bank = sys.argv[1]
        print(f"Extracting companies with loans from {bank}...")
        companies = extract_bank_loans(bank)
        print(f"Found {len(companies)} companies")
        
        print(f"\nMapping to NIC sectors...")
        result = aggregate_by_nic_sector(companies)
        print(f"\nSector-wise Exposure for {bank}:")
        print(f"Total Companies: {result['summary']['totalCompaniesProcessed']}")
        print(f"Mapped to Sectors: {result['summary']['totalMappedCompanies']}")
        print(f"Number of Sectors: {result['summary']['numberOfSectors']}")
        print(f"Total Exposure: ₹{result['summary']['totalExposure']:,.2f} Cr")
        
        if result['summary']['totalUnmappedCompanies'] > 0:
            print(f"Unmapped Companies: {result['summary']['totalUnmappedCompanies']}")
    else:
        print("Usage: python task8_nic_sector_mapping.py <BANK_SYMBOL>")

