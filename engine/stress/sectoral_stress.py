"""
sectoral_stress_pipeline.py
────────────────────────────────────────────────────────────────────────────────
Two-signal sectoral stress pipeline for Indian markets:

  Signal 1 - News (Groq LLM):  Google News RSS -> llama-3.1-8b-instant -> 0-1
  Signal 2 - Market (yfinance): Nifty sector indices -> return / vol /
                                 drawdown -> 0-1

  Final score = 0.5 x news_score + 0.5 x market_score
  Falls back to news_score alone when no yfinance ticker is mapped.

Output CSV (158 industry rows):
  industry_name | macro_sector | final_stress_score | risk_tier |
  news_score | market_score | market_return_30d | market_volatility_30d |
  drawdown_from_52w_high | articles_used | top_headline | scored_at

Rate limiting:
  Groq free tier = 30 RPM  ->  min 2 s between calls.
  CALL_DELAY is hardcoded to 2 s.

Usage:
    python sectoral_stress_pipeline.py                # reads .env for GROQ_API_KEY
    python sectoral_stress_pipeline.py --dry-run      # dummy scores, no API calls
    python sectoral_stress_pipeline.py --model llama-3.3-70b-versatile
    python sectoral_stress_pipeline.py --output march_scores.csv
    python sectoral_stress_pipeline.py --before-date 2026-01-31

Requirements:
    pip install requests yfinance python-dotenv
--------------------------------------------------------------------------------
"""

import argparse
import csv
import json
import os
import random
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, date
from email.utils import parsedate_to_datetime

import requests
import yfinance as yf
from dotenv import load_dotenv

# ---- 0. CONSTANTS ------------------------------------------------------------

# Hardcoded to 2 s  --  minimum safe interval for Groq's 30 RPM free-tier limit.
# 30 RPM = 1 req / 2 s. Do NOT reduce below 2.0 or you will get 429 errors.
CALL_DELAY: float = 2.0

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
NEWS_BEFORE_DATE = os.environ.get("NEWS_BEFORE_DATE", "").strip() or None

# ---- 1. TAXONOMY: granular industry -> macro sector --------------------------

