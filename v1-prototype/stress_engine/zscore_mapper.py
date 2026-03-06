"""
stress_engine/zscore_mapper.py
Maps a raw daily aggregate sentiment score to a [0, 1] stress value.

The mapping uses a two-stage approach:
  1. Z-score normalisation against the entity's rolling baseline (mean, std).
  2. Sigmoid squashing:  stress = 1 / (1 + exp(-Z))
     • Z = 0   → stress = 0.50  (exactly at baseline — no deviation)
     • Z = +2  → stress ≈ 0.88  (significantly more negative than usual)
     • Z = -2  → stress ≈ 0.12  (significantly more positive than usual)

Cold-start (< MIN_HISTORY_DAYS of baseline data) falls back to a direct
linear min-max mapping of the raw score into [0, 1].

Usage
-----
    from stress_engine.zscore_mapper import compute_stress

    stress = compute_stress(daily_score=0.3, mean=0.05, std=0.12)
"""

from __future__ import annotations

import math

from .config import MIN_HISTORY_DAYS


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_stress(
    daily_score: float,
    mean: float,
    std: float,
    history_days: int = MIN_HISTORY_DAYS,
) -> float:
    """
    Compute a [0, 1] news stress value.

    Parameters
    ----------
    daily_score : float
        Decay-weighted aggregate sentiment score for today, typically in
        roughly [-1, 1] where positive = more negative/stressful news.
    mean : float
        Rolling baseline mean of ``daily_score`` over the past window.
    std : float
        Rolling baseline standard deviation of ``daily_score``.
    history_days : int
        Number of days of history available.  If less than ``MIN_HISTORY_DAYS``,
        the cold-start fallback is used.

    Returns
    -------
    float
        Stress in [0, 1].  0.5 = neutral/baseline.  >0.5 = elevated stress.
    """
    if history_days < MIN_HISTORY_DAYS:
        return _cold_start_map(daily_score)

    # Avoid division by zero: if std is essentially zero the entity has had
    # perfectly consistent sentiment; treat any deviation as moderate.
    safe_std = std if std > 1e-6 else 1.0

    z = (daily_score - mean) / safe_std
    return _sigmoid(z)


def _sigmoid(z: float) -> float:
    """Numerically stable sigmoid clamped to (0, 1)."""
    # Clamp extreme Z values to prevent float overflow
    z = max(-20.0, min(20.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _cold_start_map(score: float) -> float:
    """
    Fallback mapper for entities with insufficient baseline history.

    Maps a raw FinBERT aggregate in the approximate range [-1, 1] linearly
    into [0, 1]:  stress = (score + 1) / 2
    """
    return max(0.0, min(1.0, (score + 1.0) / 2.0))


# ---------------------------------------------------------------------------
# Convenience: interpret a final stress float
# ---------------------------------------------------------------------------

def stress_label(stress: float) -> str:
    """Return a human-readable band for a [0, 1] stress score."""
    if stress < 0.30:
        return "low"
    if stress < 0.50:
        return "below-average"
    if stress < 0.65:
        return "moderate"
    if stress < 0.80:
        return "elevated"
    return "severe"
