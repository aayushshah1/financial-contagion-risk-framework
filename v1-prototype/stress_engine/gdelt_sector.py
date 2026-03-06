"""
stress_engine/gdelt_sector.py
GDELT 2.0 Article API — macro stress for PrioritySector and Industry nodes.

GDELT is too noisy for specific entity lookups, but excellent for macro-sector
temperature.  We route ALL PrioritySector and Industry node stress here.

GDELT 2.0 Doc API (free, no key required):
    https://api.gdeltproject.org/api/v2/doc/doc
        ?query=<terms>
        &mode=artlist
        &maxrecords=25
        &format=json
        &timespan=1month

Results are scored with FinBERT, decay-weighted, and the aggregate stored in
the same news_baselines collection so the pipeline is uniform.

Usage
-----
    from stress_engine.gdelt_sector import fetch_sector_stress

    stress = fetch_sector_stress("agriculture", "priority_sector")
    # Returns float in [0, 1]
"""

from __future__ import annotations

import logging
import time
from datetime import date
from typing import List, Dict, Any, Optional

import requests

from .config import (
    GDELT_API_BASE,
    GDELT_MAX_RECORDS,
    PRIORITY_SECTOR_GDELT_TERMS,
    DECAY_HALFLIFE_DAYS,
)
from .finbert_scorer import score_articles
from .decay import apply_decay
from .zscore_mapper import compute_stress, _cold_start_map

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_sector_stress(
    entity_id: str,
    entity_type: str,
    custom_query: str | None = None,
) -> tuple[List[Dict[str, Any]], float]:
    """
    Fetch GDELT articles for a macro sector and return scored articles + raw aggregate.

    Parameters
    ----------
    entity_id   : str  — rbiCategory (e.g. "agriculture") or industryCode
    entity_type : str  — "priority_sector" or "industry"
    custom_query: str | None  — override the default GDELT query string

    Returns
    -------
    (articles, raw_aggregate)
        articles       : list[dict] — scored article dicts (title, date, score, …)
        raw_aggregate  : float      — decay-weighted mean score in [-1, 1]
    """
    query = custom_query or _build_gdelt_query(entity_id, entity_type)
    if not query:
        logger.warning("[gdelt] No query template for entity_id='%s' type='%s'. Returning 0.", entity_id, entity_type)
        return [], 0.0

    raw_articles = _gdelt_fetch(query)
    if not raw_articles:
        logger.info("[gdelt] No GDELT results for '%s'. Returning neutral.", entity_id)
        return [], 0.0

    scored = score_articles(raw_articles)
    aggregate = apply_decay(scored, halflife_days=DECAY_HALFLIFE_DAYS)

    logger.info(
        "[gdelt] %d articles for '%s' (%s) → raw aggregate = %.4f",
        len(scored), entity_id, entity_type, aggregate,
    )
    return scored, aggregate


def gdelt_stress_to_01(
    raw_aggregate: float,
    mean: float,
    std: float,
    history_days: int,
) -> float:
    """Map a raw GDELT aggregate score to [0, 1] using the same Z-score approach."""
    return compute_stress(raw_aggregate, mean, std, history_days)


# ---------------------------------------------------------------------------
# Query builder
# ---------------------------------------------------------------------------

def _build_gdelt_query(entity_id: str, entity_type: str) -> str | None:
    """
    Return a GDELT query string for the given entity.

    Priority sectors use the pre-built PRIORITY_SECTOR_GDELT_TERMS dict.
    Industry nodes use the entity_id as a free-text industry descriptor.
    """
    if entity_type == "priority_sector":
        return PRIORITY_SECTOR_GDELT_TERMS.get(entity_id)

    if entity_type == "industry":
        # Use natural English phrasing that appears in news articles
        return f"sourcecountry:India {entity_id} sector bank loan (default OR stressed OR NPA)"

    logger.warning("[gdelt] Unrecognised entity_type '%s'", entity_type)
    return None


# ---------------------------------------------------------------------------
# GDELT HTTP client
# ---------------------------------------------------------------------------

# Minimum polite delay between successive GDELT requests (seconds).
# GDELT's public API enforces a hard limit of 1 request every 5 seconds per IP.
_GDELT_REQUEST_DELAY: float = 6.5


def _gdelt_fetch(
    query: str,
    max_records: int = GDELT_MAX_RECORDS,
    timespan: str = "1month",
    retries: int = 4,
    backoff_base: float = 10.0,
) -> List[Dict[str, Any]]:
    """
    Call the GDELT 2.0 Article List API and return normalised article dicts.

    Retries up to ``retries`` times on HTTP 429 (rate-limit) with exponential
    backoff.  A small polite delay is applied before every attempt.

    Each returned dict has: ``title``, ``url``, ``date`` (date | None), ``snippet``
    """
    params = {
        "query":      query,
        "mode":       "artlist",
        "maxrecords": max_records,
        "format":     "json",
        "timespan":   timespan,
        "sort":       "DateDesc",
    }

    for attempt in range(1, retries + 1):
        # Polite delay — doubles on each retry
        delay = _GDELT_REQUEST_DELAY * (2 ** (attempt - 1))
        if attempt > 1:
            logger.info("[gdelt] Retry %d/%d after %.0fs back-off …", attempt, retries, delay)
        time.sleep(delay)

        try:
            resp = requests.get(GDELT_API_BASE, params=params, timeout=30)
        except requests.exceptions.Timeout:
            logger.error("[gdelt] Request timed out for query: %s", query[:80])
            return []
        except requests.exceptions.RequestException as exc:
            logger.error("[gdelt] Connection error: %s", exc)
            return []

        if resp.status_code == 429:
            wait = backoff_base * (2 ** (attempt - 1))
            logger.warning(
                "[gdelt] Rate limited (429) on attempt %d/%d. Waiting %.0fs …",
                attempt, retries, wait,
            )
            time.sleep(wait)
            continue

        try:
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.HTTPError as exc:
            logger.error("[gdelt] HTTP error: %s", exc)
            return []
        except ValueError as exc:
            logger.error("[gdelt] JSON decode error: %s", exc)
            return []

        articles_raw = data.get("articles") or []
        if not articles_raw:
            logger.debug(
                "[gdelt] Empty articles list. Full response: %s", resp.text[:400]
            )
        logger.debug("[gdelt] Raw results: %d articles for query: %s", len(articles_raw), query[:80])
        return [_normalise_gdelt_article(a) for a in articles_raw]

    logger.error("[gdelt] Exhausted %d retries for query: %s", retries, query[:80])
    return []


def _normalise_gdelt_article(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a GDELT article record to the standard pipeline schema:
        {title, url, date (date | None), snippet}
    """
    pub_date = _parse_gdelt_date(raw.get("seendate") or raw.get("publishdate"))
    return {
        "title":   raw.get("title", ""),
        "url":     raw.get("url", ""),
        "date":    pub_date,
        "snippet": raw.get("seendate", ""),  # GDELT rarely includes body text
        "source":  raw.get("domain", ""),
    }


def _parse_gdelt_date(raw: Any) -> date | None:
    """
    GDELT dates are typically formatted as "20260304T120000Z".
    """
    from datetime import datetime as _dt
    if raw is None:
        return None
    if isinstance(raw, str):
        # Try GDELT compact format then ISO
        for fmt in ("%Y%m%dT%H%M%SZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
            try:
                return _dt.strptime(raw[:15], fmt[:len(raw[:15])]).date()
            except ValueError:
                continue
    return None
