"""
Task 5: Convert XBRL Shareholding Pattern to JSON
Parses XBRL shareholding pattern files using Arelle and extracts structured data with individual entity-level details
"""
from arelle import Cntlr
from typing import Dict, List, Optional
import os
import sys
import re
from io import StringIO
from config import DATA_PATHS, get_bank_config, TARGET_YEAR


def extract_shareholding_pattern(bank_symbol: str) -> Dict:
    """
    Extract comprehensive shareholding pattern data from XBRL file
    Includes hierarchical groups and individual entity-level data
    
    Args:
        bank_symbol: Bank symbol (e.g., 'HDFCBANK', 'SBIN', 'ICICIBANK')
        
    Returns:
        Dictionary with complete shareholding pattern data including individual entities
    """
    bank_config = get_bank_config(bank_symbol)
    if not bank_config:
        raise ValueError(f"Unknown bank symbol: {bank_symbol}")
    
    # Construct XBRL file path
    xbrl_file = os.path.join(DATA_PATHS["shp_dir"], f"shp_{bank_symbol}.xml")
    
    if not os.path.exists(xbrl_file):
        raise FileNotFoundError(f"XBRL file not found: {xbrl_file}")
    
    # Suppress Arelle logging
    old_stdout = sys.stdout
    sys.stdout = StringIO()
    
    try:
        # Create Arelle controller
        ctrl = Cntlr.Cntlr(logFileName="logToPrint")
        ctrl.webCache.workOffline = True  # Work offline
        
        # Load the XBRL instance
        modelXbrl = ctrl.modelManager.load(xbrl_file)
        
        if not modelXbrl:
            raise ValueError("Failed to load XBRL file")
        
        # Restore stdout
        sys.stdout = old_stdout
        
        # Access facts and contexts from the XBRL instance
        root = modelXbrl.modelDocument.xmlRootElement
        
        # Extract comprehensive data with individual entities
        shareholding_data = {
            "bankName": bank_config["fullName"],
            "bankSymbol": bank_symbol,
            "year": TARGET_YEAR,
            "totalShares": _extract_total_shares(root),
            "totalShareholders": _extract_total_shareholders(root),
            "shareholdingPattern": _extract_complete_shareholding_pattern(root)
        }
        
        # Close the model
        modelXbrl.close()
        
        return shareholding_data
        
    except Exception as e:
        sys.stdout = old_stdout
        raise ValueError(f"Failed to extract shareholding pattern: {e}")
    finally:
        sys.stdout = old_stdout


