import csv
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rank_tracker import __main__ as cli
from rank_tracker import catalog, config, dataforseo, sqp, vault

SKU_MAP = """marketplace_id,sku,asin,fnsku,item_name,first_seen,last_seen,retrieved_at,source_operation,value_type
A1F83G8C2ARO7P,A1,B0BTXH3SDL,,"Assisi Style Vegan Leather Belt for Men, Cork Belt 38mm, Black, Gift Boxed",,,,,
A1F83G8C2ARO7P,A2,B0BW2DXV7K,,"Assisi Style Vegan Leather Belt for Men, Cork Belt 38mm, Brown, Gift Boxed",,,,,
A1F83G8C2ARO7P,W1,B0CVBM1DZY,,"Assisi Style Vegan Wallet for Men, RFID Cork Bifold, Coin Pocket, Black",,,,,
"""


def sqp_record(asin, query, start="2026-09-27", end="2026-10-03", vol=1000, clicks=5, purchases=1):
    return {
        "startDate": start, "endDate": end, "asin": asin,
        "searchQueryData": {"searchQuery": query, "searchQueryScore": 1, "searchQueryVolume": vol},
        "impressionData": {"totalQueryImpressionCount": 9000, "asinImpressionCount": 100, "asinImpressionShare": 0.01},
        "clickData": {"totalClickCount": 500, "asinClickCount": clicks, "asinClickShare": 0.01},
        "cartAddData": {"totalCartAddCount": 50, "asinCartAddCount": 1},
        "purchaseData": {"totalPurchaseCount": 20, "asinPurchaseCount": purchases, "asinPurchaseShare": 0.05},
    }


def serp(*items):
    return {"items": [
        {"type": t, "rank_group": rg, "rank_absolute": ra, "data_asin": a, "is_amazon_choice": False}
        for t, rg, ra, a in items
    ]}


class UnitTests(unittest.TestCase):
    def test_last_complete_week(self):
        self.assertEqual(sqp.last_complete_week(dt.date(2026, 10, 7)), (dt.date(2026, 9, 27), dt.date(2026, 10, 3)))
        # On a Saturday the current week is not complete yet.
        self.assertEqual(sqp.last_complete_week(dt.date(2026, 10, 3)), (dt.date(2026, 9, 20), dt.date(2026, 9, 26)))
        self.assertEqual(sqp.last_complete_week(dt.date(2026, 10, 4)), (dt.date(2026, 9, 27), dt.date(2026, 10, 3)))

    def test_asin_batches_respect_200_chars(self):
        asins = ["B0%08d" % i for i in range(50)]
        batches = sqp.asin_batches(asins)
        self.assertTrue(all(len(" ".join(b)) <= 200 for b in batches))
        self.assertEqual(sum(len(b) for b in batches), 50)
        self.assertEqual(len(batches[0]), 18)

    def test_family(self):
        self.assertEqual(catalog.family_of("Assisi Style Vegan Cork Wallet & Belt Set, Mens 26-28\" Waist"), "Vegan Cork Wallet & Belt Set")

    def test_select_keywords(self):
        recs = [
            sqp_record("B0BTXH3SDL", "cork belt", purchases=3),
            sqp_record("B0BTXH3SDL", "vegan belt", purchases=0, clicks=9),
            sqp_record("B0BTXH3SDL", "assisi style belt", purchases=9),
            sqp_record("B0BTXH3SDL", "leather belt men", purchases=0, clicks=1),
            sqp_record("B0BW2DXV7K", "Cork Belt ", purchases=1),
        ]
        rows = [sqp.flatten(r, "A1F83G8C2ARO7P", "x") for r in recs]
        kws, window = sqp.select_keywords(rows, weeks=4, per_asin=2, max_keywords=50, exclude_terms=["assisi"])
        self.assertEqual(set(kws), {"cork belt", "vegan belt"})
        self.assertEqual(kws["cork belt"]["asins"], {"B0BTXH3SDL", "B0BW2DXV7K"})
        self.assertEqual(window, ("2026-09-27", "2026-10-03"))

    def test_parse_serp_separates_organic_and_paid(self):
        res = serp(("amazon_paid", 1, 1, "B0BTXH3SDL"), ("amazon_serp", 1, 2, "B0OTHER001"),
                   ("amazon_serp", 2, 3, "B0BTXH3SDL"), ("amazon_serp", 3, 4, "B0BTXH3SDL"))
        found = dataforseo.parse_serp(res, {"B0BTXH3SDL"})
        self.assertEqual(found["B0BTXH3SDL"]["organic_rank"], 2)
        self.assertEqual(found["B0BTXH3SDL"]["absolute_rank"], 3)
        self.assertEqual(found["B0BTXH3SDL"]["sponsored_rank"], 1)


