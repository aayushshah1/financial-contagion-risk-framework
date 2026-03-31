"""
master_stress_pipeline.py
=========================
Orchestrates all stress computation pipelines and updates MongoDB documents.

Modes:
  all           (default) - Run all 3 pipelines:
                  1. Entity stress for companies
                  2. News stress for companies
                  3. News stress for banks

  bank-news-only        - Run only news stress for banks

  sectors               - Run sectoral stress pipeline:
                  Creates/updates 'sectors' collection with macro sector stress values

Usage:
    python master_stress_pipeline.py --uri mongodb://localhost:27017 --db financial_kg
    python master_stress_pipeline.py --mode bank-news-only
    python master_stress_pipeline.py --mode sectors
    python master_stress_pipeline.py --mode sectors --dry-run
    python master_stress_pipeline.py --news-before-date 2026-01-31
"""

import subprocess
import csv
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment
load_dotenv(dotenv_path=os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env'),
    override=True)


class MasterStressPipeline:
    def __init__(self, mongo_uri, db_name, news_before_date: str | None = None):
        self.mongo_uri = mongo_uri
        self.db_name = db_name
        self.news_before_date = self._validate_before_date(news_before_date)
        self.script_dir = Path(__file__).parent
        self.project_root = self.script_dir.parent.parent
        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]

    @staticmethod
    def _validate_before_date(before_date: str | None) -> str | None:
        """Validate optional YYYY-MM-DD date string used by news fetchers."""
        if before_date is None:
            return None

        cleaned = before_date.strip()
        if not cleaned:
            return None

        try:
            datetime.strptime(cleaned, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(
                f"Invalid --news-before-date '{before_date}'. Expected format YYYY-MM-DD."
            ) from exc

        return cleaned

    def log(self, msg: str, level: str = "INFO"):
        """Print formatted log message."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] [{level}] {msg}")

    def run_entity_stress_pipeline(self):
        """
        Run entity_stress_pipeline.py for companies collection.
        Updates company documents with entity_stress_fundamental.
        """
        self.log("=" * 70)
        self.log("STEP 1: Running Entity Stress Pipeline (Companies)")
        self.log("=" * 70)

        output_csv = self.project_root / "data" / "outputs" / "entity_stress_scores.csv"
        output_csv.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable,
            str(self.script_dir / "entity_stress_pipeline.py"),
            "--uri", self.mongo_uri,
            "--db", self.db_name,
            "--col", "companies",
            "--out", str(output_csv),
        ]

        self.log(f"Running: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(result.stdout)
            if result.stderr:
                print(result.stderr)
        except subprocess.CalledProcessError as e:
            self.log(f"Entity stress pipeline failed: {e}", "ERROR")
            print(e.stdout)
            print(e.stderr)
            return False

        # Parse CSV and update MongoDB
        self.log(f"Updating MongoDB companies with entity_stress_fundamental...")
        updated_count = self._update_companies_from_csv(
            output_csv, "stressScore", "entity_stress_fundamental"
        )
        self.log(f"Updated {updated_count} companies with entity_stress_fundamental")

        return True

    def run_news_stress_pipeline_companies(self):
        """
        Run news_data_fetcher_stress_mapper.py for companies collection.
        Updates company documents with news_stress.
        """
        self.log("=" * 70)
        self.log("STEP 2: Running News Stress Pipeline (Companies)")
        self.log("=" * 70)

        output_csv = self.project_root / "stress_scores.csv"

        # Set environment variables for the news pipeline
        env = os.environ.copy()
        env["MONGO_URI"] = self.mongo_uri
        env["DB_NAME"] = self.db_name
        env["COLLECTION_NAME"] = "companies"
        env["OUTPUT_CSV"] = str(output_csv)
        if self.news_before_date:
            env["NEWS_BEFORE_DATE"] = self.news_before_date

        cmd = [
            sys.executable,
            str(self.script_dir / "news_data_fetcher_stress_mapper.py"),
        ]
        if self.news_before_date:
            cmd.extend(["--before-date", self.news_before_date])

        self.log(f"Running: {' '.join(cmd)}")
        self.log(
            "Environment: "
            f"MONGO_URI={self.mongo_uri}, DB_NAME={self.db_name}, "
            f"COLLECTION_NAME=companies, OUTPUT_CSV={output_csv}, "
            f"NEWS_BEFORE_DATE={self.news_before_date or 'none'}"
        )

        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
            print(result.stdout)
            if result.stderr:
                print(result.stderr)
        except subprocess.CalledProcessError as e:
            self.log(f"News stress pipeline (companies) failed: {e}", "ERROR")
            print(e.stdout)
            print(e.stderr)
            return False

        # Parse CSV and update MongoDB
        if output_csv.exists():
            self.log(f"Updating MongoDB companies with news_stress...")
            updated_count = self._update_companies_from_csv(
                output_csv, "stress_score", "news_stress"
            )
            self.log(f"Updated {updated_count} companies with news_stress")
        else:
            self.log(f"Output CSV not found: {output_csv}", "WARN")
            return False

        return True

    def run_news_stress_pipeline_banks(self):
        """
        Run news stress pipeline directly on banks collection.
        Fetches news about each bank and updates bank.news_stress.

        Since news_data_fetcher_stress_mapper.py expects companyCode,
        we create a temporary collection with proper field mappings.
        """
        self.log("=" * 70)
        self.log("STEP 3: Running News Stress Pipeline (Banks)")
        self.log("=" * 70)

        # Step 1: Extract and transform banks for scoring
        self.log("Extracting banks for news stress scoring...")
        banks_for_scoring = self._transform_banks_for_scoring()

        if not banks_for_scoring:
            self.log("No banks found in banks collection", "WARN")
            return False

        self.log(f"Found {len(banks_for_scoring)} banks")

        # Step 2: Create temporary collection
        temp_col_name = "banks_temp_scoring"
        temp_col = self.db[temp_col_name]
        temp_col.delete_many({})
        temp_col.insert_many(banks_for_scoring)
        self.log(f"Created temporary collection '{temp_col_name}' with {len(banks_for_scoring)} banks")

        # Step 3: Run news stress mapper on temporary collection
        output_csv = self.project_root / "stress_scores_banks.csv"

        env = os.environ.copy()
        env["MONGO_URI"] = self.mongo_uri
        env["DB_NAME"] = self.db_name
        env["COLLECTION_NAME"] = temp_col_name
        env["OUTPUT_CSV"] = str(output_csv)
        if self.news_before_date:
            env["NEWS_BEFORE_DATE"] = self.news_before_date

        cmd = [
            sys.executable,
            str(self.script_dir / "news_data_fetcher_stress_mapper.py"),
        ]
        if self.news_before_date:
            cmd.extend(["--before-date", self.news_before_date])

        self.log(f"Running news stress pipeline on banks...")
        self.log(f"Command: {' '.join(cmd)}")

        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env, timeout=3600)
            print(result.stdout)
            if result.stderr:
                print(result.stderr)
        except subprocess.CalledProcessError as e:
            self.log(f"News stress pipeline (banks) failed: {e}", "ERROR")
            print(e.stdout)
            print(e.stderr)
            temp_col.drop()
            return False
        except subprocess.TimeoutExpired:
            self.log("News stress pipeline (banks) timed out after 1 hour", "ERROR")
            temp_col.drop()
            return False

        # Step 4: Parse CSV and update banks collection
        if output_csv.exists():
            self.log("Updating MongoDB banks with news_stress...")
            updated_count = self._update_banks_from_csv_by_symbol(
                output_csv, "stress_score", "news_stress"
            )
            self.log(f"Updated {updated_count} banks with news_stress")
        else:
            self.log(f"Output CSV not found: {output_csv}", "WARN")
            temp_col.drop()
            return False

        # Step 5: Cleanup
        temp_col.drop()
        self.log(f"Cleaned up temporary collection '{temp_col_name}'")

        return True

    def _transform_banks_for_scoring(self) -> list[dict]:
        """
        Extract banks from banks collection and transform them
        to have companyCode field (mapped from bankSymbol) for compatibility
        with news_data_fetcher_stress_mapper.py.

        Only includes actual banks based on heuristics:
        - Must have bankSymbol field
        - bankSymbol should be 2-15 uppercase letters (bank tickers)
        - Should have advances field (actual banks have lending data)

        Returns:
            List of transformed bank documents
        """
        # Fallback bank names for symbols that might not have crisilName
        BANK_NAMES = {
            "SBIN": "State Bank of India",
            "HDFCBANK": "HDFC Bank Limited",
            "ICICIBANK": "ICICI Bank Limited",
            "BANKBARODA": "Bank of Baroda",
            "BANKINDIA": "Bank of India",
            "MAHABANK": "Maharashtra Bank",
            "CANBK": "Canara Bank",
            "CENTRALBK": "Central Bank of India",
            "INDIANB": "Indian Bank",
            "IOB": "Indian Overseas Bank",
            "PSB": "Punjab & Sind Bank",
            "PNB": "Punjab National Bank",
            "UCOBANK": "UCO Bank",
            "UNIONBANK": "Union Bank of India",
            "AXISBANK": "Axis Bank Limited",
            "BANDHANBNK": "Bandhan Bank Limited",
            "CUB": "City Union Bank",
            "CSBBANK": "CSB Bank Limited",
            "DCBBANK": "DCB Bank Limited",
            "DHANBANK": "Dhanlaxmi Bank",
            "FEDERALBNK": "Federal Bank",
            "IDBI": "IDBI Bank Limited",
            "IDFCFIRSTB": "IDFC FIRST Bank",
            "INDUSINDBK": "IndusInd Bank Limited",
            "KTKBANK": "Kotak Mahindra Bank",
            "KARURVYSYA": "Karur Vysya Bank",
            "KOTAKBANK": "Kotak Mahindra Bank Limited",
            "RBLBANK": "RBL Bank Limited",
            "SOUTHBANK": "South Indian Bank",
            "TMB": "Tamilnad Mercantile Bank",
            "YESBANK": "Yes Bank Limited",
            "AUBANK": "AU Small Finance Bank",
            "CAPITALSFB": "Capital Small Finance Bank",
            "EQUITASBNK": "Equitas Small Finance Bank",
            "ESAFSFB": "ESAF Small Finance Bank",
            "JSFB": "Jammu & Kashmir Bank",
            "SURYODAY": "Suryoday Small Finance Bank",
            "UJJIVANSFB": "Ujjivan Small Finance Bank",
            "UTKARSHBNK": "Utkarsh Small Finance Bank",
            "FINOPB": "Fino Payments Bank",
        }

        banks_col = self.db["banks"]
        transformed = []

        try:
            banks = list(banks_col.find({"advances": {"$exists": True}}))
            self.log(f"Found {len(banks)} documents with advances field", "DEBUG")

            for bank in banks:
                bank_symbol = bank.get("bankSymbol", "").strip()

                if not bank_symbol:
                    continue

                # Filter out company codes masquerading as bank symbols
                # Bank symbols are typically 2-15 uppercase letters (e.g., SBIN, HDFC, JSFB)
                # Company codes often have different patterns (all lowercase, numbers, longer)
                is_likely_bank = (
                    len(bank_symbol) >= 2 and
                    len(bank_symbol) <= 15 and
                    bank_symbol.isupper() and
                    bank_symbol.isalpha()  # Only letters, no digits or special chars
                )

                if not is_likely_bank:
                    self.log(f"Skipping non-bank entry: {bank_symbol}", "DEBUG")
                    continue

                # Use proper bank name for news fetching (important for fetch_news to work)
                bank_name = (
                    bank.get("crisilName") or
                    BANK_NAMES.get(bank_symbol) or
                    bank_symbol
                )

                # Transform bank doc for scoring
                transformed_bank = {
                    "companyCode": bank_symbol,  # Map bankSymbol to companyCode
                    "bankSymbol": bank_symbol,   # Keep original too
                    "crisilName": bank_name,     # Use proper name for news fetching
                    "mcaName": bank_name,
                    "listingStatus": bank.get("listingStatus", "Listed"),
                    "industryName": "Banking & Financial Services",
                    "_original_id": bank.get("_id"),
                }
                transformed.append(transformed_bank)

            self.log(f"Transformed {len(transformed)} valid banks for scoring", "DEBUG")
            return transformed

        except Exception as e:
            self.log(f"Error transforming banks: {e}", "ERROR")
            return []

    def _update_banks_from_csv_by_symbol(self, csv_path: Path, csv_column: str, db_field: str) -> int:
        """
        Read CSV output (which has companyCode = bankSymbol) and update
        banks collection using bankSymbol as the match key.

        Args:
            csv_path: Path to CSV created by stress pipeline
            csv_column: Column name in CSV (e.g., "stress_score")
            db_field: Database field to update (e.g., "news_stress")

        Returns:
            Number of banks updated
        """
        col = self.db["banks"]
        updated = 0
        csv_banks = []  # Track what was in CSV

        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # In the CSV, companyCode contains the bankSymbol
                    bank_symbol = row.get("company_code", "").strip()
                    stress_value = row.get(csv_column)

                    csv_banks.append(bank_symbol)  # Track for debugging

                    if not bank_symbol or stress_value is None or stress_value == "":
                        self.log(f"Skipping empty entry: {bank_symbol}", "DEBUG")
                        continue

                    try:
                        stress_value = float(stress_value)
                    except ValueError:
                        self.log(f"Invalid stress value for bank {bank_symbol}: {stress_value}", "WARN")
                        continue

                    # Update bank by bankSymbol
                    result = col.update_one(
                        {"bankSymbol": bank_symbol},
                        {"$set": {db_field: stress_value}}
                    )

                    if result.matched_count > 0:
                        updated += 1
                        if result.modified_count == 0:
                            self.log(f"No change (already had value): {bank_symbol}", "DEBUG")
                        else:
                            self.log(f"Updated bank: {bank_symbol} = {stress_value}", "DEBUG")
                    else:
                        # This should rarely happen now due to filtering in _transform_banks_for_scoring
                        self.log(f"Bank not found in DB: {bank_symbol}", "DEBUG")

            # Summary debugging
            self.log(f"CSV contained {len(csv_banks)} banks: {csv_banks[:5]}... (showing first 5)", "DEBUG")

        except FileNotFoundError:
            self.log(f"CSV file not found: {csv_path}", "ERROR")
        except Exception as e:
            self.log(f"Error reading CSV {csv_path}: {e}", "ERROR")

        return updated


    def _update_companies_from_csv(self, csv_path: Path, csv_column: str, db_field: str) -> int:
        """
        Read CSV output and update company documents in MongoDB.

        Args:
            csv_path: Path to CSV created by stress pipeline
            csv_column: Column name in CSV (e.g., "stressScore", "stress_score")
            db_field: Database field to update (e.g., "entity_stress_fundamental", "news_stress")

        Returns:
            Number of documents updated
        """
        col = self.db["companies"]
        updated = 0

        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    company_code = row.get("company_code") or row.get("companyCode")
                    stress_value = row.get(csv_column)

                    if not company_code or stress_value is None or stress_value == "":
                        continue

                    try:
                        stress_value = float(stress_value)
                    except ValueError:
                        self.log(f"Invalid stress value for {company_code}: {stress_value}", "WARN")
                        continue

                    result = col.update_one(
                        {"companyCode": company_code},
                        {"$set": {db_field: stress_value}}
                    )

                    if result.matched_count > 0:
                        updated += 1
                        if result.modified_count == 0:
                            self.log(f"No change: {company_code}", "DEBUG")

        except FileNotFoundError:
            self.log(f"CSV file not found: {csv_path}", "ERROR")
        except Exception as e:
            self.log(f"Error reading CSV {csv_path}: {e}", "ERROR")

        return updated

    def run_sectoral_stress_pipeline(self, dry_run: bool = False):
        """
        Run sectoral_stress.py and update sectors collection in MongoDB.
        Creates or updates macro sector documents.
        """
        self.log("=" * 70)
        self.log("SECTORAL STRESS PIPELINE")
        self.log("=" * 70)

        output_csv = self.project_root / "sectoral_stress_scores.csv"
        output_csv.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable,
            str(self.script_dir / "sectoral_stress.py"),
            "--output", str(output_csv),
        ]

        if self.news_before_date:
            cmd.extend(["--before-date", self.news_before_date])

        if dry_run:
            cmd.append("--dry-run")
            self.log("Running in DRY-RUN mode (no API calls)")

        self.log(f"Running: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(result.stdout)
            if result.stderr:
                print(result.stderr)
        except subprocess.CalledProcessError as e:
            self.log(f"Sectoral stress pipeline failed: {e}", "ERROR")
            print(e.stdout)
            print(e.stderr)
            return False

        # Parse CSV and update/create sectors collection
        self.log(f"Updating MongoDB 'sectors' collection...")
        updated_count, created_count = self._update_sectors_from_csv(output_csv)
        self.log(f"Sectors collection updated: {updated_count} updated, {created_count} created")

        return True

    def _update_sectors_from_csv(self, csv_path: Path) -> tuple[int, int]:
        """
        Read sectoral stress CSV and create/update sector documents in MongoDB.
        Uses macro_sector as the document identifier.

        Returns:
            (updated_count, created_count)
        """
        col = self.db["sectors"]
        updated = 0
        created = 0

        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    macro_sector = row.get("macro_sector", "").strip()

                    # Skip empty sectors
                    if not macro_sector or macro_sector == "Unclassified":
                        continue

                    # Build sector document
                    sector_doc = {
                        "macro_sector": macro_sector,
                        "final_stress_score": self._parse_float(row.get("final_stress_score")),
                        "risk_tier": row.get("risk_tier", ""),
                        "news_score": self._parse_float(row.get("news_score")),
                        "market_score": self._parse_float(row.get("market_score")),
                        "market_return_30d": self._parse_float(row.get("market_return_30d")),
                        "market_volatility_30d": self._parse_float(row.get("market_volatility_30d")),
                        "drawdown_from_52w_high": self._parse_float(row.get("drawdown_from_52w_high")),
                        "articles_used": self._parse_int(row.get("articles_used")),
                        "top_headline": row.get("top_headline", ""),
                        "scored_at": row.get("scored_at", ""),
                        "updated_at": datetime.utcnow().isoformat(),
                    }

                    # Upsert: update if exists, create if not
                    result = col.update_one(
                        {"macro_sector": macro_sector},
                        {"$set": sector_doc},
                        upsert=True
                    )

                    if result.upserted_id:
                        created += 1
                        self.log(f"Created sector: {macro_sector}", "DEBUG")
                    elif result.modified_count > 0:
                        updated += 1
                        self.log(f"Updated sector: {macro_sector}", "DEBUG")

        except FileNotFoundError:
            self.log(f"CSV file not found: {csv_path}", "ERROR")
        except Exception as e:
            self.log(f"Error reading CSV {csv_path}: {e}", "ERROR")

        return updated, created

    def _parse_float(self, val) -> float | None:
        """Safely parse float values."""
        if val is None or val == "" or val == "nan":
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _parse_int(self, val) -> int:
        """Safely parse int values."""
        if val is None or val == "":
            return 0
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return 0

    def run_all(self, mode: str = "all", dry_run: bool = False):
        """
        Execute stress computation pipelines based on mode.

        Args:
            mode: "all", "bank-news-only", or "sectors"
            dry_run: For sectors mode, skip API calls
        """
        self.log("Starting Master Stress Pipeline")
        self.log(f"MongoDB: {self.mongo_uri}  DB: {self.db_name}")
        self.log(f"Mode: {mode}")
        self.log(f"News before date filter: {self.news_before_date or 'none'}")

        results = {}

        if mode == "all":
            steps = [
                ("Entity Stress (Companies)", self.run_entity_stress_pipeline),
                ("News Stress (Companies)", self.run_news_stress_pipeline_companies),
                ("News Stress (Banks)", self.run_news_stress_pipeline_banks),
            ]
            for step_name, step_func in steps:
                try:
                    success = step_func()
                    results[step_name] = "✅ OK" if success else "❌ FAILED"
                except Exception as e:
                    self.log(f"Unexpected error in {step_name}: {e}", "ERROR")
                    results[step_name] = "❌ ERROR"

        elif mode == "bank-news-only":
            try:
                success = self.run_news_stress_pipeline_banks()
                results["News Stress (Banks)"] = "✅ OK" if success else "❌ FAILED"
            except Exception as e:
                self.log(f"Unexpected error in News Stress (Banks): {e}", "ERROR")
                results["News Stress (Banks)"] = "❌ ERROR"

        elif mode == "sectors":
            try:
                success = self.run_sectoral_stress_pipeline(dry_run=dry_run)
                results["Sectoral Stress"] = "✅ OK" if success else "❌ FAILED"
            except Exception as e:
                self.log(f"Unexpected error in Sectoral Stress: {e}", "ERROR")
                results["Sectoral Stress"] = "❌ ERROR"

        else:
            self.log(f"Unknown mode: {mode}", "ERROR")
            return False

        # Summary
        self.log("=" * 70)
        self.log("SUMMARY")
        self.log("=" * 70)
        for step_name, status in results.items():
            print(f"  {step_name:<40} {status}")
        self.log("=" * 70)

        return all("✅" in v for v in results.values())


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Master Stress Pipeline Orchestrator")
    ap.add_argument(
        "--uri",
        default=os.environ.get("MONGO_URI", "mongodb://localhost:27017"),
        help="MongoDB connection URI"
    )
    ap.add_argument(
        "--db",
        default=os.environ.get("MONGO_DB", "financial_kg"),
        help="MongoDB database name"
    )
    ap.add_argument(
        "--mode",
        choices=["all", "bank-news-only", "sectors"],
        default="all",
        help="Pipeline mode to run (default: all)"
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="For sectors mode: skip API calls and use dummy scores"
    )
    ap.add_argument(
        "--news-before-date",
        default=os.environ.get("NEWS_BEFORE_DATE", ""),
        help="Only include Google RSS articles published on or before YYYY-MM-DD (default: no date filter)",
    )
    a = ap.parse_args()

    pipeline = MasterStressPipeline(a.uri, a.db, news_before_date=a.news_before_date)
    success = pipeline.run_all(mode=a.mode, dry_run=a.dry_run)
    sys.exit(0 if success else 1)