def _extract_complete_shareholding_pattern(root) -> Dict:
    """
    Extract complete shareholding pattern with both aggregates and individual entities
    Creates hierarchical structure: category -> {aggregate, entities}
    """
    pattern = {}
    
    # 1. PROMOTER AND PROMOTER GROUP
    promoter = {
        "aggregate": _extract_context_facts(root, "ShareholdingOfPromoterAndPromoterGroup_ContextI"),
        "entities": []
    }
    
    # Extract promoter sub-categories with individual entities
    promoter_entities = _extract_entity_group(root, "CentralGovernmentOrStateGovernments")
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
    mf_entities = _extract_entity_group(root, "MutualFundsOrUTI")
    institutions["mutualFunds"] = {
        "aggregate": _extract_context_facts(root, "MutualFundsOrUTI_ContextI"),
        "entities": mf_entities if mf_entities else []
    }
    
    # Foreign Portfolio Investors
    fpi_cat1_entities = _extract_entity_group(root, "InstitutionsForeignPortfolioInvestorCategoryOne")
    fpi_cat2_entities = _extract_entity_group(root, "InstitutionsForeignPortfolioInvestorCategoryTwo")
    institutions["foreignPortfolioInvestors"] = {
        "category1": {
            "aggregate": _extract_context_facts(root, "InstitutionsForeignPortfolioInvestorCategoryOne_ContextI"),
            "entities": fpi_cat1_entities if fpi_cat1_entities else []
        },
        "category2": {
            "aggregate": _extract_context_facts(root, "InstitutionsForeignPortfolioInvestorCategoryTwo_ContextI"),
            "entities": fpi_cat2_entities if fpi_cat2_entities else []
        }
    }
    
    # Insurance Companies
    insurance_entities = _extract_entity_group(root, "InsuranceCompanies")
    institutions["insuranceCompanies"] = {
        "aggregate": _extract_context_facts(root, "InsuranceCompanies_ContextI"),
        "entities": insurance_entities if insurance_entities else []
    }
    
    # Banks
    bank_entities = _extract_entity_group(root, "Banks")
    institutions["banks"] = {
        "aggregate": _extract_context_facts(root, "Banks_ContextI"),
        "entities": bank_entities if bank_entities else []
    }
    
    # Provident/Pension Funds
    pension_entities = _extract_entity_group(root, "ProvidentFundsOrPensionFunds")
    institutions["providentFunds"] = {
        "aggregate": _extract_context_facts(root, "ProvidentFundsOrPensionFunds_ContextI"),
        "entities": pension_entities if pension_entities else []
    }
    
    # Other Institutions - Domestic
    other_inst_domestic_entities = _extract_entity_group(root, "OtherInstitutionsDomestic")
    institutions["otherInstitutionsDomestic"] = {
        "aggregate": _extract_context_facts(root, "OtherInstitutionsDomestic_ContextI"),
        "entities": other_inst_domestic_entities if other_inst_domestic_entities else []
    }
    
    # Other Institutions - Foreign
    other_inst_foreign_entities = _extract_entity_group(root, "OtherInstitutionsForeign")
    institutions["otherInstitutionsForeign"] = {
        "aggregate": _extract_context_facts(root, "OtherInstitutionsForeign_ContextI"),
        "entities": other_inst_foreign_entities if other_inst_foreign_entities else []
    }
    
    public["institutions"] = institutions
    
    # 2.2 Non-Institutional Holdings
    non_institutions = {}
    
    # Resident Individuals
    resident_entities = _extract_entity_group(root, "ResidentIndividuals")
    non_institutions["residentIndividuals"] = {
        "aggregate": _extract_context_facts(root, "ResidentIndividuals_ContextI"),
        "entities": resident_entities if resident_entities else []
    }
    
    # Non-Resident Indians
    nri_entities = _extract_entity_group(root, "NonResidentIndians")
    non_institutions["nonResidentIndians"] = {
        "aggregate": _extract_context_facts(root, "NonResidentIndians_ContextI"),
        "entities": nri_entities if nri_entities else []
    }
    
    # Bodies Corporate
    bodies_corp_entities = _extract_entity_group(root, "BodiesCorporate")
    non_institutions["bodiesCorporate"] = {
        "aggregate": _extract_context_facts(root, "BodiesCorporate_ContextI"),
        "entities": bodies_corp_entities if bodies_corp_entities else []
    }
    
    # Other Non-Institutions (HUF, Trusts, Clearing Members, etc.)
    other_non_inst_entities = _extract_entity_group(root, "OtherNonInstitutions")
    non_institutions["otherNonInstitutions"] = {
        "aggregate": _extract_context_facts(root, "OtherNonInstitutions_ContextI"),
        "entities": other_non_inst_entities if other_non_inst_entities else []
    }
    
    public["nonInstitutions"] = non_institutions
    
    pattern["publicHolding"] = public
    
    # 3. NON-PROMOTER NON-PUBLIC SHAREHOLDING
    non_promoter_non_public = {
        "aggregate": _extract_context_facts(root, "SharesHeldByNonPromoterNonPublicShareholders_ContextI"),
        "entities": []
    }
    
    # Custodian/DR Holders (GDR/ADR)
    custodian_entities = _extract_entity_group(root, "CustodianOrDRHolder")
    if custodian_entities:
        non_promoter_non_public["custodian"] = {
            "aggregate": _extract_context_facts(root, "CustodianOrDRHolder_ContextI"),
            "entities": custodian_entities
        }
    
    pattern["nonPromoterNonPublicHolding"] = non_promoter_non_public
    
    return pattern


