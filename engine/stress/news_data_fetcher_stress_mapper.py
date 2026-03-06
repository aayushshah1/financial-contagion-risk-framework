import requests
import feedparser
import json
import re
import numpy as np
from pymongo import MongoClient
from datetime import datetime, timezone
from urllib.parse import quote
import os

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "finincial_kg")
COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "companies")

# ─────────────────────────────────────────────
#  FinBERT Model (lazy-loaded singleton)
# ─────────────────────────────────────────────
_finbert_pipeline = None


def _get_finbert():
    """Lazy-load FinBERT so the model is only downloaded / loaded once."""
    global _finbert_pipeline
    if _finbert_pipeline is None:
        from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline

        model_name = "ProsusAI/finbert"
        print(f"\n      [finbert] Loading model '{model_name}'...")
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSequenceClassification.from_pretrained(model_name)
        _finbert_pipeline = pipeline(
            "sentiment-analysis",
            model=model,
            tokenizer=tokenizer,
            top_k=None,          # return all label scores
            truncation=True,
            max_length=512,
        )
        print(f"      [finbert] Model loaded ✓")
    return _finbert_pipeline


# ─────────────────────────────────────────────
#  STEP 1: Fetch company from MongoDB
# ─────────────────────────────────────────────
def get_company(identifier: str) -> dict:
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.server_info()
    except Exception as e:
        raise ConnectionError(
            f"Cannot connect to MongoDB at '{MONGO_URI}': {e}")

    col = client[DB_NAME][COLLECTION_NAME]

    total = col.count_documents({})
    print(
        f"      [debug] Collection '{COLLECTION_NAME}' has {total} documents")

    if total == 0:
        client.close()
        raise ValueError(
            f"Collection '{COLLECTION_NAME}' is empty — check DB_NAME and COLLECTION_NAME")

    sample = col.find_one({})
    print(f"      [debug] Sample document keys: {list(sample.keys())}")

    doc = col.find_one({"companyCode": identifier})
    if doc:
        print(f"      [debug] Matched via companyCode")
        client.close()
        return doc

    doc = col.find_one({"crisilName": {"$regex": identifier, "$options": "i"}})
    if doc:
        print(f"      [debug] Matched via crisilName")
        client.close()
        return doc

    doc = col.find_one({"mcaName": {"$regex": identifier, "$options": "i"}})
    if doc:
        print(f"      [debug] Matched via mcaName")
        client.close()
        return doc

    sample_codes = col.distinct("companyCode")[:10]
    print(f"      [debug] Sample companyCode values in DB: {sample_codes}")
    client.close()
    raise ValueError(
        f"Company not found for identifier: '{identifier}'\n"
        f"       Tried fields: companyCode, crisilName, mcaName\n"
        f"       Sample codes above — check your identifier spelling."
    )


