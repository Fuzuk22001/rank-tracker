"""Write rank results into the Obsidian vault: append-only CSV plus one note per ISO week."""
from __future__ import annotations

import csv
import datetime as dt
from collections import defaultdict
from pathlib import Path

HISTORY_FILE = "rank_history.csv"
HISTORY_COLUMNS = [
    "run_date", "iso_week", "marketplace", "keyword", "asin", "family",
    "organic_rank", "absolute_rank", "sponsored_rank", "amazons_choice", "best_seller",
    "selected_by_sqp", "sqp_weekly_volume", "sqp_window", "serp_depth", "source",
]
SOURCE = "DataForSEO Amazon Products SERP"


def build_rows(run_date: dt.date, cfg, keywords: dict, serps: dict, catalog: dict, sqp_window: tuple, parse) -> list:
    """One row per (keyword, ASIN) where the ASIN chose that keyword in SQP or appeared in the SERP."""
    iso = "%d-W%02d" % run_date.isocalendar()[:2]
    window = f"{sqp_window[0]}..{sqp_window[1]}"
    our = set(catalog)
    rows = []
    for kw, meta in sorted(keywords.items()):
        res = serps.get(kw) or {}
        if "error" in res:
            continue
        found = parse(res, our)
        for asin in sorted(meta["asins"] | set(found)):
            hit = found.get(asin, {})
            rows.append({
                "run_date": run_date.isoformat(),
                "iso_week": iso,
                "marketplace": cfg.se_domain,
                "keyword": kw,
                "asin": asin,
                "family": catalog.get(asin, ""),
                "organic_rank": _s(hit.get("organic_rank")),
                "absolute_rank": _s(hit.get("absolute_rank")),
                "sponsored_rank": _s(hit.get("sponsored_rank")),
                "amazons_choice": "1" if hit.get("amazons_choice") else "",
                "best_seller": "1" if hit.get("best_seller") else "",
                "selected_by_sqp": "1" if asin in meta["asins"] else "",
                "sqp_weekly_volume": "%d" % meta["volume"],
                "sqp_window": window,
                "serp_depth": str(cfg.serp_depth),
                "source": SOURCE,
            })
    return rows


def _s(v) -> str:
    return "" if v is None else str(v)


def write_history(rank_dir: Path, rows: list) -> list:
    """Append rows (replacing any earlier rows for the same run_date). Returns all prior rows."""
    path = rank_dir / HISTORY_FILE
    existing = []
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            existing = list(csv.DictReader(f))
    run_dates = {r["run_date"] for r in rows}
    prior = [r for r in existing if r["run_date"] not in run_dates]
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(prior + rows)
    tmp.replace(path)
    return prior


def _best_by_family(rows: list) -> dict:
    """{(family, keyword): (best organic rank or None, asin)} across all ASINs in the family."""
    best = {}
    for r in rows:
        key = (r["family"], r["keyword"])
        rank = int(r["organic_rank"]) if r["organic_rank"] else None
        cur = best.get(key)
        if cur is None or (rank is not None and (cur[0] is None or rank < cur[0])):
            best[key] = (rank, r["asin"] if rank is not None else "")
    return best


def _delta(now, before, had_before: bool) -> str:
    if not had_before:
        return "new"
    if now is None and before is None:
        return ""
    if now is None:
        return "lost"
    if before is None:
        return "entered"
    d = before - now
    return "" if d == 0 else ("▲%d" % d if d > 0 else "▼%d" % -d)


def _fmt(rank) -> str:
    return "-" if rank is None else str(rank)


