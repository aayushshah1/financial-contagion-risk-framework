"""
stress_engine/finbert_scorer.py
FinBERT-based sentiment scorer for financial news headlines.

FinBERT (ProsusAI/finbert) is a BERT model fine-tuned on financial text.
Unlike generic sentiment models, it correctly handles domain vocabulary:
  • "debt dropped"    → positive (good for the company)
  • "auditor resigned" → negative (catastrophic red flag)
  • "NPA surged"      → negative

The model is loaded once as a module-level singleton to avoid re-loading
on every call (the model is ~420 MB).

Hard-trigger bypass
-------------------
If a headline contains any of the HARD_TRIGGER_KEYWORDS from config, we
skip FinBERT entirely and assign score = 1.0 (maximum stress).  This
avoids the risk of FinBERT misclassifying extremely explicit distress
signals and ensures instant maximum-stress spikes.

Signed score convention
-----------------------
FinBERT outputs three classes: positive / neutral / negative.
We convert these to a signed float:
    score = P(negative) - P(positive)
Range: [-1, 1] where +1 = fully negative (high stress), -1 = fully positive.
Neutral articles produce ≈ 0.

Usage
-----
    from stress_engine.finbert_scorer import score_articles

    articles = [
        {"title": "HDFC Bank reports surge in NPAs", "date": ..., "snippet": "..."},
    ]
    scored = score_articles(articles)
    # Each dict now has "sentiment" and "score" keys appended.
"""

from __future__ import annotations

import logging
from typing import List, Dict, Any

from .config import FINBERT_MODEL, HARD_TRIGGER_KEYWORDS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton model loader
# ---------------------------------------------------------------------------

_pipeline = None  # transformers pipeline instance (lazy-loaded)


def _get_pipeline():
    """Load FinBERT pipeline once and cache it for subsequent calls."""
    global _pipeline
    if _pipeline is not None:
        return _pipeline

    try:
        from transformers import pipeline as hf_pipeline

        logger.info("Loading FinBERT model (%s) — this may take a moment …", FINBERT_MODEL)
        _pipeline = hf_pipeline(
            task="text-classification",
            model=FINBERT_MODEL,
            top_k=None,           # Return scores for all 3 classes
            truncation=True,
            max_length=512,
        )
        logger.info("FinBERT model loaded successfully.")
    except ImportError as exc:
        raise ImportError(
            "The 'transformers' package is required for FinBERT scoring. "
            "Install it with: pip install transformers torch"
        ) from exc

    return _pipeline


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_articles(
    articles: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Score a list of article dicts with FinBERT sentiment.

    Each input dict should have at minimum a ``"title"`` key.
    The ``"snippet"`` key (if present) is appended to the title to give
    FinBERT more context (up to the 512-token limit).

    The function appends two keys to each dict in-place:
        - ``"sentiment"``  : str  — "positive" | "negative" | "neutral"
        - ``"score"``      : float — signed stress score in [-1, 1]

    Hard-trigger articles receive ``score = 1.0`` without FinBERT inference.

    Returns
    -------
    list[dict]
        Same list, with ``"sentiment"`` and ``"score"`` added to each item.
    """
    if not articles:
        return articles

    to_infer: List[int] = []  # indices that need FinBERT inference
    texts: List[str] = []

    for idx, article in enumerate(articles):
        title = article.get("title") or article.get("heading") or ""
        snippet = article.get("snippet") or article.get("body") or ""
        text = f"{title}. {snippet}".strip(". ")

        # Hard-trigger check
        title_lower = title.lower()
        if _is_hard_trigger(title_lower):
            article["sentiment"] = "negative"
            article["score"] = 1.0
            logger.debug("Hard-trigger override on: %s", title[:80])
        else:
            to_infer.append(idx)
            texts.append(text[:512])  # Safety truncation for very long strings

    # Batch inference for non-triggered articles
    if texts:
        nlp = _get_pipeline()
        results = nlp(texts, batch_size=16)

        for article_idx, finbert_result in zip(to_infer, results):
            articles[article_idx]["sentiment"], articles[article_idx]["score"] = (
                _parse_finbert_output(finbert_result)
            )

    return articles


def score_single(text: str) -> tuple[str, float]:
    """
    Score a single text string.  Returns ``(sentiment, score)`` tuple.
    Useful for quick interactive checks or GDELT snippet scoring.
    """
    text_lower = text.lower()
    if _is_hard_trigger(text_lower):
        return "negative", 1.0

    nlp = _get_pipeline()
    result = nlp([text[:512]], batch_size=1)[0]
    return _parse_finbert_output(result)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_hard_trigger(text_lower: str) -> bool:
    """Return True if any hard-trigger keyword appears in the lowercased text."""
    return any(kw in text_lower for kw in HARD_TRIGGER_KEYWORDS)


def _parse_finbert_output(finbert_result) -> tuple[str, float]:
    """
    Convert FinBERT's ``top_k=None`` output into (sentiment, score).

    FinBERT returns a list of dicts like:
        [{"label": "positive", "score": 0.87}, {"label": "negative", "score": 0.08}, ...]

    We pick the argmax label and compute signed score:
        stress_score = P(negative) - P(positive)
    """
    label_scores: Dict[str, float] = {
        item["label"].lower(): item["score"] for item in finbert_result
    }

    p_pos = label_scores.get("positive", 0.0)
    p_neg = label_scores.get("negative", 0.0)

    # Argmax label
    dominant = max(label_scores, key=label_scores.get)

    # Signed score: positive means stressed, negative means healthy
    signed = p_neg - p_pos
    return dominant, signed
