# Knowledge Graph for Financial Instituions - Banks

## Description
This repository will soon be a large repository, for creating a knowledge graph of different Indian Banks, NBFCs and Compnaies. The aim is to map the exposure of each entity to the other, so that the risk can be measured between them.

## Completed Stages

## Current Status: Prototype Knowledge Graph (prototype_kg)

Data consolidation is mostly complete for the initial test scope (SBI, HDFC Bank, ICICI Bank). The repository is now moving from raw data consolidation into the prototype knowledge-graph stage where consolidated bank records will be modeled as nodes and lending / exposure relationships will be represented as edges.

### Data Sources 
All the data is currently in `data_consolidation/data` folder.

```
data_consolidation/data
├───bank
│   ├───balance_sheet
│   │       assets.html
│   │       balance_sheet.xlsx
│   │       liabilities.html
│   │
│   ├───integrated_xbrl
│   │       integrated_HDFCBANK_2025-12-31.xml
│   │       integrated_ICICIBANK_2025-12-31.xml
│   │       integrated_SBIN_2025-12-31.xml
│   │
│   ├───outstanding_advances
│   │       outstanding_advances.html
│   │       outstanding_advances.xlsx
│   │
│   ├───ratios
│   │       ratios_all_banks.html
│   │       ratios_all_banks.xlsx
│   │
│   ├───shp
│   │       shp_HDFCBANK.xml
│   │       shp_ICICIBANK.xml
│   │       shp_SBIN.xml
│   │
│   └───swa
│           HDFCBANK_SWA.json
│           ICICIBANK_SWA.json
│           SBIN_SWA.json
│
└───company
    └───crisil_reports
            crisil_ratings.rating_reports.json
```

#### data_consolidation/data/bank
This contains 6 subfolders:
- balance_sheet: Contains 2 HTML files that has assets and liabilities of all Scheduled Commercial Banks (SCBs) in India. The Excel file (.xlsx) contains 2 worksheets, one containing assets and other liabilities. I have kept both HTML and Excel formats to compare which would be easiser to extract from using python
- integrated_xbrl: Contains XBRL format (Extensible Business Reporting Language) Integrated Filings of 3 Banks (SBI, HDFC, ICICI) of FY26 Q3. Integrated filings contains latest financial sheets (Balance Sheet, Income Statement, Cash Flows, and Related Party Transactions). In this, what I value the most is the Related Party Transactions data
- outstanding_advances: Outstanding advances of Indian SCBs to the priority sector in both Excel and HTML format
- ratios: Important Ratios of all Indian SCBs in both Excel and HTML format
- shp: Shareholding Pattern of 3 Indian Banks (SBI, HDFC, ICICI) in XBRL format
- swa: Sector-wise Advances of 3 Indian banks (SBI, HDFC, ICICI) in JSON format

#### data_consolidation/data/company
This currently contains only one subfolder:
- crisil_reports: Contains CRISIL Rating reports of 9000+ Entities (Banks, NBFCs, Companies) in JSON format (exported from MongoDB). Primarily this contains the lender facilities data that explains how much an entity has taken in loans and from which entity. This is the backbone of mapping. 

#### Current Issues / Notes:
The consolidated data is available under `data_consolidation/data`. Before building the prototype KG we should verify data completeness for each bank and ensure consistent identifiers (bankSymbol, companyCode) across sources.

##### Scope
As a test phase, I'm only considering 3 Banks: SBI, HDFC Bank, and ICICI bank

##### CRISIL Report Data
- I want to filter out data from this where there are Loans held by companies from the mentioned 3 banks. I'm attaching the structure of the data mentioned.