TAXONOMY: dict[str, str] = {
    # Banking & Financial Services
    "Private Sector Bank":                    "Banking & Financial Services",
    "Non Banking Financial Company (NBFC)":   "Banking & Financial Services",
    "Housing Finance Company":                "Banking & Financial Services",
    "Microfinance Institutions":              "Banking & Financial Services",
    "Financial Institution":                  "Banking & Financial Services",
    "Asset Management Company":               "Banking & Financial Services",
    "Stockbroking & Allied":                  "Banking & Financial Services",
    "Other Capital Market related Services":  "Banking & Financial Services",
    "Other Financial Services":               "Banking & Financial Services",
    "Investment Company":                     "Banking & Financial Services",
    # Energy
    "Oil Exploration & Production":           "Energy",
    "Refineries & Marketing":                 "Energy",
    "Oil Equipment & Services":               "Energy",
    "Oil Storage & Transportation":           "Energy",
    "LPG/CNG/PNG/LNG Supplier":               "Energy",
    "Power Generation":                       "Energy",
    "Integrated Power Utilities":             "Energy",
    "Power Distribution":                     "Energy",
    "Power Trading":                          "Energy",
    "Power - Transmission":                   "Energy",
    "Other Utilities":                        "Energy",
    "Offshore Support Solution Drilling":     "Energy",
    # Metals & Mining
    "Iron & Steel":                           "Metals & Mining",
    "Iron & Steel Products":                  "Metals & Mining",
    "Aluminium":                              "Metals & Mining",
    "Copper":                                 "Metals & Mining",
    "Zinc":                                   "Metals & Mining",
    "Diversified Metals":                     "Metals & Mining",
    "Ferro & Silica Manganese":               "Metals & Mining",
    "Sponge Iron":                            "Metals & Mining",
    "Pig Iron":                               "Metals & Mining",
    "Precious Metals":                        "Metals & Mining",
    "Coal":                                   "Metals & Mining",
    "Trading - Metals":                       "Metals & Mining",
    "Trading - Minerals":                     "Metals & Mining",
    "Industrial Minerals":                    "Metals & Mining",
    "Aluminium, Copper & Zinc Products":      "Metals & Mining",
    "Trading - Coal":                         "Metals & Mining",
    # Automobiles & Auto Components
    "Passenger Cars & Utility Vehicles":      "Automobiles & Auto Components",
    "Commercial Vehicles":                    "Automobiles & Auto Components",
    "2/3 Wheelers":                           "Automobiles & Auto Components",
    "Auto Components & Equipments":           "Automobiles & Auto Components",
    "Tractors":                               "Automobiles & Auto Components",
    "Auto Dealer":                            "Automobiles & Auto Components",
    "Dealers-Commercial Vehicles, Tractors, Construction Vehicles": "Automobiles & Auto Components",
    "Trading - Auto Components":              "Automobiles & Auto Components",
    "Cycles":                                 "Automobiles & Auto Components",
    "Tyres & Rubber Products":                "Automobiles & Auto Components",
    # Pharmaceuticals & Healthcare
    "Pharmaceuticals":                        "Pharmaceuticals & Healthcare",
    "Biotechnology":                          "Pharmaceuticals & Healthcare",
    "Healthcare Service Provider":            "Pharmaceuticals & Healthcare",
    "Medical Equipment & Supplies":           "Pharmaceuticals & Healthcare",
    "Healthcare Research, Analytics & Technology": "Pharmaceuticals & Healthcare",
    "Hospital":                               "Pharmaceuticals & Healthcare",
    # IT & Technology
    "Computers - Software & Consulting":      "IT & Technology",
    "IT Enabled Services":                    "IT & Technology",
    "Business Process Outsourcing (BPO)/ Knowledge Process Outsourcing (KPO)": "IT & Technology",
    "Data Processing Services":               "IT & Technology",
    "Computers Hardware & Equipments":        "IT & Technology",
    "Telecom - Equipment & Accessories":      "IT & Technology",
    "Telecom - Cellular & Fixed line services": "IT & Technology",
    "Telecom - Infrastructure":               "IT & Technology",
    "Consulting Services":                    "IT & Technology",
    # Chemicals & Petrochemicals
    "Specialty Chemicals":                    "Chemicals & Petrochemicals",
    "Commodity Chemicals":                    "Chemicals & Petrochemicals",
    "Petrochemicals":                         "Chemicals & Petrochemicals",
    "Dyes And Pigments":                      "Chemicals & Petrochemicals",
    "Pesticides & Agrochemicals":             "Chemicals & Petrochemicals",
    "Fertilizers":                            "Chemicals & Petrochemicals",
    "Carbon Black":                           "Chemicals & Petrochemicals",
    "Explosives":                             "Chemicals & Petrochemicals",
    "Industrial Gases":                       "Chemicals & Petrochemicals",
    "Lubricants":                             "Chemicals & Petrochemicals",
    "Paints":                                 "Chemicals & Petrochemicals",
    "Trading - Chemicals":                    "Chemicals & Petrochemicals",
    # FMCG & Consumer Goods
    "Diversified FMCG":                       "FMCG & Consumer Goods",
    "Packaged Foods":                         "FMCG & Consumer Goods",
    "Other Food Products":                    "FMCG & Consumer Goods",
    "Personal Care":                          "FMCG & Consumer Goods",
    "Household Products":                     "FMCG & Consumer Goods",
    "Household Appliances":                   "FMCG & Consumer Goods",
    "Consumer Electronics":                   "FMCG & Consumer Goods",
    "Diversified Retail":                     "FMCG & Consumer Goods",
    "Speciality Retail":                      "FMCG & Consumer Goods",
    "Houseware":                              "FMCG & Consumer Goods",
    "Stationary":                             "FMCG & Consumer Goods",
    "Leisure Products":                       "FMCG & Consumer Goods",
    # Infrastructure & Construction
    "Civil Construction":                     "Infrastructure & Construction",
    "Cement & Cement Products":               "Infrastructure & Construction",
    "Road Assets-Toll, Annuity, Hybrid-Annuity": "Infrastructure & Construction",
    "Road Transport":                         "Infrastructure & Construction",
    "Other Construction Materials":           "Infrastructure & Construction",
    "Airport & Airport services":             "Infrastructure & Construction",
    "Railway Wagons":                         "Infrastructure & Construction",
    "Water Supply & Management":              "Infrastructure & Construction",
    "Dredging":                               "Infrastructure & Construction",
    "Waste Management":                       "Infrastructure & Construction",
    "Other Electrical Equipment":             "Infrastructure & Construction",
    "Electrodes & Refractories":              "Infrastructure & Construction",
    # Real Estate
    "Real Estate Investment Trusts (REITs)":  "Real Estate",
    "Real Estate related services":           "Real Estate",
    "Residential, Commercial Projects":       "Real Estate",
    "Furniture, Home Furnishing":             "Real Estate",
    "Granites & Marbles":                     "Real Estate",
    "Plywood Boards/ Laminates":              "Real Estate",
    "Ceramics":                               "Real Estate",
    # Media & Entertainment
    "Media & Entertainment":                  "Media & Entertainment",
    "TV Broadcasting & Software Production":  "Media & Entertainment",
    "Film Production, Distribution & Exhibition": "Media & Entertainment",
    "Print Media":                            "Media & Entertainment",
    "Advertising & Media Agencies":           "Media & Entertainment",
    "Printing & Publication":                 "Media & Entertainment",
    "Amusement Parks/ Other Recreation":      "Media & Entertainment",
    "Other Consumer Services":                "Media & Entertainment",
    # Agriculture & Food Processing
    "Sugar":                                  "Agriculture & Food Processing",
    "Tea & Coffee":                           "Agriculture & Food Processing",
    "Edible Oil":                             "Agriculture & Food Processing",
    "Dairy Products":                         "Agriculture & Food Processing",
    "Seafood":                                "Agriculture & Food Processing",
    "Meat Products including Poultry":        "Agriculture & Food Processing",
    "Animal Feed":                            "Agriculture & Food Processing",
    "Other Agricultural Products":            "Agriculture & Food Processing",
    "Other Beverages":                        "Agriculture & Food Processing",
    "Breweries & Distilleries":               "Agriculture & Food Processing",
    "Cigarettes & Tobacco Products":          "Agriculture & Food Processing",
    "Restaurants":                            "Agriculture & Food Processing",
    # Logistics & Transport
    "Logistics Solution Provider":            "Logistics & Transport",
    "Shipping":                               "Logistics & Transport",
    "Transport Related Services":             "Logistics & Transport",
    "Tour, Travel Related Services":          "Logistics & Transport",
    "Airline":                                "Logistics & Transport",
    # Textiles & Apparel
    "Garments & Apparels":                    "Textiles & Apparel",
    "Other Textile Products":                 "Textiles & Apparel",
    "Trading - Textile Products":             "Textiles & Apparel",
    "Leather And Leather Products":           "Textiles & Apparel",
    "Jute & Jute Products":                   "Textiles & Apparel",
    "Footwear":                               "Textiles & Apparel",
    "Rubber":                                 "Textiles & Apparel",
    # Capital Goods & Industrials
    "Heavy Electrical Equipment":             "Capital Goods & Industrials",
    "Compressors, Pumps & Diesel Engines":    "Capital Goods & Industrials",
    "Castings & Forgings":                    "Capital Goods & Industrials",
    "Abrasives & Bearings":                   "Capital Goods & Industrials",
    "Industrial Products":                    "Capital Goods & Industrials",
    "Other Industrial Products":              "Capital Goods & Industrials",
    "Aerospace & Defense":                    "Capital Goods & Industrials",
    "Plastic Products - Industrial":          "Capital Goods & Industrials",
    "Plastic Products - Consumer":            "Capital Goods & Industrials",
    "Packaging":                              "Capital Goods & Industrials",
    "Paper & Paper Products":                 "Capital Goods & Industrials",
    "Cables - Electricals":                   "Capital Goods & Industrials",
    # Gems, Jewellery & Luxury
    "Gems, Jewellery And Watches":            "Gems, Jewellery & Luxury",
    "Hotels & Resorts":                       "Gems, Jewellery & Luxury",
    "Education":                              "Gems, Jewellery & Luxury",
    # Diversified / Conglomerates
    "Diversified":                            "Diversified / Conglomerates",
    "Diversified Commercial Services":        "Diversified / Conglomerates",
    "Trading & Distributors":                 "Diversified / Conglomerates",
    "Distributors":                           "Diversified / Conglomerates",
}

