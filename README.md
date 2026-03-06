# financial-contagion-risk-framework

This project processes banking ratio data, builds knowledge graphs, and loads data into MongoDB for analytics.

## Project Structure

- `data/ratio_data_csv/` — Raw CSV files for banking ratios
- `data-cleanser/xlsx_ratio_extrator.py` — Cleanses and normalizes banking data
- `v1-prototype/` — Prototype for financial knowledge graph (made by  [@snehil-sinha](https://www.github.com/nex7-7) )
  - `data_analysis/` — Jupyter notebooks and scripts for data analysis
  - `data_consolidation/` — Scripts and data for consolidating financial info
  - `prototype_kg/` — Knowledge graph builder (main pipeline: `loader.py`)
- `docs/` — Documentation
- `Makefile` — Run main pipelines easily

## Usage

### 1. Prepare Data

Place all your CSV files in the `data/ratio_data_csv/` directory.

### 2. Run Data Cleanser

Run the script using the Makefile:

```sh
make run
```

Or directly:

```sh
python3 data-cleanser/xlsx_ratio_extrator.py data/ratio_data_csv
```

### 3. Run v1-prototype Knowledge Graph Loader

Run the KG pipeline using the Makefile:

```sh
make run-v1-kg
```

Or directly:

```sh
python3 v1-prototype/prototype_kg/loader.py
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
