"""
Task 7: Extract Related Party Transactions from Integrated Bank XBRL Filings
Parses integrated XBRL files using Arelle and extracts related party transaction data
"""
from arelle import Cntlr
from typing import Dict, List, Optional
import glob
import os
import sys
import re
from io import StringIO
from config import DATA_PATHS, get_bank_config


def extract_related_party_transactions(bank_symbol: str) -> Dict:
    """
    Extract related party transactions from integrated bank XBRL file
    
    Args:
        bank_symbol: Bank symbol (e.g., 'HDFCBANK', 'SBIN', 'ICICIBANK')
        
    Returns:
        Dictionary with related party transaction data
    """
    bank_config = get_bank_config(bank_symbol)
    if not bank_config:
        raise ValueError(f"Unknown bank symbol: {bank_symbol}")
    
    # Discover XBRL file — pattern: integrated_{SYMBOL}_{YYYY-MM-DD}.xml
    xbrl_file_pattern = os.path.join(
        DATA_PATHS["integrated_xbrl_dir"],
        f"integrated_{bank_symbol}_*.xml"
    )
    matches = sorted(glob.glob(xbrl_file_pattern))
    if not matches:
        raise FileNotFoundError(
            f"No integrated XBRL file found for {bank_symbol} in {DATA_PATHS['integrated_xbrl_dir']}. "
            f"Expected pattern: integrated_{bank_symbol}_YYYY-MM-DD.xml"
        )
    xbrl_file = matches[-1]  # Use the most recent date if multiple files exist
    
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
        
        # Extract related party transactions
        rpt_data = {
            "bankName": bank_config["fullName"],
            "bankSymbol": bank_symbol,
            "reportingPeriod": _extract_reporting_period(root),
            "relatedPartyTransactions": _extract_all_rpt(root),
            "transactionSummary": {}
        }
        
        # Generate summary statistics
        rpt_data["transactionSummary"] = _generate_summary(rpt_data["relatedPartyTransactions"])
        
        # Close the model
        modelXbrl.close()
        
        return rpt_data
        
    except Exception as e:
        sys.stdout = old_stdout
        raise ValueError(f"Failed to extract related party transactions: {e}")
    finally:
        sys.stdout = old_stdout


def _extract_reporting_period(root) -> Dict[str, str]:
    """
    Extract reporting period information from contexts
    """
    # Look for period information in contexts
    period_info = {
        "startDate": None,
        "endDate": None,
        "quarter": "Q2FY26"
    }
    
    # Search for context elements with period information
    namespace = {'xbrli': 'http://www.xbrl.org/2003/instance'}
    
    for context in root.findall('.//xbrli:context', namespace):
        period = context.find('xbrli:period', namespace)
        if period is not None:
            start_date = period.find('xbrli:startDate', namespace)
            end_date = period.find('xbrli:endDate', namespace)
            
            if start_date is not None and end_date is not None:
                period_info["startDate"] = start_date.text
                period_info["endDate"] = end_date.text
                break
    
    return period_info


def _extract_all_rpt(root) -> List[Dict]:
    """
    Extract all related party transactions from the XBRL file
    Identifies transactions by finding contexts with RelatedPartyTransaction pattern
    """
    transactions = []
    
    # Find all unique RPT contexts
    rpt_contexts = set()
    
    # Pattern to match RelatedPartyTransaction contexts (e.g., D_RelatedPartyTransaction1)
    context_pattern = re.compile(r'D_RelatedPartyTransaction\d+')
    
    for elem in root:
        context_ref = elem.get('contextRef', '')
        match = context_pattern.match(context_ref)
        if match:
            rpt_contexts.add(context_ref)
    
    # Extract data for each transaction context
    for context in sorted(rpt_contexts, key=lambda x: int(re.search(r'\d+', x).group())):
        transaction = _extract_transaction_data(root, context)
        if transaction:
            transactions.append(transaction)
    
    return transactions


