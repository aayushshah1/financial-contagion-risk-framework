"""
stress_engine/scraper.py
ddgs + Tor scraping layer for entity-specific news retrieval.

Reuses the existing TorSessionManager from data_consolidation/tor_manager.py.
Falls back to direct (non-Tor) ddgs if Tor is not available or disabled.

Entity routing
--------------
    "bank"            → ddgs query against financial news sites + RBI
    "company"         → ddgs query against financial news sites + CRISIL keywords
    "priority_sector" → delegated to gdelt_sector (not handled here)
    "industry"        → delegated to gdelt_sector (not handled here)

Usage
-----
    from stress_engine.scraper import fetch_news
    from data_consolidation.tor_manager import TorSessionManager

    with TorSessionManager(project_root="...", tor_enabled=True) as tor:
        articles = fetch_news("HDFC Bank Limited", "bank", tor_session=tor)

    # Without Tor (direct):
    articles = fetch_news("HDFC Bank Limited", "bank", tor_session=None)
"""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

from ddgs import DDGS

from .config import (
    DDGS_TIMELIMIT,
    MAX_ARTICLES_PER_ENTITY,
    MAX_ARTICLES_PER_QUERY,
    ENTITY_SEARCH_ALIASES,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_news(
    entity_name: str,
    entity_type: str,
    tor_session=None,
    max_results: int = MAX_ARTICLES_PER_ENTITY,
) -> List[Dict[str, Any]]:
    """
    Fetch recent financial news for a named entity using ddgs.

    Runs multiple query variants (e.g. ``"HDFC Bank Limited"`` *and*
    ``"HDFC Bank"``) and deduplicates results by URL so that a single
    entity can accumulate 60-100+ articles per run instead of the ~30
    DDG returns for a single query string.

    Parameters
    ----------
    entity_name  : str  — display name (e.g. "HDFC Bank Limited", "Tata Motors Limited")
    entity_type  : str  — "bank" or "company" (sector/industry → use gdelt_sector)
    tor_session  : TorSessionManager | None  — if provided, HTTP GETs route through Tor
    max_results  : int  — maximum number of articles to return (across all variants)

    Returns
    -------
    list[dict]
        Each dict contains: ``title``, ``url``, ``date`` (date | None), ``snippet``
    """
    if entity_type in ("priority_sector", "industry"):
        raise ValueError(
            f"Entity type '{entity_type}' should be handled by gdelt_sector, not scraper."
        )

    name_variants = _get_name_variants(entity_name)
    logger.info(
        "[scraper] Fetching news for '%s' (%s) via %d query variant(s)",
        entity_name, entity_type, len(name_variants),
    )

    seen_urls: set = set()
    raw_results: List[Dict[str, Any]] = []

    for variant in name_variants:
        if len(raw_results) >= max_results:
            break
        query = _build_query(variant, entity_type)
        logger.debug("[scraper] variant query: %s", query)
        results = _ddgs_search(
            query,
            max_results=MAX_ARTICLES_PER_QUERY,
            tor_session=tor_session,
        )
        added = 0
        for r in results:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                raw_results.append(r)
                added += 1
        logger.debug("[scraper] variant '%s' added %d unique article(s)", variant, added)

    articles = _normalise(raw_results[:max_results])
    logger.info(
        "[scraper] Retrieved %d articles for '%s' (%d variant(s))",
        len(articles), entity_name, len(name_variants),
    )
    return articles


# ---------------------------------------------------------------------------
# Query builder
# ---------------------------------------------------------------------------

def _get_name_variants(entity_name: str) -> List[str]:
    """
    Return a deduplicated list of name strings to query for a given entity.

    Combines:
    1. The original display name.
    2. Explicit aliases from ``ENTITY_SEARCH_ALIASES`` (config).
    3. An auto-generated shorter form produced by stripping common corporate
       suffixes (" Limited", " Ltd", " Private Limited", etc.).
    """
    variants: List[str] = [entity_name]

    # Explicit config aliases (e.g. "State Bank of India" → ["SBI", "SBI Bank"])
    for alias in ENTITY_SEARCH_ALIASES.get(entity_name, []):
        if alias and alias not in variants:
            variants.append(alias)

    # Auto-strip common corporate suffixes to generate a shorter variant.
    # Only add the stripped form if it isn't already in the list.
    _SUFFIXES = (
        " Private Limited",
        " Pvt. Ltd.",
        " Pvt. Ltd",
        " Pvt Ltd",
        " Limited",
        " Ltd.",
        " Ltd",
        " Private",
    )
    for suffix in _SUFFIXES:
        if entity_name.endswith(suffix):
            shorter = entity_name[: -len(suffix)].strip()
            if shorter and shorter not in variants:
                variants.append(shorter)
            break

    return variants


def _build_query(entity_name: str, entity_type: str) -> str:
    """
    Build a ddgs news query string.

    Uses the entity name only (quoted) so the news index returns as many
    relevant articles as possible.  FinBERT then scores each article for
    sentiment — there is no benefit to pre-filtering for negative keywords
    because doing so severely reduces article count for healthy entities.

    site: operators are intentionally omitted — DDG's news endpoint does
    not support them reliably.
    """
    return f'"{entity_name}"'


def _build_fallback_query(entity_name: str) -> str:
    """Minimal fallback query (no timelimit) used when the primary returns nothing."""
    return f'"{entity_name}" India finance'


# ---------------------------------------------------------------------------
# ddgs wrapper
# ---------------------------------------------------------------------------

def _ddgs_search(
    query: str,
    max_results: int,
    tor_session=None,
) -> List[Dict[str, Any]]:
    """
    Execute a ddgs news search.

    If ``tor_session`` is provided, the request is proxied through Tor by
    temporarily overriding the HTTP call via DDGS's ``proxies`` parameter
    (SOCKS5 from TorSessionManager port).

    Returns raw ddgs result dicts.
    """
    proxies = None

    if tor_session is not None:
        try:
            socks_port = tor_session.TOR_SOCKS_PORT
            proxies = {
                "http":  f"socks5h://127.0.0.1:{socks_port}",
                "https": f"socks5h://127.0.0.1:{socks_port}",
            }
            # Rotate IP before each entity fetch
            tor_session.rotate_ip()
        except Exception as e:
            logger.warning("[scraper] Tor rotation failed (%s), proceeding without proxy.", e)
            proxies = None

    base_kwargs: Dict[str, Any] = {
        "region":      "in-en",
        "timelimit":   DDGS_TIMELIMIT,
        "max_results": max_results,
    }
    if proxies:
        base_kwargs["proxies"] = proxies

    # Primary attempt
    try:
        with DDGS() as ddgs:
            results = list(ddgs.news(query=query, **base_kwargs))
        if results:
            return results
        logger.debug("[scraper] Primary query returned 0 results, trying fallback.")
    except Exception as exc:
        logger.warning("[scraper] Primary ddgs query failed (%s), trying fallback.", exc)

    # Fallback: simpler query, no timelimit
    fallback_query = _build_fallback_query(query.split('"')[1] if '"' in query else query)
    try:
        fallback_kwargs = {k: v for k, v in base_kwargs.items() if k != "timelimit"}
        with DDGS() as ddgs:
            results = list(ddgs.news(query=fallback_query, **fallback_kwargs))
        if results:
            logger.info("[scraper] Fallback query returned %d results.", len(results))
        return results
    except Exception as exc:
        logger.error("[scraper] ddgs search failed (fallback): %s", exc)
        return []


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _normalise(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convert raw ddgs news result dicts to a uniform schema:
        {title, url, date (date | None), snippet}
    """
    articles = []
    for item in raw:
        pub_date = _parse_date(item.get("date") or item.get("published"))
        articles.append({
            "title":   item.get("title", ""),
            "url":     item.get("url", ""),
            "date":    pub_date,
            "snippet": item.get("body") or item.get("excerpt") or "",
        })
    return articles


def _parse_date(raw: Any) -> date | None:
    """
    Parse a date from various ddgs formats.
    ddgs typically returns ISO-8601 strings like "2026-03-01T12:00:00+00:00"
    or simple "2026-03-01".
    """
    if raw is None:
        return None
    if isinstance(raw, (date, datetime)):
        return raw.date() if isinstance(raw, datetime) else raw
    if isinstance(raw, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw[:19], fmt.split("%z")[0]).date()
            except ValueError:
                continue
    return None
