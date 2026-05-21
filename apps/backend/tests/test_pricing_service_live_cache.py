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

from app.services.pricing_service import generate_price_recommendation


class PricingServiceLiveCacheTestCase(unittest.TestCase):
    def test_generate_price_recommendation_prefers_live_cache(self) -> None:
        live_rows = [
            {
                'target_name': '全季杭州西湖店',
                'target_url': 'https://example.com/hotel-a',
                'signals_json': {'price_signals': ['¥298起']},
                'collected_at': '2026-03-31 15:30:00',
                'source': 'fliggy_live_latest_prices',
            }
        ]
        inventory_snapshot = {
            'total_rooms': 20,
            'available_rooms': 5,
            'current_price': 299.0,
        }

        with patch('app.services.pricing_service.query_live_competitor_rows', return_value=live_rows), patch(
            'app.services.pricing_service.get_live_competitor_prices',
            return_value={
                'count': 1,
                'latest_collected_at': '2026-03-31 15:30:00',
                'matched_page_url': 'https://hotel.fliggy.com/hotel_list3.htm?city=330100',
                'target_page_url_keyword': 'city=330100',
                'debug_url': 'http://127.0.0.1:9222',
                'collect_mode': 'cdp_current_page',
                'hotels': [
                    {
                        'hotel_name': '全季杭州西湖店',
                        'price': 298.0,
                        'price_signals': ['¥298起'],
                        'url': 'https://example.com/hotel-a',
                    }
                ],
            },
        ), patch(
            'app.services.pricing_service._query_competitor_price_rows'
        ) as mocked_query_db, patch(
            'app.services.pricing_service._select_provider_settings',
            return_value=('', '', '', ''),
        ):
            result = generate_price_recommendation(
                db=object(),
                shop_id=1,
                inventory_snapshot=inventory_snapshot,
                target_name='全季',
                days=7,
                strategy='balanced',
            )

        mocked_query_db.assert_not_called()
        self.assertEqual(result['competitor_context'].get('data_source'), 'live_cache')
        self.assertGreater(result['competitor_context'].get('price_count') or 0, 0)
        self.assertEqual(result['competitor_context'].get('live_capture', {}).get('matched_page_url'), 'https://hotel.fliggy.com/hotel_list3.htm?city=330100')
        self.assertEqual(result['competitor_context'].get('live_capture', {}).get('sample_hotel_names'), ['全季杭州西湖店'])
        self.assertEqual(result['target_name'], '全季')


if __name__ == '__main__':
    unittest.main()

