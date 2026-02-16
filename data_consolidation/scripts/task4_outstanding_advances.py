"""
Task 4: Extract Outstanding Advances to Priority Sector
Reads Excel file and extracts priority sector advances data for specified banks
"""
import pandas as pd
from typing import Dict
from config import DATA_PATHS, get_bank_config, TARGET_YEAR


def clean_numeric_value(value):
    """Convert value to float, handling None, '-', commas and other non-numeric values"""
    if pd.isna(value) or value in ['-', '', 'NA', 'na']:
        return None
    try:
        # Remove commas if present
        if isinstance(value, str):
            value = value.replace(',', '')
        return float(value)
    except (ValueError, TypeError):
        return None


def extract_outstanding_advances(bank_symbol: str) -> Dict:
    """
    Extract outstanding advances to priority sector for a specific bank from Excel file.
    
    Excel Structure:
    - Row 7: Main category headers
    - Row 8: Sub-headers (No. of A/cs, Balance O/s)
    - Row 9+: Bank data
    
    Args:
        bank_symbol: Bank symbol (e.g., 'HDFCBANK', 'SBIN', 'ICICIBANK')
        
    Returns:
        Dictionary with priority sector advances data structured by categories
    """
    bank_config = get_bank_config(bank_symbol)
    if not bank_config:
        raise ValueError(f"Unknown bank symbol: {bank_symbol}")
    
    # Bank name variations in the Excel file
    bank_name_variations = {
        "SBIN": ["State Bank Of India", "STATE BANK OF INDIA"],
        "HDFCBANK": ["Hdfc Bank Ltd.", "HDFC BANK LTD.", "HDFC Bank Limited"],
        "ICICIBANK": ["Icici Bank Limited", "ICICI BANK LIMITED", "ICICI Bank Limited"]
    }
    
    target_names = bank_name_variations.get(bank_symbol, [bank_config["excelName"]])
    
    # Read Excel file with proper header handling
    excel_path = DATA_PATHS["outstanding_advances"]
    
    try:
        # Read the Excel file without headers first to get raw data
        df = pd.read_excel(excel_path, header=None)
        
        # Extract headers from row 7 (main categories) and row 8 (sub-categories)
        main_headers = df.iloc[7].tolist()  # Row 7: main category names
        sub_headers = df.iloc[8].tolist()   # Row 8: No. of A/cs, Balance O/s
        
        # Data starts from row 9
        data_df = df.iloc[9:].copy()
        
        # Find the bank row
        bank_row = None
        for idx, row in data_df.iterrows():
            bank_name = str(row.iloc[1])  # Column 1 has bank names
            for target_name in target_names:
                if target_name.lower() in bank_name.lower():
                    bank_row = row
                    break
            if bank_row is not None:
                break
        
        if bank_row is None:
            raise ValueError(f"Bank {bank_config['fullName']} not found in the Excel file")
        
        # Parse the data structure
        advances_data = {
            "bankName": bank_config["fullName"],
            "year": TARGET_YEAR,
            "currency": {
                "accounts": "Lakhs",
                "balance": "INR Crores"
            }
        }
        
        # Column mapping based on Excel structure
        # Column 0: Empty, Column 1: Bank Name, Column 2: ANBC, Column 3: CEOBE
        advances_data["adjustedNetBankCredit"] = clean_numeric_value(bank_row.iloc[2])
        advances_data["ceobe"] = clean_numeric_value(bank_row.iloc[3])
        
        # Priority Sector categories and their column indices
        categories = [
            ("prioritySectorTotal", 4, 5),
            ("agriculture", 6, 7),
            ("msme", 8, 9),
            ("exportCredit", 10, 11),
            ("education", 12, 13),
            ("housing", 14, 15),
            ("renewableEnergy", 16, 17),
            ("socialInfrastructure", 18, 19),
            ("othersCategory", 20, 21),
            ("weakerSections", 22, 23)
        ]
        
        for category_name, accounts_col, balance_col in categories:
            advances_data[category_name] = {
                "numberOfAccounts": clean_numeric_value(bank_row.iloc[accounts_col]),
                "balanceOutstanding": clean_numeric_value(bank_row.iloc[balance_col])
            }
        
        return advances_data
        
    except Exception as e:
        raise ValueError(f"Failed to extract outstanding advances for {bank_config['fullName']}: {e}")


if __name__ == "__main__":
    # Test with all three banks
    import json
    
    for symbol in ['SBIN', 'HDFCBANK', 'ICICIBANK']:
        print(f"\n{'='*80}")
        print(f"Testing Outstanding Advances extraction for {symbol}")
        print('='*80)
        try:
            data = extract_outstanding_advances(symbol)
            print(f"✓ Successfully extracted outstanding advances for {data['bankName']}")
            print(f"\nYear: {data['year']}")
            print(f"Currency - Accounts: {data['currency']['accounts']}, Balance: {data['currency']['balance']}")
            print(f"\nAdjusted Net Bank Credit (ANBC): {data['adjustedNetBankCredit']:,.2f} Crores" if data['adjustedNetBankCredit'] else "\nAdjusted Net Bank Credit (ANBC): N/A")
            print(f"CEOBE: {data['ceobe']:,.2f} Crores" if data['ceobe'] else "CEOBE: N/A")
            
            print("\n--- Priority Sector Breakdown ---")
            categories = [
                ("Priority Sector Total", "prioritySectorTotal"),
                ("I. Agriculture", "agriculture"),
                ("II. MSMEs", "msme"),
                ("III. Export Credit", "exportCredit"),
                ("IV. Education", "education"),
                ("V. Housing", "housing"),
                ("VI. Renewable Energy", "renewableEnergy"),
                ("VII. Social Infrastructure", "socialInfrastructure"),
                ("VIII. Others Category", "othersCategory"),
                ("Weaker Sections", "weakerSections")
            ]
            
            for display_name, key in categories:
                cat_data = data[key]
                accounts = cat_data['numberOfAccounts']
                balance = cat_data['balanceOutstanding']
                
                accounts_str = f"{accounts:,.2f} Lakhs" if accounts is not None else "N/A"
                balance_str = f"{balance:,.2f} Crores" if balance is not None else "N/A"
                
                print(f"  {display_name:.<35} Accounts: {accounts_str:>20} | Balance: {balance_str:>20}")
            
        except Exception as e:
            print(f"✗ Error: {e}")
            import traceback
            traceback.print_exc()
