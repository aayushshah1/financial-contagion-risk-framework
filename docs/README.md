# Bank Contagion Knowledge Graph Pipeline

A financial contagion model that ingests bank & company data from MongoDB, builds a knowledge graph in Neo4j, and simulates systemic stress propagation across the financial system.

## Architecture

```mermaid
flowchart TD
    subgraph MongoDB["📦 MongoDB — financial_kg database"]
        CO["companies collection\n(2818 docs)"]
        BK["banks collection\n(3 docs)"]
    end

    subgraph DataExtraction["🔍 Step 1 — Data Extraction"]
        LOAD["load_from_mongo()"]
        LOADB["load_banks_from_mongo()"]
    end

    subgraph DataPoints["📊 Extracted Data Points"]
        BF["Bank Facilities\nlenderName, facility,\namount, rating"]
        CR["CRISIL Ratings\nrating → stress score\n(AAA=0.05 … D=1.0)"]
        SH["Shareholding Pattern\nmutual funds, insurance,\nFPI, DII percentages"]
        NIC["NIC Code\n→ Sector mapping\n→ Priority sector flag"]
    end

    subgraph Neo4jCheck["🔒 Step 2 — Neo4j Check"]
        CHECK{"neo4j_has_data()?\nCompany/Bank/Sector\nnodes exist?"}
    end

    subgraph Neo4j["🔷 Neo4j Knowledge Graph"]
        subgraph Nodes["Nodes"]
            COMP["🏢 Company\ncin, name, stress_score,\nindustry, nic_code"]
            BANK["🏦 Bank\nname, total_exposure,\nstress_score"]
            SECT["📂 Sector\nname, is_priority,\nstress_score"]
        end
        subgraph Edges["Relationships"]
            LT["LENT_TO\n(Bank → Company)\namount, facility_type, npa_flag"]
            OI["OPERATES_IN\n(Company → Sector)"]
            HS["HOLDS_SHARES\n(Company ↔ Company)\nweight, category"]
        end
    end

    subgraph Propagation["⚡ Step 4 — Contagion Propagation"]
        CH1["Channel 1: Lending\nBank stress ↔ Company\nweight = amount / total_exposure"]
        CH2["Channel 2: Shareholding\nCompany ↔ Company\nvia shared institutional investors\n(dampened 0.3×)"]
        CH4["Channel 4: Priority Sector\nCompany → Sector → Bank\naggregated stress flow"]
        CH3["Channel 3: News\n(placeholder)"]
        CH5["Channel 5: Cash Flow\n(placeholder)"]
    end

    subgraph Output["📤 Step 6 — Results"]
        CSV["contagion_results.csv\nentity_id, name, type, stress_final"]
        PRINT["Console Summary\nTop 50 most stressed entities\n+ breakdown by type"]
    end

    CO --> LOAD
    BK --> LOADB
    LOAD --> BF & CR & SH & NIC
    LOADB --> BANK

    BF & CR & SH & NIC --> CHECK
    CHECK -- "No data" --> Neo4j
    CHECK -- "Data exists" --> |"Skip build"| Propagation

    COMP --- LT
    LT --- BANK
    COMP --- OI
    OI --- SECT
    COMP --- HS

    Neo4j --> Propagation
    CH1 & CH2 & CH4 --> |"iterate until\nconvergence"| Neo4j
    Propagation --> Output
```

## Pipeline Steps

### Step 1 — Data Extraction from MongoDB

| Source Collection | Key Fields Extracted | Purpose |
|---|---|---|
| `companies` (2818 docs) | `companyCode`, `cin`, `crisilName` | Company identity |
| | `bankFacilities[].lenderName, facility, amount, rating` | Lending relationships & NPA detection |
| | `crisilRatings[].rating` | Stress score (AAA=0.05 → D=1.0) |
| | `shareholdingPattern.aggregates` | Institutional investor overlap for Channel 2 |
| | `nicCode`, `industryName` | Sector classification & priority sector flag |
| `banks` (3 docs) | `bankSymbol`, `advances.totalExposure` | Bank-level aggregate exposure |
| | `advances.companies[].facilities` | Cross-reference with company facilities |

### Step 2 — Neo4j Existence Check

Before writing to Neo4j, the pipeline counts existing `Company`, `Bank`, and `Sector` nodes:
- **If data exists** → Skip graph build, go straight to loading the graph state
- **If empty** → Build the full graph from MongoDB data

### Step 3 — Knowledge Graph Construction

Three node types and three relationship types are created:

| Element | Key | Properties |
|---|---|---|
| `Company` node | `cin` (unique) | `name`, `stress_score`, `industry`, `nic_code`, `is_priority`, `sector` |
| `Bank` node | `name` (unique) | `stress_score` (init 0.3), `total_exposure` |
| `Sector` node | `name` (unique) | `is_priority`, `stress_score` |
| `LENT_TO` edge | Bank → Company | `facility_type`, `amount`, `npa_flag` |
| `OPERATES_IN` edge | Company → Sector | — |
| `HOLDS_SHARES` edge | Company ↔ Company | `weight` (pct_A × pct_B), `category` |

### Step 4 — Contagion Propagation

Iterative stress propagation across 5 channels (3 active, 2 placeholders):

| Channel | Direction | Weight Formula | Status |
|---|---|---|---|
| **1 — Lending** | Bank ↔ Company | `amount / total_exposure × npa_mult` | ✅ Active |
| **2 — Shareholding** | Company ↔ Company | `pct_A × pct_B × 0.3` (dampened) | ✅ Active |
| **3 — News** | — | — | ⏳ Placeholder |
| **4 — Priority Sector** | Company → Sector → Bank | `1/companies_in_sector` | ✅ Active |
| **5 — Cash Flow** | — | — | ⏳ Placeholder |

Propagation stops when `max_delta < 0.001` or after 20 iterations.

### Step 5 — Write Back

Propagated `stress_final` scores are written back to all Neo4j nodes.

### Step 6 — Export Results

Results exported to `contagion_results.csv` with columns: `entity_id`, `name`, `type`, `stress_final`.

## Configuration

Set these environment variables in `.env`:

```env
MONGO_URI=mongodb+srv://...
MONGO_DB=financial_kg
MONGO_COLL=companies
MONGO_BANKS_COLL=banks
NEO4J_URI=neo4j+s://...
NEO4J_USER=neo4j
NEO4J_PASS=your_password
```

## Running

```bash
pip install neo4j pymongo python-dotenv pandas tqdm
python main.py
```