def _extract_entity_group(root, category_prefix: str) -> List[Dict]:
    """
    Extract individual entities for a given category
    
    Args:
        root: XML root element
        category_prefix: Category prefix (e.g., 'MutualFundsOrUTI', 'InsuranceCompanies')
        
    Returns:
        List of entity dictionaries with comprehensive data
    """
    entities = []
    
    # Find all contexts matching this category pattern (e.g., MutualFundsOrUTI_Context15, Context16, etc.)
    # We look for contexts ending with _Context followed by numbers
    context_pattern = re.compile(rf"^{category_prefix}_Context\d+$")
    
    # Scan all contexts in the root
    entity_contexts = []
    for elem in root:
        local_name = elem.tag.split('}')[1] if '}' in elem.tag else elem.tag
        
        # Look for NameOfTheShareholder facts to identify entity contexts
        if local_name == 'NameOfTheShareholder':
            context_ref = elem.get('contextRef', '')
            # Remove D_ prefix if present to get the base context
            base_context = context_ref.replace('D_', '')
            
            if context_pattern.match(base_context):
                shareholder_name = elem.text
                # Filter out masked or empty names
                if shareholder_name and shareholder_name not in ['******', 'NA', '', 'Not Applicable']:
                    entity_contexts.append({
                        'context': base_context,
                        'name': shareholder_name
                    })
    
    # Extract full data for each entity
    for entity_ctx in entity_contexts:
        context = entity_ctx['context']
        name = entity_ctx['name']
        
        # Extract all facts for this entity
        facts = _extract_context_facts(root, context)
        
        if facts:
            entity = {
                'name': name,
                'numberOfShares': facts.get('numberOfShares') or facts.get('numberOfFullyPaidUpEquityShares'),
                'shareholdingPercentage': facts.get('shareholdingAsAPercentageOfTotalNumberOfShares'),
                'numberOfVotingRights': facts.get('numberOfVotingRights'),
                'votingRightsPercentage': facts.get('percentageOfTotalVotingRights'),
                'pan': facts.get('permanentAccountNumberOfShareholder'),
                'dematerializedShares': facts.get('numberOfEquitySharesHeldInDematerializedForm'),
                'numberOfShareholders': facts.get('numberOfShareholders')
            }
            
            # Clean up None values and add additional fields if available
            entity = {k: v for k, v in entity.items() if v is not None}
            
            # Add type/category if available
            if facts.get('typeOfPromoterShareholding'):
                entity['type'] = facts.get('typeOfPromoterShareholding')
            if facts.get('categoryOfOtherInstitutions'):
                entity['category'] = facts.get('categoryOfOtherInstitutions')
            if facts.get('categoryOfOtherNonInstitutions'):
                entity['category'] = facts.get('categoryOfOtherNonInstitutions')
            
            entities.append(entity)
    
    # Sort by shareholding percentage if available
    entities.sort(key=lambda x: x.get('shareholdingPercentage', 0), reverse=True)
    
    return entities


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


def _extract_total_shares(root) -> Optional[int]:
    """Extract total number of shares"""
    facts = _extract_context_facts(root, "ShareholdingPattern_ContextI")
    if facts:
        return facts.get('numberOfShares') or facts.get('totalNumberOfShares')
    
    # Try main context
    facts = _extract_context_facts(root, "MainI")
    if facts:
        return facts.get('numberOfShares') or facts.get('totalNumberOfShares')
    
    return None


