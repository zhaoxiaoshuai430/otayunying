import os
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
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

from app.core.config import get_settings

get_settings.cache_clear()

try:
    from app.main import create_app
except ModuleNotFoundError:  # Flask not installed in minimal test env
    create_app = None
from app.schemas.pricing import PricingRecommendationRequest
from app.services.pricing_service import generate_price_recommendation


class PricingServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = SimpleNamespace(
            llm_provider='openai',
            openai_api_key='',
            openai_model='gpt-4o-mini',
            openai_base_url='https://api.openai.com/v1',
            tongyi_api_key='',
            tongyi_model='qwen-plus',
            tongyi_base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
            fliggy_timeout_sec=3,
        )

    @patch('app.services.pricing_service.get_settings')
    @patch('app.services.pricing_service._query_competitor_price_rows')
    def test_generate_price_recommendation_fallback(self, mocked_rows, mocked_settings) -> None:
        mocked_settings.return_value = self.settings
        mocked_rows.return_value = [
            {
                'target_name': '竞对A',
                'signals_json': '{"price_signals": ["¥500", "¥520", "¥540"]}',
                'collected_at': '2026-03-06 10:00:00',
            }
        ]
        event_date = date.today() + timedelta(days=5)

        result = generate_price_recommendation(
            db=object(),
            shop_id=1,
            inventory_snapshot={'total_rooms': 20, 'available_rooms': 4, 'current_price': 500},
            target_name='竞对A',
            days=7,
            strategy='balanced',
            limit=20,
            event_date=event_date,
            target_occupancy_min=0.15,
            target_occupancy_max=0.20,
            demand_heat=0.7,
            competitor_price_cap_ratio=1.15,
        )

        card = result['price_recommendation']
        policy = card['policy_context']
        self.assertEqual(result['recommendation_source'], 'fallback')
        self.assertEqual(policy['stage'], 'dynamic_markup')
        self.assertGreaterEqual(card['price_mid'], 540)
        self.assertLessEqual(card['price_max'], policy['competitor_cap_price'])
        self.assertEqual(card['suggested_action']['action_type'], 'adjust_price')
        self.assertGreaterEqual(len(card['reasons']), 3)

    @patch('app.services.pricing_service.get_settings')
    @patch('app.services.pricing_service._call_chat_completions_for_pricing')
    @patch('app.services.pricing_service._query_competitor_price_rows')
    def test_generate_price_recommendation_llm(self, mocked_rows, mocked_llm, mocked_settings) -> None:
        mocked_settings.return_value = SimpleNamespace(
            llm_provider='openai',
            openai_api_key='test-key',
            openai_model='gpt-4o-mini',
            openai_base_url='https://api.openai.com/v1',
            tongyi_api_key='',
            tongyi_model='qwen-plus',
            tongyi_base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
            fliggy_timeout_sec=3,
        )
        mocked_rows.return_value = [
            {
                'target_name': '竞对A',
                'signals_json': '{"price_signals": ["¥520", "¥560", "¥580"]}',
                'collected_at': '2026-03-06 10:00:00',
            }
        ]
        mocked_llm.return_value = {
            'price_min': 560,
            'price_max': 650,
            'price_mid': 620,
            'currency': 'CNY',
            'reasons': ['竞对价格高位运行', '节前库存需要筛选高意愿客群'],
            'risk_level': 'L2',
            'context_summary': '节前建议提价',
        }

        result = generate_price_recommendation(
            db=object(),
            shop_id=1,
            inventory_snapshot={'total_rooms': 20, 'available_rooms': 3, 'current_price': 540},
            strategy='aggressive',
            event_date=date.today() + timedelta(days=2),
        )

        self.assertEqual(result['recommendation_source'], 'openai')
        self.assertEqual(result['price_recommendation']['suggested_action']['risk_level'], 'L2')
        self.assertIn('policy_context', result['price_recommendation'])
        self.assertLessEqual(
            result['price_recommendation']['price_max'],
            result['price_recommendation']['policy_context']['competitor_cap_price'],
        )

    @patch('app.services.pricing_service.get_settings')
    @patch('app.services.pricing_service._query_competitor_price_rows')
    def test_generate_price_recommendation_blends_merchant_history(self, mocked_rows, mocked_settings) -> None:
        mocked_settings.return_value = self.settings
        mocked_rows.return_value = [
            {
                'target_name': '竞对A',
                'signals_json': '{"price_signals": ["¥760", "¥780", "¥800"]}',
                'collected_at': '2026-03-06 10:00:00',
            }
        ]
        baseline = generate_price_recommendation(
            db=object(),
            shop_id=1,
            inventory_snapshot={'total_rooms': 20, 'available_rooms': 4, 'current_price': 500},
            strategy='balanced',
        )
        with_history = generate_price_recommendation(
            db=object(),
            shop_id=1,
            inventory_snapshot={'total_rooms': 20, 'available_rooms': 4, 'current_price': 500},
            strategy='balanced',
            merchant_history_context={
                'price_count': 8,
                'price_min': 500,
                'price_max': 530,
                'price_avg': 520,
                'latest_price': 510,
                'latest_collected_at': '2026-03-15 16:00:00',
            },
        )

        self.assertGreater(baseline['price_recommendation']['price_mid'], with_history['price_recommendation']['price_mid'])
        self.assertEqual(with_history['merchant_history_context']['price_count'], 8)
        self.assertEqual(with_history['price_recommendation']['merchant_history_context']['price_avg'], 520.0)
        self.assertIn('商家历史价', ''.join(with_history['price_recommendation']['reasons']))




