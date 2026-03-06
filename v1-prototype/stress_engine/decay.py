"""
stress_engine/decay.py
Exponential decay weighting for time-stamped news articles.

The stress impact of an article decays exponentially based on its age.
Half-life is configurable (default: 5 days per config.py).

Usage
-----
    from stress_engine.decay import apply_decay

    # scored_articles: list of dicts with 'date' (date | datetime) and 'score' (float)
    daily_agg = apply_decay(scored_articles, halflife_days=5.0)
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import List, Dict, Any

from .config import DECAY_HALFLIFE_DAYS


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_decay(
    scored_articles: List[Dict[str, Any]],
    halflife_days: float = DECAY_HALFLIFE_DAYS,
    reference_date: date | None = None,
) -> float:
    """
    Compute a decay-weighted aggregate sentiment score from a list of articles.

    Parameters
    ----------
    scored_articles : list[dict]
        Each dict must contain:
            - ``"date"``  : ``datetime.date`` or ``datetime.datetime`` of publication
            - ``"score"`` : float — signed stress score where positive values
                            represent more stress (range typically [-1, 1] from
                            FinBERT, or 1.0 for hard-trigger overrides)
    halflife_days : float
        Number of days after which an article's weight halves without
        reinforcement.  Defaults to ``DECAY_HALFLIFE_DAYS`` from config.
    reference_date : date | None
        Date to measure age against.  Defaults to today's UTC date.

    Returns
    -------
    float
        Decay-weighted mean score in approximately [-1, 1].
        Returns 0.0 if the input list is empty or all weights round to zero.

    Notes
    -----
    Weight formula:  ``w_i = 2 ** (-days_ago_i / halflife_days)``
    This ensures:
        - articles published today  → weight = 1.0
        - articles at 1 half-life   → weight = 0.5
        - articles at 2 half-lives  → weight = 0.25
    """
    if not scored_articles:
        return 0.0

    ref = reference_date or date.today()

    total_weight = 0.0
    weighted_sum = 0.0

    for article in scored_articles:
        pub = article.get("date")
        score = article.get("score", 0.0)

        if pub is None:
            # No date available — treat as today (no decay)
            days_ago = 0
        elif isinstance(pub, datetime):
            days_ago = max((ref - pub.date()).days, 0)
        elif isinstance(pub, date):
            days_ago = max((ref - pub).days, 0)
        else:
            days_ago = 0

        weight = math.pow(2.0, -days_ago / halflife_days)
        weighted_sum += score * weight
        total_weight += weight

    if total_weight == 0.0:
        return 0.0

    return weighted_sum / total_weight


def decay_weight(days_ago: int, halflife_days: float = DECAY_HALFLIFE_DAYS) -> float:
    """Return the scalar decay weight for an article published ``days_ago`` days ago."""
    return math.pow(2.0, -max(days_ago, 0) / halflife_days)
