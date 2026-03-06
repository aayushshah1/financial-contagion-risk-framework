"""
Task 2: Extract Balance Sheet Data (Assets and Liabilities)
Reads Excel file and extracts balance sheet data for specified banks
"""
import pandas as pd
from typing import Dict
from config import DATA_PATHS, get_bank_config, TARGET_YEAR, YEAR_LABEL


def clean_numeric_value(value):
    """Convert value to float, handling None, '-', and other non-numeric values"""
    if pd.isna(value) or value in ['-', '', 'NA', 'na']:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def extract_balance_sheet_data(bank_symbol: str) -> Dict:
    """
    Extract assets and liabilities data for a specific bank
    
    Args:
        bank_symbol: Bank symbol (e.g., 'HDFCBANK', 'SBIN', 'ICICIBANK')
        
    Returns:
        Dictionary with assets and liabilities data
    """
    bank_config = get_bank_config(bank_symbol)
    if not bank_config:
        raise ValueError(f"Unknown bank symbol: {bank_symbol}")
    
    excel_name = bank_config["excelName"]
    
    # Read Assets sheet
    try:
        assets_df = pd.read_excel(DATA_PATHS["balance_sheet"], sheet_name="ASSETS")
    except FileNotFoundError:
        raise FileNotFoundError(f"Balance sheet file not found at {DATA_PATHS['balance_sheet']}")
    except Exception as e:
        raise ValueError(f"Error reading Assets sheet: {e}")
    
    # Read Liabilities sheet
    try:
        liabilities_df = pd.read_excel(DATA_PATHS["balance_sheet"], sheet_name="LIABILITIES_2020_Onwards")
    except Exception as e:
        raise ValueError(f"Error reading Liabilities sheet: {e}")
    
    # Clean Assets dataframe
    assets_clean = assets_df.iloc[5:].copy()
    assets_clean.columns = assets_clean.iloc[0]
    assets_clean = assets_clean.iloc[1:].reset_index(drop=True)
    assets_clean['Year'] = assets_clean['Year'].ffill()
    assets_clean = assets_clean.dropna(axis=1, how='all')
    
    # Clean Liabilities dataframe
    liabilities_clean = liabilities_df.iloc[5:].copy()
    liabilities_clean.columns = liabilities_clean.iloc[0]
    liabilities_clean = liabilities_clean.iloc[1:].reset_index(drop=True)
    liabilities_clean['Year'] = liabilities_clean['Year'].ffill()
    liabilities_clean = liabilities_clean.dropna(axis=1, how='all')
    
    # Make duplicate column names unique
    cols = liabilities_clean.columns.tolist()
    seen = {}
    for i, col in enumerate(cols):
        if col in seen:
            seen[col] += 1
            cols[i] = f"{col}.{seen[col]}"
        else:
            seen[col] = 0
    liabilities_clean.columns = cols
    
    # Filter for our target bank and year
    # Convert Year to string for comparison and clean bank names
    assets_clean['Year_str'] = assets_clean['Year'].astype(str).str.strip()
    assets_clean['Banks_clean'] = assets_clean['Banks'].astype(str).str.strip()
    
    assets_bank = assets_clean[
        (assets_clean['Banks_clean'] == excel_name) & 
        (assets_clean['Year_str'] == YEAR_LABEL)
    ]
    
    liabilities_clean['Year_str'] = liabilities_clean['Year'].astype(str).str.strip()
    liabilities_clean['Banks_clean'] = liabilities_clean['Banks'].astype(str).str.strip()
    
    liabilities_bank = liabilities_clean[
        (liabilities_clean['Banks_clean'] == excel_name) & 
        (liabilities_clean['Year_str'] == YEAR_LABEL)
    ]
    
    if assets_bank.empty:
        raise ValueError(f"No assets data found for {excel_name} in year {YEAR_LABEL}")
    
    if liabilities_bank.empty:
        raise ValueError(f"No liabilities data found for {excel_name} in year {YEAR_LABEL}")
    
    # Extract assets data
    assets_data = _extract_assets(assets_bank.iloc[0])
    
    # Extract liabilities data
    liabilities_data = _extract_liabilities(liabilities_bank.iloc[0])
    
    return {
        "assets": assets_data,
        "liabilities": liabilities_data,
        "year": TARGET_YEAR,
        "currency": "INR Crore"
    }


