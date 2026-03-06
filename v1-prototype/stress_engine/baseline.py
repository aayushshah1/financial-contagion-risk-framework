"""
stress_engine/baseline.py
MongoDB CRUD for rolling 60-day sentiment baselines.

Documents are stored in  financial_kg.news_baselines  with the schema:
    {
        "entity_id":   str,        # bankSymbol | cin | rbiCategory | industryCode
        "entity_type": str,        # "bank" | "company" | "priority_sector" | "industry"
        "date":        str,        # ISO-8601 date string "YYYY-MM-DD"
        "daily_score": float,      # decay-weighted aggregate for that day
    }
A compound unique index on (entity_id, entity_type, date) prevents duplicates.

Usage
-----
    from stress_engine.baseline import BaselineStore

    store = BaselineStore()
    store.upsert_daily("HDFCBANK", "bank", date(2026, 3, 4), 0.32)
    mean, std, n = store.get_baseline("HDFCBANK", "bank", window_days=60)
    store.close()

    # Or as a context manager
    with BaselineStore() as store:
        mean, std, n = store.get_baseline("HDFCBANK", "bank")
"""

from __future__ import annotations

import logging
import statistics
from datetime import date, timedelta
from typing import Tuple

from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError

from .config import MONGODB_URI, DB_NAME, BASELINE_COLLECTION, BASELINE_WINDOW_DAYS

logger = logging.getLogger(__name__)


class BaselineStore:
    """Thin wrapper around the MongoDB ``news_baselines`` collection."""

    def __init__(self, mongo_uri: str = MONGODB_URI, db_name: str = DB_NAME):
        if not mongo_uri:
            raise EnvironmentError(
                "db_cluster_link must be set in the environment / .env file."
            )
        self._client = MongoClient(
            mongo_uri,
            serverSelectionTimeoutMS=10_000,
            connectTimeoutMS=10_000,
        )
        self._col = self._client[db_name][BASELINE_COLLECTION]
        self._ensure_index()

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------

    def _ensure_index(self) -> None:
        """Create the compound unique index if it does not exist."""
        self._col.create_index(
            [("entity_id", ASCENDING), ("entity_type", ASCENDING), ("date", ASCENDING)],
            unique=True,
            name="entity_date_unique",
        )

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert_daily(
        self,
        entity_id: str,
        entity_type: str,
        record_date: date,
        daily_score: float,
    ) -> None:
        """
        Insert or update today's aggregate score for an entity.

        Parameters
        ----------
        entity_id   : str   — e.g. "HDFCBANK", a company CIN, "agriculture"
        entity_type : str   — one of "bank", "company", "priority_sector", "industry"
        record_date : date  — the date the score represents (usually today)
        daily_score : float — decay-weighted aggregate sentiment score
        """
        date_str = record_date.isoformat()
        try:
            self._col.update_one(
                {
                    "entity_id": entity_id,
                    "entity_type": entity_type,
                    "date": date_str,
                },
                {
                    "$set": {
                        "entity_id": entity_id,
                        "entity_type": entity_type,
                        "date": date_str,
                        "daily_score": daily_score,
                    }
                },
                upsert=True,
            )
        except DuplicateKeyError:
            logger.debug(
                "Duplicate key on upsert for %s/%s/%s — skipped.", entity_id, entity_type, date_str
            )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_baseline(
        self,
        entity_id: str,
        entity_type: str,
        window_days: int = BASELINE_WINDOW_DAYS,
    ) -> Tuple[float, float, int]:
        """
        Retrieve rolling statistics for an entity.

        Returns
        -------
        (mean, std, n)
            mean : float — rolling mean of daily_score over the window
            std  : float — rolling sample std-dev (0.0 if n < 2)
            n    : int   — number of data points available in the window
        """
        cutoff = (date.today() - timedelta(days=window_days)).isoformat()
        docs = list(
            self._col.find(
                {
                    "entity_id": entity_id,
                    "entity_type": entity_type,
                    "date": {"$gte": cutoff},
                },
                {"daily_score": 1, "_id": 0},
            )
        )
        scores = [d["daily_score"] for d in docs]
        n = len(scores)
        if n == 0:
            return 0.0, 1.0, 0
        mean = statistics.mean(scores)
        std = statistics.stdev(scores) if n > 1 else 0.0
        return mean, std, n

    def get_history_count(self, entity_id: str, entity_type: str) -> int:
        """Return the total number of daily records persisted for this entity."""
        return self._col.count_documents(
            {"entity_id": entity_id, "entity_type": entity_type}
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
