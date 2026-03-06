"""
stress_engine — News-based stress pipeline for the Financial Knowledge Graph.

Modules:
    config          — constants, MongoDB/FinBERT settings
    scraper         — ddgs + Tor scraping layer
    finbert_scorer  — FinBERT sentiment scoring with hard-trigger overrides
    decay           — exponential decay weighting of time-stamped articles
    baseline        — rolling 60-day MongoDB baseline CRUD
    zscore_mapper   — Z-score → [0, 1] sigmoid stress mapper
    gdelt_sector    — GDELT macro stress for PrioritySector / Industry nodes
    pipeline        — orchestrator; CLI entry point
"""