def _extract_transaction_data(root, context_id: str) -> Optional[Dict]:
    """
    Extract complete data for a single related party transaction
    
    Args:
        root: XML root element
        context_id: Transaction context ID (e.g., D_RelatedPartyTransaction1)
        
    Returns:
        Dictionary with transaction details
    """
    # Extract all facts for this context
    facts = _extract_context_facts(root, context_id)
    
    if not facts:
        return None
    
    # Also extract corresponding instant context facts (e.g., I_RelatedPartyTransaction1)
    transaction_num = re.search(r'\d+', context_id).group()
    instant_context = f"I_RelatedPartyTransaction{transaction_num}"
    prior_year_context = f"I_RelatedPartyTransaction_PY{transaction_num}"
    
    instant_facts = _extract_context_facts(root, instant_context) or {}
    prior_year_facts = _extract_context_facts(root, prior_year_context) or {}
    
    # Build structured transaction record
    transaction = {
        "transactionId": int(transaction_num),
        "listedEntity": {
            "name": facts.get('nameOfListedEntityOrSubsidiaryEnteringIntoTheTransaction'),
            "pan": facts.get('panOfListedEntityOrSubsidiaryEnteringIntoTheTransaction')
        },
        "counterParty": {
            "name": facts.get('nameOfCounterParty'),
            "pan": facts.get('panOfCounterParty'),
            "relationship": facts.get('relationshipOfTheCounterpartyWithTheListedEntityOrItsSubsidiary')
        },
        "transaction": {
            "type": facts.get('typeOfRelatedPartyTransaction'),
            "details": facts.get('detailsOfOtherRelatedPartyTransaction'),
            "approvedValue": facts.get('valueOfTheRelatedPartyTransactionAsApprovedByTheAuditCommittee'),
            "actualAmount": facts.get('amountOfRelatedPartyTransactionDuringTheReportingPeriod'),
            "outstandingCurrentPeriod": instant_facts.get('amountOfRelatedPartyTransaction'),
            "outstandingPriorYear": prior_year_facts.get('amountOfRelatedPartyTransaction')
        },
        "remarks": facts.get('remarksOnApprovalByAuditCommittee'),
        "explanation": facts.get('relatedPartyTransactionExplanatory')
    }
    
    # Clean up None values
    transaction = _clean_none_values(transaction)
    
    return transaction


def _extract_context_facts(root, context_id: str) -> Optional[Dict]:
    """
    Extract all facts for a specific context ID
    
    Args:
        root: XML root element
        context_id: Context ID to search for
        
    Returns:
        Dictionary with fact names and values, or None if no facts found
    """
    data = {}
    
    # Use list comprehension for better performance
    for elem in root:
        try:
            context_ref = elem.get('contextRef', '')
            if context_ref == context_id:
                # Get the local name (strip namespace)
                local_name = elem.tag.split('}')[1] if '}' in elem.tag else elem.tag
                value = elem.text
                
                # Convert to camelCase
                key = _to_camel_case(local_name)
                
                # Try to convert to numeric if possible
                try:
                    if value is not None:
                        # Try integer first
                        if '.' not in str(value) and value.strip().replace('-', '').isdigit():
                            data[key] = int(value)
                        else:
                            # Try float
                            data[key] = float(value)
                except (ValueError, TypeError, AttributeError):
                    # Keep as string
                    data[key] = value
        except Exception:
            # Skip any problematic elements
            continue
    
    return data if data else None


def _to_camel_case(name: str) -> str:
    """
    Convert a name to camelCase
    Examples: 
        NameOfCounterParty -> nameOfCounterParty
        TypeOfRelatedPartyTransaction -> typeOfRelatedPartyTransaction
    """
    if not name:
        return name
    
    # If the first character is uppercase, make it lowercase
    return name[0].lower() + name[1:] if name else name


def _clean_none_values(obj):
    """
    Recursively remove None values from dictionaries
    """
    if isinstance(obj, dict):
        return {k: _clean_none_values(v) for k, v in obj.items() if v is not None and v != {} and v != []}
    elif isinstance(obj, list):
        return [_clean_none_values(item) for item in obj if item is not None]
    else:
        return obj


