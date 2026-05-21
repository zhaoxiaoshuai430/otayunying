import json
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
    class _FakeHTTPResponse:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return json.dumps(self.payload, ensure_ascii=False).encode('utf-8')

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
        self.assertEqual(result['prompt_profile']['role'], '酒店收益管理与OTA定价专家')
        self.assertEqual(len(result['room_recommendations']), 2)
        self.assertEqual(result['merchant_room_snapshot']['item_count'], 2)
        self.assertEqual(result['advice_summary']['recommended_room_count'], 2)
        first_room = result['room_recommendations'][0]
        self.assertIn('competitor_min_price', first_room)
        self.assertIn('competitor_avg_price', first_room)
        self.assertIn('competitor_max_price', first_room)
        self.assertIn('suggested_price', first_room)
        self.assertGreater(first_room['suggested_price'], 0)

    @patch('app.services.competitor_pricing_advice_service._select_provider_settings', return_value=('fallback', '', '', ''))
    @patch('app.services.competitor_pricing_advice_service.get_room_price_trend_summary')
    @patch('app.services.competitor_pricing_advice_service.get_latest_merchant_price_snapshot')
    def test_preview_applies_majority_market_trend_ratio_to_room_suggestion(
        self,
        mocked_snapshot,
        mocked_trend_summary,
        _mocked_provider,
    ) -> None:
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
        mocked_trend_summary.return_value = {
            'shop_id': 1,
            'days': 2,
            'series_type': 'hotel_min_price',
            'latest_collected_at': '2026-04-14 18:00:00',
            'series': [
                {
                    'hotel_name': '竞对A',
                    'points': [
                        {'collected_at': '2026-04-14 10:00:00', 'min_price': 300},
                        {'collected_at': '2026-04-14 14:00:00', 'min_price': 315},
                        {'collected_at': '2026-04-14 18:00:00', 'min_price': 330},
                    ],
                },
                {
                    'hotel_name': '竞对B',
                    'points': [
                        {'collected_at': '2026-04-14 10:00:00', 'min_price': 280},
                        {'collected_at': '2026-04-14 14:00:00', 'min_price': 294},
                        {'collected_at': '2026-04-14 18:00:00', 'min_price': 308},
                    ],
                },
                {
                    'hotel_name': '竞对C',
                    'points': [
                        {'collected_at': '2026-04-14 10:00:00', 'min_price': 260},
                        {'collected_at': '2026-04-14 14:00:00', 'min_price': 273},
                        {'collected_at': '2026-04-14 18:00:00', 'min_price': 286},
                    ],
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
                {
                    'hotel_name': '竞对B',
                    'rooms': [
                        {'room_type': '豪华大床房', 'rate_name': '含早价', 'price': 480},
                    ],
                },
            ],
            strategy='balanced',
        )

        self.assertEqual(result['market_trend_context']['majority_signal'], 'up')
        self.assertAlmostEqual(result['market_trend_context']['representative_change_pct'], 10.0)
        room = result['room_recommendations'][0]
        self.assertAlmostEqual(room['trend_based_price'], 462.0)
        self.assertEqual(room['market_trend_pct'], 10.0)
        self.assertAlmostEqual(room['suggested_price'], 462.0)

    @patch('app.services.competitor_pricing_advice_service._select_provider_settings', return_value=('fallback', '', '', ''))
    @patch('app.services.competitor_pricing_advice_service.get_room_price_trend_summary')
    @patch('app.services.competitor_pricing_advice_service.get_latest_merchant_price_snapshot')
    def test_preview_applies_down_market_trend_ratio_to_room_suggestion(
        self,
        mocked_snapshot,
        mocked_trend_summary,
        _mocked_provider,
    ) -> None:
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
        mocked_trend_summary.return_value = {
            'shop_id': 1,
            'days': 2,
            'series_type': 'hotel_min_price',
            'latest_collected_at': '2026-04-14 18:00:00',
            'series': [
                {
                    'hotel_name': '竞对A',
                    'points': [
                        {'collected_at': '2026-04-14 10:00:00', 'min_price': 500},
                        {'collected_at': '2026-04-14 14:00:00', 'min_price': 475},
                        {'collected_at': '2026-04-14 18:00:00', 'min_price': 450},
                    ],
                },
                {
                    'hotel_name': '竞对B',
                    'points': [
                        {'collected_at': '2026-04-14 10:00:00', 'min_price': 400},
                        {'collected_at': '2026-04-14 14:00:00', 'min_price': 380},
                        {'collected_at': '2026-04-14 18:00:00', 'min_price': 360},
                    ],
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
                {
                    'hotel_name': '竞对B',
                    'rooms': [
                        {'room_type': '豪华大床房', 'rate_name': '含早价', 'price': 480},
                    ],
                },
            ],
            strategy='balanced',
        )

        self.assertEqual(result['market_trend_context']['majority_signal'], 'down')
        self.assertAlmostEqual(result['market_trend_context']['representative_change_pct'], -10.0)
        room = result['room_recommendations'][0]
        self.assertAlmostEqual(room['trend_based_price'], 378.0)
        self.assertEqual(room['market_trend_pct'], -10.0)
        self.assertAlmostEqual(room['suggested_price'], 378.0)

    @patch('app.services.competitor_pricing_advice_service._select_provider_settings', return_value=('fallback', '', '', ''))
    @patch('app.services.competitor_pricing_advice_service.get_room_price_trend_summary')
    @patch('app.services.competitor_pricing_advice_service.get_latest_merchant_price_snapshot')
    def test_preview_keeps_current_price_when_market_trend_is_flat(
        self,
        mocked_snapshot,
        mocked_trend_summary,
        _mocked_provider,
    ) -> None:
        mocked_snapshot.return_value = {
            'shop_id': 1,
            'collected_at': '2026-04-14 18:00:00',
            'item_count': 1,
            'items': [
                {
                    'room_name': '特惠大床房',
                    'rate_name': '标准价',
                    'display_name': '特惠大床房',
                    'gid': 'g1',
                    'hid': 'h1',
                    'observed_price': 212,
                },
            ],
        }
        mocked_trend_summary.return_value = {
            'shop_id': 1,
            'days': 2,
            'series_type': 'hotel_min_price',
            'latest_collected_at': '2026-04-14 18:00:00',
            'series': [
                {
                    'hotel_name': '竞对A',
                    'points': [
                        {'collected_at': '2026-04-14 10:00:00', 'min_price': 367},
                        {'collected_at': '2026-04-14 18:00:00', 'min_price': 367},
                    ],
                },
                {
                    'hotel_name': '竞对B',
                    'points': [
                        {'collected_at': '2026-04-14 10:00:00', 'min_price': 378},
                        {'collected_at': '2026-04-14 18:00:00', 'min_price': 378},
                    ],
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
                        {'room_type': '特惠大床房', 'rate_name': '标准价', 'price': 367},
                    ],
                },
                {
                    'hotel_name': '竞对B',
                    'rooms': [
                        {'room_type': '特惠大床房', 'rate_name': '标准价', 'price': 378},
                    ],
                },
            ],
            strategy='balanced',
        )

        self.assertEqual(result['market_trend_context']['majority_signal'], 'flat')
        room = result['room_recommendations'][0]
        self.assertAlmostEqual(room['trend_based_price'], 212.0)
        self.assertEqual(room['market_trend_pct'], 0.0)
        self.assertAlmostEqual(room['suggested_price'], 212.0)
        self.assertEqual(room['change_amount'], 0.0)
        self.assertIn('保持本店当前价', room['reasoning'])

    @patch('app.services.competitor_pricing_advice_service.urlopen')
    @patch('app.services.competitor_pricing_advice_service._select_provider_settings', return_value=('openai', 'test-key', 'test-model', 'https://example.com/v1'))
    @patch('app.services.competitor_pricing_advice_service.get_room_price_trend_summary')
    @patch('app.services.competitor_pricing_advice_service.get_latest_merchant_price_snapshot')
    def test_preview_keeps_current_price_when_llm_suggests_higher_without_trend(
        self,
        mocked_snapshot,
        mocked_trend_summary,
        _mocked_provider,
        mocked_urlopen,
    ) -> None:
        mocked_snapshot.return_value = {
            'shop_id': 1,
            'collected_at': '2026-04-14 18:00:00',
            'item_count': 1,
            'items': [
                {
                    'room_name': '特惠大床房',
                    'rate_name': '标准价',
                    'display_name': '特惠大床房',
                    'gid': 'g1',
                    'hid': 'h1',
                    'observed_price': 212,
                },
            ],
        }
        mocked_trend_summary.return_value = {
            'shop_id': 1,
            'days': 2,
            'series_type': 'hotel_min_price',
            'latest_collected_at': '2026-04-14 18:00:00',
            'series': [
                {
                    'hotel_name': '竞对A',
                    'points': [
                        {'collected_at': '2026-04-14 10:00:00', 'min_price': 367},
                        {'collected_at': '2026-04-14 18:00:00', 'min_price': 367},
                    ],
                },
            ],
        }
        mocked_urlopen.return_value = self._FakeHTTPResponse(
            {
                'choices': [
                    {
                        'message': {
                            'content': json.dumps(
                                {
                                    'room_recommendations': [
                                        {
                                            'display_name': '特惠大床房',
                                            'room_name': '特惠大床房',
                                            'rate_name': '标准价',
                                            'suggested_price': 262.39,
                                            'reasoning': '竞对均价更高，建议上调。',
                                            'risk_level': 'L3',
                                        }
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }
        )

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
                        {'room_type': '特惠大床房', 'rate_name': '标准价', 'price': 367},
                    ],
                },
            ],
            strategy='balanced',
        )

        self.assertEqual(result['recommendation_source'], 'openai')
        room = result['room_recommendations'][0]
        self.assertAlmostEqual(room['suggested_price'], 212.0)
        self.assertEqual(room['change_amount'], 0.0)
        self.assertEqual(room['risk_level'], 'L1')
        self.assertIn('不使用竞对均价调价', room['reasoning'])

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
    @patch('app.services.competitor_pricing_advice_service.get_latest_room_prices')
    @patch('app.services.competitor_pricing_advice_service.get_latest_merchant_price_snapshot')
    def test_preview_supports_manual_room_mappings_without_snapshot(self, mocked_snapshot, _mocked_latest_rooms, _mocked_provider) -> None:
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
    @patch('app.services.competitor_pricing_advice_service.get_latest_room_prices')
    @patch('app.services.competitor_pricing_advice_service.get_latest_merchant_price_snapshot')
    def test_preview_uses_manual_price_and_latest_competitor_room_prices(self, mocked_snapshot, mocked_latest_rooms, _mocked_provider) -> None:
        mocked_snapshot.return_value = {'shop_id': 1, 'collected_at': None, 'item_count': 0, 'items': []}
        mocked_latest_rooms.return_value = {
            'shop_id': 1,
            'collected_at': '2026-04-25 10:00:00',
            'hotel_count': 1,
            'hotels': [
                {
                    'hotel_name': '竞对A',
                    'hotel_url': 'https://example.com/a',
                    'rooms': [
                        {'room_type': '高级大床房', 'rate_name': '标准价', 'price': 520},
                        {'room_type': '高级大床房', 'rate_name': '含早价', 'price': 560},
                    ],
                }
            ],
        }

        result = preview_competitor_pricing_advice(
            db=object(),
            shop_id=1,
            inventory_snapshot={'total_rooms': 100, 'available_rooms': 20},
            competitor_hotels=[],
            manual_room_mappings=[
                {
                    'display_name': '高级大床房',
                    'room_type': '高级大床房',
                    'rate_name': '标准价',
                    'current_price': 480,
                    'competitor_room_names': ['高级大床房'],
                    'enabled': True,
                }
            ],
            strategy='balanced',
        )

        mocked_latest_rooms.assert_called_once()
        mocked_snapshot.assert_not_called()
        room = result['room_recommendations'][0]
        self.assertEqual(result['merchant_room_snapshot']['source'], 'manual_room_mappings')
        self.assertEqual(room['current_price'], 480)
        self.assertEqual(room['competitor_min_price'], 520)
        self.assertEqual(room['match_mode'], 'manual_mapping')

    @patch('app.services.competitor_pricing_advice_service._select_provider_settings', return_value=('fallback', '', '', ''))
    def test_trims_one_low_and_one_high_when_price_sample_gt_five(self, _mocked_provider) -> None:
        result = preview_competitor_pricing_advice(
            db=object(),
            shop_id=1,
            inventory_snapshot={'total_rooms': 100, 'available_rooms': 20},
            competitor_hotels=[
                {
                    'hotel_name': '竞对A',
                    'rooms': [
                        {'room_type': '高级大床房', 'rate_name': '标准价', 'price': 100},
                        {'room_type': '高级大床房', 'rate_name': '标准价', 'price': 200},
                        {'room_type': '高级大床房', 'rate_name': '标准价', 'price': 210},
                        {'room_type': '高级大床房', 'rate_name': '标准价', 'price': 220},
                        {'room_type': '高级大床房', 'rate_name': '标准价', 'price': 230},
                        {'room_type': '高级大床房', 'rate_name': '标准价', 'price': 1000},
                    ],
                }
            ],
            manual_room_mappings=[
                {
                    'display_name': '高级大床房',
                    'room_type': '高级大床房',
                    'rate_name': '标准价',
                    'current_price': 218,
                    'competitor_room_names': ['高级大床房'],
                    'enabled': True,
                }
            ],
            strategy='balanced',
        )

        room = result['room_recommendations'][0]
        self.assertEqual(room['competitor_min_price'], 200)
        self.assertEqual(room['competitor_avg_price'], 215)
        self.assertEqual(room['competitor_max_price'], 230)
        self.assertEqual(room['effective_price_count'], 4)
        self.assertEqual(room['trimmed_outlier_count'], 2)
        self.assertEqual(result['competitor_context']['price_min'], 200)
        self.assertEqual(result['competitor_context']['price_max'], 230)

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
