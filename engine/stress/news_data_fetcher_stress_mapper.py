import argparse
import requests
import feedparser
import re
import csv
import numpy as np
import os
from pymongo import MongoClient
from datetime import datetime, timezone, date
from urllib.parse import quote
from tqdm import tqdm

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
MONGO_URI       = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME         = os.environ.get("DB_NAME", "financial_kg")
COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "companies")
OUTPUT_CSV      = os.environ.get("OUTPUT_CSV", "stress_scores.csv")
NEWS_BEFORE_DATE = os.environ.get("NEWS_BEFORE_DATE", "").strip() or None

CSV_COLUMNS = [
    "company_code", "company_name", "listing_status", "industry",
    "stress_score", "stress_band", "confidence", "key_drivers", "summary", "news_used",
    "article_1_title", "article_1_link", "article_1_source",
    "article_2_title", "article_2_link", "article_2_source",
    "article_3_title", "article_3_link", "article_3_source",
    "article_4_title", "article_4_link", "article_4_source",
    "article_5_title", "article_5_link", "article_5_source",
    "scored_at", "error",
]


# ─────────────────────────────────────────────
#  FinBERT (lazy-loaded singleton)
# ─────────────────────────────────────────────
_finbert_pipeline = None

def _get_finbert():
    global _finbert_pipeline
    if _finbert_pipeline is None:
        from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline
        model_name = "ProsusAI/finbert"
        tqdm.write(f"\n[finbert] Loading '{model_name}' (first run only)...")
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model     = AutoModelForSequenceClassification.from_pretrained(model_name)
        _finbert_pipeline = pipeline(
            "sentiment-analysis", model=model, tokenizer=tokenizer,
            top_k=None, truncation=True, max_length=512,
        )
        tqdm.write("[finbert] Model loaded successfully\n")
    return _finbert_pipeline


# ─────────────────────────────────────────────
#  MongoDB
# ─────────────────────────────────────────────
def get_all_companies() -> list[dict]:
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.server_info()
    except Exception as e:
        raise ConnectionError(f"Cannot connect to MongoDB at '{MONGO_URI}': {e}")

    col   = client[DB_NAME][COLLECTION_NAME]
    total = col.count_documents({})
    print(f"[MongoDB] Found {total} companies in '{DB_NAME}.{COLLECTION_NAME}'")

    if total == 0:
        client.close()
        raise ValueError(
            f"Collection '{DB_NAME}.{COLLECTION_NAME}' is empty.\n"
            f"Check your MONGO_URI, DB_NAME, and COLLECTION_NAME env vars."
        )

    companies = list(col.find({}))
    client.close()
    return companies


