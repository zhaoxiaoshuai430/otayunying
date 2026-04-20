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

from app.services.competitor_pricing_advice_service import preview_competitor_pricing_advice


class CompetitorPricingAdviceServiceTestCase(unittest.TestCase):
    @patch('app.services.competitor_pricing_advice_service._select_provider_settings', return_value=('fallback', '', '', ''))
    @patch('app.services.competitor_pricing_advice_service.get_latest_merchant_price_snapshot')
    def test_preview_returns_room_level_recommendations(self, mocked_snapshot, _mocked_provider) -> None:
        mocked_snapshot.return_value = {
            'shop_id': 1,
            'collected_at': '2026-04-14 18:00:00',
            'item_count': 2,
            'items': [
                {
                    'room_name': '豪华大床房',
                    'rate_name': '标准价',
                    'display_name': '豪华大床房',
                    'gid': 'g1',
                    'hid': 'h1',
                    'observed_price': 420,
                },
                {
                    'room_name': '豪华双床房',
                    'rate_name': '标准价',
                    'display_name': '豪华双床房',
                    'gid': 'g2',
                    'hid': 'h2',
                    'observed_price': 460,
                },
            ],
        }

        result = preview_competitor_pricing_advice(
            db=object(),
            shop_id=1,
            inventory_snapshot={
                'total_rooms': 100,
                'available_rooms': 22,
            },
            competitor_hotels=[
                {
                    'hotel_name': '竞对A',
                    'rooms': [
                        {'room_type': '豪华大床房', 'rate_name': '标准价', 'price': 450},
                        {'room_type': '豪华双床房', 'rate_name': '标准价', 'price': 470},
                    ],
                },
                {
                    'hotel_name': '竞对B',
                    'rooms': [
                        {'room_type': '豪华大床房', 'rate_name': '含早价', 'price': 480},
                        {'room_type': '豪华双床房', 'rate_name': '含早价', 'price': 500},
                    ],
                },
            ],
            strategy='balanced',
        )

        self.assertEqual(result['recommendation_source'], 'fallback')
        self.assertEqual(result['prompt_profile']['role'], '酒店OTA运营专家')
        self.assertEqual(len(result['room_recommendations']), 2)
        self.assertEqual(result['merchant_room_snapshot']['item_count'], 2)
        self.assertEqual(result['advice_summary']['recommended_room_count'], 2)
        first_room = result['room_recommendations'][0]
        self.assertIn('competitor_min_price', first_room)
        self.assertIn('competitor_avg_price', first_room)
        self.assertIn('competitor_max_price', first_room)
        self.assertIn('suggested_price', first_room)
        self.assertGreater(first_room['suggested_price'], 0)

    @patch('app.services.competitor_pricing_advice_service.urlopen', side_effect=TimeoutError())
    @patch('app.services.competitor_pricing_advice_service._select_provider_settings', return_value=('openai', 'test-key', 'test-model', 'https://example.com/v1'))
    @patch('app.services.competitor_pricing_advice_service.get_latest_merchant_price_snapshot')
    def test_preview_falls_back_when_llm_times_out(self, mocked_snapshot, _mocked_provider, _mocked_urlopen) -> None:
        mocked_snapshot.return_value = {
            'shop_id': 1,
            'collected_at': '2026-04-14 18:00:00',
            'item_count': 1,
            'items': [
                {
                    'room_name': '豪华大床房',
                    'rate_name': '标准价',
                    'display_name': '豪华大床房',
                    'gid': 'g1',
                    'hid': 'h1',
                    'observed_price': 420,
                },
            ],
        }

        result = preview_competitor_pricing_advice(
            db=object(),
            shop_id=1,
            inventory_snapshot={
                'total_rooms': 100,
                'available_rooms': 22,
            },
            competitor_hotels=[
                {
                    'hotel_name': '竞对A',
                    'rooms': [
                        {'room_type': '豪华大床房', 'rate_name': '标准价', 'price': 450},
                    ],
                },
            ],
            strategy='balanced',
        )

        self.assertEqual(result['recommendation_source'], 'fallback')
        self.assertEqual(len(result['room_recommendations']), 1)
        self.assertGreater(result['room_recommendations'][0]['suggested_price'], 0)

    @patch('app.services.competitor_pricing_advice_service._select_provider_settings', return_value=('fallback', '', '', ''))
    @patch('app.services.competitor_pricing_advice_service.get_latest_merchant_price_snapshot')
    def test_preview_supports_manual_room_mappings_without_snapshot(self, mocked_snapshot, _mocked_provider) -> None:
        mocked_snapshot.return_value = {'shop_id': 1, 'collected_at': None, 'item_count': 0, 'items': []}

        result = preview_competitor_pricing_advice(
            db=object(),
            shop_id=1,
            inventory_snapshot={
                'total_rooms': 100,
                'available_rooms': 22,
            },
            competitor_hotels=[
                {
                    'hotel_name': 'CompA',
                    'rooms': [
                        {'room_type': 'Superior King', 'rate_name': 'standard', 'price': 450},
                        {'room_type': 'Superior Twin', 'rate_name': 'standard', 'price': 470},
                    ],
                },
            ],
            manual_room_mappings=[
                {
                    'display_name': 'Superior King',
                    'room_type': 'King',
                    'rate_name': 'standard',
                    'current_price': 420,
                    'competitor_room_names': ['Superior King'],
                    'enabled': True,
                }
            ],
            strategy='balanced',
        )

        self.assertEqual(result['merchant_room_snapshot']['source'], 'manual_room_mappings')
        self.assertEqual(result['merchant_room_snapshot']['item_count'], 1)
        self.assertEqual(result['room_recommendations'][0]['display_name'], 'Superior King')
        self.assertEqual(result['room_recommendations'][0]['match_mode'], 'manual_mapping')

    @patch('app.services.competitor_pricing_advice_service._select_provider_settings', return_value=('fallback', '', '', ''))
    @patch('app.services.competitor_pricing_advice_service.get_latest_merchant_price_snapshot', return_value={'shop_id': 1, 'collected_at': None, 'item_count': 0, 'items': []})
    def test_preview_requires_merchant_room_snapshot(self, _mocked_snapshot, _mocked_provider) -> None:
        with self.assertRaisesRegex(ValueError, '本店房型价格快照'):
            preview_competitor_pricing_advice(
                db=object(),
                shop_id=1,
                inventory_snapshot={'total_rooms': 100, 'available_rooms': 20},
                competitor_hotels=[
                    {
                        'hotel_name': '竞对A',
                        'rooms': [
                            {'room_type': '豪华大床房', 'rate_name': '标准价', 'price': 450},
                        ],
                    }
                ],
                strategy='balanced',
            )


if __name__ == '__main__':
    unittest.main()
