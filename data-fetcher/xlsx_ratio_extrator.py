import pandas as pd
import glob
import re
import json
from pymongo import MongoClient
import numpy as np
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv(dotenv_path=os.path.join(
    os.path.dirname(os.path.dirname(__file__)), '.env'))


def standardize_metric(m):
    """Normalize column texts safely using both substring and strict exact matches."""
    m = str(m)
    # Strip symbols and extra spaces
    m_clean = re.sub(r'[\*\#\n]', ' ', m)
    m_clean = re.sub(r'\s+', ' ', m_clean).strip().lower()

    # 1. Complex Name Variations Mapping (Substring matches)
    if 'business per employee' in m_clean:
        return 'Business Per Employee'
    if 'profit per employee' in m_clean:
        return 'Profit Per Employee'
    if 'capital adequacy ratio' in m_clean or 'car' in m_clean:
        return 'Capital Adequacy Ratio (Basel-III)'
    if 'operating' in m_clean and 'exp' in m_clean and '%' in m_clean:
        return 'Operating Expenses as % to Total Expenses'
    if 'provision' in m_clean and 'contingenc' in m_clean:
        return 'Provisions & Contingencies'
    if 'provision' in m_clean and 'coverage' in m_clean:
        return 'Provision Coverage Ratio (%)'
    if 'return on assets' in m_clean:
        return 'Return on Assets (%)'
    if 'spread' in m_clean and 'asset' in m_clean:
        return 'Spread as % of Total Assets'
    if 'net npa as %' in m_clean:
        return 'Net NPA as % to Net Advances'
    if 'total expenditure' in m_clean:
        return 'Total Expenditure'

    # 2. Strict Exact Matches (Prevents collapsing unrelated columns)
    if m_clean == 'gross npa':
        return 'Gross NPA'
    if m_clean == 'net npa':
        return 'Net NPA'
    if m_clean == 'operating profit':
        return 'Operating Profit'
    if m_clean == 'net profit':
        return 'Net Profit'
    if m_clean == 'operating expenses':
        return 'Operating Expenses'
    if m_clean == 'interest expended':
        return 'Interest Expended'
    if m_clean == 'interest income':
        return 'Interest Income'
    if m_clean == 'other income':
        return 'Other Income'
    if m_clean == 'total income':
        return 'Total Income'
    if m_clean == 'total assets':
        return 'Total Assets'
    if m_clean == 'credit deposit ratio':
        return 'Credit Deposit Ratio'
    if m_clean == 'investment deposit ratio':
        return 'Investment Deposit Ratio'
    if m_clean == 'investments':
        return 'Investments'
    if m_clean == 'advances':
        return 'Advances'
    if m_clean == 'deposits':
        return 'Deposits'

    # 3. Fallback: Preserve all other unique metrics
    return m.strip().title()


