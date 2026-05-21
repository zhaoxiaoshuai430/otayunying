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

from app.services.competitor_room_price_schedule_service import (
    build_competitor_fetch_jobs,
    collect_all_enabled_competitor_room_prices,
    collect_competitor_room_prices_for_shop,
    list_enabled_competitor_hotel_groups,
    list_enabled_competitor_hotel_subscriptions,
)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class FakeDb:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.closed = False
        self.committed = False
        self.rolled_back = False

    def execute(self, statement, params=None):
        sql = str(statement)
        if "CREATE TABLE IF NOT EXISTS competitor_hotels" in sql:
            return FakeResult([])
        return FakeResult(self.rows)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class CompetitorRoomPriceScheduleServiceTestCase(unittest.TestCase):
    def test_list_enabled_competitor_hotel_groups_limits_per_shop(self) -> None:
        rows = [
            {'tenant_id': 1, 'shop_id': 11, 'hotel_name': 'A 酒店', 'hotel_url': 'https://example.com/a', 'sort_order': 10, 'id': 1},
            {'tenant_id': 1, 'shop_id': 11, 'hotel_name': 'B 酒店', 'hotel_url': 'https://example.com/b', 'sort_order': 20, 'id': 2},
            {'tenant_id': 1, 'shop_id': 12, 'hotel_name': 'C 酒店', 'hotel_url': 'https://example.com/c', 'sort_order': 10, 'id': 3},
        ]

        groups = list_enabled_competitor_hotel_groups(FakeDb(rows), max_hotels_per_shop=1)

        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]['shop_id'], 11)
        self.assertEqual(groups[0]['hotels'], [{'name': 'A 酒店', 'url': 'https://example.com/a'}])
        self.assertEqual(groups[1]['shop_id'], 12)

    def test_collect_competitor_room_prices_for_shop_saves_crawl_results(self) -> None:
        crawl_results = [
            {'hotel_name': 'A 酒店', 'rooms': [{'room_type': '大床房', 'price': 399.0}]},
            {'hotel_name': 'B 酒店', 'error': 'timeout', 'rooms': []},
        ]
        with patch('app.services.competitor_room_price_schedule_service.save_room_prices', return_value=1) as mocked_save:
            result = collect_competitor_room_prices_for_shop(
                FakeDb(),
                shop_id=11,
                crawl_results=crawl_results,
            )

        self.assertEqual(result['saved_count'], 1)
        self.assertEqual(result['total_rooms'], 1)
        self.assertEqual(result['failed_count'], 1)
        mocked_save.assert_called_once()

    def test_list_enabled_competitor_hotel_subscriptions_flattens_groups(self) -> None:
        rows = [
            {'tenant_id': 1, 'shop_id': 11, 'hotel_name': 'A 酒店', 'hotel_url': 'https://example.com/a', 'sort_order': 10, 'id': 1},
            {'tenant_id': 1, 'shop_id': 12, 'hotel_name': 'B 酒店', 'hotel_url': 'https://example.com/b', 'sort_order': 20, 'id': 2},
        ]

        with patch(
            'app.services.competitor_room_price_schedule_service.get_merchant_credential',
            side_effect=[
                {'storage_state_name': 'guest-shop-11.json'},
                {'storage_state_name': 'guest-shop-12.json'},
            ],
        ):
            subscriptions = list_enabled_competitor_hotel_subscriptions(FakeDb(rows), max_hotels_per_shop=5)

        self.assertEqual(
            subscriptions,
            [
                {'tenant_id': 1, 'shop_id': 11, 'hotel_name': 'A 酒店', 'hotel_url': 'https://example.com/a', 'storage_state_name': 'guest-shop-11.json'},
                {'tenant_id': 1, 'shop_id': 12, 'hotel_name': 'B 酒店', 'hotel_url': 'https://example.com/b', 'storage_state_name': 'guest-shop-12.json'},
            ],
        )

    def test_build_competitor_fetch_jobs_deduplicates_same_hotel_url(self) -> None:
        jobs = build_competitor_fetch_jobs(
            [
                {'tenant_id': 1, 'shop_id': 11, 'hotel_name': 'A 酒店', 'hotel_url': 'https://example.com/a', 'storage_state_name': 'shared.json'},
                {'tenant_id': 1, 'shop_id': 12, 'hotel_name': 'A 酒店别名', 'hotel_url': 'https://example.com/a', 'storage_state_name': 'shared.json'},
            ]
        )

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['hotel_url'], 'https://example.com/a')
        self.assertEqual(jobs[0]['storage_state_name'], 'shared.json')
        self.assertEqual(jobs[0]['crawl_shop_id'], 11)
        self.assertEqual(len(jobs[0]['subscriptions']), 2)

    def test_collect_all_enabled_competitor_room_prices_deduplicates_fetch_and_distributes_to_shops(self) -> None:
        dbs = [
            FakeDb(
                [
                    {'tenant_id': 1, 'shop_id': 11, 'hotel_name': 'A 酒店', 'hotel_url': 'https://example.com/a', 'sort_order': 10, 'id': 1},
                    {'tenant_id': 1, 'shop_id': 12, 'hotel_name': 'A 酒店别名', 'hotel_url': 'https://example.com/a', 'sort_order': 10, 'id': 2},
                ]
            ),
            FakeDb(),
            FakeDb(),
        ]

        def session_factory():
            return dbs.pop(0)

        with patch(
            'app.services.competitor_room_price_schedule_service.get_merchant_credential',
            side_effect=[
                {'storage_state_name': 'shared.json'},
                {'storage_state_name': 'shared.json'},
            ],
        ), patch(
            'app.services.competitor_room_price_schedule_service.collect_competitor_room_price_job',
            return_value={
                'hotel_url': 'https://example.com/a',
                'crawl_name': 'A 酒店',
                'started_at': '2026-04-28 12:00:00',
                'hotel_count': 1,
                'total_rooms': 1,
                'failed_count': 0,
                'failed_hotels': [],
                'crawl_result': {
                    'hotel_name': 'A 酒店',
                    'hotel_url': 'https://example.com/a',
                    'collected_at': '2026-04-28 12:00:00',
                    'room_count': 1,
                    'rooms': [{'room_type': '大床房', 'price': 399.0, 'breakfast': '含早', 'cancelable': '可取消', 'raw_text': ''}],
                },
            },
        ) as mocked_fetch:
            result = collect_all_enabled_competitor_room_prices(session_factory=session_factory)

        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['shop_count'], 2)
        self.assertEqual(result['fetch_job_count'], 1)
        self.assertEqual(result['hotel_count'], 2)
        self.assertEqual(result['total_rooms'], 2)
        self.assertEqual(result['saved_count'], 2)
        self.assertEqual([item['shop_id'] for item in result['results']], [11, 12])
        mocked_fetch.assert_called_once()
        self.assertEqual(mocked_fetch.call_args.kwargs['storage_state_name'], 'shared.json')


if __name__ == '__main__':
    unittest.main()