# ---- 2. MACRO SECTOR -> NEWS KEYWORDS ----------------------------------------

MACRO_KEYWORDS: dict[str, list[str]] = {
    "Banking & Financial Services":    ["India banking sector news", "RBI NBFC news India"],
    "Energy":                          ["India oil gas sector news", "India power sector news"],
    "Metals & Mining":                 ["India steel metals sector", "India mining industry news"],
    "Automobiles & Auto Components":   ["India automobile sector news", "India auto industry"],
    "Pharmaceuticals & Healthcare":    ["India pharma sector news", "Indian healthcare industry"],
    "IT & Technology":                 ["India IT sector news", "Indian tech telecom industry"],
    "Chemicals & Petrochemicals":      ["India chemicals sector news", "India agrochemicals fertilizers"],
    "FMCG & Consumer Goods":           ["India FMCG sector news", "Indian consumer goods retail"],
    "Infrastructure & Construction":   ["India infrastructure construction news", "India cement roads"],
    "Real Estate":                     ["India real estate sector news", "India property REIT market"],
    "Media & Entertainment":           ["India media entertainment news", "India OTT broadcasting"],
    "Agriculture & Food Processing":   ["India agriculture food sector", "India agri commodity news"],
    "Logistics & Transport":           ["India logistics aviation shipping news", "India transport freight"],
    "Textiles & Apparel":              ["India textile apparel sector", "India garments export news"],
    "Capital Goods & Industrials":     ["India capital goods manufacturing", "India defense aerospace"],
    "Gems, Jewellery & Luxury":        ["India gems jewellery sector", "India gold luxury hospitality"],
    "Diversified / Conglomerates":     ["India conglomerates trading sector", "Indian diversified companies"],
}