# ─────────────────────────────────────────────
#  STEP 2: Fetch news from Google News RSS
# ─────────────────────────────────────────────
def fetch_news(company_name: str, max_articles: int = 10) -> list[dict]:
    """
    Tries 2 query strategies in order:
      1. Exact quoted name        → "Alpha Ecoplast Private Limited"
      2. Short name (drop suffix) → "Alpha Ecoplast"
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # Build a short name by stripping common suffixes
    short_name = re.sub(
        r'\s+(Private Limited|Pvt\.? Ltd\.?|Limited|Ltd\.?|LLP|Inc\.?)$',
        '', company_name, flags=re.IGNORECASE
    ).strip()

    queries = [
        ("exact-quoted",  f'"{company_name}"'),
        ("short-name",    short_name),
    ]

    for strategy, query in queries:
        encoded = quote(query)
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en-IN&gl=IN&ceid=IN:en"

        print(f"\n      [news] Strategy: {strategy}")
        print(f"      [news] Query:    {query}")
        print(f"      [news] URL:      {url}")

        try:
            resp = requests.get(url, headers=headers,
                                timeout=15, allow_redirects=True)

            print(f"      [news] HTTP status:       {resp.status_code}")
            print(f"      [news] Final URL:         {resp.url}")
            print(
                f"      [news] Content-Type:      {resp.headers.get('Content-Type', 'N/A')}")
            print(f"      [news] Response length:   {len(resp.text)} chars")
            print(f"      [news] Response preview:  {resp.text[:300].strip()}")

            feed = feedparser.parse(resp.text)

            print(
                f"      [news] Feed title:        {feed.feed.get('title', 'N/A')}")
            print(
                f"      [news] Feed status:       {feed.get('status', 'N/A')}")
            print(f"      [news] Entries found:     {len(feed.entries)}")
            if feed.bozo:
                print(
                    f"      [news] ⚠ feedparser bozo error: {feed.bozo_exception}")

            if feed.entries:
                print(
                    f"      [news] ✓ Using strategy '{strategy}' — {len(feed.entries)} articles")
                articles = []
                for entry in feed.entries[:max_articles]:
                    articles.append({
                        "title":     entry.get("title", ""),
                        "link":      entry.get("link", ""),
                        "source":    entry.get("source", {}).get("title", "Unknown"),
                        "published": entry.get("published", ""),
                        "summary":   entry.get("summary", "")
                    })
                return articles

            print(
                f"      [news] ✗ Strategy '{strategy}' returned 0 entries, trying next...")

        except requests.exceptions.RequestException as e:
            print(
                f"      [news] ✗ Request failed for strategy '{strategy}': {e}")

    print(f"\n      [news] All strategies exhausted — 0 articles found.")
    return []


# ─────────────────────────────────────────────
#  STEP 3: Build text snippets for FinBERT
# ─────────────────────────────────────────────
def build_scoring_texts(company: dict, articles: list[dict]) -> list[str]:
    """
    Produce a list of short text snippets for FinBERT to classify.
    Each snippet is kept under ~450 chars so FinBERT's 512-token
    window is not exceeded after tokenisation.

    Sources of text (in priority order):
      1. Each news headline + summary  (best signal)
      2. CRISIL heading                (always available)
      3. Baseline profile sentence     (fallback)
    """
    texts = []

    # ── news articles ──
    for a in articles:
        headline = a.get("title", "").strip()
        summary_raw = re.sub(r"<[^>]+>", "", a.get("summary", "")).strip()
        snippet = f"{headline}. {summary_raw}" if summary_raw else headline
        if snippet:
            texts.append(snippet[:450])

    # ── CRISIL heading (always fed in as an extra signal) ──
    crisil = company.get("crisilHeading", "")
    if crisil:
        texts.append(f"CRISIL rating action: {crisil}"[:450])

    # ── baseline fallback when nothing else exists ──
    if not texts:
        name = company.get("crisilName") or company.get("mcaName") or "Unknown"
        industry = company.get("industryName", "Unknown")
        status = company.get("mcaCompanyStatus", "Active")
        listing = company.get("listingStatus", "Unknown")
        capital = company.get("mcaPaidupCapital", "N/A")
        texts.append(
            f"{name} is a {listing} {industry} company. "
            f"Status: {status}. Paid-up capital: {capital}."
        )

    return texts


# ─────────────────────────────────────────────
#  STEP 4: Score with FinBERT
# ─────────────────────────────────────────────
def score_with_finbert(company: dict, articles: list[dict]) -> dict:
    """
    Run each text snippet through FinBERT and aggregate into a single
    stress score in [0, 1].

    FinBERT returns three labels per snippet:
        positive  — good financial news
        neutral   — no strong signal
        negative  — bad financial news / stress

    Mapping to stress:
        stress_i = negative_prob + 0.5 * neutral_prob

    Final score is a weighted average where news headlines are weighted
    more than the CRISIL / baseline fallback.
    """
    finbert = _get_finbert()
    texts = build_scoring_texts(company, articles)

    print(f"      [finbert] Scoring {len(texts)} text snippet(s)...")

    snippet_scores = []
    snippet_details = []
    news_count = len(articles)

    for i, text in enumerate(texts):
        result = finbert(text)[0]  # list of {label, score} dicts
        probs = {r["label"]: r["score"] for r in result}

        neg = probs.get("negative", 0.0)
        neu = probs.get("neutral", 0.0)
        pos = probs.get("positive", 0.0)

        # Map to stress value
        stress_i = neg + 0.5 * neu
        snippet_scores.append(stress_i)

        dominant = max(probs, key=probs.get)
        snippet_details.append({
            "text_preview": text[:80],
            "positive": round(pos, 4),
            "neutral":  round(neu, 4),
            "negative": round(neg, 4),
            "stress":   round(stress_i, 4),
            "dominant":  dominant,
        })

        print(
            f"      [finbert]   [{i+1}/{len(texts)}] "
            f"pos={pos:.3f}  neu={neu:.3f}  neg={neg:.3f}  "
            f"→ stress={stress_i:.3f}  ({dominant})"
        )

    # ── weighted aggregation ──
    # News snippets get weight 2, CRISIL / baseline snippets get weight 1
    weights = []
    for i in range(len(snippet_scores)):
        if i < news_count:
            weights.append(2.0)      # news headline
        else:
            weights.append(1.0)      # CRISIL / baseline

    weights = np.array(weights)
    scores = np.array(snippet_scores)
    final_score = float(np.average(scores, weights=weights))

    # ── confidence from variance + volume ──
    if news_count >= 5:
        confidence = "high"
    elif news_count >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    # ── key drivers — pick most negative snippets ──
    ranked = sorted(snippet_details, key=lambda d: d["stress"], reverse=True)
    key_drivers = [
        d["text_preview"] for d in ranked[:3]
        if d["stress"] > 0.4
    ]
    if not key_drivers:
        key_drivers = [ranked[0]["text_preview"]] if ranked else ["No signal"]

    # ── summary sentence ──
    if final_score >= 0.8:
        band = "Severe financial stress"
    elif final_score >= 0.6:
        band = "High financial stress"
    elif final_score >= 0.4:
        band = "Moderate financial stress"
    elif final_score >= 0.2:
        band = "Low financial stress"
    else:
        band = "Minimal financial stress"

    name = company.get("crisilName") or company.get("mcaName") or "Unknown"
    summary = (
        f"{band} detected for {name} "
        f"(FinBERT score {final_score:.2f}, {confidence} confidence, "
        f"{news_count} article(s) analysed)."
    )

    return {
        "score":       round(final_score, 4),
        "confidence":  confidence,
        "key_drivers": key_drivers,
        "summary":     summary,
        "snippet_details": snippet_details,
    }


# ─────────────────────────────────────────────
#  STEP 5: Main orchestrator
# ─────────────────────────────────────────────
def get_stress_score(identifier: str) -> dict:
    print(f"\n{'='*55}")
    print(f"  News Stress Scorer  (FinBERT)")
    print(f"{'='*55}")

    # 1. MongoDB lookup
    print(f"\n[1/4] Looking up company: '{identifier}'...")
    company = get_company(identifier)
    name = company.get("crisilName") or company.get("mcaName")
    print(f"      Found: {name}")

    # 2. Fetch news
    print(f"\n[2/4] Fetching news for '{name}'...")
    articles = fetch_news(name)
    print(f"\n      Total articles collected: {len(articles)}")

    # 3. Score with FinBERT
    print(f"\n[3/4] Scoring with FinBERT...")
    finbert_result = score_with_finbert(company, articles)

    # 4. Build final output
    article_links = [
        {"title": a["title"], "link": a["link"], "source": a["source"]}
        for a in articles if a.get("link")
    ]

    result = {
        "company_code":   company.get("companyCode"),
        "company_name":   name,
        "listing_status": company.get("listingStatus"),
        "industry":       company.get("industryName"),
        "stress_score":   finbert_result["score"],
        "confidence":     finbert_result["confidence"],
        "key_drivers":    finbert_result["key_drivers"],
        "summary":        finbert_result["summary"],
        "news_used":      len(articles),
        "articles":       article_links,
        "scored_at":      datetime.now(timezone.utc).isoformat(),
    }

    print(f"\n[4/4] Done.\n")
    print(json.dumps(result, indent=2))
    print(f"\n{'='*55}\n")

    return result


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    identifier = sys.argv[1] if len(sys.argv) > 1 else "LICHOUS"
    get_stress_score(identifier)
