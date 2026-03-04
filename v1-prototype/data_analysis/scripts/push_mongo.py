#!/usr/bin/env python3
"""Push data/mca_records.json into MongoDB collection 'mca data' in DB 'company'.

Usage:
  python scripts/push_mca_to_mongo.py [--file PATH] [--uri URI] [--batch N]

Defaults:
  --file: ../data/mca_records.json (relative to this script)
  --uri: mongodb://127.0.0.1:27108/?directConnection=true
  --batch: 1000
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Iterable, List

from pymongo import MongoClient


logger = logging.getLogger("push_mca")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def read_json_file(path: Path) -> List[dict]:
    """Read JSON from path. Supports a top-level array, single object, or newline-delimited JSON objects."""
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # single object -> wrap
            return [data]
    except json.JSONDecodeError:
        # fallback to line-delimited JSON
        docs = []
        for i, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                docs.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.error("Failed to parse JSON on line %d: %s", i, e)
                raise
        return docs
    raise ValueError("Unsupported JSON structure in %s" % path)


def chunked(iterable: List[dict], size: int) -> Iterable[List[dict]]:
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]


def push_to_mongo(uri: str, db_name: str, coll_name: str, docs: List[dict], batch: int = 1000) -> int:
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    # quick ping to ensure connection
    client.admin.command("ping")
    db = client[db_name]
    coll = db[coll_name]
    total = 0
    for chunk in chunked(docs, batch):
        if not chunk:
            continue
        result = coll.insert_many(chunk)
        total += len(result.inserted_ids)
        logger.info("Inserted %d documents (total %d)", len(result.inserted_ids), total)
    return total


def main() -> None:
    p = argparse.ArgumentParser()
    default_file = Path(__file__).resolve().parent.parent / "outputs" / "crisil_mca_reconciled.json"
    p.add_argument("--file", "-f", default=str(default_file), help="Path to mca_records.json")
    p.add_argument(
        "--uri",
        "-u",
        default="mongodb://127.0.0.1:27108/?directConnection=true",
        help="MongoDB connection URI",
    )
    p.add_argument("--batch", "-b", type=int, default=1000, help="Batch insert size")
    args = p.parse_args()

    path = Path(args.file)
    if not path.exists():
        logger.error("File not found: %s", path)
        raise SystemExit(1)

    logger.info("Reading JSON from %s", path)
    docs = read_json_file(path)
    if not docs:
        logger.info("No documents found in input. Exiting.")
        return

    logger.info("Connecting to MongoDB at %s", args.uri)
    try:
        count = push_to_mongo(args.uri, "company", "mca_crisil_match", docs, batch=args.batch)
    except Exception as e:
        logger.error("Failed to push to MongoDB: %s", e)
        raise SystemExit(1)

    logger.info("Finished. Total documents inserted: %d", count)


if __name__ == "__main__":
    main()