# ---- 3. MACRO SECTOR -> YFINANCE NIFTY INDEX TICKERS -------------------------
#
# Official NSE sector indices available on Yahoo Finance.
# None = no direct index; pipeline uses news score only for that sector.

SECTOR_TICKERS: dict[str, str | None] = {
    "Banking & Financial Services":    "^NSEBANK",   # Nifty Bank
    "Energy":                          "^CNXENERGY", # Nifty Energy
    "Metals & Mining":                 "^CNXMETAL",  # Nifty Metal
    "Automobiles & Auto Components":   "^CNXAUTO",   # Nifty Auto
    "Pharmaceuticals & Healthcare":    "^CNXPHARMA", # Nifty Pharma
    "IT & Technology":                 "^CNXIT",     # Nifty IT
    "Chemicals & Petrochemicals":      None,         # No direct Nifty index
    "FMCG & Consumer Goods":           "^CNXFMCG",  # Nifty FMCG
    "Infrastructure & Construction":   "^CNXINFRA",  # Nifty Infra
    "Real Estate":                     "^CNXREALTY", # Nifty Realty
    "Media & Entertainment":           "^CNXMEDIA",  # Nifty Media
    "Agriculture & Food Processing":   None,         # No direct Nifty index
    "Logistics & Transport":           None,         # No direct Nifty index
    "Textiles & Apparel":              None,         # No direct Nifty index
    "Capital Goods & Industrials":     "^CNXCMDT",  # Nifty Commodities as proxy
    "Gems, Jewellery & Luxury":        None,         # No direct Nifty index
    "Diversified / Conglomerates":     "^CNX500",    # Nifty 500 broad proxy
}

# ---- 4. RISK TIER ------------------------------------------------------------

RISK_TIERS = [
    (0.00, 0.20, "Minimal"),
    (0.20, 0.40, "Low"),
    (0.40, 0.55, "Moderate"),
    (0.55, 0.70, "Elevated"),
    (0.70, 0.85, "High"),
    (0.85, 1.01, "Critical"),
]

def score_to_tier(score: float) -> str:
    for lo, hi, label in RISK_TIERS:
        if lo <= score < hi:
            return label
    return "Unknown"

# ---- 5. GOOGLE NEWS RSS FETCHER ----------------------------------------------

RSS_URL = "https://news.google.com/rss/search?q={query}+India&hl=en-IN&gl=IN&ceid=IN:en"

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


