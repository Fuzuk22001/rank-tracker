"""Assisi Style ASIN list and product families, read from the SP-API sync's sku_map.csv."""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path


def family_of(item_name: str) -> str:
    # "Assisi Style Vegan Leather Belt for Men, Cork Belt 38mm, Brown" -> "Vegan Leather Belt for Men"
    stem = item_name.split(",")[0].strip()
    if stem.lower().startswith("assisi style "):
        stem = stem[len("assisi style "):]
    return stem


def load_catalog(sync_dir: Path, marketplace_id: str) -> dict:
    """Return {asin: family}. Every ASIN in sku_map counts as an Assisi ASIN."""
    names = defaultdict(Counter)
    with open(sync_dir / "sku_map.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["marketplace_id"] != marketplace_id or not row["asin"]:
                continue
            names[row["asin"]][family_of(row["item_name"])] += 1
    return {asin: c.most_common(1)[0][0] for asin, c in names.items()}