def _extract_assets(row: pd.Series) -> Dict:
    """Extract and structure assets data from a row"""
    return {
        "cash": {
            "cashInHand": clean_numeric_value(row.get('1.     Cash in hand')),
            "balancesWithRBI": clean_numeric_value(row.get('2.     Balances with RBI')),
            "balancesWithBanksInIndia": clean_numeric_value(row.get('3.     Balances with banks in India')),
            "moneyAtCallAndShortNotice": clean_numeric_value(row.get('4.     Money at call and short notice')),
            "balancesWithBanksOutsideIndia": clean_numeric_value(row.get('5.     Balances with banks outside India'))
        },
        "investments": {
            "total": clean_numeric_value(row.get('6.     Investments')),
            "investmentsInIndia": {
                "total": clean_numeric_value(row.get('6.1.       Investments in India')),
                "governmentSecurities": clean_numeric_value(row.get('(i)     Government securities')),
                "otherApprovedSecurities": clean_numeric_value(row.get('(ii)    Other approved securities')),
                "shares": clean_numeric_value(row.get('(iii)   Shares')),
                "debenturesAndBonds": clean_numeric_value(row.get('(iv)   Debentures and Bonds')),
                "subsidiariesAndJointVentures": clean_numeric_value(row.get('(v)    Subsidiaries and/or joint ventures')),
                "others": clean_numeric_value(row.get('(vi)   Others'))
            },
            "investmentsOutsideIndia": {
                "total": clean_numeric_value(row.get('6.2.       Investments outside India')),
                "governmentSecurities": clean_numeric_value(row.get('(i)      Government securities')),
                "subsidiariesAndJointVentures": clean_numeric_value(row.get('(ii)    Subsidiaries and/or joint ventures')),
                "others": clean_numeric_value(row.get('(iii)   Others'))
            }
        },
        "advances": {
            "total": clean_numeric_value(row.get('7.     Advances')),
            "byType": {
                "billsPurchasedAndDiscounted": clean_numeric_value(row.get('7A.1.    Bills purchased and discounted')),
                "cashCreditsOverdraftsAndLoans": clean_numeric_value(row.get('7A.2.    Cash credits, overdrafts & loans')),
                "termLoans": clean_numeric_value(row.get('7A.3.    Term loans'))
            },
            "bySecurity": {
                "securedByTangibleAssets": clean_numeric_value(row.get('7B.1.    Secured by tangible assets')),
                "coveredByBankGovtGuarantees": clean_numeric_value(row.get('7B.2.    Covered by Bank/Govt. Guarantees')),
                "unsecured": clean_numeric_value(row.get('7B.3.    Unsecured'))
            },
            "byLocation": {
                "advancesInIndia": {
                    "total": clean_numeric_value(row.get('7C.1.     Advances in India')),
                    "prioritySectors": clean_numeric_value(row.get('(i)         Priority sectors ')),
                    "publicSectors": clean_numeric_value(row.get('(ii)        Public sectors')),
                    "banks": clean_numeric_value(row.get('(iii)       Banks')),
                    "others": clean_numeric_value(row.get('(iv)       others'))
                },
                "advancesOutsideIndia": clean_numeric_value(row.get('7C.2.    Advances outside India'))
            }
        },
        "fixedAssets": {
            "total": clean_numeric_value(row.get('8.     Fixed Assets')),
            "premises": clean_numeric_value(row.get('8.1.      Premises')),
            "fixedAssetsUnderConstruction": clean_numeric_value(row.get('8.2.      Fixed assets under construction')),
            "otherFixedAssets": clean_numeric_value(row.get('8.3.      Other Fixed assets'))
        },
        "otherAssets": {
            "total": clean_numeric_value(row.get('9.     Other Assets')),
            "interOfficeAdjustments": clean_numeric_value(row.get('9.1.      Inter-office adjustments (net)')),
            "interestAccrued": clean_numeric_value(row.get('9.2.      Interest accrued ')),
            "taxPaid": clean_numeric_value(row.get('9.3.      Tax paid')),
            "stationeryAndStamps": clean_numeric_value(row.get('9.4.      Stationery and Stamps')),
            "others": clean_numeric_value(row.get('9.5.      Others'))
        },
        "totalAssets": clean_numeric_value(row.get('Total Assets'))
    }