```json
{
  "_id": {
    "$oid": "69873b55ea997c930e1a49ff"
  },
  "companyCode": "ZCLC",
  "industryName": "",
  "ratingDate": "Jan 31, 2026",
  "heading": "ZCL Chemicals Limited-(Amalgamated):Issuer not cooperating, based on best-available information; Ratings continues to be ‘Crisil B/Stable/Crisil A4 Issuer not cooperating’",
  "companyName": "ZCL Chemicals Limited-(Amalgamated)",
  "ratingFileName": "https://www.crisilratings.com/mnt/winshare/Ratings/RatingList/RatingDocs/ZCLChemicalsLimited_Amalgamated_January 31_ 2026_RR_387132.html",
  "transDate": "Jan 31, 2026",
  "prId": "2182185",
  "showAbstarct": "0",
  "abstractTemp": "A",
  "processingStatus": "completed",
  "processedAt": {
    "$date": "2026-02-07T16:27:51.811Z"
  },
  "errorMessage": null,
  "instruments": [
    {
      "isin": "ISIN",
      "instrumentName": "Name Of Instrument",
      "allotmentDate": "Date Of Allotment",
      "couponRate": "Coupon Rate (%)",
      "maturityDate": "Maturity Date",
      "issueSize": null,
      "complexityLevel": "Complexity Levels",
      "rating": "Rating Outstanding with Outlook"
    },
    {
      "isin": "NA",
      "instrumentName": "Proposed Working Capital Facility",
      "allotmentDate": "NA",
      "couponRate": "NA",
      "maturityDate": "NA",
      "issueSize": 10,
      "complexityLevel": "NA",
      "rating": "Crisil B/Stable(Issuer Not Cooperating)"
    },
    {
      "isin": "NA",
      "instrumentName": "Working Capital Facility",
      "allotmentDate": "NA",
      "couponRate": "NA",
      "maturityDate": "NA",
      "issueSize": 40,
      "complexityLevel": "NA",
      "rating": "Crisil B/Stable(Issuer Not Cooperating)"
    },
    {
      "isin": "NA",
      "instrumentName": "Proposed Long Term Bank Loan Facility",
      "allotmentDate": "NA",
      "couponRate": "NA",
      "maturityDate": "NA",
      "issueSize": 46,
      "complexityLevel": "NA",
      "rating": "Crisil B/Stable(Issuer Not Cooperating)"
    },
    {
      "isin": "NA",
      "instrumentName": "Proposed Short Term Bank Loan Facility",
      "allotmentDate": "NA",
      "couponRate": "NA",
      "maturityDate": "NA",
      "issueSize": 1,
      "complexityLevel": "NA",
      "rating": "Crisil A4(Issuer Not Cooperating)"
    }
  ],
  "bankFacilities": [
    {
      "facility": "Proposed Long Term Bank Loan Facility",
      "amount": 46,
      "lenderName": "Not Applicable",
      "rating": "Crisil B /Stable(Issuer Not Cooperating)*"
    },
    {
      "facility": "Proposed Short Term Bank Loan Facility",
      "amount": 1,
      "lenderName": "Not Applicable",
      "rating": "Crisil A4 (Issuer Not Cooperating)*"
    },
    {
      "facility": "Proposed Working Capital Facility",
      "amount": 10,
      "lenderName": "Citibank N. A.",
      "rating": "Crisil B /Stable(Issuer Not Cooperating)*"
    },
    {
      "facility": "Working Capital Facility",
      "amount": 15,
      "lenderName": "HDFC Bank Limited",
      "rating": "Crisil B /Stable(Issuer Not Cooperating)*"
    },
    {
      "facility": "Working Capital Facility",
      "amount": 15,
      "lenderName": "Citibank N. A.",
      "rating": "Crisil B /Stable(Issuer Not Cooperating)*"
    },
    {
      "facility": "Working Capital Facility",
      "amount": 10,
      "lenderName": "State Bank of India",
      "rating": "Crisil B /Stable(Issuer Not Cooperating)*"
    }
  ],
  "createdAt": {
    "$date": "2026-02-07T13:17:09.180Z"
  },
  "updatedAt": {
    "$date": "2026-02-07T16:27:51.811Z"
  }
},
```
As you can see here, under `bankFacilities`, HDFC is mentioned as a lender. The first task with CRISIL Reports will be to filter entities like such, and extract their company name and company code.

