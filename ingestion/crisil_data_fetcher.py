import requests
from bs4 import BeautifulSoup
import pymongo
from datetime import datetime, timedelta
import time
import logging
from typing import List, Dict, Optional
import re
from urllib.parse import urljoin

import os
from dotenv import load_dotenv
import certifi

load_dotenv()

# Configuration
CONFIG = {
    "api_endpoint": os.getenv("API_ENDPOINT", "https://www.crisilratings.com/content/crisilratings/en/home/our-business/ratings/rating-rationale/_jcr_content/wrapper_100_par/ratingresultlisting.results.json?cmd=RR&start=0&limit=10000&filters={%22fromDate%22:%2201/01/2025%22,%22toDate%22:%2202/01/2026%22}&_=1770467786548"),
    "html_base_url": os.getenv("HTML_BASE_URL", "https://www.crisilratings.com/mnt/winshare/Ratings/RatingList/RatingDocs/"),
    "mongodb_uri": os.getenv("MONGO_URI") or os.getenv("MONGODB_URI", "mongodb://localhost:27017/"),
    "database_name": os.getenv("MONGO_DB") or os.getenv("DATABASE_NAME", "crisil_ratings"),
    "collection_name": os.getenv("MONGO_COLLECTION") or os.getenv("COLLECTION_NAME", "rating_reports"),
    "batch_size": int(os.getenv("BATCH_SIZE", 1)),
    # seconds between cycles
    "sleep_interval": int(os.getenv("SLEEP_INTERVAL", 1)),
    # seconds between requests
    "request_delay": int(os.getenv("REQUEST_DELAY", 1)),
}

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('crisil_scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class CrisilScraper:
    def __init__(self):
        self.mongo_client = None
        self.db = None
        self.collection = None
        self.connect_mongodb()

    def connect_mongodb(self):
        """Establish MongoDB connection"""
        try:
            self.mongo_client = pymongo.MongoClient(
                CONFIG["mongodb_uri"],
                tlsCAFile=certifi.where()
            )
            self.db = self.mongo_client[CONFIG["database_name"]]
            self.collection = self.db[CONFIG["collection_name"]]

            # Create indexes for efficient querying
            self.collection.create_index(
                [("companyCode", 1), ("ratingDate", 1)], unique=True)
            self.collection.create_index("processingStatus")
            self.collection.create_index("prId", unique=True)

            logger.info("Connected to MongoDB successfully")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise

    def make_request(self, url: str, headers: Dict, timeout: int = 30) -> requests.Response:
        """Make HTTP request with retry logic for 406 errors"""
        while True:
            try:
                response = requests.get(url, headers=headers, timeout=timeout)
                response.raise_for_status()
                return response
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 406:
                    logger.warning(
                        "Received 406 Not Acceptable. Sleeping for 10 minutes...")
                    time.sleep(600)  # Sleep for 10 minutes
                    logger.info("Retrying request after sleep...")
                    continue
                raise
            except Exception:
                raise

    def fetch_api_data(self) -> Optional[List[Dict]]:
        """Fetch rating reports list from API"""
        try:
            logger.info("Fetching data from API...")
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "en-US,en;q=0.9"
            }

            response = self.make_request(
                CONFIG["api_endpoint"], headers=headers, timeout=30)

            data = response.json()
            docs = data.get("docs", [])
            logger.info(f"Fetched {len(docs)} reports from API")
            return docs
        except Exception as e:
            logger.error(f"Error fetching API data: {e}")
            return None

    def insert_new_reports(self, reports: List[Dict]):
        """Insert new reports into MongoDB, skip duplicates"""
        inserted_count = 0
        skipped_count = 0

        for report in reports:
            try:
                # Check if report already exists
                existing = self.collection.find_one({
                    "companyCode": report.get("companyCode"),
                    "ratingDate": report.get("ratingDate")
                })

                if existing:
                    skipped_count += 1
                    continue

                # Prepare document for insertion
                # Construct full URL for ratingFileName if it exists
                rating_file_name = report.get("ratingFileName")
                if rating_file_name and not rating_file_name.startswith("http"):
                    rating_file_name = urljoin(
                        CONFIG["html_base_url"], rating_file_name)

                document = {
                    **report,
                    "ratingFileName": rating_file_name,
                    "processingStatus": "pending",
                    "processedAt": None,
                    "errorMessage": None,
                    "instruments": [],
                    "bankFacilities": [],
                    "createdAt": datetime.utcnow(),
                    "updatedAt": datetime.utcnow()
                }

                self.collection.insert_one(document)
                inserted_count += 1
                logger.info(
                    f"Inserted new report: {report.get('companyName')} - {report.get('ratingDate')}")

            except pymongo.errors.DuplicateKeyError:
                skipped_count += 1
                logger.debug(
                    f"Duplicate report skipped: {report.get('companyName')}")
            except Exception as e:
                logger.error(
                    f"Error inserting report {report.get('companyName')}: {e}")

        logger.info(
            f"Insertion complete - Inserted: {inserted_count}, Skipped: {skipped_count}")

    def parse_amount(self, amount_str: str) -> Optional[float]:
        """Parse amount string to float"""
        try:
            if not amount_str or amount_str.upper() in ['NA', 'N/A', 'NOT APPLICABLE', '']:
                return None
            # Remove commas and convert to float
            cleaned = amount_str.replace(',', '').strip()
            return float(cleaned)
        except:
            return None

    def extract_instruments_table(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract Annexure - Details of Instrument(s) table"""
        instruments = []

        try:
            # Find the table with instruments data
            # Look for text containing "Annexure - Details of Instrument"
            target_text = None
            for element in soup.find_all(['p', 'span', 'td']):
                if 'Annexure - Details of Instrument' in element.get_text():
                    target_text = element
                    break

            if not target_text:
                logger.warning("Instruments table header not found")
                return instruments

            # Find the next table after this header
            table = target_text.find_next('table')

            if not table:
                logger.warning("Instruments table not found")
                return instruments

            rows = table.find_all('tr')

            # Skip header row(s) and process data rows
            for row in rows[1:]:  # Skip first row (header)
                cols = row.find_all('td')
                if len(cols) >= 8:
                    instrument = {
                        "isin": cols[0].get_text(strip=True),
                        "instrumentName": cols[1].get_text(strip=True),
                        "allotmentDate": cols[2].get_text(strip=True),
                        "couponRate": cols[3].get_text(strip=True),
                        "maturityDate": cols[4].get_text(strip=True),
                        "issueSize": self.parse_amount(cols[5].get_text(strip=True)),
                        "complexityLevel": cols[6].get_text(strip=True),
                        "rating": cols[7].get_text(strip=True)
                    }
                    instruments.append(instrument)

            logger.info(f"Extracted {len(instruments)} instruments")

        except Exception as e:
            logger.error(f"Error extracting instruments table: {e}")

        return instruments

    def extract_bank_facilities_table(self, soup: BeautifulSoup) -> List[Dict]:
        """Extract Annexure - Details of Bank Lenders & Facilities table"""
        facilities = []

        try:
            # Find the table with bank facilities data
            target_text = None
            for element in soup.find_all(['p', 'span', 'td']):
                if 'Annexure - Details of Bank Lenders' in element.get_text():
                    target_text = element
                    break

            if not target_text:
                logger.warning("Bank facilities table header not found")
                return facilities

            # Find the next table after this header
            table = target_text.find_next('table')

            if not table:
                logger.warning("Bank facilities table not found")
                return facilities

            rows = table.find_all('tr')

            # Skip header row and process data rows
            for row in rows[1:]:  # Skip first row (header)
                # Skip rows that contain nested tables (container rows)
                if row.find('table'):
                    continue

                cols = row.find_all('td', recursive=False)

                if len(cols) < 3:
                    continue

                facility_name = cols[0].get_text(strip=True)

                # Skip header rows that might be found due to nested tables
                if "Facility" in facility_name and "Amount" in cols[1].get_text(strip=True):
                    continue

                # Handle 4-column table (Facility, Amount, Lender, Rating)
                if len(cols) >= 4:
                    facility = {
                        "facility": facility_name,
                        "amount": self.parse_amount(cols[1].get_text(strip=True)),
                        "lenderName": cols[2].get_text(strip=True),
                        "rating": cols[3].get_text(strip=True)
                    }
                    facilities.append(facility)
                # Handle 3-column table (Facility, Amount, Rating) - Missing Lender
                else:  # len(cols) == 3
                    facility = {
                        "facility": facility_name,
                        "amount": self.parse_amount(cols[1].get_text(strip=True)),
                        "lenderName": None,
                        "rating": cols[2].get_text(strip=True)
                    }
                    facilities.append(facility)

            logger.info(f"Extracted {len(facilities)} bank facilities")

        except Exception as e:
            logger.error(f"Error extracting bank facilities table: {e}")

        return facilities

    def fetch_and_parse_html(self, filename: str) -> tuple:
        """Fetch HTML report and extract tables"""
        instruments = []
        bank_facilities = []

        try:
            url = urljoin(CONFIG["html_base_url"], filename)
            logger.info(f"Fetching HTML from: {url}")
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9"
            }

            response = self.make_request(url, headers=headers, timeout=30)

            soup = BeautifulSoup(response.content, 'html.parser')

            # Extract both tables
            instruments = self.extract_instruments_table(soup)
            bank_facilities = self.extract_bank_facilities_table(soup)

        except Exception as e:
            logger.error(f"Error fetching/parsing HTML {filename}: {e}")
            raise

        return instruments, bank_facilities

    def process_pending_reports(self):
        """Process all pending reports"""
        pending_reports = self.collection.find({
            "processingStatus": "pending"
        }).limit(CONFIG["batch_size"])

        processed_count = 0

        for report in pending_reports:
            try:
                logger.info(
                    f"Processing: {report['companyName']} - {report['ratingDate']}")

                # Update status to processing
                self.collection.update_one(
                    {"_id": report["_id"]},
                    {
                        "$set": {
                            "processingStatus": "processing",
                            "updatedAt": datetime.utcnow()
                        }
                    }
                )

                # Fetch and parse HTML
                instruments, bank_facilities = self.fetch_and_parse_html(
                    report["ratingFileName"])

                # Update document with extracted data
                self.collection.update_one(
                    {"_id": report["_id"]},
                    {
                        "$set": {
                            "processingStatus": "completed",
                            "processedAt": datetime.utcnow(),
                            "instruments": instruments,
                            "bankFacilities": bank_facilities,
                            "errorMessage": None,
                            "updatedAt": datetime.utcnow()
                        }
                    }
                )

                processed_count += 1
                logger.info(f"Successfully processed: {report['companyName']}")

                # Delay between requests to be respectful
                time.sleep(CONFIG["request_delay"])

            except Exception as e:
                error_msg = str(e)
                logger.error(
                    f"Failed to process {report['companyName']}: {error_msg}")

                # Mark as failed
                self.collection.update_one(
                    {"_id": report["_id"]},
                    {
                        "$set": {
                            "processingStatus": "failed",
                            "errorMessage": error_msg,
                            "updatedAt": datetime.utcnow()
                        }
                    }
                )

        logger.info(f"Processed {processed_count} reports in this batch")
        return processed_count

    def get_statistics(self) -> Dict:
        """Get processing statistics"""
        stats = {
            "total": self.collection.count_documents({}),
            "pending": self.collection.count_documents({"processingStatus": "pending"}),
            "processing": self.collection.count_documents({"processingStatus": "processing"}),
            "completed": self.collection.count_documents({"processingStatus": "completed"}),
            "failed": self.collection.count_documents({"processingStatus": "failed"})
        }
        return stats

    def run(self):
        """Main run loop"""
        logger.info("Starting CRISIL Scraper...")

        cycle_count = 0
        start_time = time.time()
        total_processed_session = 0

        while True:
            try:
                cycle_count += 1
                logger.info(f"=== Starting Cycle {cycle_count} ===")

                # Step 1: Fetch new reports from API
                reports = self.fetch_api_data()

                if reports:
                    # Step 2: Insert new reports to MongoDB
                    self.insert_new_reports(reports)

                # Step 3: Process pending reports
                processed_count = self.process_pending_reports()
                total_processed_session += processed_count

                # Step 4: Log statistics
                stats = self.get_statistics()

                eta_msg = ""
                if total_processed_session > 0 and stats['pending'] > 0:
                    elapsed = time.time() - start_time
                    avg_rate = elapsed / total_processed_session
                    eta_seconds = stats['pending'] * avg_rate
                    eta = str(timedelta(seconds=int(eta_seconds)))
                    eta_msg = f", ETA: {eta}"

                logger.info(f"Statistics - Total: {stats['total']}, Pending: {stats['pending']}, "
                            f"Completed: {stats['completed']}, Failed: {stats['failed']}{eta_msg}")

                # Step 5: Sleep before next cycle
                logger.info(
                    f"Cycle {cycle_count} complete. Sleeping for {CONFIG['sleep_interval']} seconds...")
                time.sleep(CONFIG["sleep_interval"])

            except KeyboardInterrupt:
                logger.info(
                    "Received interrupt signal. Shutting down gracefully...")
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                logger.info("Waiting 60 seconds before retry...")
                time.sleep(60)

        # Cleanup
        if self.mongo_client:
            self.mongo_client.close()
            logger.info("MongoDB connection closed")


if __name__ == "__main__":
    scraper = CrisilScraper()
    scraper.run()
