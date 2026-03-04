# Makefile for running the data-cleanser

DATA_DIR=./data/ratio_data_csv
SCRIPT=./data-cleanser/xlsx_ratio_extrator.py

run-ratio-extractor:
	python3 $(SCRIPT) $(DATA_DIR)

help:
	@echo "Available targets:"
	@echo "  run-ratio-extractor   Run the ratio data extractor (data-cleanser)"
	@echo "  run-v1-kg            Run the v1-prototype KG loader"
	@echo "  help                 Show this help message"

.PHONY: run-ratio-extractor run-v1-kg help

# v1-prototype KG loader
V1_PROTOTYPE_DIR=./v1-prototype
KG_LOADER=$(V1_PROTOTYPE_DIR)/prototype_kg/loader.py

run-v1-kg:
	python3 $(KG_LOADER)

.PHONY: run-v1-kg
