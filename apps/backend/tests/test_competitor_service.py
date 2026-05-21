import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for key, value in {
    'DB_HOST': '127.0.0.1',
    'DB_PORT': '3306',
    'DB_NAME': 'demo',
    'DB_USER': 'demo',
    'DB_PASSWORD': 'demo',
}.items():
    os.environ.setdefault(key, value)

try:
    from app.main import create_app
except ModuleNotFoundError:  # pragma: no cover - minimal env
    create_app = None

from app.services.competitor_service import (
    _build_collection_result_from_fliggy_rows,
    _extract_chat_completions_text,
    _extract_fliggy_price_from_text,
    _extract_response_text,
    _normalize_competitor_snapshot_source,
    build_competitor_snapshot_cleanup_plan,
    build_competitor_snapshot_rows,
    collect_fliggy_hotel_prices_from_extension_page,
    collect_competitor_intel,
    collect_fliggy_hotel_prices_playwright,
    generate_room_price_trend_advice,
    get_room_price_trend_summary,
)

class CompetitorServiceTestCase(unittest.TestCase):
    def test_get_room_price_trend_summary_groups_min_price_points(self) -> None:
        class FakeResult:
            def __init__(self, rows):
                self._rows = rows

            def mappings(self):
                return self

            def all(self):
                return self._rows

        class FakeDb:
            def execute(self, statement, params=None):
                sql = str(statement)
                if "CREATE TABLE IF NOT EXISTS hotel_room_prices" in sql:
                    return FakeResult([])
                return FakeResult(
                    [
                        {
                            "hotel_name": "杭州君悦酒店",
                            "hotel_url": "https://example.com/hyatt",
                            "room_type": "商务大床房",
                            "price": 520.0,
                            "collected_at": "2026-04-24 08:00:00",
                        },
                        {
                            "hotel_name": "杭州君悦酒店",
                            "hotel_url": "https://example.com/hyatt",
                            "room_type": "商务大床房",
                            "price": 488.0,
                            "collected_at": "2026-04-24 10:00:00",
                        },
                        {
                            "hotel_name": "杭州西子湖四季酒店",
                            "hotel_url": "https://example.com/four-seasons",
                            "room_type": "商务双床房",
                            "price": 680.0,
                            "collected_at": "2026-04-24 10:05:00",
                        },
                        {
                            "hotel_name": "杭州西子湖四季酒店",
                            "hotel_url": "https://example.com/four-seasons",
                            "room_type": "亲子套房",
                            "price": 1288.0,
                            "collected_at": "2026-04-24 10:00:00",
                        },
                        {
                            "hotel_name": "杭州西子湖四季酒店",
                            "hotel_url": "https://example.com/four-seasons",
                            "room_type": "标准双床房",
                            "price": 688.0,
                            "collected_at": "2026-04-24 10:00:00",
                        },
                    ]
                )

        result = get_room_price_trend_summary(
            FakeDb(),
            shop_id=1,
            days=7,
            point_limit=60,
        )

        self.assertEqual(result["hotel_count"], 2)
        self.assertEqual(result["category_count"], 4)
        self.assertEqual(result["point_count"], 5)
        self.assertEqual(result["series_type"], "room_category")
        self.assertEqual(result["metric"], "min_price")
        self.assertEqual(result["latest_collected_at"], "2026-04-24 10:05:00")
        self.assertEqual(result["price_min"], 488.0)
        self.assertEqual(result["price_max"], 1288.0)
        self.assertEqual(result["series"][0]["category_name"], "商务房")
        self.assertEqual(result["series"][0]["hotel_name"], "杭州君悦酒店")
        self.assertEqual(result["series"][0]["hotel_url"], "https://example.com/hyatt")
        self.assertEqual(result["series"][0]["latest_min_price"], 488.0)
        self.assertEqual(result["series"][0]["change_amount"], -32.0)
        business_series = [
            item for item in result["series"]
            if item.get("category_name") == "商务房"
        ]
        self.assertEqual({item["hotel_name"] for item in business_series}, {"杭州君悦酒店", "杭州西子湖四季酒店"})
        xizi_business = next(item for item in business_series if item["hotel_name"] == "杭州西子湖四季酒店")
        self.assertEqual(xizi_business["points"][0]["collected_at"], "2026-04-24 10:00:00")
        self.assertEqual(xizi_business["points"][0]["collected_at_end"], "2026-04-24 10:05:00")

    def test_get_room_price_trend_summary_groups_hotel_min_price_points(self) -> None:
        class FakeResult:
            def __init__(self, rows):
                self._rows = rows

            def mappings(self):
                return self

            def all(self):
                return self._rows

        class FakeDb:
            def execute(self, statement, params=None):
                sql = str(statement)
                if "CREATE TABLE IF NOT EXISTS hotel_room_prices" in sql:
                    return FakeResult([])
                return FakeResult(
                    [
                        {
                            "hotel_name": "杭州君悦酒店",
                            "hotel_url": "https://example.com/hyatt",
                            "room_type": "商务大床房",
                            "price": 520.0,
                            "collected_at": "2026-04-24 08:00:00",
                        },
                        {
                            "hotel_name": "杭州君悦酒店",
                            "hotel_url": "https://example.com/hyatt",
                            "room_type": "高级双床房",
                            "price": 488.0,
                            "collected_at": "2026-04-24 08:00:00",
                        },
                        {
                            "hotel_name": "杭州西子湖四季酒店",
                            "hotel_url": "https://example.com/four-seasons",
                            "room_type": "亲子套房",
                            "price": 1288.0,
                            "collected_at": "2026-04-24 08:00:00",
                        },
                        {
                            "hotel_name": "杭州西子湖四季酒店",
                            "hotel_url": "https://example.com/four-seasons",
                            "room_type": "标准双床房",
                            "price": 1188.0,
                            "collected_at": "2026-04-24 10:00:00",
                        },
                    ]
                )

        result = get_room_price_trend_summary(
            FakeDb(),
            shop_id=1,
            days=7,
            point_limit=60,
            series_type="hotel_min_price",
        )

        self.assertEqual(result["series_type"], "hotel_min_price")
        self.assertEqual(result["hotel_count"], 2)
        self.assertEqual(result["category_count"], 2)
        self.assertEqual(result["series"][0]["hotel_name"], "杭州西子湖四季酒店")
        self.assertEqual(result["series"][0]["hotel_url"], "https://example.com/four-seasons")
        self.assertEqual(result["series"][0]["latest_min_price"], 1188.0)
        self.assertEqual(result["series"][1]["hotel_name"], "杭州君悦酒店")
        self.assertEqual(result["series"][1]["hotel_url"], "https://example.com/hyatt")
        self.assertEqual(result["series"][1]["latest_min_price"], 488.0)

    def test_generate_room_price_trend_advice_uses_rule_fallback(self) -> None:
        trend_summary = {
            "days": 7,
            "hotel_count": 2,
            "category_count": 2,
            "point_count": 4,
            "latest_price_avg": 688.0,
            "series": [
                {
                    "category_name": "商务房",
                    "latest_min_price": 488.0,
                    "change_amount": -32.0,
                    "change_pct": -6.15,
                    "points": [
                        {"collected_at": "2026-04-24 08:00:00", "min_price": 520.0},
                        {"collected_at": "2026-04-24 10:00:00", "min_price": 488.0},
                    ],
                },
                {
                    "category_name": "亲子房",
                    "latest_min_price": 888.0,
                    "change_amount": 44.0,
                    "change_pct": 5.21,
                    "points": [
                        {"collected_at": "2026-04-24 08:00:00", "min_price": 844.0},
                        {"collected_at": "2026-04-24 10:00:00", "min_price": 888.0},
                    ],
                },
            ],
        }

        with patch("app.services.competitor_service._call_room_price_trend_advice_llm", return_value=None):
            advice = generate_room_price_trend_advice(trend_summary)

        self.assertEqual(advice["source"], "rule_based")
        self.assertIn("最近 7 天", advice["summary"])
        self.assertEqual(len(advice["items"]), 2)
        self.assertEqual(advice["items"][0]["signal"], "down")
        self.assertEqual(advice["items"][1]["signal"], "up")

    def test_collect_competitor_intel_heuristic(self) -> None:
        html = """
        <html>
          <head>
            <title>Competitor Product</title>
            <meta name="description" content="Best sale price ¥199">
          </head>
          <body>
            <h1>Promo</h1>
            <p>Now only ¥199, limited sale.</p>
          </body>
        </html>
        """
        with patch("app.services.competitor_service._fetch_html", return_value=html):
            result = collect_competitor_intel(
                shop_id=1,
                targets=[{"name": "A", "url": "https://example.com/a"}],
                use_openclaw=False,
                limit_per_page_chars=6000,
            )

        self.assertEqual(result["count"], 1)
        item = result["items"][0]
        self.assertEqual(item["fetch_status"], "success")
        self.assertEqual(item["analysis_source"], "heuristic")
        self.assertIn("¥199", item["signals"]["price_signals"])

    def test_collect_competitor_intel_openclaw_fallback(self) -> None:
        html = "<html><head><title>Demo</title></head><body>price ￥88</body></html>"
        with patch("app.services.competitor_service._fetch_html", return_value=html):
            with patch("app.services.competitor_service._call_openclaw_analysis", side_effect=RuntimeError("unavailable")):
                result = collect_competitor_intel(
                    shop_id=1,
                    targets=[{"name": "B", "url": "https://example.com/b"}],
                    use_openclaw=True,
                    limit_per_page_chars=3000,
                )

        item = result["items"][0]
        self.assertEqual(item["analysis_source"], "heuristic")
        self.assertEqual(item["fetch_status"], "success")
        self.assertIn("openclaw_error", item)

    def test_build_competitor_snapshot_rows(self) -> None:
        result = {
            "collected_at": "2026-03-04 16:00:00",
            "items": [
                {
                    "name": "A",
                    "url": "https://example.com/a",
                    "fetch_status": "success",
                    "analysis_source": "openclaw",
                    "signals": {"price_signals": ["¥100", "¥120"]},
                    "analysis": {"promotion_signals": ["sale"], "risk_notes": ["note1", "note2"]},
                }
            ],
        }
        rows = build_competitor_snapshot_rows(shop_id=1, result=result, source="fliggy_playwright_daily")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["shop_id"], 1)
        self.assertEqual(row["target_name"], "A")
        self.assertEqual(row["price_signal_count"], 2)
        self.assertEqual(row["promotion_signal_count"], 1)
        self.assertEqual(row["risk_note_count"], 2)
        self.assertEqual(row["analysis_source"], "openclaw")
        self.assertEqual(row["source"], "fliggy_playwright_daily")

    def test_extract_fliggy_price_from_text(self) -> None:
        self.assertEqual(_extract_fliggy_price_from_text("限时价 ¥399 起"), 399.0)
        self.assertEqual(_extract_fliggy_price_from_text("促销 ￥88"), 88.0)
        self.assertIsNone(_extract_fliggy_price_from_text("暂无价格"))

    def test_build_collection_result_from_fliggy_rows(self) -> None:
        rows = [
            {
                "hotel_name": "酒店A",
                "price": 299.0,
                "url": "https://hotel.example.com/a",
                "raw_text": "酒店A ¥299",
            }
        ]
        result = _build_collection_result_from_fliggy_rows(shop_id=1, start_url="https://hotel.fliggy.com", rows=rows)
        self.assertEqual(result["count"], 1)
        item = result["items"][0]
        self.assertEqual(item["name"], "酒店A")
        self.assertEqual(item["analysis_source"], "playwright")
        self.assertIn("¥299", item["signals"]["price_signals"][0])


    def test_build_collection_result_normalizes_hotel_name(self) -> None:
        rows = [
            {
                "hotel_name": "杭州西湖国宾馆\uE123 会员价 立减20元",
                "price": 899.0,
                "url": "https://hotel.example.com/hangzhou",
                "raw_text": "杭州西湖国宾馆 会员价 立减20元 ¥899",
            }
        ]
        result = _build_collection_result_from_fliggy_rows(shop_id=1, start_url="https://hotel.fliggy.com", rows=rows)
        item = result["items"][0]
        self.assertEqual(item["name"], "杭州西湖国宾馆")
        self.assertEqual(item["signals"]["title"], "杭州西湖国宾馆")

    def test_build_collection_result_normalizes_incomplete_marketing_suffix(self) -> None:
        rows = [
            {
                "hotel_name": "河南天地粤海酒店\uE123 立减",
                "price": 699.0,
                "url": "https://hotel.example.com/henan",
                "raw_text": "河南天地粤海酒店\uE123 立减 ¥699",
            }
        ]
        result = _build_collection_result_from_fliggy_rows(shop_id=1, start_url="https://hotel.fliggy.com", rows=rows)
        item = result["items"][0]
        self.assertEqual(item["name"], "河南天地粤海酒店")
        self.assertEqual(item["signals"]["title"], "河南天地粤海酒店")


    @patch("app.services.competitor_service._collect_fliggy_hotel_prices_via_cdp")
    def test_collect_fliggy_prices_filters_to_selected_target_hotels(self, mocked_collect) -> None:
        mocked_collect.return_value = {
            "shop_id": 1,
            "collected_at": "2026-04-01 10:00:00",
            "count": 2,
            "raw_row_count": 2,
            "kept_row_count": 2,
            "filtered_row_count": 0,
            "filter_summary": {},
            "filtered_examples": [],
            "items": [
                {
                    "name": "全季杭州西湖店",
                    "url": "https://example.com/a",
                    "fetch_status": "success",
                    "analysis_source": "playwright",
                    "signals": {"price_signals": ["¥298起"], "snippet": "全季杭州西湖店 ¥298起"},
                    "analysis": {},
                },
                {
                    "name": "汉庭郑州东站店",
                    "url": "https://example.com/b",
                    "fetch_status": "success",
                    "analysis_source": "playwright",
                    "signals": {"price_signals": ["¥218起"], "snippet": "汉庭郑州东站店 ¥218起"},
                    "analysis": {},
                },
            ],
        }

        result = collect_fliggy_hotel_prices_playwright(
            db=None,
            shop_id=1,
            start_url="https://hotel.fliggy.com/hotel_list3.htm?city=330100",
            max_pages=1,
            max_hotels=20,
            headless=True,
            collect_mode="cdp_current_page",
            target_hotel_names=["全季", "桔子"],
        )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["name"], "全季杭州西湖店")
        self.assertEqual(result["target_hotel_names"], ["全季", "桔子"])
        self.assertEqual(result["missing_target_hotel_names"], ["桔子"])
        self.assertEqual(result["filter_summary"]["target_hotel_name_mismatch"], 1)


    @patch("app.services.competitor_service._collect_fliggy_hotel_prices_via_cdp")
    def test_collect_fliggy_prices_matches_trimmed_branch_name_for_selected_hotel(self, mocked_collect) -> None:
        mocked_collect.return_value = {
            "shop_id": 1,
            "collected_at": "2026-04-09 10:00:00",
            "count": 1,
            "raw_row_count": 1,
            "kept_row_count": 1,
            "filtered_row_count": 0,
            "filter_summary": {},
            "filtered_examples": [],
            "items": [
                {
                    "name": "中油花园酒店（CBD会展中心店）",
                    "url": "https://example.com/zyhy",
                    "fetch_status": "success",
                    "analysis_source": "playwright",
                    "signals": {"price_signals": ["¥468起"], "snippet": "中油花园酒店（CBD会展中心店） ¥468起"},
                    "analysis": {},
                },
            ],
        }

        result = collect_fliggy_hotel_prices_playwright(
            db=None,
            shop_id=1,
            start_url="https://hotel.fliggy.com/hotel_list3.htm?city=410100",
            max_pages=1,
            max_hotels=20,
            headless=True,
            collect_mode="cdp_current_page",
            target_hotel_names=["郑州中油花园酒店"],
        )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["name"], "中油花园酒店（CBD会展中心店）")
        self.assertEqual(result["matched_target_hotel_names"], ["郑州中油花园酒店"])
        self.assertEqual(result["missing_target_hotel_names"], [])



    def test_extension_page_collect_keeps_all_items_and_marks_target_match(self) -> None:
        result = collect_fliggy_hotel_prices_from_extension_page(
            shop_id=1,
            start_url="https://hotel.fliggy.com/hotel_list3.htm?city=410100",
            max_hotels=1,
            target_hotel_names=["郑州中油花园酒店"],
            page_snapshot={
                "candidate_rows": [
                    {
                        "name": "郑州建业艾美酒店",
                        "text": "郑州建业艾美酒店\n4.7分 1500条点评 地图\n¥588起",
                        "href": "https://hotel.fliggy.com/hotel_detail.htm?id=1",
                        "price": 588,
                    },
                    {
                        "name": "中油花园酒店（CBD会展中心店）",
                        "text": "中油花园酒店（CBD会展中心店）\n4.8分 999条点评 早餐\n¥468",
                        "href": "https://hotel.fliggy.com/hotel_detail.htm?id=2",
                        "price": 468,
                    },
                ]
            },
        )

        self.assertEqual(result["raw_row_count"], 2)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["items"][0]["name"], "郑州建业艾美酒店")
        self.assertEqual(result["matched_target_hotel_names"], ["郑州中油花园酒店"])
        self.assertEqual(result["missing_target_hotel_names"], [])
        self.assertEqual(result["target_match_items"][0]["matched_name"], "中油花园酒店（CBD会展中心店）")


    @patch("app.services.competitor_service._collect_fliggy_hotel_prices_via_cdp")
    def test_collect_fliggy_prices_matches_target_from_snippet_when_name_is_truncated(self, mocked_collect) -> None:
        mocked_collect.return_value = {
            "shop_id": 1,
            "collected_at": "2026-04-09 11:20:00",
            "count": 1,
            "raw_row_count": 1,
            "kept_row_count": 1,
            "filtered_row_count": 0,
            "filter_summary": {},
            "filtered_examples": [],
            "items": [
                {
                    "name": "CBD会展中心店",
                    "url": "https://example.com/zyhy-snippet",
                    "fetch_status": "success",
                    "analysis_source": "playwright",
                    "signals": {
                        "title": "CBD会展中心店",
                        "price_signals": ["¥468起"],
                        "snippet": "郑州中油花园酒店（CBD会展中心店） ¥468起",
                    },
                    "analysis": {},
                },
            ],
        }

        result = collect_fliggy_hotel_prices_playwright(
            db=None,
            shop_id=1,
            start_url="https://hotel.fliggy.com/hotel_list3.htm?city=410100",
            max_pages=1,
            max_hotels=20,
            headless=True,
            collect_mode="cdp_current_page",
            target_hotel_names=["郑州中油花园酒店"],
        )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["matched_target_hotel_names"], ["郑州中油花园酒店"])
        self.assertEqual(result["missing_target_hotel_names"], [])


    def test_extension_page_collect_matches_full_target_name_with_city_prefix(self) -> None:
        result = collect_fliggy_hotel_prices_from_extension_page(
            shop_id=1,
            start_url="https://hotel.fliggy.com/hotel_list3.htm?city=410100",
            max_hotels=5,
            target_hotel_names=["郑州中油花园酒店（CBD会展中心店）"],
            page_snapshot={
                "candidate_rows": [
                    {
                        "name": "中油花园酒店",
                        "text": "中油花园酒店\n4.8分 999条点评 早餐\n¥468",
                        "href": "https://hotel.fliggy.com/hotel_detail.htm?id=2",
                        "price": 468,
                    },
                ]
            },
        )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["matched_target_hotel_names"], ["郑州中油花园酒店（CBD会展中心店）"])
        self.assertEqual(result["missing_target_hotel_names"], [])

    def test_extension_page_collect_keeps_target_row_even_when_hotel_signal_is_weak(self) -> None:
        result = collect_fliggy_hotel_prices_from_extension_page(
            shop_id=1,
            start_url="https://hotel.fliggy.com/hotel_list3.htm?city=410100",
            max_hotels=5,
            target_hotel_names=["郑州中油花园酒店（CBD会展中心店）"],
            page_snapshot={
                "candidate_rows": [
                    {
                        "name": "CBD会展中心店",
                        "text": "郑州中油花园CBD会展中心店\n¥468",
                        "href": "",
                        "price": 468,
                    },
                ]
            },
        )

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["matched_target_hotel_names"], ["郑州中油花园酒店（CBD会展中心店）"])
        self.assertEqual(result["missing_target_hotel_names"], [])
        self.assertEqual(result["target_match_items"][0]["price"], "¥468")


    def test_extension_page_collect_warns_when_page_city_conflicts_with_target_hotel(self) -> None:
        result = collect_fliggy_hotel_prices_from_extension_page(
            shop_id=1,
            start_url="https://hotel.fliggy.com/hotel_list3.htm?cityName=北京",
            max_hotels=5,
            target_hotel_names=["郑州中油花园酒店"],
            page_snapshot={
                "page_context": {"cityName": "北京"},
                "candidate_rows": [],
            },
        )

        self.assertIn("当前页城市为北京", result["warning_message"])
        self.assertIn("郑州中油花园酒店", result["warning_message"])

    def test_extract_response_text_openresponses_message(self) -> None:
        payload = {
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "{\"summary\":\"ok\",\"pricing_signals\":[]}",
                        }
                    ],
                }
            ]
        }
        text = _extract_response_text(payload)
        self.assertIn('"summary":"ok"', text)

    def test_extract_chat_completions_text(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "{\"summary\":\"ok\",\"pricing_signals\":[]}",
                    }
                }
            ]
        }
        text = _extract_chat_completions_text(payload)
        self.assertIn('"summary":"ok"', text)
    def test_normalize_competitor_snapshot_source_aliases(self) -> None:
        self.assertEqual(_normalize_competitor_snapshot_source("fliggy-daily"), "fliggy_playwright_daily")
        self.assertEqual(_normalize_competitor_snapshot_source("scheduler"), "schedule")
        self.assertEqual(_normalize_competitor_snapshot_source("manual"), "manual")

    def test_build_competitor_snapshot_cleanup_plan_normalizes_name_and_source(self) -> None:
        plan = build_competitor_snapshot_cleanup_plan(
            {
                "id": 11,
                "target_name": "杭州西湖国宾馆\uE123 会员价 立减20元",
                "target_url": "https://hotel.fliggy.com/hotel_detail.htm?id=11",
                "source": "fliggy-daily",
                "signals_json": {
                    "title": "杭州西湖国宾馆",
                    "snippet": "杭州西湖国宾馆 4.8分 早餐 ¥899起",
                    "price_signals": ["¥899起"],
                },
            }
        )

        self.assertTrue(plan["should_update"])
        self.assertEqual(plan["updates"]["target_name"], "杭州西湖国宾馆")
        self.assertEqual(plan["updates"]["source"], "fliggy_playwright_daily")
        self.assertFalse(plan["should_delete"])

    def test_build_competitor_snapshot_cleanup_plan_trims_incomplete_marketing_suffix(self) -> None:
        plan = build_competitor_snapshot_cleanup_plan(
            {
                "id": 14,
                "target_name": "河南天地粤海酒店立减",
                "target_url": "https://hotel.fliggy.com/hotel_detail.htm?id=14",
                "source": "fliggy",
                "signals_json": {
                    "title": "河南天地粤海酒店立减",
                    "snippet": "河南天地粤海酒店立减 ¥699起",
                    "price_signals": ["¥699起"],
                },
            }
        )

        self.assertTrue(plan["should_update"])
        self.assertEqual(plan["updates"]["target_name"], "河南天地粤海酒店")
        self.assertFalse(plan["should_delete"])

    def test_build_competitor_snapshot_cleanup_plan_uses_signal_title_when_name_unknown(self) -> None:
        plan = build_competitor_snapshot_cleanup_plan(
            {
                "id": 12,
                "target_name": "unknown",
                "target_url": "https://hotel.fliggy.com/hotel_detail.htm?id=12",
                "source": "fliggy",
                "signals_json": {
                    "title": "杭州君悦酒店",
                    "snippet": "杭州君悦酒店 4.7分 地图 ¥1099起",
                    "price_signals": ["¥1099起"],
                },
            }
        )

        self.assertEqual(plan["updates"]["target_name"], "杭州君悦酒店")
        self.assertFalse(plan["should_delete"])

    def test_build_competitor_snapshot_cleanup_plan_marks_login_url_invalid(self) -> None:
        plan = build_competitor_snapshot_cleanup_plan(
            {
                "id": 13,
                "target_name": "杭州西湖国宾馆",
                "target_url": "https://login.taobao.com/member/login.jhtml",
                "source": "fliggy",
                "signals_json": {
                    "title": "杭州西湖国宾馆",
                    "snippet": "杭州西湖国宾馆 ¥899起",
                    "price_signals": ["¥899起"],
                },
            }
        )

        self.assertTrue(plan["should_delete"])
        self.assertEqual(plan["invalid_reason"], "invalid_fliggy_entry_url")