class FakeDataForSEO:
    serps = {}

    def __init__(self, cfg):
        self.cost = 0.0

    def post(self, keywords, tag):
        self.cost += 0.0015 * len(keywords)
        return {kw: "id-" + kw for kw in keywords}

    def collect(self, ids, state_file):
        state = json.loads(state_file.read_text()) if state_file.exists() else {}
        state["results"] = {kw: self.serps.get(kw, {"items": []}) for kw in ids}
        state_file.write_text(json.dumps(state))
        return state["results"]


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "sync").mkdir()
        (self.tmp / "vault").mkdir()
        (self.tmp / "sync" / "sku_map.csv").write_text(SKU_MAP)
        rows = [sqp.flatten(r, "A1F83G8C2ARO7P", "x") for r in [
            sqp_record("B0BTXH3SDL", "cork belt", vol=2000),
            sqp_record("B0BW2DXV7K", "cork belt", vol=2000),
            sqp_record("B0CVBM1DZY", "cork wallet men", vol=800),
        ]]
        sqp.upsert(self.tmp / "sync" / sqp.SQP_FILE, rows)
        cfg_path = self.tmp / "config.json"
        cfg_path.write_text(json.dumps({
            "sync_exports_dir": str(self.tmp / "sync"), "vault_dir": str(self.tmp / "vault"),
            "state_dir": str(self.tmp / "state"),
        }))
        self.cfg = config.load(cfg_path)

    def run_on(self, day, serps):
        FakeDataForSEO.serps = serps
        args = mock.Mock(dry_run=False, skip_sqp=True)
        with mock.patch.object(cli.dataforseo, "DataForSEO", FakeDataForSEO), \
             mock.patch.object(cli.dt, "date", mock.Mock(today=lambda: day)):
            self.assertEqual(cli.cmd_run(self.cfg, args), 0)

    def test_two_weeks(self):
        self.run_on(dt.date(2026, 10, 7), {
            "cork belt": serp(("amazon_serp", 1, 1, "B0X0000001"), ("amazon_serp", 12, 14, "B0BW2DXV7K")),
            "cork wallet men": serp(("amazon_serp", 30, 33, "B0CVBM1DZY")),
        })
        self.run_on(dt.date(2026, 10, 14), {
            "cork belt": serp(("amazon_serp", 5, 6, "B0BTXH3SDL"), ("amazon_paid", 2, 2, "B0BTXH3SDL")),
            "cork wallet men": serp(),
        })
        rank_dir = self.cfg.rank_dir
        with open(rank_dir / "rank_history.csv") as f:
            hist = list(csv.DictReader(f))
        self.assertEqual({r["run_date"] for r in hist}, {"2026-10-07", "2026-10-14"})
        note = (rank_dir / "2026-W42.md").read_text()
        self.assertIn("| cork belt | 2000 | 5 | B0BTXH3SDL | ▲7 | 2 |", note)
        self.assertIn("| cork wallet men | 800 | - |  | lost | - |", note)
        self.assertIn("Compared with: 2026-10-07", note)
        self.assertNotIn("—", note)  # no em dashes in published output

        # Rerunning the same day replaces, not duplicates.
        self.run_on(dt.date(2026, 10, 14), {"cork belt": serp(), "cork wallet men": serp()})
        with open(rank_dir / "rank_history.csv") as f:
            self.assertEqual(sum(1 for r in csv.DictReader(f) if r["run_date"] == "2026-10-14"), 3)


if __name__ == "__main__":
    unittest.main()
