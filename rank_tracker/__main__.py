"""Weekly run: SQP refresh -> keyword pick -> DataForSEO SERPs -> vault.

  python3 -m rank_tracker run            full weekly run
  python3 -m rank_tracker run --dry-run  show keywords and task count, no DataForSEO spend
  python3 -m rank_tracker sqp            only refresh the SQP export
  python3 -m rank_tracker smoke "cork belt"   one paid SERP check, prints the response shape
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from . import catalog, config, dataforseo, sqp, vault


def refresh_sqp(cfg, asins: list, today: dt.date) -> None:
    start, end = sqp.last_complete_week(today)
    existing = {r["week_start"] for r in sqp.read_rows(cfg.sync_exports_dir / sqp.SQP_FILE)}
    # Backfill the selection window on first run, then just the newest week.
    wanted = [(start - dt.timedelta(weeks=i), end - dt.timedelta(weeks=i)) for i in range(cfg.sqp_weeks)]
    for s, e in reversed(wanted):
        if s.isoformat() in existing and s != start:
            continue
        try:
            n = sqp.fetch_week(cfg, asins, s, e)
            print(f"SQP {s}..{e}: {n} rows")
        except RuntimeError as err:
            # Newest week can lag a few days; carry on with what is on disk.
            print(f"SQP {s}..{e} not available: {err}")


def cmd_run(cfg, args) -> int:
    today = dt.date.today()
    cat = catalog.load_catalog(cfg.sync_exports_dir, cfg.marketplace_id)
    print(f"{len(cat)} Assisi ASINs from sku_map.csv")

    if not args.skip_sqp:
        refresh_sqp(cfg, sorted(cat), today)
    rows = [r for r in sqp.read_rows(cfg.sync_exports_dir / sqp.SQP_FILE) if r["marketplace_id"] == cfg.marketplace_id]
    keywords, window = sqp.select_keywords(rows, cfg.sqp_weeks, cfg.keywords_per_asin, cfg.max_keywords, cfg.exclude_terms)
    if not keywords:
        print("No SQP keywords available; nothing to check.")
        return 1
    print(f"{len(keywords)} unique keywords from SQP {window[0]}..{window[1]}")

    if args.dry_run:
        for kw, meta in sorted(keywords.items(), key=lambda kv: -kv[1]["volume"]):
            print(f"  {int(meta['volume']):>7}  {kw}  ({len(meta['asins'])} ASINs)")
        print(f"Would post {len(keywords)} DataForSEO tasks at depth {cfg.serp_depth}.")
        return 0

    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    state_file = cfg.state_dir / f"serp_{today.isoformat()}.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    client = dataforseo.DataForSEO(cfg)
    ids = state.get("ids", {})
    to_post = [kw for kw in keywords if kw not in ids]
    if to_post:
        ids.update(client.post(to_post, tag=f"assisi-rank-{today.isoformat()}"))
        state["ids"] = ids
        state["post_cost"] = state.get("post_cost", 0.0) + client.cost
        state_file.write_text(json.dumps(state))
        print(f"Posted {len(to_post)} SERP tasks (cost so far ${client.cost:.4f})")
    serps = client.collect(ids, state_file)
    failed = [kw for kw in keywords if kw not in serps or "error" in serps[kw]]
    # DataForSEO bills at task_post; post_cost survives resumed runs via the state file.
    cost = json.loads(state_file.read_text()).get("post_cost", 0.0)

    cfg.rank_dir.mkdir(parents=True, exist_ok=True)
    out_rows = vault.build_rows(today, cfg, keywords, serps, cat, window, dataforseo.parse_serp)
    prior = vault.write_history(cfg.rank_dir, out_rows)
    note = vault.render_note(today, cfg, out_rows, prior, window, cost, failed)
    path = vault.write_note(cfg.rank_dir, out_rows[0]["iso_week"] if out_rows else "%d-W%02d" % today.isocalendar()[:2], note)
    print(f"Wrote {path} and {len(out_rows)} rows to {vault.HISTORY_FILE}")
    return 0


def cmd_sqp(cfg, args) -> int:
    cat = catalog.load_catalog(cfg.sync_exports_dir, cfg.marketplace_id)
    refresh_sqp(cfg, sorted(cat), dt.date.today())
    return 0


def cmd_smoke(cfg, args) -> int:
    client = dataforseo.DataForSEO(cfg)
    ids = client.post([args.keyword], tag="assisi-rank-smoke")
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    res = client.collect(ids, cfg.state_dir / "smoke.json")[args.keyword]
    print(json.dumps(dataforseo.item_types(res), indent=2))
    cat = catalog.load_catalog(cfg.sync_exports_dir, cfg.marketplace_id)
    print("Assisi ASINs found:", json.dumps(dataforseo.parse_serp(res, set(cat)), indent=2))
    print(f"Cost: ${client.cost:.4f}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="rank_tracker")
    p.add_argument("--config", default="config.json")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--skip-sqp", action="store_true", help="use SQP rows already on disk")
    sub.add_parser("sqp")
    s = sub.add_parser("smoke")
    s.add_argument("keyword")
    args = p.parse_args(argv)
    cfg = config.load(args.config)
    return {"run": cmd_run, "sqp": cmd_sqp, "smoke": cmd_smoke}[args.cmd](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