if __name__ == "__main__":
    unittest.main()

    @patch('app.services.competitor_service._collect_fliggy_hotel_prices_playwright_once')
    @patch('app.services.competitor_service.login_fliggy_guest_session')
    @patch('app.services.competitor_service.save_merchant_credential')
    @patch('app.services.competitor_service._resolve_fliggy_guest_context')
    def test_collect_fliggy_prices_auto_logins_guest_when_state_missing(
        self,
        mocked_resolve,
        mocked_save,
        mocked_login,
        mocked_collect_once,
    ) -> None:
        mocked_resolve.return_value = {
            'credential': {'tenant_id': 1},
            'login_url': 'https://hotel.fliggy.com/',
            'start_url': 'https://hotel.fliggy.com/',
            'storage_state_name': 'guest-shop-1.json',
            'selectors': {},
        }
        mocked_login.return_value = {'session_saved': True}
        mocked_collect_once.return_value = {
            'shop_id': 1,
            'count': 0,
            'items': [],
            'collected_at': '2026-03-18 10:00:00',
        }

        result = collect_fliggy_hotel_prices_playwright(
            db=object(),
            shop_id=1,
            start_url='https://hotel.fliggy.com/',
            max_pages=1,
            max_hotels=10,
            headless=True,
            username='guest@example.com',
            password='guest-secret',
            auto_login=True,
            login_headless=False,
        )

        mocked_save.assert_called_once()
        mocked_login.assert_called_once()
        mocked_collect_once.assert_called_once()
        self.assertTrue(result['auto_login_performed'])
        self.assertTrue(result['credential_saved'])


@unittest.skipIf(create_app is None, 'Flask is not installed')
class CompetitorRouteTestCase(unittest.TestCase):
    def test_guest_login_route_saves_session(self) -> None:
        app = create_app(session_factory=lambda: object())
        app.testing = True
        client = app.test_client()

        with (
            patch('app.api.routes.require_tenant_shop', return_value=(1, 1)),
            patch(
                'app.api.routes.login_fliggy_guest_session',
                return_value={
                    'shop_id': 1,
                    'status': 'success',
                    'storage_state_name': 'guest-shop-1.json',
                    'session_saved': True,
                },
            ) as mocked_login,
        ):
            resp = client.post(
                '/competitor/fliggy/session/login',
                json={
                    'shop_id': 1,
                    'login_url': 'https://hotel.fliggy.com/',
                    'start_url': 'https://hotel.fliggy.com/',
                    'storage_state_name': 'guest-shop-1.json',
                    'username': 'guest@example.com',
                    'password': 'guest-secret',
                    'headless': False,
                },
                headers={'X-Tenant-Id': '1', 'X-Shop-Id': '1'},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['message'], 'guest session saved')
        self.assertTrue(data['session_saved'])
        mocked_login.assert_called_once()




