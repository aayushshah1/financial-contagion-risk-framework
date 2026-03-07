"""
Task 3: Extract Financial Ratios Data
Reads Excel file and extracts financial ratios for specified banks
"""
import pandas as pd
from typing import Dict
from config import DATA_PATHS, get_bank_config, TARGET_YEAR, YEAR_LABEL


def clean_ratio_value(value):
    """Convert ratio value to float, handling None, '-', and other non-numeric values"""
    if pd.isna(value) or value in ['-', '', 'NA', 'na', 'nan']:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def extract_ratios_data(bank_symbol: str) -> Dict:
    """
    Extract financial ratios for a specific bank
    
    Args:
        bank_symbol: Bank symbol (e.g., 'HDFCBANK', 'SBIN', 'ICICIBANK')
        
    Returns:
        Dictionary with all financial ratios
    """
    bank_config = get_bank_config(bank_symbol)
    if not bank_config:
        raise ValueError(f"Unknown bank symbol: {bank_symbol}")
    
    excel_name = bank_config["excelName"]
    
    # Read Ratios sheet
    try:
        ratios_df = pd.read_excel(DATA_PATHS["ratios"], sheet_name="Report 1")
    except FileNotFoundError:
        raise FileNotFoundError(f"Ratios file not found at {DATA_PATHS['ratios']}")
    except Exception as e:
        raise ValueError(f"Error reading Ratios sheet: {e}")
    
    # Clean dataframe
    ratios_clean = ratios_df.iloc[5:].copy()
    ratios_clean.columns = ratios_clean.iloc[0]
    ratios_clean = ratios_clean.iloc[1:].reset_index(drop=True)
    ratios_clean['Year'] = ratios_clean['Year'].ffill()
    ratios_clean = ratios_clean.dropna(axis=1, how='all')
    
    # Filter for our target bank and year
    ratios_clean['Year_str'] = ratios_clean['Year'].astype(str).str.strip()
    ratios_clean['Bank_clean'] = ratios_clean['Bank'].astype(str).str.strip()
    
    ratios_bank = ratios_clean[
        (ratios_clean['Bank_clean'] == excel_name) & 
        (ratios_clean['Year_str'] == YEAR_LABEL)
    ]
    
    if ratios_bank.empty:
        raise ValueError(f"No ratios data found for {excel_name} in year {YEAR_LABEL}")
    
    # Extract ratios data
    row = ratios_bank.iloc[0]
    
    ratios_data = {
        "liquidityAndDeployment": {
            "cashDepositRatio": clean_ratio_value(row.get('1.  Cash - Deposit Ratio')),
            "creditDepositRatio": clean_ratio_value(row.get('2.  Credit - Deposit Ratio')),
            "investmentDepositRatio": clean_ratio_value(row.get('3.  Investment - Deposit Ratio')),
            "creditPlusInvestmentDepositRatio": clean_ratio_value(row.get('4.  (Credit + Investment) - Deposit Ratio'))
        },
        "depositMetrics": {
            "depositsToTotalLiabilities": clean_ratio_value(row.get('5.   Ratio of deposits to total liabilities')),
            "demandAndSavingsToTotalDeposits": clean_ratio_value(row.get('6.   Ratio of demand & savings bank deposits to total deposits'))
        },
        "advancesComposition": {
            "prioritySectorToTotalAdvances": clean_ratio_value(row.get('7.   Ratio of priority sector advances to total advances')),
            "termLoansToTotalAdvances": clean_ratio_value(row.get('8.   Ratio of term loans to total advances')),
            "securedAdvancesToTotalAdvances": clean_ratio_value(row.get('9.   Ratio of secured advances to total advances'))
        },
        "investmentComposition": {
            "nonApprovedSecuritiesToTotalInvestments": clean_ratio_value(row.get('10.  Ratio of investments in non-approved securities to total investments'))
        },
        "incomeMetrics": {
            "interestIncomeToTotalAssets": clean_ratio_value(row.get('11.  Ratio of interest income to total assets')),
            "netInterestMargin": clean_ratio_value(row.get('12.  Ratio of net interest income to total assets (Net Interest Margin)')),
            "nonInterestIncomeToTotalAssets": clean_ratio_value(row.get('13.  Ratio of non-interest income to total assets'))
        },
        "costMetrics": {
            "intermediationCostToTotalAssets": clean_ratio_value(row.get('14.  Ratio of intermediation cost to total assets')),
            "wageBillsToIntermediationCost": clean_ratio_value(row.get('15.  Ratio of wage bills to intermediation cost')),
            "wageBillsToTotalExpense": clean_ratio_value(row.get('16.  Ratio of wage bills to total expense')),
            "wageBillsToTotalIncome": clean_ratio_value(row.get('17.  Ratio of wage bills to total income')),
            "burdenToTotalAssets": clean_ratio_value(row.get('18.  Ratio of burden to total assets')),
            "burdenToInterestIncome": clean_ratio_value(row.get('19.  Ratio of burden to interest income'))
        },
        "profitabilityMetrics": {
            "operatingProfitsToTotalAssets": clean_ratio_value(row.get('20.  Ratio of operating profits to total assets')),
            "returnOnAssets": clean_ratio_value(row.get('21.  Return on assets')),
            "returnOnEquity": clean_ratio_value(row.get('22.  Return on equity'))
        },
        "costOfFunds": {
            "costOfDeposits": clean_ratio_value(row.get('23.  Cost of deposits')),
            "costOfBorrowings": clean_ratio_value(row.get('24.  Cost of borrowings')),
            "costOfFunds": clean_ratio_value(row.get('25.  Cost of funds'))
        },
        "returnMetrics": {
            "returnOnAdvances": clean_ratio_value(row.get('26.  Return on advances')),
            "returnOnInvestments": clean_ratio_value(row.get('27.  Return on investments')),
            "returnOnAdvancesAdjusted": clean_ratio_value(row.get('28.  Return on advances adjusted to cost of funds')),
            "returnOnInvestmentsAdjusted": clean_ratio_value(row.get('29.  Return on investments adjusted to cost of funds'))
        },
        "productivity": {
            "businessPerEmployee": clean_ratio_value(row.get('30.  Business per employee(in Rupees Lakh)')),
            "profitPerEmployee": clean_ratio_value(row.get('31.  Profit per employee (in Rupees Lakh)'))
        },
        "capitalAdequacy": {
            "totalCAR": clean_ratio_value(row.get('32.  Capital adequacy ratio')),
            "tier1CAR": clean_ratio_value(row.get('33. Capital adequacy ratio - Tier I')),
            "tier2CAR": clean_ratio_value(row.get('34. Capital adequacy ratio - Tier II'))
        },
        "assetQuality": {
            "netNPAToNetAdvances": clean_ratio_value(row.get('35.  Ratio of net NPA To net advances'))
        },
        "year": TARGET_YEAR,
        "unit": "Percent (except productivity metrics which are in Rupees Lakh)"
    }
    
    return ratios_data


if __name__ == "__main__":
    # Test with all three banks
    for symbol in ['SBIN', 'HDFCBANK', 'ICICIBANK']:
        print(f"\nTesting Ratios extraction for {symbol}...")
        try:
            data = extract_ratios_data(symbol)
            print(f"✓ Successfully extracted ratios for {get_bank_config(symbol)['fullName']}")
            print(f"  Credit-Deposit Ratio: {data['liquidityAndDeployment']['creditDepositRatio']}%")
            print(f"  Return on Assets: {data['profitabilityMetrics']['returnOnAssets']}%")
            print(f"  Return on Equity: {data['profitabilityMetrics']['returnOnEquity']}%")
            print(f"  Capital Adequacy Ratio: {data['capitalAdequacy']['totalCAR']}%")
            print(f"  Net NPA to Net Advances: {data['assetQuality']['netNPAToNetAdvances']}%")
        except Exception as e:
            print(f"✗ Error: {e}")