def render_note(run_date: dt.date, cfg, rows: list, prior: list, sqp_window: tuple, cost: float, failed: list) -> str:
    iso = rows[0]["iso_week"] if rows else "%d-W%02d" % run_date.isocalendar()[:2]
    prev_date = max((r["run_date"] for r in prior), default=None)
    prev_rows = [r for r in prior if r["run_date"] == prev_date] if prev_date else []

    now_best = _best_by_family(rows)
    prev_best = _best_by_family(prev_rows)
    volume = {r["keyword"]: int(r["sqp_weekly_volume"] or 0) for r in rows}
    sponsored = defaultdict(list)
    for r in rows:
        if r["sponsored_rank"]:
            sponsored[(r["family"], r["keyword"])].append(int(r["sponsored_rank"]))
    # Only show family/keyword pairs that one of the family's ASINs chose via SQP.
    chosen = {(r["family"], r["keyword"]) for r in rows if r["selected_by_sqp"]}

    keywords = {r["keyword"] for r in rows}
    best_any = {}
    for (fam, kw), (rank, _) in now_best.items():
        if rank is not None and (kw not in best_any or rank < best_any[kw]):
            best_any[kw] = rank
    top10 = sum(1 for v in best_any.values() if v <= 10)
    top48 = sum(1 for v in best_any.values() if v <= 48)
    missing = len(keywords) - len(best_any)

    movers = []
    for key in chosen:
        if key in prev_best and now_best[key][0] is not None and prev_best[key][0] is not None:
            movers.append((prev_best[key][0] - now_best[key][0], key))
    movers.sort(key=lambda x: (-x[0], x[1]))
    up = [m for m in movers if m[0] > 0][:10]
    down = sorted([m for m in movers if m[0] < 0], key=lambda x: (x[0], x[1]))[:10]

    out = [
        "---",
        "type: rank-report",
        f"week: {iso}",
        f"run_date: {run_date.isoformat()}",
        f"marketplace: {cfg.se_domain}",
        f"source: {SOURCE}",
        f"keywords_from: Amazon SP-API (synced) SQP {sqp_window[0]} to {sqp_window[1]}",
        f"keywords_checked: {len(keywords)}",
        f"serp_depth: {cfg.serp_depth}",
        f"dataforseo_cost_usd: {cost:.4f}",
        "tags: [amazon, rank-tracker]",
        "---",
        "",
        f"# Amazon UK organic rank, {iso}",
        "",
        f"Source: {SOURCE}, {cfg.se_domain}, checked {run_date.isoformat()}. Keywords picked from "
        f"Amazon SP-API (synced) Search Query Performance, {sqp_window[0]} to {sqp_window[1]}. "
        "Ranks are a single snapshot of organic positions (sponsored slots excluded), not an average.",
        f"Compared with: {prev_date or 'no earlier run'}.",
        "",
        "## Summary",
        "",
        f"- Keywords checked: {len(keywords)}",
        f"- Best Assisi rank in top 10: {top10}",
        f"- Best Assisi rank in top 48 (roughly page 1): {top48}",
        f"- No Assisi ASIN in top {cfg.serp_depth} organic: {missing}",
        f"- DataForSEO cost this run: ${cost:.4f} (USD, as billed)",
    ]
    if failed:
        out.append(f"- SERP checks that failed: {len(failed)} ({', '.join(sorted(failed)[:10])})")
    out.append("")

    if prev_rows:
        out += ["## Biggest movers", "", "| Product | Keyword | Last week | This week | Move |", "|---|---|---|---|---|"]
        for d, (fam, kw) in up + down:
            out.append(f"| {fam} | {kw} | {prev_best[(fam, kw)][0]} | {now_best[(fam, kw)][0]} | {_delta(now_best[(fam, kw)][0], prev_best[(fam, kw)][0], True)} |")
        if not (up or down):
            out.append("| - | No rank changes | | | |")
        out.append("")

    out += ["## By product", ""]
    families = sorted({fam for fam, _ in chosen})
    for fam in families:
        out += [f"### {fam}", "", "| Keyword | SQP vol/wk | Organic | ASIN | Move | Sponsored |", "|---|---|---|---|---|---|"]
        kws = sorted((kw for f, kw in chosen if f == fam), key=lambda k: (-volume.get(k, 0), k))
        for kw in kws:
            rank, asin = now_best[(fam, kw)]
            had = (fam, kw) in prev_best
            move = _delta(rank, prev_best[(fam, kw)][0] if had else None, had) if prev_rows else ""
            sp = sponsored.get((fam, kw))
            out.append(f"| {kw} | {volume.get(kw, 0)} | {_fmt(rank)} | {asin} | {move} | {_fmt(min(sp)) if sp else '-'} |")
        out.append("")

    out += [
        "## Notes",
        "",
        "- Organic: best organic position of any ASIN in the product family. Per ASIN detail is in `rank_history.csv`.",
        "- Move: ▲ = moved up (better), ▼ = moved down. 'new' = keyword not tracked last week, "
        "'lost' = dropped out of the checked depth, 'entered' = newly found.",
        "- Amazon often shows one variation per family, so a size or colour variant can rank while its siblings show '-'.",
        "",
    ]
    return "\n".join(out)


def write_note(rank_dir: Path, iso_week: str, text: str) -> Path:
    path = rank_dir / f"{iso_week}.md"
    path.write_text(text, encoding="utf-8")
    return path