@unittest.skipIf(create_app is None, 'Flask is not installed')
class PricingRouteTestCase(unittest.TestCase):
    @patch('app.api.routes.generate_price_recommendation')
    def test_pricing_recommend_route(self, mocked_generate) -> None:
        mocked_generate.return_value = {
            'shop_id': 1,
            'target_name': None,
            'days': 7,
            'strategy': 'balanced',
            'inventory_snapshot': {'total_rooms': 10, 'available_rooms': 2, 'occupancy_rate': 0.8},
            'competitor_context': {
                'price_count': 3,
                'price_min': 280,
                'price_max': 320,
                'price_avg': 300,
                'price_median': 300,
                'price_low_band': 290,
                'price_high_band': 315,
                'target_names': ['竞店A'],
                'latest_collected_at': '2026-03-06 10:00:00',
            },
            'event_policy': {'stage': 'dynamic_markup'},
            'price_recommendation': {
                'price_min': 295,
                'price_max': 325,
                'price_mid': 310,
                'currency': 'CNY',
                'reasons': ['原因1', '原因2'],
                'risk_level': 'L2',
                'context_summary': '竞对均价稳定',
                'policy_context': {'stage': 'dynamic_markup'},
                'suggested_action': {'action_type': 'adjust_price', 'risk_level': 'L2', 'payload': {'max_change_pct': 5}},
                'updated_at': '2026-03-06 12:00:00',
            },
            'recommendation_source': 'fallback',
        }

        app = create_app(session_factory=lambda: object())
        app.testing = True
        client = app.test_client()

        with patch('app.api.routes.require_tenant_shop', return_value=(1, 1)):
            resp = client.post(
                '/pricing/recommend',
                json={
                    'shop_id': 1,
                    'inventory_snapshot': {'total_rooms': 10, 'available_rooms': 2, 'current_price': 300},
                    'days': 7,
                    'strategy': 'balanced',
                    'limit': 20,
                    'event_date': '2030-01-01',
                },
                headers={'X-Tenant-Id': '1', 'X-Shop-Id': '1'},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['message'], 'pricing recommendation generated')
        self.assertEqual(data['price_recommendation']['suggested_action']['action_type'], 'adjust_price')


if __name__ == '__main__':
    unittest.main()
