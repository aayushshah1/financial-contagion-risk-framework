# V1 Prototype codebase

This part of the repository is the inital prototype that was driven by and built by  [@snehil-sinha](https://www.github.com/nex7-7)

A research-grade system that builds a **Knowledge Graph** of major Indian banks, NBFCs, and corporates to map inter-entity credit exposure and measure systemic risk. The project ingests data from multiple regulatory and commercial sources, consolidates it into MongoDB, and models it as a property graph in Neo4j.

---

## Table of Contents

- [Project Overview](#project-overview)
- [Architecture](#architecture)
- [Repository Structure](#repository-structure)
- [Modules](#modules)
  - [data_consolidation](#data_consolidation)
  - [data_analysis](#data_analysis)
  - [prototype_kg](#prototype_kg)
- [Data Sources](#data-sources)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Environment Variables](#environment-variables)
- [Usage](#usage)
- [Knowledge Graph Schema](#knowledge-graph-schema)
- [Tech Stack](#tech-stack)
- [Scope & Roadmap](#scope--roadmap)

---

## Project Overview

The goal of this project is to quantify **credit exposure** between Indian financial entities. By combining:

- Loan facilities listed in **CRISIL rating reports** (9 000+ entities)
- **Balance sheets**, **financial ratios**, and **outstanding advances** of Scheduled Commercial Banks (SCBs)
- **Shareholding patterns** and **related-party transactions** from XBRL filings
- **Sector-wise advances** and **Basel regulatory** data

…we construct a graph where:

- **Nodes** represent banks, companies, industries, and shareholders
- **Edges** represent lending relationships, shareholding stakes, related-party links, and sector/industry classification

The initial test scope covers three banks: **SBI**, **HDFC Bank**, and **ICICI Bank**.

---

## Architecture

```
Raw Data Sources
      │
      ▼
data_consolidation/          ← Extract, normalize, and upsert into MongoDB
      │
      ▼
MongoDB  (financial_kg DB)
      │
      ▼
prototype_kg/                ← Load from MongoDB → build Neo4j property graph
      │
      ▼
Neo4j AuraDB                 ← Query exposures, two-hop paths, risk metrics
      │
      ▼
data_analysis/               ← Jupyter notebooks for EDA, reconciliation, outputs
```

---

## Repository Structure

```
Capstone/
├── README.md                           ← This file
├── requirements.txt                    ← Consolidated dependencies (all modules)
│
├── data_consolidation/                 ← Stage 1: Data ingestion & consolidation
│   ├── main.py                         ← Orchestrator (run all tasks / by bank)
│   ├── bank_consolidation.py
│   ├── README.md                       ← Module-level documentation
│   ├── scripts/
│   │   ├── bank/
│   │   │   ├── config.py               ← Bank registry & path config
│   │   │   ├── task1_crisil_filter.py  ← CRISIL loan facilities extraction
│   │   │   ├── task2_balance_sheet.py  ← Balance sheet (Excel/HTML)
│   │   │   ├── task3_ratios.py         ← Financial ratios
│   │   │   ├── task4_outstanding_advances.py
│   │   │   ├── task5_shareholding_xbrl.py
│   │   │   ├── task6_sector_advances.py
│   │   │   ├── task7_related_party_transactions.py
│   │   │   ├── task8_nic_sector_mapping.py
│   │   │   └── task9_basel.py
│   │   └── company/
│   ├── data/
│   │   ├── bank/
│   │   │   ├── balance_sheet/          ← Excel & HTML balance sheets (all SCBs)
│   │   │   ├── integrated_xbrl/        ← XBRL integrated filings (FY26 Q3)
│   │   │   ├── outstanding_advances/   ← Priority sector advances
│   │   │   ├── ratios/                 ← Key ratio files
│   │   │   ├── shp/                    ← Shareholding pattern XBRL
│   │   │   └── swa/                    ← Sector-wise advances JSON
│   │   └── company/
│   │       └── crisil_reports/         ← CRISIL rating reports (9 000+ entities)
│   └── taxonomies/                     ← XBRL taxonomy files
│       ├── annual_report/
│       ├── integrated_filing/
│       └── shareholding_pattern/
│
├── data_analysis/                      ← Stage 2: Exploratory analysis & QA
│   ├── analysis_crisil_bank_facilities.ipynb
│   ├── analysis_mca_records.ipynb
│   ├── scripts/
│   │   ├── fix_json_encoding.py
│   │   ├── push_mongo.py
│   │   └── task_assign_dummy_cin.py
│   └── outputs/                        ← Derived CSVs/JSONs from analysis
│
└── prototype_kg/                       ← Stage 3: Knowledge Graph (Neo4j)
    ├── config.py                       ← Neo4j + MongoDB connection settings
    ├── loader.py                       ← Load consolidated docs → Neo4j
    ├── schema.cypher                   ← Constraints & indexes DDL
    ├── nodes/
    │   ├── bank_node.py
    │   ├── company_node.py
    │   ├── industry_node.py
    │   ├── sector_node.py
    │   └── shareholder_node.py
    ├── relationships/
    │   ├── lends_to.py                 ← LENDS_TO (bank → company)
    │   ├── belongs_to.py               ← BELONGS_TO (company → sector/industry)
    │   ├── shareholder_of.py           ← SHAREHOLDER_OF
    │   ├── subsidiary_of.py            ← SUBSIDIARY_OF
    │   ├── related_party.py            ← RELATED_PARTY
    │   └── priority_exposure.py        ← PRIORITY_SECTOR_EXPOSURE
    ├── resolution/
    │   └── entity_resolver.py          ← Fuzzy entity resolution across sources
    └── queries/
        ├── interesting_queries.cypher
        └── run_queries.py
```

---

## Modules

### data_consolidation

Extracts and normalizes data from all raw sources and upserts bank-wise documents into MongoDB.

Each task script (`task1_` … `task9_`) accepts a `bankSymbol` and returns a Python dict. The orchestrator (`main.py`) calls them in sequence and writes a single consolidated document per bank:

```json
{
  "bankSymbol": "HDFCBANK",
  "bankName": "HDFC Bank Limited",
  "dataYear": 2025,
  "loans": { "totalCompanies": 1247, "totalExposure": 306931.51, "companies": [...] },
  "balanceSheet": { "assets": {...}, "liabilities": {...} },
  "financialRatios": {...},
  "outstandingAdvances": {...},
  "shareholdingPattern": {...},
  "sectorWiseAdvances": {...},
  "relatedPartyTransactions": {...}
}
```

**MongoDB target:** `financial_kg` database → `banks` collection (upsert on `bankSymbol`).

Run all banks:

```bash
python data_consolidation/main.py --all
```

Run specific banks without uploading to MongoDB:

```bash
python data_consolidation/main.py --banks SBIN HDFCBANK --no-db
```

---

### data_analysis

Jupyter notebooks for exploratory data analysis, QA, and reconciliation:

| Notebook                                | Purpose                                                                      |
| --------------------------------------- | ---------------------------------------------------------------------------- |
| `analysis_crisil_bank_facilities.ipynb` | Analyse CRISIL loan facility distributions, lender coverage, exposure sizing |
| `analysis_mca_records.ipynb`            | MCA company registry reconciliation with CRISIL entity names                 |

Outputs (CSVs / JSONs) are written to `data_analysis/outputs/`.

---

### prototype_kg

Builds the Neo4j property graph from consolidated MongoDB documents.

1. **Load** consolidated bank and company documents from MongoDB (`loader.py`)
2. **Upsert nodes** — Bank, Company, Industry, Sector, Shareholder
3. **Upsert relationships** — `LENDS_TO`, `BELONGS_TO`, `SHAREHOLDER_OF`, `SUBSIDIARY_OF`, `RELATED_PARTY`, `PRIORITY_SECTOR_EXPOSURE`
4. **Resolve entities** — fuzzy-match lender names and company codes across sources (`resolution/entity_resolver.py`)
5. **Query** — run Cypher queries to compute direct and two-hop exposures (`queries/`)

Apply schema constraints before loading:

```bash
# Run schema.cypher against your Neo4j instance once
cypher-shell -u neo4j -p <password> -f prototype_kg/schema.cypher
```

Load graph:

```bash
python prototype_kg/loader.py
```

---

## Data Sources

| Source                     | Format                | Coverage                   | Key Fields Used                                       |
| -------------------------- | --------------------- | -------------------------- | ----------------------------------------------------- |
| CRISIL Rating Reports      | JSON (MongoDB export) | 9 000+ entities            | `bankFacilities` → lender name, amount, facility type |
| RBI Balance Sheet          | Excel / HTML          | All Indian SCBs            | Assets, liabilities by category                       |
| RBI Financial Ratios       | Excel / HTML          | All Indian SCBs            | CAR, NPA, ROA, CASA, etc.                             |
| RBI Outstanding Advances   | Excel / HTML          | All Indian SCBs            | Priority-sector breakdowns                            |
| XBRL Integrated Filings    | XML (XBRL)            | SBI, HDFC, ICICI (FY26 Q3) | Related-party transactions                            |
| XBRL Shareholding Pattern  | XML (XBRL)            | SBI, HDFC, ICICI           | Promoter / institutional / public stakes              |
| Sector-wise Advances (SWA) | JSON                  | SBI, HDFC, ICICI           | Industry-level lending breakdown                      |
| Basel Disclosures          | JSON                  | HDFC, ICICI                | Capital adequacy, credit risk weights                 |

---

## Getting Started

### Prerequisites

- Python **3.10+**
- **MongoDB Atlas** cluster (or local `mongod`)
- **Neo4j AuraDB** instance (or local Neo4j 5.x)
- Arelle XBRL parser (installed via `arelle-release` pip package)

### Installation

```bash
# Clone the repository
git clone https://github.com/<your-username>/Capstone.git
cd Capstone

# Install all dependencies
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file in the project root:

```env
# MongoDB
db_cluster_link=mongodb+srv://<user>:<password>@<cluster>.mongodb.net/

# Neo4j AuraDB
NEO4J_URI=neo4j+s://<instance-id>.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=<your-neo4j-password>
```

---

## Usage

### Full pipeline (data → MongoDB → Neo4j)

```bash
# Step 1 — Consolidate all 3 banks into MongoDB
python data_consolidation/main.py --all

# Step 2 — Load consolidated data into Neo4j
python prototype_kg/loader.py

# Step 3 — Run example exposure queries
python prototype_kg/queries/run_queries.py
```

### Individual task scripts

```bash
python data_consolidation/scripts/bank/task1_crisil_filter.py
python data_consolidation/scripts/bank/task2_balance_sheet.py
python data_consolidation/scripts/bank/task3_ratios.py
python data_consolidation/scripts/bank/task4_outstanding_advances.py
python data_consolidation/scripts/bank/task5_shareholding_xbrl.py
python data_consolidation/scripts/bank/task6_sector_advances.py
```

---

## Knowledge Graph Schema

```
(Bank)        -[:LENDS_TO {amount, facility, rating}]->    (Company)
(Bank)        -[:LENDS_TO {amount, facility, rating}]->    (Bank)
(Company)     -[:BELONGS_TO]->                             (Sector)
(Sector)      -[:BELONGS_TO]->                             (Industry)
(Shareholder) -[:SHAREHOLDER_OF {percentage, category}]->  (Bank)
(Company)     -[:SUBSIDIARY_OF]->                          (Company)
(Company)     -[:RELATED_PARTY {transactionType, amount}]-> (Bank)
(Bank)        -[:PRIORITY_SECTOR_EXPOSURE {amount, year}]-> (Sector)
```

---

## Tech Stack

| Layer               | Technology                          |
| ------------------- | ----------------------------------- |
| Language            | Python 3.10+                        |
| Data processing     | pandas, openpyxl, lxml              |
| XBRL parsing        | arelle-release                      |
| Web / scraping      | beautifulsoup4, selenium, curl-cffi |
| Entity resolution   | rapidfuzz, metaphone                |
| Document store      | MongoDB (pymongo)                   |
| Graph database      | Neo4j 5.x (neo4j Python driver)     |
| Graph visualisation | PyVis, Matplotlib                   |
| Task runner / TUI   | textual, rich                       |
| Environment         | python-dotenv                       |

---