def _generate_summary(transactions: List[Dict]) -> Dict:
    """
    Generate summary statistics for related party transactions
    
    Args:
        transactions: List of transaction dictionaries
        
    Returns:
        Dictionary with summary statistics
    """
    if not transactions:
        return {
            "totalTransactions": 0,
            "totalApprovedValue": 0,
            "totalActualAmount": 0
        }
    
    summary = {
        "totalTransactions": len(transactions),
        "totalApprovedValue": 0,
        "totalActualAmount": 0,
        "byRelationship": {},
        "byType": {},
        "counterParties": []
    }
    
    # Aggregate data
    for txn in transactions:
        # Sum approved and actual values
        if txn.get("transaction", {}).get("approvedValue"):
            summary["totalApprovedValue"] += txn["transaction"]["approvedValue"]
        
        if txn.get("transaction", {}).get("actualAmount"):
            summary["totalActualAmount"] += txn["transaction"]["actualAmount"]
        
        # Count by relationship
        relationship = txn.get("counterParty", {}).get("relationship")
        if relationship:
            summary["byRelationship"][relationship] = summary["byRelationship"].get(relationship, 0) + 1
        
        # Count by transaction type
        txn_type = txn.get("transaction", {}).get("type")
        if txn_type:
            summary["byType"][txn_type] = summary["byType"].get(txn_type, 0) + 1
        
        # Collect unique counter parties
        counter_party = txn.get("counterParty", {}).get("name")
        if counter_party and counter_party not in summary["counterParties"]:
            summary["counterParties"].append(counter_party)
    
    # Count unique counter parties
    summary["uniqueCounterParties"] = len(summary["counterParties"])
    
    return summary


def main():
    """
    Test the extraction for all three banks
    """
    import json
    
    banks = ['SBIN', 'HDFCBANK', 'ICICIBANK']
    
    for bank in banks:
        print(f"\n{'='*60}")
        print(f"Extracting Related Party Transactions for {bank}")
        print('='*60)
        
        try:
            rpt_data = extract_related_party_transactions(bank)
            
            print(f"\nBank: {rpt_data['bankName']}")
            print(f"Symbol: {rpt_data['bankSymbol']}")
            print(f"Reporting Period: {rpt_data['reportingPeriod']}")
            print(f"\nTotal Transactions: {rpt_data['transactionSummary']['totalTransactions']}")
            print(f"Total Approved Value: ₹{rpt_data['transactionSummary']['totalApprovedValue']:,.0f}")
            print(f"Total Actual Amount: ₹{rpt_data['transactionSummary']['totalActualAmount']:,.0f}")
            print(f"Unique Counter Parties: {rpt_data['transactionSummary']['uniqueCounterParties']}")
            
            print("\nTransactions by Relationship:")
            for rel, count in rpt_data['transactionSummary']['byRelationship'].items():
                print(f"  - {rel}: {count}")
            
            print("\nTransactions by Type:")
            for txn_type, count in rpt_data['transactionSummary']['byType'].items():
                print(f"  - {txn_type}: {count}")
            
            # Show first 3 transactions as sample
            print("\nSample Transactions (first 3):")
            for i, txn in enumerate(rpt_data['relatedPartyTransactions'][:3], 1):
                print(f"\n  Transaction {i}:")
                print(f"    Counter Party: {txn.get('counterParty', {}).get('name')}")
                print(f"    Relationship: {txn.get('counterParty', {}).get('relationship')}")
                print(f"    Type: {txn.get('transaction', {}).get('type')}")
                print(f"    Actual Amount: ₹{txn.get('transaction', {}).get('actualAmount', 0):,.0f}")
            
            # Save to JSON file for verification
            output_file = os.path.join(
                DATA_PATHS["integrated_xbrl_dir"], 
                f"{bank}_related_party_transactions.json"
            )
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(rpt_data, f, indent=2, ensure_ascii=False)
            
            print(f"\n✓ Data saved to: {output_file}")
            
        except Exception as e:
            print(f"✗ Error extracting data for {bank}: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