def _is_item_on_or_before(item: ET.Element, before_date: date | None) -> bool:
    if before_date is None:
        return True

    pub_date = (item.findtext("pubDate") or "").strip()
    if not pub_date:
        return False

    try:
        return parsedate_to_datetime(pub_date).date() <= before_date
    except (TypeError, ValueError):
        return False


def fetch_headlines(
    keywords: list[str],
    max_articles: int = 6,
    before_date: date | None = None,
) -> list[str]:
    headlines, seen = [], set()
    for kw in keywords:
        try:
            query = f"{kw} before:{before_date.isoformat()}" if before_date else kw
            url  = RSS_URL.format(query=requests.utils.quote(query))
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item"):
                if not _is_item_on_or_before(item, before_date):
                    continue
                t = (item.findtext("title") or "").strip()
                if t and t not in seen:
                    seen.add(t)
                    headlines.append(t)
                if len(headlines) >= max_articles:
                    break
        except Exception as e:
            print(f"    WARNING  RSS fetch failed for '{kw}': {e}")
        if len(headlines) >= max_articles:
            break
    return headlines[:max_articles]

# ---- 6. YFINANCE MARKET STRESS SCORER ----------------------------------------
#
# Three sub-signals, each normalised to [0, 1]:
#   a) 30-day return      : -25% -> 1.0 ;  +10% -> 0.0
#   b) 30-day ann. vol    :  45% -> 1.0 ;   8%  -> 0.0
#   c) Drawdown from 52w high: 35% -> 1.0 ;  0%  -> 0.0
#
# market_score = mean(a, b, c)

RETURN_BOUNDS   = (-0.25,  0.10)
VOL_BOUNDS      = ( 0.08,  0.45)
DRAWDOWN_BOUNDS = ( 0.00,  0.35)

def _norm(value: float, lo: float, hi: float, invert: bool = False) -> float:
    n = max(0.0, min(1.0, (value - lo) / (hi - lo)))
    return (1.0 - n) if invert else n

def fetch_market_stress(ticker: str) -> dict:
    empty = {
        "market_score": None,
        "market_return_30d": None,
        "market_volatility_30d": None,
        "drawdown_from_52w_high": None,
    }
    try:
        hist = yf.Ticker(ticker).history(period="1y")
        if hist.empty or len(hist) < 10:
            print(f"    WARNING  yfinance: insufficient data for {ticker}")
            return empty

        close   = hist["Close"]
        recent  = close.iloc[-1]
        past    = close.iloc[-min(22, len(close))]   # ~22 trading days = 1 month
        ret_30  = (recent - past) / past

        daily_ret = close.pct_change().dropna()
        vol_30    = daily_ret.iloc[-22:].std() * (252 ** 0.5)

        high_52w = close.max()
        drawdown = (high_52w - recent) / high_52w

        # Lower return = higher stress (invert return normalisation)
        s_return   = _norm(ret_30,   RETURN_BOUNDS[1],   RETURN_BOUNDS[0])
        s_vol      = _norm(vol_30,   VOL_BOUNDS[0],      VOL_BOUNDS[1])
        s_drawdown = _norm(drawdown, DRAWDOWN_BOUNDS[0], DRAWDOWN_BOUNDS[1])

        return {
            "market_score":           round((s_return + s_vol + s_drawdown) / 3, 4),
            "market_return_30d":      round(float(ret_30),   4),
            "market_volatility_30d":  round(float(vol_30),   4),
            "drawdown_from_52w_high": round(float(drawdown), 4),
        }
    except Exception as e:
        print(f"    WARNING  yfinance error for {ticker}: {e}")
        return empty

# ---- 7. GROQ NEWS STRESS SCORER ----------------------------------------------

SYSTEM_PROMPT = (
    "You are a financial stress analyst specializing in the Indian market.\n"
    "Given a set of news headlines for a sector, output a single JSON object with:\n"
    "  - stress_score: float between 0.0 (no stress) and 1.0 (extreme stress)\n"
    "  - reasoning: one concise sentence explaining the score\n\n"
    "Rules:\n"
    "- Negative/crisis headlines -> higher score (0.6-1.0)\n"
    "- Neutral/mixed headlines   -> moderate score (0.3-0.6)\n"
    "- Positive/growth headlines -> lower score (0.0-0.3)\n"
    "- Output ONLY valid JSON. No markdown. No explanation outside JSON."
)

