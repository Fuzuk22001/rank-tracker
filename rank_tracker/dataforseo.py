"""DataForSEO Merchant API, Amazon Products (task based, standard queue).

Flow: task_post (batches of up to 100) -> poll task_get/advanced/{id} until done.
Posted task IDs are saved to the state dir first, so a crash or rerun never pays twice.
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path

from . import http

BASE = "https://api.dataforseo.com/v3/merchant/amazon/products"
OK = 20000
PENDING = {40601, 40602}  # Task Handed, Task In Queue


class DataForSEO:
    def __init__(self, cfg):
        self.cfg = cfg
        token = base64.b64encode(f"{cfg.dataforseo_login}:{cfg.dataforseo_password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}"}
        self.cost = 0.0

    def _call(self, method: str, path: str, body=None) -> dict:
        resp = http.request_json(method, BASE + path, headers=self.headers, body=body)
        self.cost += float(resp.get("cost") or 0)
        if resp.get("status_code") != OK:
            raise RuntimeError(f"DataForSEO {path}: {resp.get('status_code')} {resp.get('status_message')}")
        return resp

    def post(self, keywords: list, tag: str) -> dict:
        """Returns {keyword: task_id}."""
        ids = {}
        for i in range(0, len(keywords), 100):
            batch = keywords[i:i + 100]
            body = [{
                "keyword": kw,
                "location_code": self.cfg.location_code,
                "language_code": self.cfg.language_code,
                "se_domain": self.cfg.se_domain,
                "depth": self.cfg.serp_depth,
                "priority": 1,
                "tag": tag,
            } for kw in batch]
            resp = self._call("POST", "/task_post", body)
            for task in resp["tasks"]:
                kw = task["data"]["keyword"]
                if task["status_code"] in (20100, OK):
                    ids[kw] = task["id"]
                else:
                    print(f"  ! task_post failed for '{kw}': {task['status_code']} {task['status_message']}")
        return ids

    def get(self, task_id: str):
        """Returns the result dict, or None while still queued."""
        resp = self._call("GET", f"/task_get/advanced/{task_id}")
        task = resp["tasks"][0]
        if task["status_code"] in PENDING:
            return None
        if task["status_code"] != OK:
            raise RuntimeError(f"task {task_id}: {task['status_code']} {task['status_message']}")
        return (task.get("result") or [None])[0] or {}

    def collect(self, ids: dict, state_file: Path) -> dict:
        """Poll until every task is done. Results are cached to state_file as they arrive."""
        state = json.loads(state_file.read_text()) if state_file.exists() else {}
        results = state.setdefault("results", {})
        pending = {kw: tid for kw, tid in ids.items() if kw not in results}
        deadline = time.time() + self.cfg.poll_timeout_s
        while pending:
            for kw, tid in list(pending.items()):
                try:
                    res = self.get(tid)
                except RuntimeError as e:
                    print(f"  ! {kw}: {e}")
                    results[kw] = {"error": str(e)}
                    pending.pop(kw)
                    continue
                if res is not None:
                    results[kw] = res
                    pending.pop(kw)
            state_file.write_text(json.dumps(state))
            if not pending:
                break
            if time.time() > deadline:
                raise RuntimeError(f"{len(pending)} DataForSEO tasks still queued after timeout; rerun to resume")
            print(f"  waiting on {len(pending)} SERP tasks...")
            time.sleep(self.cfg.poll_interval_s)
        return results


def parse_serp(result: dict, our_asins: set) -> dict:
    """Pull our ASINs out of one SERP result.

    Organic rank = rank_group of `amazon_serp` items (position among organic results only).
    Sponsored rank = rank_group of `amazon_paid` items. Other block types (editorial picks,
    related searches) are ignored for ranking.
    Returns {asin: {organic_rank, absolute_rank, sponsored_rank, amazons_choice, best_seller}}.
    """
    found = {}
    for item in result.get("items") or []:
        asin = item.get("data_asin")
        if asin not in our_asins:
            continue
        rec = found.setdefault(asin, {
            "organic_rank": None, "absolute_rank": None, "sponsored_rank": None,
            "amazons_choice": False, "best_seller": False,
        })
        kind = item.get("type")
        if kind == "amazon_serp" and rec["organic_rank"] is None:
            rec["organic_rank"] = item.get("rank_group")
            rec["absolute_rank"] = item.get("rank_absolute")
            rec["amazons_choice"] = bool(item.get("is_amazon_choice"))
            rec["best_seller"] = bool(item.get("is_best_seller"))
        elif kind == "amazon_paid" and rec["sponsored_rank"] is None:
            rec["sponsored_rank"] = item.get("rank_group")
    return found


def item_types(result: dict) -> dict:
    """For the smoke test: count of each item type and the keys on the first of each."""
    out = {}
    for item in result.get("items") or []:
        t = item.get("type")
        if t not in out:
            out[t] = {"count": 0, "keys": sorted(item.keys())}
        out[t]["count"] += 1
    return out