# ─────────────────────────────────────────────
#  Google News RSS
# ─────────────────────────────────────────────
def parse_before_date(value: str | None) -> date | None:
    """Parse YYYY-MM-DD to a date. Empty value means no filter."""
    if value is None:
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    try:
        return datetime.strptime(cleaned, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(
            f"Invalid --before-date '{value}'. Expected format YYYY-MM-DD."
        ) from exc


def _is_entry_on_or_before(entry: dict, before_date: date | None) -> bool:
    if before_date is None:
        return True

    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return False

    try:
        entry_date = datetime(*parsed[:6]).date()
    except (TypeError, ValueError):
        return False

    return entry_date <= before_date


def fetch_news(company_name: str, max_articles: int = 10, before_date: date | None = None) -> list[dict]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    short_name = re.sub(
        r'\s+(Private Limited|Pvt\.? Ltd\.?|Limited|Ltd\.?|LLP|Inc\.?)$',
        '', company_name, flags=re.IGNORECASE
    ).strip()

    for _, query in [("exact", f'"{company_name}"'), ("short", short_name)]:
        query_text = f"{query} before:{before_date.isoformat()}" if before_date else query
        url = (
            "https://news.google.com/rss/search"
            f"?q={quote(query_text)}&hl=en-IN&gl=IN&ceid=IN:en"
        )
        try:
            resp = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
            feed = feedparser.parse(resp.text)
            filtered_entries = [
                e for e in feed.entries
                if _is_entry_on_or_before(e, before_date)
            ]
            if filtered_entries:
                return [
                    {
                        "title":     e.get("title", ""),
                        "link":      e.get("link", ""),
                        "source":    e.get("source", {}).get("title", "Unknown"),
                        "published": e.get("published", ""),
                        "summary":   re.sub(r"<[^>]+>", "", e.get("summary", "")).strip(),
                    }
                    for e in filtered_entries[:max_articles]
                ]
        except requests.exceptions.RequestException:
            pass
    return []


# ─────────────────────────────────────────────
#  FinBERT scoring
# ─────────────────────────────────────────────
def build_scoring_texts(company: dict, articles: list[dict]) -> list[str]:
    texts = []
    for a in articles:
        headline = a.get("title", "").strip()
        summary  = re.sub(r"<[^>]+>", "", a.get("summary", "")).strip()
        snippet  = f"{headline}. {summary}" if summary else headline
        if snippet:
            texts.append(snippet[:450])

    crisil = company.get("crisilHeading", "")
    if crisil:
        texts.append(f"CRISIL rating action: {crisil}"[:450])

    if not texts:
        name     = company.get("crisilName") or company.get("mcaName") or "Unknown"
        industry = company.get("industryName", "Unknown")
        status   = company.get("mcaCompanyStatus", "Active")
        listing  = company.get("listingStatus", "Unknown")
        capital  = company.get("mcaPaidupCapital", "N/A")
        texts.append(
            f"{name} is a {listing} {industry} company. "
            f"Status: {status}. Paid-up capital: {capital}."
        )
    return texts


def score_with_finbert(company: dict, articles: list[dict]) -> dict:
    finbert    = _get_finbert()
    texts      = build_scoring_texts(company, articles)
    news_count = len(articles)

    snippet_scores  = []
    snippet_details = []

    for text in texts:
        probs    = {r["label"]: r["score"] for r in finbert(text)[0]}
        neg      = probs.get("negative", 0.0)
        neu      = probs.get("neutral",  0.0)
        pos      = probs.get("positive", 0.0)
        stress_i = neg + 0.5 * neu
        snippet_scores.append(stress_i)
        snippet_details.append({
            "text_preview": text[:80],
            "stress":   round(stress_i, 4),
            "dominant": max(probs, key=probs.get),
        })

    weights     = np.array([2.0 if i < news_count else 1.0 for i in range(len(snippet_scores))])
    final_score = float(np.average(np.array(snippet_scores), weights=weights))
    confidence  = "high" if news_count >= 5 else ("medium" if news_count >= 2 else "low")

    ranked      = sorted(snippet_details, key=lambda d: d["stress"], reverse=True)
    key_drivers = [d["text_preview"] for d in ranked[:3] if d["stress"] > 0.4]
    if not key_drivers:
        key_drivers = [ranked[0]["text_preview"]] if ranked else ["No signal"]

    band = (
        "Severe"   if final_score >= 0.8 else
        "High"     if final_score >= 0.6 else
        "Moderate" if final_score >= 0.4 else
        "Low"      if final_score >= 0.2 else
        "Minimal"
    )

    name    = company.get("crisilName") or company.get("mcaName") or "Unknown"
    summary = (
        f"{band} financial stress detected for {name} "
        f"(FinBERT score {final_score:.2f}, {confidence} confidence, "
        f"{news_count} article(s) analysed)."
    )
    return {
        "score": round(final_score, 4), "stress_band": band,
        "confidence": confidence, "key_drivers": key_drivers, "summary": summary,
    }


# ─────────────────────────────────────────────
#  Build CSV row
# ─────────────────────────────────────────────
def _sanitize_text(text: str) -> str:
    """Remove/replace problematic Unicode characters for CSV output."""
    if not text:
        return ""
    # Replace common problematic Unicode characters with ASCII equivalents
    replacements = {
        "\u2713": "[OK]",  # Checkmark → ASCII equivalent
        "\u2014": "-",  # Em dash
        "\u2013": "-",  # En dash
        "\u201c": '"',  # Left double quote
        "\u201d": '"',  # Right double quote
        "\u2018": "'",  # Left single quote
        "\u2019": "'",  # Right single quote
        "\u2026": "...",  # Ellipsis
    }
    for unicode_char, ascii_char in replacements.items():
        text = text.replace(unicode_char, ascii_char)
    # Remove any remaining non-ASCII characters
    text = text.encode("ascii", "ignore").decode("ascii")
    return text

def build_csv_row(company: dict, articles: list[dict], result: dict, error: str = "") -> dict:
    name = company.get("crisilName") or company.get("mcaName") or "Unknown"
    row  = {
        "company_code":   company.get("companyCode", ""),
        "company_name":   _sanitize_text(name),
        "listing_status": _sanitize_text(company.get("listingStatus", "")),
        "industry":       _sanitize_text(company.get("industryName", "")),
        "stress_score":   result.get("score", ""),
        "stress_band":    _sanitize_text(str(result.get("stress_band", ""))),
        "confidence":     _sanitize_text(str(result.get("confidence", ""))),
        "key_drivers":    " | ".join(_sanitize_text(d) for d in result.get("key_drivers", [])),
        "summary":        _sanitize_text(result.get("summary", "")),
        "news_used":      len(articles),
        "scored_at":      datetime.now(timezone.utc).isoformat(),
        "error":          _sanitize_text(error),
    }
    for i in range(1, 6):
        a = articles[i - 1] if i <= len(articles) else {}
        row[f"article_{i}_title"]  = _sanitize_text(a.get("title", ""))
        row[f"article_{i}_link"]   = a.get("link", "")
        row[f"article_{i}_source"] = _sanitize_text(a.get("source", ""))
    return row


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────
def run_all(before_date: date | None = None):
    print(f"\n{'='*60}")
    print(f"  Bulk News Stress Scorer  (FinBERT)")
    if before_date:
        print(f"  News filter: only articles on or before {before_date.isoformat()}")
    print(f"{'='*60}\n")

    companies = get_all_companies()

    file_exists  = os.path.isfile(OUTPUT_CSV)
    already_done = {}  # Maps company_code -> stress_score (only if non-empty)
    if file_exists:
        with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                code = r.get("company_code", "")
                stress_score = r.get("stress_score", "").strip()
                # Only mark as done if it has a valid stress_score
                if code and stress_score:
                    already_done[code] = stress_score

        skipped = len(already_done)
        print(f"[resume] {skipped} already scored with valid stress_score — skipping.\n")

    csv_file = open(OUTPUT_CSV, "a", newline="", encoding="utf-8")
    writer   = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    if not file_exists or os.path.getsize(OUTPUT_CSV) == 0:
        writer.writeheader()
        csv_file.flush()

    errors = 0
    with tqdm(companies, desc="Scoring", unit="co", dynamic_ncols=True) as pbar:
        for company in pbar:
            code = company.get("companyCode", "")
            name = company.get("crisilName") or company.get("mcaName") or "Unknown"

            if code and code in already_done:
                pbar.set_postfix_str(f"skip {name[:28]}")
                continue

            pbar.set_postfix_str(f"-> {name[:33]}")

            try:
                articles = fetch_news(name, before_date=before_date)
                result   = score_with_finbert(company, articles)
                row      = build_csv_row(company, articles, result)
            except Exception as e:
                errors += 1
                row = build_csv_row(company, [], {}, error=str(e))
                tqdm.write(f"  [ERROR] {name}: {e}")

            writer.writerow(row)
            csv_file.flush()

    csv_file.close()
    print(f"\n{'='*60}")
    print(f"  Done. {len(companies) - len(already_done)} processed ({errors} errors).")
    print(f"  Output: {os.path.abspath(OUTPUT_CSV)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bulk news stress scorer (FinBERT)")
    parser.add_argument(
        "--before-date",
        default=NEWS_BEFORE_DATE,
        help="Only include Google RSS articles published on or before YYYY-MM-DD (default: no date filter)",
    )
    args = parser.parse_args()

    try:
        before_date = parse_before_date(args.before_date)
    except ValueError as exc:
        raise SystemExit(str(exc))

    run_all(before_date=before_date)