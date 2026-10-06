"""Brand Analytics Search Query Performance (SQP): fetch weekly report, store CSV, pick keywords.

Schema: amzn/selling-partner-api-models schemas/reports/sellingPartnerSearchQueryPerformanceReport.json
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import json
import time
from collections import defaultdict
from pathlib import Path

from . import http

SQP_FILE = "sqp_asin_weekly.csv"
REPORT_TYPE = "GET_BRAND_ANALYTICS_SEARCH_QUERY_PERFORMANCE_REPORT"
COLUMNS = [
    "marketplace_id", "week_start", "week_end", "asin", "search_query",
    "search_query_score", "search_query_volume",
    "total_impressions", "asin_impressions", "asin_impression_share",
    "total_clicks", "asin_clicks", "asin_click_share",
    "total_cart_adds", "asin_cart_adds",
    "total_purchases", "asin_purchases", "asin_purchase_share",
    "retrieved_at", "source_operation", "value_type",
]


def last_complete_week(today: dt.date) -> tuple:
    """Most recent Sunday..Saturday week that has fully ended before today."""
    days_since_sat = (today.weekday() - 5) % 7 or 7
    end = today - dt.timedelta(days=days_since_sat)
    return end - dt.timedelta(days=6), end


def asin_batches(asins: list, limit: int = 200) -> list:
    """SQP takes a space-separated ASIN list capped at 200 characters."""
    batches, cur = [], []
    for a in sorted(asins):
        if cur and len(" ".join(cur + [a])) > limit:
            batches.append(cur)
            cur = []
        cur.append(a)
    if cur:
        batches.append(cur)
    return batches


class SpApi:
    def __init__(self, cfg):
        self.cfg = cfg
        self._token = None
        self._token_exp = 0.0

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        from urllib.parse import urlencode
        resp = http.request_json(
            "POST", "https://api.amazon.com/auth/o2/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=urlencode({
                "grant_type": "refresh_token",
                "refresh_token": self.cfg.spapi_refresh_token,
                "client_id": self.cfg.lwa_client_id,
                "client_secret": self.cfg.lwa_client_secret,
            }),
        )
        self._token = resp["access_token"]
        self._token_exp = time.time() + int(resp.get("expires_in", 3600))
        return self._token

    def call(self, method: str, path: str, body=None):
        return http.request_json(
            method, self.cfg.spapi_endpoint + path,
            headers={"x-amz-access-token": self._access_token()}, body=body,
        )

    def run_report(self, report_type: str, start: dt.date, end: dt.date, options: dict) -> list:
        rep = self.call("POST", "/reports/2021-06-30/reports", {
            "reportType": report_type,
            "marketplaceIds": [self.cfg.marketplace_id],
            "dataStartTime": start.isoformat(),
            "dataEndTime": end.isoformat(),
            "reportOptions": options,
        })
        report_id = rep["reportId"]
        deadline = time.time() + 1800
        while True:
            status = self.call("GET", f"/reports/2021-06-30/reports/{report_id}")
            state = status["processingStatus"]
            if state == "DONE":
                break
            if state in ("CANCELLED", "FATAL"):
                raise RuntimeError(f"SQP report {report_id} {state} for {start}..{end} (data may not be published yet)")
            if time.time() > deadline:
                raise RuntimeError(f"SQP report {report_id} timed out")
            time.sleep(30)
        doc = self.call("GET", f"/reports/2021-06-30/documents/{status['reportDocumentId']}")
        raw = http.download(doc["url"])
        if doc.get("compressionAlgorithm") == "GZIP":
            raw = gzip.decompress(raw)
        return json.loads(raw.decode()).get("dataByAsin", [])


def flatten(record: dict, marketplace_id: str, retrieved_at: str) -> dict:
    q = record.get("searchQueryData", {})
    imp = record.get("impressionData", {})
    clk = record.get("clickData", {})
    cart = record.get("cartAddData", {})
    pur = record.get("purchaseData", {})
    return {
        "marketplace_id": marketplace_id,
        "week_start": record.get("startDate"),
        "week_end": record.get("endDate"),
        "asin": record.get("asin"),
        "search_query": (q.get("searchQuery") or "").strip().lower(),
        "search_query_score": q.get("searchQueryScore"),
        "search_query_volume": q.get("searchQueryVolume"),
        "total_impressions": imp.get("totalQueryImpressionCount"),
        "asin_impressions": imp.get("asinImpressionCount"),
        "asin_impression_share": imp.get("asinImpressionShare"),
        "total_clicks": clk.get("totalClickCount"),
        "asin_clicks": clk.get("asinClickCount"),
        "asin_click_share": clk.get("asinClickShare"),
        "total_cart_adds": cart.get("totalCartAddCount"),
        "asin_cart_adds": cart.get("asinCartAddCount"),
        "total_purchases": pur.get("totalPurchaseCount"),
        "asin_purchases": pur.get("asinPurchaseCount"),
        "asin_purchase_share": pur.get("asinPurchaseShare"),
        "retrieved_at": retrieved_at,
        "source_operation": "createReport:" + REPORT_TYPE,
        "value_type": "reported",
    }


def read_rows(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def upsert(path: Path, new_rows: list) -> None:
    """Replace any existing rows for the weeks in new_rows, keep the rest."""
    weeks = {r["week_start"] for r in new_rows}
    keep = [r for r in read_rows(path) if r["week_start"] not in weeks]
    rows = keep + new_rows
    rows.sort(key=lambda r: (r["week_start"], r["asin"], r["search_query"]))
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def fetch_week(cfg, asins: list, start: dt.date, end: dt.date) -> int:
    api = SpApi(cfg)
    retrieved_at = dt.datetime.now().isoformat(timespec="seconds")
    rows = []
    for batch in asin_batches(asins):
        data = api.run_report(REPORT_TYPE, start, end, {"reportPeriod": "WEEK", "asin": " ".join(batch)})
        rows.extend(flatten(r, cfg.marketplace_id, retrieved_at) for r in data)
    upsert(cfg.sync_exports_dir / SQP_FILE, rows)
    return len(rows)


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def select_keywords(rows: list, weeks: int, per_asin: int, max_keywords: int, exclude_terms: list) -> tuple:
    """Pick each ASIN's top SQP queries over the last `weeks` weeks.

    Per ASIN, queries are ranked by ASIN purchases, then ASIN clicks, then search volume,
    so we track the terms that actually bring that product traffic and sales.
    Returns ({keyword: {"asins": set, "volume": float}}, (first_week, last_week)).
    """
    all_weeks = sorted({r["week_start"] for r in rows})
    window = set(all_weeks[-weeks:])
    if not window:
        return {}, (None, None)
    excl = [t.lower() for t in exclude_terms]

    per = defaultdict(lambda: {"purchases": 0.0, "clicks": 0.0, "impressions": 0.0, "volume": 0.0})
    for r in rows:
        if r["week_start"] not in window:
            continue
        q = r["search_query"]
        if not q or any(t in q for t in excl):
            continue
        agg = per[(r["asin"], q)]
        agg["purchases"] += _num(r["asin_purchases"])
        agg["clicks"] += _num(r["asin_clicks"])
        agg["impressions"] += _num(r["asin_impressions"])
        agg["volume"] += _num(r["search_query_volume"])

    by_asin = defaultdict(list)
    for (asin, q), agg in per.items():
        if agg["impressions"] > 0:
            by_asin[asin].append((q, agg))

    chosen = {}
    for asin, items in by_asin.items():
        items.sort(key=lambda x: (-x[1]["purchases"], -x[1]["clicks"], -x[1]["volume"], x[0]))
        for q, agg in items[:per_asin]:
            k = chosen.setdefault(q, {"asins": set(), "volume": 0.0})
            k["asins"].add(asin)
            k["volume"] = max(k["volume"], agg["volume"] / len(window))

    if len(chosen) > max_keywords:
        top = sorted(chosen.items(), key=lambda kv: (-kv[1]["volume"], kv[0]))[:max_keywords]
        chosen = dict(top)
    span = sorted(window)
    last_end = max(r["week_end"] for r in rows if r["week_start"] == span[-1])
    return chosen, (span[0], last_end)
