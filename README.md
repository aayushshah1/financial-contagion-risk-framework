# Financial Contagion Risk Framework

## Overview & Core Concept
The **Financial Contagion Risk Framework** is a comprehensive system designed to model, analyze, and visualize systemic risk and stress propagation across financial networks. The core concept is to evaluate the fundamental health of individual entities (banks, companies) and simulate how financial distress in one entity can cascade through the network via lending, shareholding, and subsidiary relationships.

By combining historical credit default data, live news sentiment analysis, and graph-based contagion modeling, the framework provides an interactive 3D environment for risk assessment and network monitoring.

---

## Basic Logic & Flow

1. **Data Ingestion & Consolidation**: Raw financial data, corporate relationships, and credit ratings are extracted from various sources (XLSX files, CRISIL databases, MCA data). This data is cleaned, normalized, and stored natively as nested documents in **MongoDB**.
2. **Fundamental Stress Scoring**: 
   - Entities are evaluated to produce baseline stress scores. 
   - Uses real-world probability of default (PD) transition matrices and exposures to gauge counterparty risk.
   - Textual inputs (like news or profile data) are analyzed using NLP (FinBERT) to capture real-time market sentiment.
3. **Knowledge Graph Construction**: Relational data in MongoDB is translated into a **Neo4j** Knowledge Graph. Entities (Banks, Companies, Sectors, Industries) become nodes, while underlying relationships (`LENDS_TO`, `SHAREHOLDER_OF`, `SUBSIDIARY_OF`) become edges.
4. **Contagion Propagation**: A mathematical fixed-point model is run over the graph to simulate how stress is transferred. If a highly-leveraged company defaults, the model propagates that financial stress back to its lending banks and major shareholders.
5. **Interactive Visualization**: The computed network and stress metrics are visualized via a modern 3D web application. This allows users to interactively explore structural vulnerabilities, toggle data sources, and trigger real-time layout and stress algorithms.

---

## Code Architecture

- **`ingestion/`**: Scripts and pipelines for fetching and parsing raw data.
  - Examples: CRISIL data scrapers, XLSX ratio extractors.
- **`data_consolidation/`**: Consolidation logic to push unified, structured financial information into MongoDB (`financial_kg`).
- **`engine/`**: The core stress analytics engine.
  - Calculates entity stress based on rating transitions (`engine/stress/entity_stress_pipeline.py`).
  - Fetches and scores news sentiment using FinBERT (`news_data_fetcher_stress_mapper.py`).
  - Calculates contagion transfer through the graph.
- **`prototype_kg/`**: Orchestrates the Neo4j graph building.
  - `loader.py` acts as the main pipeline to resolve entities and write nodes/edges from MongoDB into the AuraDB/Neo4j graph.
- **`visualser/`**: React/Vite/TypeScript frontend utilizing React Three Fiber for 3D network visualization. Features robust gesture/mouse controls, data toggling, and interactive node inspection.
- **`data/`**: Local storage layer for inputs and outputs.
  - `data/raw/`: Initial source CSVs and spreadsheets.
  - `data/outputs/`: Processed calculation artifacts, such as `entity_stress_scores.csv`.

---

## Inputs
- **Base Financials**: Raw banking ratios, financial statements, and lending facility datasets (CSVs/XLSX).
- **Corporate Metadata**: Company hierarchies, RPT (Related Party Transactions) data, listing statuses, and sector categories.
- **Market Signals**: Live/historical news events and credit rating agency datasets (e.g., CRISIL default mappings).

## Outputs
- **Structured Database Models**: Cleaned, unified databases housed in local/cloud MongoDB.
- **Stress Metrics**: Actionable stress scores (`0-100`), probability of default percentages, confidence intervals, and categorical risk tiers (Investment Grade vs Default).
- **Relational Knowledge Graph**: A dynamically generated Neo4j database mapping the exact flow of capital and risk.
- **Visual Network Interface**: An interactive, 3D web portal showcasing node-link risk heatmaps.

---

## Getting Started

### 1. Environment Parsing
Ensure your `.env` contains the required URI and authentication variables for `MongoDB` and `Neo4j`, as well as configuration for the frontend visualization.

### 2. Extract and Consolidate Data
Run the ratio extractor to clean input documents:
```sh
make run-ratio-extractor
```

### 3. Generate Stress Scores
Run the fundamental entity stress generation:
```sh
python3 engine/stress/entity_stress_pipeline.py
```

### 4. Build Knowledge Graph
Clear and populate the Neo4j database with mapped entities and relationships:
```sh
make run-v1-kg
```

### 5. Launch Visualization
Navigate into the `visualser/` directory and spin up the frontend:
```sh
cd visualser
npm install
npm run dev
```

---
*License: MIT*
