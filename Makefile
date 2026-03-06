# Makefile for running the data-cleanser

DATA_DIR=./data/ratio_data_csv
SCRIPT=./data-cleanser/xlsx_ratio_extrator.py

run-ratio-extractor:
	python3 $(SCRIPT) $(DATA_DIR)

help:
	@echo "Available targets:"
	@echo "  run-ratio-extractor      Run the ratio data extractor (data-cleanser)"
	@echo "  run-v1-kg                Run the v1-prototype KG loader"
	@echo "  run-crisil-scraper       Run the CRISIL data scraper"
	@echo "  run-bank-stress-mapper   Run the bank stress mapper (fundamental stress pipeline)"
	@echo "  entity-stress            Run the entity stress pipeline (engine/stress/entity_stress_pipeline.py)"
	@echo "  help                     Show this help message"
	@echo "  run-news-stress-mapper   Run the news stress mapper (engine/stress/news_data_fetcher_stress_mapper.py) with .env config"
# Entity stress pipeline
ENTITY_STRESS_PIPELINE=./engine/stress/entity_stress_pipeline.py

entity-stress:
	python3 $(ENTITY_STRESS_PIPELINE)

# v1-prototype KG loader
V1_PROTOTYPE_DIR=./v1-prototype
KG_LOADER=$(V1_PROTOTYPE_DIR)/prototype_kg/loader.py

run-v1-kg:
	python3 $(KG_LOADER)

# CRISIL scraper
CRISIL_SCRAPER=./data-fetcher/crisil_data_fetcher.py

run-crisil-scraper:
	python3 $(CRISIL_SCRAPER)

# Bank stress mapper
BANK_STRESS_MAPPER=./engine/stress/bank_stress_mapper.py

run-bank-stress-mapper:
	python3 $(BANK_STRESS_MAPPER)

# News stress mapper with env config
NEWS_STRESS_MAPPER=./engine/stress/news_data_fetcher_stress_mapper.py

run-news-stress-mapper:
	set -a && . .env && set +a && python3 $(NEWS_STRESS_MAPPER)

.PHONY: run-ratio-extractor run-v1-kg run-crisil-scraper run-bank-stress-mapper entity-stress help