def create_bank_dataframe(data_dir='./data/ratio_data_csv'):
    """Parses all sheets from CSVs and XLSX files dynamically into a wide DataFrame"""
    all_data = []

    # Look for both CSV and XLSX files. Use xxxxxxxxx for any local context overrides.
    csv_files = glob.glob(f'{data_dir}/*.csv')
    xlsx_files = glob.glob(f'{data_dir}/*.xlsx')
    files = csv_files + xlsx_files

    if not files:
        raise FileNotFoundError(
            f"No CSV or XLSX files found in {data_dir}. Please check the directory path.")

    print(f"Found {len(files)} file(s) to process.")

    for file in files:
        dfs = []
        # Process ALL sheets inside Excel files
        if file.endswith('.xlsx'):
            xls_dict = pd.read_excel(file, sheet_name=None, header=None)
            dfs = list(xls_dict.values())
        else:
            dfs = [pd.read_csv(file, header=None)]

        for df in dfs:
            main_header_idx = -1
            for i, row in df.iterrows():
                for val in row:
                    if str(val).lower().strip() in ['banks', 'name of the bank', 'name of bank']:
                        main_header_idx = i
                        break
                if main_header_idx != -1:
                    break

            if main_header_idx == -1:
                continue

            main_header = df.iloc[main_header_idx].ffill()
            sub_header = df.iloc[main_header_idx + 1]

            bank_col_idx = -1
            for i, val in enumerate(df.iloc[main_header_idx]):
                if str(val).lower().strip() in ['banks', 'name of the bank', 'name of bank']:
                    bank_col_idx = i
                    break

            if bank_col_idx == -1:
                continue

            for i in range(main_header_idx + 1, len(df)):
                row = df.iloc[i]

                # Check for completely empty rows to prevent indexing errors
                if pd.isna(row[bank_col_idx]):
                    continue

                bank_name = str(row[bank_col_idx]).strip()

                invalid_names = ['nan', 'none', '', 'old private sector banks', 'new private sector banks',
                                 'nationalised banks', 'state bank of india', 'private sector banks']
                if bank_name.lower() in invalid_names:
                    continue
                if 'total' in bank_name.lower() or 'average' in bank_name.lower() or 'median' in bank_name.lower():
                    continue

                for col_idx in range(bank_col_idx + 1, len(row)):
                    metric = str(main_header[col_idx]).strip()
                    if metric.lower() in ['nan', 'none', ''] or 'unnamed' in metric.lower():
                        continue

                    year = str(sub_header[col_idx]).strip()
                    year_match = re.search(r'202\d', year)
                    if not year_match:
                        continue

                    year_val = year_match.group()
                    val = row[col_idx]

                    if pd.isna(val) or str(val).strip() in ['-', 'NA', 'nan', 'c', '#', '*']:
                        continue

                    try:
                        val_float = float(str(val).replace(',', '').strip())
                    except ValueError:
                        val_float = str(val).replace(',', '').strip()

                    metric_clean = standardize_metric(metric)
                    all_data.append({
                        'Bank Name': bank_name,
                        'Metric': metric_clean,
                        'Year': year_val,
                        'Value': val_float
                    })

    if not all_data:
        raise ValueError(
            "No valid banking data extracted. Please check the formats.")

    df_all = pd.DataFrame(all_data)
    df_all['Bank Name'] = df_all['Bank Name'].str.replace(
        r'[\*\#]', '', regex=True).str.strip()
    df_all['Metric_Year'] = df_all['Metric'] + ' ' + df_all['Year']

    df_pivoted = df_all.pivot_table(
        index='Bank Name', columns='Metric_Year', values='Value', aggfunc='first').reset_index()
    return df_pivoted


def convert_to_nested_json(df):
    """Converts wide dataframe into per-bank nested year objects"""
    json_data = []
    df = df.replace([np.nan, np.inf, -np.inf], None)

    for _, row in df.iterrows():
        bank_doc = {"Bank Name": row["Bank Name"]}

        for col in df.columns:
            if col == "Bank Name":
                continue

            match = re.search(r'(.*)\s+(\d{4})$', col)
            if match:
                metric = match.group(1).strip()
                year = match.group(2)

                if year not in bank_doc:
                    bank_doc[year] = {}

                val = row[col]
                bank_doc[year][metric] = val

        json_data.append(bank_doc)
    return json_data


def push_to_mongo(json_data):
    """Inserts structured dictionary into MongoDB"""
    mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    mongo_db = os.getenv("MONGO_DB", "banking_analytics")
    mongo_collection = os.getenv("MONGO_COLLECTION", "performance_metrics")

    client = MongoClient(mongo_uri)
    db = client[mongo_db]
    collection = db[mongo_collection]

    collection.delete_many({})
    result = collection.insert_many(json_data)
    print(
        f"Successfully inserted {len(result.inserted_ids)} records into MongoDB.")


if __name__ == "__main__":
    import sys
    data_dir = sys.argv[1] if len(sys.argv) > 1 else './data/ratio_data_csv'

    print("1. Parsing CSV and XLSX files...")
    df_clean = create_bank_dataframe(data_dir)
    df_clean.to_csv("Normalized_Banks_Data.csv", index=False)

    print("2. Restructuring into nested JSON dictionary...")
    structured_json = convert_to_nested_json(df_clean)

    with open("Structured_Banks_Data.json", "w") as f:
        json.dump(structured_json, f, indent=4)

    print("3. Pushing to MongoDB...")
    push_to_mongo(structured_json)

    print("All tasks completed.")