def score_with_groq(sector: str, headlines: list[str], model: str, api_key: str) -> tuple[float, str]:
    raw = ""
    news_block = "\n".join(f"- {h}" for h in headlines) if headlines else "No recent news available."
    prompt = f"Sector: {sector}\n\nRecent headlines:\n{news_block}\n\nReturn JSON only."

    payload = {
        "model":       model,
        "messages":    [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        "temperature": 0.2,
    }
    print(f"    [Groq payload]\n{json.dumps(payload, indent=2)}")

    try:
        resp = requests.post(
            GROQ_API_URL,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        print(f"    [Groq response] {raw}")
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        parsed = json.loads(raw)
        score  = max(0.0, min(1.0, float(parsed.get("stress_score", 0.5))))
        reason = str(parsed.get("reasoning", ""))
        return round(score, 4), reason
    except requests.HTTPError:
        print(f"    WARNING  Groq HTTP {resp.status_code} for '{sector}': {resp.text[:200]}")
        return 0.5, f"HTTP error {resp.status_code}"
    except json.JSONDecodeError as e:
        print(f"    WARNING  JSON parse error for '{sector}': {e} | raw: {raw[:120]}")
        return 0.5, "Parse error - defaulted to 0.5"
    except Exception as e:
        print(f"    WARNING  Groq error for '{sector}': {e}")
        return 0.5, f"Error: {str(e)[:80]}"

# ---- 8. DUMMY SCORER (--dry-run) ---------------------------------------------

random.seed(42)
_DRY_SCORES: dict[str, float] = {}

def _dry_score(sector: str) -> float:
    if sector not in _DRY_SCORES:
        _DRY_SCORES[sector] = round(random.uniform(0.1, 0.9), 4)
    return _DRY_SCORES[sector]

# ---- 9. MAIN PIPELINE --------------------------------------------------------

CSV_COLUMNS = [
    "industry_name",
    "macro_sector",
    "final_stress_score",
    "risk_tier",
    "news_score",
    "market_score",
    "market_return_30d",
    "market_volatility_30d",
    "drawdown_from_52w_high",
    "articles_used",
    "top_headline",
    "scored_at",
]

def run_pipeline(
    model:   str  = "llama-3.1-8b-instant",
    output:  str  = "sectoral_stress_scores.csv",
    api_key: str  = "",
    dry_run: bool = False,
    before_date: date | None = None,
):
    macro_sectors = list(MACRO_KEYWORDS.keys())
    scored_sectors: dict[str, dict] = {}
    est_mins = round((len(macro_sectors) * CALL_DELAY) / 60, 1)

    print(f"\n{'='*64}")
    print(f"  Sectoral Stress Pipeline  -  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Mode      : {'DRY RUN' if dry_run else f'Groq ({model}) + yfinance'}")
    print(f"  Sectors   : {len(macro_sectors)}")
    print(f"  Call delay: {CALL_DELAY}s  (30 RPM Groq limit)")
    print(f"  News filter: {'on or before ' + before_date.isoformat() if before_date else 'none'}")
    print(f"  Est. time : ~{est_mins} min")
    print(f"  Output    : {output}")
    print(f"{'='*64}\n")

    last_groq_call: float = 0.0

    for i, sector in enumerate(macro_sectors, 1):
        print(f"[{i:02d}/{len(macro_sectors)}] {sector}")

        # -- News score --------------------------------------------------------
        if dry_run:
            headlines  = [f"[Dry run] Headline {j+1} for {sector}" for j in range(3)]
            news_score = _dry_score(sector)
            reasoning  = "Dry-run dummy score"
        else:
            print(f"    -> Fetching news ...")
            headlines = fetch_headlines(
                MACRO_KEYWORDS[sector],
                max_articles=6,
                before_date=before_date,
            )
            print(f"    -> {len(headlines)} headlines fetched")

            elapsed = time.time() - last_groq_call
            wait    = CALL_DELAY - elapsed
            if wait > 0:
                print(f"    [wait] Rate limit: {wait:.1f}s ...")
                time.sleep(wait)

            print(f"    -> Groq scoring ...")
            news_score, reasoning = score_with_groq(sector, headlines, model, api_key)
            last_groq_call = time.time()

        # -- Market score (yfinance) -------------------------------------------
        ticker = SECTOR_TICKERS.get(sector)
        if dry_run or ticker is None:
            if not dry_run and ticker is None:
                print(f"    [info] No yfinance ticker for this sector - news score only")
            mdata = {
                "market_score": None,
                "market_return_30d": None,
                "market_volatility_30d": None,
                "drawdown_from_52w_high": None,
            }
        else:
            print(f"    -> yfinance {ticker} ...")
            mdata = fetch_market_stress(ticker)

        # -- Blend -------------------------------------------------------------
        if mdata["market_score"] is not None:
            final      = round(0.5 * news_score + 0.5 * mdata["market_score"], 4)
            blend_note = f"news={news_score:.3f}  market={mdata['market_score']:.3f}"
        else:
            final      = news_score
            blend_note = f"news={news_score:.3f}  market=N/A"

        tier = score_to_tier(final)
        print(f"    OK  final={final:.4f}  [{tier}]  ({blend_note})")

        scored_sectors[sector] = {
            "final_stress_score":     final,
            "risk_tier":              tier,
            "news_score":             news_score,
            "market_score":           mdata["market_score"],
            "market_return_30d":      mdata["market_return_30d"],
            "market_volatility_30d":  mdata["market_volatility_30d"],
            "drawdown_from_52w_high": mdata["drawdown_from_52w_high"],
            "articles_used":          len(headlines),
            "top_headline":           headlines[0] if headlines else "",
        }

    # -- Build rows for all 158 industries -------------------------------------
    now  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    rows = []

    for industry, macro in TAXONOMY.items():
        s = scored_sectors.get(macro, {})
        rows.append({
            "industry_name":          industry,
            "macro_sector":           macro,
            "final_stress_score":     s.get("final_stress_score",     ""),
            "risk_tier":              s.get("risk_tier",               ""),
            "news_score":             s.get("news_score",              ""),
            "market_score":           s.get("market_score",            ""),
            "market_return_30d":      s.get("market_return_30d",       ""),
            "market_volatility_30d":  s.get("market_volatility_30d",   ""),
            "drawdown_from_52w_high": s.get("drawdown_from_52w_high",  ""),
            "articles_used":          s.get("articles_used",           0),
            "top_headline":           s.get("top_headline",            ""),
            "scored_at":              now,
        })

    # null industry row (BSE has one null entry)
    rows.append({
        "industry_name": "", "macro_sector": "Unclassified",
        "final_stress_score": "", "risk_tier": "", "news_score": "",
        "market_score": "", "market_return_30d": "",
        "market_volatility_30d": "", "drawdown_from_52w_high": "",
        "articles_used": 0, "top_headline": "", "scored_at": now,
    })

    rows.sort(
        key=lambda r: float(r["final_stress_score"]) if r["final_stress_score"] != "" else -1,
        reverse=True,
    )

    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n{'='*64}")
    print(f"  OK  Wrote {len(rows)} rows -> {output}")
    print(f"\n  Top stressed sectors (final blended score):")
    seen: set = set()
    for r in rows:
        macro = r["macro_sector"]
        if macro not in seen and r["final_stress_score"] != "":
            seen.add(macro)
            ms = f"  mkt={float(r['market_score']):.3f}" if r["market_score"] not in ("", None) else "  mkt=N/A"
            print(f"    {float(r['final_stress_score']):.4f}  [{r['risk_tier']:<10}]  {macro}{ms}")
    print(f"{'='*64}\n")

# ---- 10. ENTRY POINT ---------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sectoral stress pipeline -> CSV (Groq + yfinance)")
    parser.add_argument("--model",   default="llama-3.1-8b-instant",       help="Groq model (default: llama-3.1-8b-instant)")
    parser.add_argument("--output",  default="sectoral_stress_scores.csv", help="Output CSV path")
    parser.add_argument("--dry-run", action="store_true",                  help="Skip all API calls, use dummy scores")
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

    load_dotenv()
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key and not args.dry_run:
        raise SystemExit("ERROR  GROQ_API_KEY not found. Add it to your .env file.")

    run_pipeline(
        model   = args.model,
        output  = args.output,
        api_key = api_key,
        dry_run = args.dry_run,
        before_date = before_date,
    )