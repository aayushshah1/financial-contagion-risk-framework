# financial-contagion-risk-framework

This project processes banking ratio data, builds knowledge graphs, and loads data into MongoDB for analytics.

## Project Structure

- `ingestion/` — Fetch and extract raw data (CRISIL scraper, XLSX ratio extractor)
- `data/raw/` — Raw input files (banking ratios, XLSX)
- `data/outputs/` — Computed artifacts (stress scores, normalised CSVs)
- `data_consolidation/` — Scripts and data for consolidating financial info into MongoDB
- `data_analysis/` — Jupyter notebooks and scripts for EDA and reconciliation
- `prototype_kg/` — Knowledge graph builder (main pipeline: `loader.py`)
- `engine/` — Stress scoring pipelines (bank, entity, news)
- `engine/migrations/` — One-off data migration scripts
- `docs/` — Documentation (see `docs/archive/` for v1 README)
- `Makefile` — Run main pipelines easily

## Usage

### 1. Prepare Data

Place all your CSV files in the `data/raw/ratio_data_csv/` directory.

### 2. Run Ratio Extractor

Run the script using the Makefile:

```sh
make run-ratio-extractor
```

Or directly:

```sh
python3 ingestion/xlsx_ratio_extractor.py data/raw/ratio_data_csv
```

### 3. Run Knowledge Graph Loader

Run the KG pipeline using the Makefile:

```sh
make run-v1-kg
```

Or directly:

```sh
python3 prototype_kg/loader.py
```

### 4. Output

- `Normalized_Banks_Data.csv` — Cleaned, normalized data
- `Structured_Banks_Data.json` — Nested JSON for MongoDB
- Neo4j database — Populated with financial knowledge graph

### 5. MongoDB

The data cleanser script pushes structured data to a local MongoDB instance (`banking_analytics.performance_metrics`).

## Requirements

- Python 3.x
- pandas
- numpy
- pymongo

Install dependencies:

```sh
pip install pandas numpy pymongo
```

## License

MIT
