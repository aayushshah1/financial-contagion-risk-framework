# Knowledge Graph for Financial Instituions - Banks

## Description
This repository will soon be a large repository, for creating a knowledge graph of different Indian Banks, NBFCs and Compnaies. The aim is to map the exposure of each entity to the other, so that the risk can be measured between them.

## Completed Stages

## Current Status: Data Consolidation

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

#### Current Issues:
As I mentioned that we are in data consolidation stage. This involves cleaning and filtering data from all these sources and creating a central database.

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

#### Desired Tasks (COMPLETED)
I need you to create python scripts to extract and consolidate data into a single mongodb collection. The collection should be bank-wise. These scripts should be reusable and scalable. For now there are only 3 banks, but soon there'll be more.

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
##### Task 1: Filtering CRISIL Data bank-wise (DONE)
##### Task 2: Extracting Balance-Sheet data bank-wise (DONE)
##### Task 3: Extracting Ratio Data bank-wise (DONE)
##### Task 4: Extracting Outstanding Advances data bank-wise (DONE)
##### Task 5: Converting XBRL Data of Shareholding to JSON (DONE)
##### Task 6: Pulling Sector-wise advances data from the folder (DONE)

#### Structure for scripts:
Create six (or more) python scripts for the tasks. The scripts should be such that it can be called by a main program. All scripts will take in the bank name, and output the data that is required. 

Example: CRISIL Data Script
Input: HDFC Bank
Output: List of all companies that have taken loans from HDFC bank

A main program at `data_consolidation` will take user input for the bank symbols to extract data for and call the scripts one by one, consolidating data and will push it into the mongo db

#### Tech Stack
- Programing Language: Python
- Backend: MongoDB
- Other Libraries: Arelle, Mongo, and others

#### Approach
- Do not rush into coding. 
- First understand the broad context of the project, and what is being requested from you
- Second, go step by step, one task at a time
- Third, understand the finer tasks of the project, and most importantly, the format of the data. Excel and XBRL are challenging data formats
- Fourth, Make a plan for each task, and ask me for details, clarifications, and most importantly structure of data if you can't understand it. (Like asking for image format data of the Excel Tables)
- You'll execute tasks one by one. Understand -> Plan -> Ask -> Code -> Repeat for next task