def _extract_liabilities(row: pd.Series) -> Dict:
    """Extract and structure liabilities data from a row"""
    return {
        "capital": clean_numeric_value(row.get('1.     Capital')),
        "reservesAndSurplus": {
            "total": clean_numeric_value(row.get('2. Reserves and Surplus')),
            "statutoryReserve": clean_numeric_value(row.get('2.1 Statutory Reserve')),
            "capitalReserve": clean_numeric_value(row.get('2.2 Capital Reserve')),
            "sharePremium": clean_numeric_value(row.get('2.3       Share Premium')),
            "revenueAndOtherReserves": clean_numeric_value(row.get('2.4 Revenue and other Reserves')),
            "balanceOfProfit": clean_numeric_value(row.get('2.5 Balance of Profit'))
        },
        "deposits": {
            "total": clean_numeric_value(row.get('3. Deposits')),
            "byType": {
                "demandDeposits": {
                    "total": clean_numeric_value(row.get('3A.1.  Demand deposits')),
                    "fromBanks": clean_numeric_value(row.get('(i)          From banks')),  # First occurrence
                    "fromOthers": clean_numeric_value(row.get('(ii)         From others'))  # First occurrence
                },
                "savingsBankDeposits": clean_numeric_value(row.get('3A.2.   Savings bank deposits')),
                "termDeposits": {
                    "total": clean_numeric_value(row.get('3A.3.   Term deposits')),
                    "fromBanks": clean_numeric_value(row.get('(i)          From banks.1')),  # Second occurrence (renamed)
                    "fromOthers": clean_numeric_value(row.get('(ii)         From others.1'))  # Second occurrence (renamed)
                }
            },
            "byLocation": {
                "depositsOfBranchesInIndia": clean_numeric_value(row.get('3B.1.   Deposits of branches in India')),
                "depositsOfBranchesOutsideIndia": clean_numeric_value(row.get('3B.2.   Deposits of branches outside India'))
            }
        },
        "borrowings": {
            "total": clean_numeric_value(row.get('4. Borrowings')),
            "borrowingsInIndia": {
                "total": clean_numeric_value(row.get('4.1.      Borrowings in India')),
                "fromRBI": clean_numeric_value(row.get('(i)        From Reserve Bank of India')),
                "fromOtherBanks": clean_numeric_value(row.get('(ii)       From other banks')),
                "fromOtherInstitutions": clean_numeric_value(row.get('(iii)      From other institutions and agencies'))
            },
            "borrowingsOutsideIndia": clean_numeric_value(row.get('4.2.      Borrowings outside India')),
            "securedBorrowings": clean_numeric_value(row.get('Secured borrowings included in 4.'))
        },
        "otherLiabilitiesAndProvisions": {
            "total": clean_numeric_value(row.get('5. Other liabilities & provisions')),
            "billsPayable": clean_numeric_value(row.get('5.1.      Bills Payable')),
            "interOfficeAdjustments": clean_numeric_value(row.get('5.2.      Inter-office adjustments')),
            "interestAccrued": clean_numeric_value(row.get('5.3.      Interest accrued')),
            "subordinateDebt": clean_numeric_value(row.get('5.4.Subordinate debt')),
            "deferredTaxLiabilities": clean_numeric_value(row.get('5.5.      Deferred Tax Liabilities')),
            "others": clean_numeric_value(row.get('5.6.Others (including provisions)'))
        },
        "totalLiabilities": clean_numeric_value(row.get('Total Liabilities'))
    }


if __name__ == "__main__":
    # Test with all three banks
    for symbol in ['SBIN', 'HDFCBANK', 'ICICIBANK']:
        print(f"\nTesting Balance Sheet extraction for {symbol}...")
        try:
            data = extract_balance_sheet_data(symbol)
            print(f"✓ Successfully extracted balance sheet for {get_bank_config(symbol)['fullName']}")
            print(f"  Total Assets: {data['assets']['totalAssets']} {data['currency']}")
            print(f"  Total Liabilities: {data['liabilities']['totalLiabilities']} {data['currency']}")
            print(f"  Total Advances: {data['assets']['advances']['total']} {data['currency']}")
            print(f"  Total Deposits: {data['liabilities']['deposits']['total']} {data['currency']}")
        except Exception as e:
            print(f"✗ Error: {e}")
