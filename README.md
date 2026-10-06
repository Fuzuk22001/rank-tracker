# Assisi Style rank tracker

Runs once a week on the iMac. It records the Amazon UK organic rank of every Assisi Style ASIN for the search terms that actually bring that ASIN traffic, and writes the results into the Obsidian vault.

## How it works

1. **ASINs.** Every ASIN in `sku_map.csv` from the SP-API sync (`AmazonSyncExports` on Google Drive). Product family = the title before the first comma, e.g. "Vegan Leather Belt for Men".
2. **SQP refresh.** Pulls the Brand Analytics Search Query Performance report for the last complete Sunday to Saturday week, in batches of up to 18 ASINs (Amazon caps the list at 200 characters). Writes `sqp_asin_weekly.csv` into the sync folder next to the other exports. The first run backfills 4 weeks.
3. **Keyword pick.** For each ASIN, takes its top 5 queries over the last 4 SQP weeks, ranked by that ASIN's purchases, then clicks, then search volume. Queries containing "assisi" are skipped. Duplicates across ASINs are merged and the list is capped at 150 by search volume.
4. **Rank check.** Sends one DataForSEO Amazon Products search per keyword (amazon.co.uk, en_GB, top 100 results). A single search returns every Assisi ASIN on the page, so cost depends on the number of keywords, not the number of ASINs. Organic rank = position among organic results only. Sponsored slots are recorded separately.
5. **Vault.** Writes to `<vault>/Amazon/Rank Tracker/`:
   - `rank_history.csv`: one row per keyword and ASIN per run. Append-only, and a rerun on the same day replaces that day's rows.
   - `2026-W41.md` etc.: the weekly note, with a summary, biggest movers against the previous run, and a table per product family.

Posted DataForSEO task IDs are saved in `state/` before polling starts. If a run dies part way through, rerunning picks up the same tasks instead of paying for them again.

## Setup on the iMac

```bash
git clone <this repo> ~/rank-tracker && cd ~/rank-tracker
cp config.example.json config.json   # set sync_exports_dir and vault_dir
cp .env.example .env                 # DataForSEO login, plus the SP-API app creds the sync already uses
chmod 600 .env
```

The SP-API app needs the **Brand Analytics** role for the SQP report.

Check it before scheduling:

```bash
source .env
python3 -m rank_tracker sqp                    # fetch SQP only, free
python3 -m rank_tracker run --dry-run          # list chosen keywords and task count, no spend
python3 -m rank_tracker smoke "cork belt"      # one paid search, roughly a fraction of a cent; prints response shape
python3 -m rank_tracker run                    # full run
```

Run `smoke` once before the first full run. The DataForSEO response parsing was written without access to their live docs. The smoke output lists each item `type` with its fields and should show `amazon_serp` and `amazon_paid` items carrying `data_asin`, `rank_group` and `rank_absolute`. If it doesn't, fix `parse_serp` in `rank_tracker/dataforseo.py` before scheduling.

Schedule it (Wednesdays at 07:15):

```bash
sed "s#REPO_PATH#$PWD#g" launchd/com.assisistyle.rank-tracker.plist > ~/Library/LaunchAgents/com.assisistyle.rank-tracker.plist
launchctl load ~/Library/LaunchAgents/com.assisistyle.rank-tracker.plist
launchctl start com.assisistyle.rank-tracker   # optional test run now
```

The job runs on wake if the Mac was asleep at 07:15, but not if it was switched off. Logs are written to `logs/`. If the vault or Drive folder sits under `~/Library/CloudStorage` or iCloud and the job can't write to it, give `/bin/bash` Full Disk Access in System Settings, as for the sync job.

## Tuning (config.json)

| Key | Default | Effect |
|---|---|---|
| `keywords_per_asin` | 5 | More terms per ASIN means more coverage and more cost |
| `max_keywords` | 150 | Hard cap on paid searches per week |
| `serp_depth` | 100 | How deep to look. DataForSEO prices by depth, so 100 is the cheapest tier |
| `sqp_weeks` | 4 | Weeks of SQP used to pick keywords. More weeks gives a steadier list |
| `exclude_terms` | `["assisi"]` | Drop branded queries, where you'd rank first anyway |

## Tests

```bash
python3 -m unittest -v
```