def _extract_total_shareholders(root) -> Optional[int]:
    """Extract total number of shareholders"""
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
    # Test with all three banks
    import json
    
    for symbol in ['SBIN', 'HDFCBANK', 'ICICIBANK']:
        print(f"\n{'='*100}")
        print(f"Testing Shareholding Pattern extraction for {symbol}")
        print('='*100)
        try:
            data = extract_shareholding_pattern(symbol)
            print(f"✓ Successfully extracted shareholding pattern for {data['bankName']}")
            print(f"\nYear: {data['year']}")
            
            if data.get('totalShares'):
                print(f"Total Shares: {data['totalShares']:,.0f}")
            if data.get('totalShareholders'):
                print(f"Total Shareholders: {data['totalShareholders']:,.0f}")
            
            pattern = data.get('shareholdingPattern', {})
            
            # Print Promoter Holding with entities
            print("\n" + "="*100)
            print("PROMOTER HOLDING")
            print("="*100)
            promoter = pattern.get('promoterHolding', {})
            if promoter.get('aggregate'):
                agg = promoter['aggregate']
                print(f"\nAggregate:")
                print(f"  Shares: {agg.get('numberOfShares', 'N/A'):,.0f}" if agg.get('numberOfShares') else "  Shares: N/A")
                print(f"  Percentage: {agg.get('shareholdingPercentage', 'N/A')}%" if agg.get('shareholdingPercentage') else "  Percentage: N/A")
            
            if promoter.get('government'):
                gov = promoter['government']
                print(f"\nGovernment Holdings:")
                if gov.get('entities'):
                    print(f"  {len(gov['entities'])} entities found:")
                    for i, entity in enumerate(gov['entities'][:5], 1):
                        shares_str = f"{entity.get('numberOfShares', 0):,.0f}" if entity.get('numberOfShares') else "N/A"
                        pct_str = f"{entity.get('shareholdingPercentage', 0):.2f}%" if entity.get('shareholdingPercentage') else "N/A"
                        print(f"    {i}. {entity.get('name', 'Unknown')[:70]:<70} | {shares_str:>18} | {pct_str:>10}")
            
            # Print Institutional Holdings with entities
            print("\n" + "="*100)
            print("INSTITUTIONAL HOLDINGS")
            print("="*100)
            
            institutions = pattern.get('publicHolding', {}).get('institutions', {})
            
            # Mutual Funds
            if institutions.get('mutualFunds'):
                mf = institutions['mutualFunds']
                print(f"\nMutual Funds:")
                if mf.get('aggregate'):
                    agg = mf['aggregate']
                    print(f"  Aggregate: {agg.get('numberOfShares', 0):,.0f} shares ({agg.get('shareholdingPercentage', 0)}%)")
                if mf.get('entities'):
                    print(f"  {len(mf['entities'])} entities found (showing top 10):")
                    for i, entity in enumerate(mf['entities'][:10], 1):
                        shares_str = f"{entity.get('numberOfShares', 0):,.0f}" if entity.get('numberOfShares') else "N/A"
                        pct_str = f"{entity.get('shareholdingPercentage', 0):.2f}%" if entity.get('shareholdingPercentage') else "N/A"
                        print(f"    {i:2d}. {entity.get('name', 'Unknown')[:70]:<70} | {shares_str:>18} | {pct_str:>10}")
            
            # Insurance Companies
            if institutions.get('insuranceCompanies'):
                ic = institutions['insuranceCompanies']
                print(f"\nInsurance Companies:")
                if ic.get('aggregate'):
                    agg = ic['aggregate']
                    print(f"  Aggregate: {agg.get('numberOfShares', 0):,.0f} shares ({agg.get('shareholdingPercentage', 0)}%)")
                if ic.get('entities'):
                    print(f"  {len(ic['entities'])} entities found:")
                    for i, entity in enumerate(ic['entities'][:10], 1):
                        shares_str = f"{entity.get('numberOfShares', 0):,.0f}" if entity.get('numberOfShares') else "N/A"
                        pct_str = f"{entity.get('shareholdingPercentage', 0):.2f}%" if entity.get('shareholdingPercentage') else "N/A"
                        print(f"    {i:2d}. {entity.get('name', 'Unknown')[:70]:<70} | {shares_str:>18} | {pct_str:>10}")
            
            # Provident/Pension Funds
            if institutions.get('providentFunds'):
                pf = institutions['providentFunds']
                print(f"\nProvident/Pension Funds:")
                if pf.get('aggregate'):
                    agg = pf['aggregate']
                    print(f"  Aggregate: {agg.get('numberOfShares', 0):,.0f} shares ({agg.get('shareholdingPercentage', 0)}%)")
                if pf.get('entities'):
                    print(f"  {len(pf['entities'])} entities found:")
                    for i, entity in enumerate(pf['entities'][:10], 1):
                        shares_str = f"{entity.get('numberOfShares', 0):,.0f}" if entity.get('numberOfShares') else "N/A"
                        pct_str = f"{entity.get('shareholdingPercentage', 0):.2f}%" if entity.get('shareholdingPercentage') else "N/A"
                        print(f"    {i:2d}. {entity.get('name', 'Unknown')[:70]:<70} | {shares_str:>18} | {pct_str:>10}")
            
            # Foreign Portfolio Investors
            if institutions.get('foreignPortfolioInvestors'):
                fpi = institutions['foreignPortfolioInvestors']
                if fpi.get('category1'):
                    cat1 = fpi['category1']
                    print(f"\nForeign Portfolio Investors (Category I):")
                    if cat1.get('aggregate'):
                        agg = cat1['aggregate']
                        print(f"  Aggregate: {agg.get('numberOfShares', 0):,.0f} shares ({agg.get('shareholdingPercentage', 0)}%)")
                    if cat1.get('entities'):
                        print(f"  {len(cat1['entities'])} entities found (showing top 5):")
                        for i, entity in enumerate(cat1['entities'][:5], 1):
                            shares_str = f"{entity.get('numberOfShares', 0):,.0f}" if entity.get('numberOfShares') else "N/A"
                            pct_str = f"{entity.get('shareholdingPercentage', 0):.2f}%" if entity.get('shareholdingPercentage') else "N/A"
                            print(f"    {i}. {entity.get('name', 'Unknown')[:70]:<70} | {shares_str:>18} | {pct_str:>10}")
            
            # Other Institutions - Foreign
            if institutions.get('otherInstitutionsForeign'):
                oif = institutions['otherInstitutionsForeign']
                print(f"\nOther Foreign Institutions:")
                if oif.get('aggregate'):
                    agg = oif['aggregate']
                    print(f"  Aggregate: {agg.get('numberOfShares', 0):,.0f} shares ({agg.get('shareholdingPercentage', 0)}%)")
                if oif.get('entities'):
                    print(f"  {len(oif['entities'])} entities found:")
                    for i, entity in enumerate(oif['entities'][:10], 1):
                        shares_str = f"{entity.get('numberOfShares', 0):,.0f}" if entity.get('numberOfShares') else "N/A"
                        pct_str = f"{entity.get('shareholdingPercentage', 0):.2f}%" if entity.get('shareholdingPercentage') else "N/A"
                        cat = entity.get('category', 'N/A')
                        print(f"    {i:2d}. {entity.get('name', 'Unknown')[:50]:<50} | {cat[:15]:<15} | {shares_str:>18} | {pct_str:>10}")
            
            # Non-Institutional Holdings with entities
            print("\n" + "="*100)
            print("NON-INSTITUTIONAL HOLDINGS")
            print("="*100)
            
            non_institutions = pattern.get('publicHolding', {}).get('nonInstitutions', {})
            
            # Other Non-Institutions (HUF, Trusts, Clearing Members, etc.)
            if non_institutions.get('otherNonInstitutions'):
                oni = non_institutions['otherNonInstitutions']
                print(f"\nOther Non-Institutions (HUF, Trusts, Clearing Members, etc.):")
                if oni.get('aggregate'):
                    agg = oni['aggregate']
                    print(f"  Aggregate: {agg.get('numberOfShares', 0):,.0f} shares ({agg.get('shareholdingPercentage', 0)}%)")
                if oni.get('entities'):
                    print(f"  {len(oni['entities'])} entities/categories found:")
                    for i, entity in enumerate(oni['entities'][:15], 1):
                        shares_str = f"{entity.get('numberOfShares', 0):,.0f}" if entity.get('numberOfShares') else "N/A"
                        pct_str = f"{entity.get('shareholdingPercentage', 0):.2f}%" if entity.get('shareholdingPercentage') else "N/A"
                        shareholders = entity.get('numberOfShareholders', '')
                        sh_str = f"({shareholders:,.0f} SH)" if shareholders else ""
                        cat = entity.get('category', '')
                        name = entity.get('name', 'Unknown')
                        print(f"    {i:2d}. {name[:40]:<40} | {cat[:20]:<20} | {shares_str:>18} | {pct_str:>8} {sh_str}")
            
            # Custodian/DR Holders
            print("\n" + "="*100)
            print("NON-PROMOTER NON-PUBLIC HOLDING")
            print("="*100)
            
            npnp = pattern.get('nonPromoterNonPublicHolding', {})
            if npnp.get('custodian'):
                cust = npnp['custodian']
                print(f"\nCustodian/DR Holders (GDR/ADR):")
                if cust.get('aggregate'):
                    agg = cust['aggregate']
                    print(f"  Aggregate: {agg.get('numberOfShares', 0):,.0f} shares ({agg.get('shareholdingPercentage', 0)}%)")
                if cust.get('entities'):
                    print(f"  {len(cust['entities'])} entities found:")
                    for i, entity in enumerate(cust['entities'], 1):
                        shares_str = f"{entity.get('numberOfShares', 0):,.0f}" if entity.get('numberOfShares') else "N/A"
                        pct_str = f"{entity.get('shareholdingPercentage', 0):.2f}%" if entity.get('shareholdingPercentage') else "N/A"
                        vr_str = f"{entity.get('numberOfVotingRights', 0):,.0f}" if entity.get('numberOfVotingRights') is not None else "N/A"
                        print(f"    {i}. {entity.get('name', 'Unknown')[:70]:<70} | {shares_str:>18} | {pct_str:>8} | VR: {vr_str}")
            
            # Optionally save to JSON file for inspection
            output_file = f'shareholding_{symbol}.json'
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"\n✓ Full data saved to {output_file}")
                    
        except Exception as e:
            print(f"✗ Error: {e}")
            import traceback
            traceback.print_exc()
