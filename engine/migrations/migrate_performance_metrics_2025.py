"""
migrate_performance_metrics_2025.py
------------------------------------
Copies the "2025" performance metrics object from `financial_kg.performance_metrics`
into the matching document in `financial_kg.banks` under the key `performanceMetrics`.

Steps:
  1. Build an explicit, verified name-mapping between the two collections.
  2. For each mapping look up the 2025 data in performance_metrics.
  3. Write it to the banks document.
  4. Run a validator to confirm all 41 banks received the data.
"""

import os
from pymongo import MongoClient
from datetime import datetime, timezone

# load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── connection ──────────────────────────────────────────────────────────────
MONGO_URI = os.environ.get(
    "MONGO_URI",
    "mongodb+srv://prabirkalwani:prabirkalwani%40123@maincluster.tvef4tx.mongodb.net/"
)
DB_NAME   = "financial_kg"

client = MongoClient(MONGO_URI)
db     = client[DB_NAME]
banks_col   = db["banks"]
metrics_col = db["performance_metrics"]

# ── explicit name mapping ────────────────────────────────────────────────────
# key   = bankName in banks collection
# value = Bank Name in performance_metrics collection
NAME_MAP = {
    "State Bank of India":           "State Bank of India (SBI)",
    "HDFC Bank Limited":             "HDFC Bank Ltd.",
    "ICICI Bank Limited":            "ICICI Bank Ltd.",
    "Bank of Baroda":                "Bank of Baroda",
    "Bank of India":                 "Bank of India",
    "Bank of Maharashtra":           "Bank of Maharashtra",
    "Canara Bank":                   "Canara Bank",
    "Central Bank of India":         "Central Bank of India",
    "Indian Bank":                   "Indian Bank",
    "Indian Overseas Bank":          "Indian Overseas Bank",
    "Punjab & Sind Bank":            "Punjab & Sind Bank",
    "Punjab National Bank":          "Punjab National Bank",
    "UCO Bank":                      "UCO Bank",
    "Union Bank of India":           "Union Bank of India",
    "Axis Bank Limited":             "Axis Bank Ltd.",
    "Bandhan Bank Limited":          "Bandhan Bank",
    "City Union Bank Limited":       "City Union Bank Ltd.",
    "CSB Bank Limited":              "CSB Bank Ltd.",
    "DCB Bank Limited":              "DCB Bank Ltd.",
    "Dhanlaxmi Bank Limited":        "Dhanlaxmi Bank Ltd",
    "Federal Bank Ltd":              "The Federal Bank Ltd.",
    "IDBI Bank Limited":             "IDBI Ltd.",
    "IDFC First Bank Limited":       "IDFC First Bank Ltd.",
    "IndusInd Bank Ltd":             "Indusind Bank Ltd.",
    "Jammu & Kashmir Bank Ltd":      "The Jammu & Kashmir Bank Ltd.",
    "Karnataka Bank Ltd":            "The Karnataka Bank Ltd.",
    "Karur Vysya Bank Ltd":          "The Karur Vysya Bank Ltd.",
    "Kotak Mahindra Bank Ltd":       "Kotak Mahindra Bank Ltd.",
    "RBL Bank Ltd":                  "RBL Bank",
    "South Indian Bank Ltd":         "The South Indian Bank Ltd.",
    "Tamilnad Mercantile Bank Ltd":  "Tamilnad Mercantile Bank Ltd.",
    "Yes Bank Ltd":                  "YES Bank",
    "AU Small Finance Bank Limited": "Au Small Finance Bank Ltd.",
    "Capital Small Finance Bank Limited":  "Capital Small Finance Bank Ltd.",
    "Equitas Small Finance Bank Limited":  "Equitas Small Finance Bank Ltd.",
    "ESAF Small Finance Bank Limited":     "ESAF Small Finance Bank Ltd.",
    "Jana Small Finance Bank Limited":     "Jana Small Finance Bank Ltd.",
    "Suryoday Small Finance Bank Limited": "Suryoday Small Finance Bank Ltd.",
    "Ujjivan Small Finance Bank Limited":  "Ujjivan Small Finance Bank Ltd.",
    "Utkarsh Small Finance Bank Limited":  "Utkarsh Small Finance Bank Ltd.",
    "Fino Payments Bank Limited":          "Fino Payments Bank Ltd.",
}

# ── sanity-check mapping size ────────────────────────────────────────────────
assert len(NAME_MAP) == 41, f"Expected 41 entries in NAME_MAP, got {len(NAME_MAP)}"


def migrate():
    migrated   = []
    not_found  = []    # performance_metrics doc missing for a bank
    no_2025    = []    # doc found but no 2025 key

    for bank_name, pm_name in NAME_MAP.items():
        # fetch the performance_metrics document
        pm_doc = metrics_col.find_one({"Bank Name": pm_name})
        if pm_doc is None:
            not_found.append((bank_name, pm_name))
            continue

        data_2025 = pm_doc.get("2025")
        if data_2025 is None:
            no_2025.append((bank_name, pm_name))
            continue

        # write to banks collection
        result = banks_col.update_one(
            {"bankName": bank_name},
            {
                "$set": {
                    "performanceMetrics.2025": data_2025,
                    "lastUpdated": datetime.now(timezone.utc).isoformat(),
                }
            },
        )

        if result.matched_count == 1:
            migrated.append(bank_name)
        else:
            not_found.append((bank_name, f"[banks doc not found for: {bank_name}]"))

    # ── report ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"  MIGRATION COMPLETE — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("=" * 60)
    print(f"\n✅  Migrated : {len(migrated)}")
    for b in migrated:
        print(f"      • {b}")

    if not_found:
        print(f"\n❌  Not found ({len(not_found)}):")
        for bank_name, pm_name in not_found:
            print(f"      • [{bank_name}] ← looked for [{pm_name}]")

    if no_2025:
        print(f"\n⚠️   No 2025 data ({len(no_2025)}):")
        for bank_name, pm_name in no_2025:
            print(f"      • [{bank_name}] ← [{pm_name}]")

    return migrated, not_found, no_2025


def validate():
    """Confirm all 41 banks in the banks collection have performanceMetrics.2025."""
    print("\n" + "=" * 60)
    print("  VALIDATION")
    print("=" * 60)

    all_banks = list(banks_col.find({}, {"bankName": 1, "performanceMetrics": 1}))
    total     = len(all_banks)
    has_2025  = []
    missing   = []

    for doc in all_banks:
        bname = doc.get("bankName", str(doc["_id"]))
        pm    = doc.get("performanceMetrics", {})
        if pm and "2025" in pm:
            has_2025.append(bname)
        else:
            missing.append(bname)

    print(f"\nTotal banks in collection : {total}")
    print(f"Banks with 2025 data       : {len(has_2025)}  ✅")
    print(f"Banks still missing        : {len(missing)}")

    if missing:
        print("\nMissing:")
        for b in missing:
            print(f"   ⚠️  {b}")
    else:
        print("\n🎉  All 41 banks have 2025 performance metrics data!")

    return len(has_2025), len(missing)


if __name__ == "__main__":
    migrated, not_found, no_2025 = migrate()
    validate()
    client.close()