##### Bank Data
- For Balance Sheet, Ratios, and Outstanding Advances both Excel and HTML is given. I think, Excel will be easier to extract from as it is more ordered. Although you can also use HTML to explore and understand the data. I'll need you to extract data for the 3 banks I've mentioned.
- Shareholding Pattern: This data is in xbrl format. I have have placed taxonomies for xbrl in the `data_consolidation/taxonomies/shareholding_pattern. You may use that taxonomy and arelle library in python to extract data from it.

```
├───.github
└───data_consolidation
    ├───data
    │   ├───bank
    │   │   ├───balance_sheet
    │   │   ├───integrated_xbrl
    │   │   ├───outstanding_advances     
    │   │   ├───ratios
    │   │   ├───shp
    │   │   └───swa
    │   └───company
    │       └───crisil_reports
    └───taxonomies
        ├───annual_report
        │   ├───in-ca
        │   │   ├───Calculation
        │   │   ├───Definition
        │   │   └───Presentation
        │   └───ind-as
        │       ├───Calculation
        │       ├───Definition
        │       ├───Formula
        │       └───Presentation
        ├───integrated_filing
        │   ├───core
        │   ├───IntegratedFinance_IndAS
        │   └───META-INF
        └───shareholding_pattern
            └───SHP Taxonomy_2025-10-31
                └───META-INF
```                
- Sector-wise advances are already in JSON format, so it shouldn't be much of an Issue.

#### Desired Tasks (COMPLETED / In-repo)
The extraction and consolidation scripts live in `data_consolidation/scripts`. They are intended to extract and normalize source files and prepare bank-wise documents that can be inserted into MongoDB. The scripts are designed to be reusable and scalable as more banks and data sources are added.

```json
{
    "bankName": "HDFC Bank Limited",
    "bankSymbol": "HDFCBANK",
    ... #Other Bank Details,
    "assets": {
        2025: {
            ... #list assets with bifucations and values
        }
    },
    "liabilities": {
        2025: {
            ... #list assets with bifucations and values
        }
    },
    "shareholdingPattern": {...},
    "sectorWiseAdvances": {...},
    "loans": {#list names of companies}
    .... and so on
}
```
##### Tasks (current scripts in `data_consolidation/scripts`)
- Task 1: `task1_crisil_filter.py` — Filter CRISIL reports to find companies with facilities from target banks (done)
- Task 2: `task2_balance_sheet.py` — Extract bank balance-sheet data from Excel/HTML (done)
- Task 3: `task3_ratios.py` — Extract ratio data for banks (done)
- Task 4: `task4_outstanding_advances.py` — Extract outstanding advances (done)
- Task 5: `task5_shareholding_xbrl.py` — Convert shareholding XBRL to JSON (done)
- Task 6: `task6_sector_advances.py` — Load sector-wise advances (done)
- Task 7: `task7_related_party_transactions.py` — Extract related-party transactions from integrated XBRL (new)
- Task 8: `task8_nic_sector_mapping.py` — Map NIC codes / sector taxonomy for companies (new)
- Task 9: `task9_basel.py` — Basel / regulatory calculations and mappings (new)

#### Structure for scripts and next-stage flow:
- The extraction scripts are placed in `data_consolidation/scripts` and are designed to be callable from a coordinator (already present as `data_consolidation/main.py`).
- Script contract: each script accepts a `bankSymbol` or `bankName` argument and returns a Python dict representing the extracted data for that bank (or writes intermediate JSON to `data_consolidation/data/outputs`).
- The coordinator (`data_consolidation/main.py`) should orchestrate the scripts in sequence and upsert the consolidated bank document into MongoDB as a single bank-wise record with fields like `bankName`, `bankSymbol`, `assets`, `liabilities`, `shareholdingPattern`, `sectorWiseAdvances`, `loans`, `relatedPartyTransactions`, etc.

Next stage (prototype_kg):
- Build a lightweight graph model from the consolidated bank documents (nodes: banks, companies; edges: lending exposure, related-party links, shareholding stakes).
- Create a minimal prototype in `prototype_kg/` that can load consolidated records from MongoDB (or JSON exports) and produce a simple graph (e.g., NetworkX or Neo4j-compatible export) for visualization and analysis.
- Implement simple queries to compute direct exposures and two-hop exposures between banks and corporates.

#### Tech Stack
- Programming Language: Python
- Backend: MongoDB (consolidated bank collection)
- Optional graph tools for prototype: NetworkX, PyVis, or Neo4j (export)
- XBRL tooling: Arelle or other XBRL parser for `integrated_xbrl` and `shp`

#### Approach (prototype transition)
- Verify consolidated bank documents exist and are complete for the 3 test banks.
- Add/confirm `relatedPartyTransactions` extraction (see `task7_related_party_transactions.py`).
- Produce consolidated JSON exports and load them into a simple graph prototype in `prototype_kg/`.
- Iterate: refine entity resolution (companyCode, lenderName normalization), then recompute exposures.