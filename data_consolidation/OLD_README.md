# Bank Data Consolidation System

A comprehensive data consolidation system for extracting and consolidating financial data from multiple sources for Indian banks into a centralized MongoDB database.

## Overview

This system consolidates data from 6 different sources:
1. **CRISIL Rating Reports** - Loan facilities and borrower information
2. **Balance Sheets** - Assets and liabilities data from RBI
3. **Financial Ratios** - Key performance indicators
4. **Outstanding Advances** - Priority sector lending data
5. **Shareholding Patterns** - XBRL format ownership structure
6. **Sector-wise Advances** - Detailed sector lending breakdown

## Current Scope

The system currently supports 3 major Indian banks:
- **State Bank of India** (SBIN)
- **HDFC Bank Limited** (HDFCBANK)
- **ICICI Bank Limited** (ICICIBANK)

Financial Year: FY25 (ending March 31, 2025)

## Installation

### Prerequisites

- Python 3.8 or higher
- MongoDB Atlas account (or local MongoDB instance)
- Environment variables configured

### Setup

1. Install required packages:
```bash
cd data_consolidation
pip install -r requirements.txt
```

2. Configure environment variables:
Create a `.env` file in the root directory:
```env
db_cluster_link=mongodb+srv://username:password@cluster.mongodb.net/
```

## Usage
### Run Full Consolidation

Process all configured banks:
```bash
python main.py --all
```

Process specific banks:
```bash
python main.py --banks SBIN HDFCBANK ICICIBANK
```

Process without MongoDB upload (testing):
```bash
python main.py --banks HDFCBANK --no-db
```

Interactive mode:
```bash
python main.py
```

### Test Individual Tasks

Each task can be tested independently:

```bash
# Test CRISIL data extraction
python scripts/task1_crisil_filter.py

# Test Balance Sheet extraction
python scripts/task2_balance_sheet.py

# Test Ratios extraction
python scripts/task3_ratios.py

# Test Outstanding Advances extraction
python scripts/task4_outstanding_advances.py

# Test Shareholding Pattern extraction
python scripts/task5_shareholding_xbrl.py

# Test Sector-wise Advances extraction
python scripts/task6_sector_advances.py
```

## Project Structure

```
data_consolidation/
├── main.py                     # Main consolidation program
├── requirements.txt            # Python dependencies
├── scripts/
│   ├── config.py              # Configuration and bank mappings
│   ├── task1_crisil_filter.py # CRISIL loan data extraction
│   ├── task2_balance_sheet.py # Balance sheet extraction
│   ├── task3_ratios.py        # Financial ratios extraction
│   ├── task4_outstanding_advances.py  # Outstanding advances
│   ├── task5_shareholding_xbrl.py     # Shareholding pattern (XBRL)
│   └── task6_sector_advances.py       # Sector-wise advances
├── data/
│   ├── bank/
│   │   ├── balance_sheet/     # Excel/HTML balance sheet files
│   │   ├── ratios/            # Excel/HTML ratios files
│   │   ├── outstanding_advances/ # Excel/HTML advances files
│   │   ├── shp/               # XBRL shareholding pattern files
│   │   └── swa/               # JSON sector-wise advances files
│   └── company/
│       └── crisil_reports/    # CRISIL rating reports JSON
└── taxonomies/                # XBRL taxonomy files
```

## Output Data Structure

The consolidated data for each bank is stored in MongoDB with the following structure:

```json
{
  "bankSymbol": "HDFCBANK",
  "bankName": "HDFC Bank Limited",
  "dataYear": 2025,
  "lastUpdated": "2026-02-16T00:00:00.000Z",
  
  "loans": {
    "totalCompanies": 1247,
    "totalExposure": 306931.51,
    "companies": [
      {
        "companyName": "...",
        "companyCode": "...",
        "facilities": [...],
        "totalExposure": 0.0
      }
    ]
  },
  
  "balanceSheet": {
    "assets": {
      "cash": {...},
      "investments": {...},
      "advances": {...},
      "fixedAssets": {...},
      "otherAssets": {...},
      "totalAssets": 0.0
    },
    "liabilities": {
      "capital": 0.0,
      "reservesAndSurplus": {...},
      "deposits": {...},
      "borrowings": {...},
      "otherLiabilitiesAndProvisions": {...},
      "totalLiabilities": 0.0
    },
    "year": 2025,
    "currency": "INR Crore"
  },
  
  "financialRatios": {
    "liquidityAndDeployment": {...},
    "depositMetrics": {...},
    "advancesComposition": {...},
    "profitabilityMetrics": {...},
    "capitalAdequacy": {...},
    "assetQuality": {...}
  },
  
  "outstandingAdvances": {
    "bankName": "...",
    "year": 2025,
    "currency": "INR Lakh",
    ...
  },
  
  "shareholdingPattern": {
    "bankName": "...",
    "year": 2025,
    "categories": {...},
    "topShareholders": [...]
  },
  
  "sectorWiseAdvances": {
    "bankName": "...",
    "yearEnded": "March 31, 2025",
    "currency": "INR Crore",
    "sector": {...}
  }
}
```

## MongoDB Configuration

- **Database**: `financial_knowledge_graph`
- **Collection**: `banks`
- **Index**: `bankSymbol` (unique)

The system uses upsert operations, so running the consolidation multiple times will update existing records rather than creating duplicates.

## Extending the System

### Adding New Banks

1. Add bank configuration in `scripts/config.py`:
```python
"NEWBANK": {
    "symbol": "NEWBANK",
    "fullName": "New Bank Limited",
    "excelName": "NEW BANK LIMITED",  # As it appears in Excel files
    "crisilVariations": ["New Bank Limited", "New Bank Ltd"]
}
```

2. Ensure data files exist in the appropriate directories

### Adding New Data Sources

1. Create a new task script in `scripts/` folder
2. Follow the pattern of existing task scripts
3. Update `main.py` to incorporate the new task
4. Update `config.py` if new paths are needed

## Error Handling

The system is designed to continue processing even if individual tasks fail:
- Each task is wrapped in try-except blocks
- Errors are logged and stored in the output
- The consolidation summary shows which banks succeeded/failed

## Notes

- Excel file parsing includes handling for duplicate column names
- XBRL parsing uses namespace-aware XML parsing
- Bank name matching handles various formats (uppercase, punctuation variations)
- All monetary values are preserved with original units (Crore/Lakh as specified)

## Dependencies

Key dependencies:
- `pandas` - Excel/CSV data processing
- `openpyxl` - Excel file reading
- `pymongo` - MongoDB operations
- `python-dotenv` - Environment variable management
- `lxml` - XML/XBRL parsing

## License

This project is part of the Financial Knowledge Graph initiative.
