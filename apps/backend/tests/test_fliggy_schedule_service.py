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

from app.services.fliggy_schedule_service import (
    build_fliggy_schedule_settings,
    generate_fliggy_schedule_recommendation,
    get_fliggy_schedule_status,
    merge_fliggy_schedule_settings,
)


class _AliveRunner:
    def is_alive(self) -> bool:
        return True


class FliggyScheduleServiceTestCase(unittest.TestCase):
    def test_build_schedule_settings(self) -> None:
        settings = build_fliggy_schedule_settings(
            {
                'schedule_enabled': True,
                'schedule_interval_minutes': 120,
                'debug_url': 'http://127.0.0.1:9333',
                'target_page_url_keyword': 'city=330100',
                'max_pages': 3,
                'max_hotels': 88,
                'target_hotel_names': ['全季杭州西湖店', '汉庭郑州东站店'],
            }
        )
        self.assertTrue(settings['schedule_enabled'])
        self.assertEqual(settings['schedule_interval_minutes'], 120)
        self.assertEqual(settings['debug_url'], 'http://127.0.0.1:9333')
        self.assertEqual(settings['max_pages'], 3)
        self.assertEqual(settings['max_hotels'], 88)
        self.assertEqual(settings['target_hotel_names'], ['全季杭州西湖店', '汉庭郑州东站店'])

    def test_merge_schedule_settings_normalizes_target_hotels(self) -> None:
        merged = merge_fliggy_schedule_settings(
            {'room_rows': ['.row']},
            schedule_enabled=True,
            schedule_interval_minutes=30,
            debug_url='http://127.0.0.1:9222',
            target_page_url_keyword='city=410100',
            max_pages=2,
            max_hotels=40,
            target_hotel_names=['全季杭州西湖店', ' 全季杭州西湖店 ', '汉庭郑州东站店'],
        )
        self.assertEqual(merged['room_rows'], ['.row'])
        self.assertTrue(merged['schedule_enabled'])
        self.assertEqual(merged['schedule_interval_minutes'], 60)
        self.assertEqual(merged['target_page_url_keyword'], 'city=410100')
        self.assertEqual(merged['max_pages'], 2)
        self.assertEqual(merged['max_hotels'], 40)
        self.assertEqual(merged['target_hotel_names'], ['全季杭州西湖店', '汉庭郑州东站店'])

    @patch('app.services.fliggy_schedule_service.create_merchant_pricing_audit', return_value={'audit_id': 9, 'shop_id': 1, 'stage': 'fliggy_schedule_recommendation', 'audit_mode': 'dry_run', 'status': 'success', 'item_count': 1, 'action_count': 0})
    @patch('app.services.fliggy_schedule_service.evaluate_auto_pricing_risk', return_value={'current_price': 299.0, 'final_price': 312.0, 'change_pct': 4.35, 'risk_level': 'L1', 'require_manual_approval': False})
    @patch('app.services.fliggy_schedule_service.generate_auto_pricing_recommendation')
    @patch('app.services.fliggy_schedule_service.collect_auto_pricing_context')
    def test_generate_schedule_recommendation_persists_audit(self, mocked_context, mocked_generate, mocked_risk, mocked_create_audit) -> None:
        mocked_context.return_value = {
            'status': 'ok',
            'rule': {'strategy': 'balanced', 'target_name': None, 'max_change_pct': 8},
            'inventory_snapshot': {'total_rooms': 20, 'available_rooms': 5, 'current_price': 299.0},
        }
        mocked_generate.return_value = {
            'shop_id': 1,
            'suggested_price': 312.0,
            'recommendation': {
                'recommendation_source': 'fallback',
                'competitor_context': {'price_count': 6, 'price_avg': 305.0, 'latest_collected_at': '2026-04-01 10:00:00'},
                'price_recommendation': {
                    'price_min': 298.0,
                    'price_mid': 312.0,
                    'price_max': 326.0,
                    'context_summary': '竞对均价高于当前价，建议小幅上调。',
                    'reasons': ['竞对均价更高', '库存可控'],
                    'updated_at': '2026-04-01 10:05:00',
                },
            },
        }

        result = generate_fliggy_schedule_recommendation(db=object(), shop_id=1, trigger_type='fliggy_schedule')

        self.assertEqual(result['suggested_price'], 312.0)
        self.assertEqual(result['final_price'], 312.0)
        self.assertEqual(result['recommendation_source'], 'fallback')
        self.assertEqual(result['competitor_price_count'], 6)
        self.assertEqual(result['reasons'], ['竞对均价更高', '库存可控'])
        mocked_create_audit.assert_called_once()
        self.assertEqual(mocked_create_audit.call_args.kwargs['stage'], 'fliggy_schedule_recommendation')
        self.assertEqual(mocked_create_audit.call_args.kwargs['payload']['trigger_type'], 'fliggy_schedule')
        self.assertEqual(mocked_risk.call_args.kwargs['suggested_price'], 312.0)

    @patch('app.services.fliggy_schedule_service.get_latest_fliggy_schedule_recommendation', return_value={'created_at': '2026-04-01 10:05:00', 'suggested_price': 312.0, 'price_min': 298.0, 'price_mid': 312.0, 'price_max': 326.0, 'recommendation_source': 'fallback', 'competitor_price_count': 6, 'risk_level': 'L1'})
    @patch('app.services.fliggy_schedule_service._RUNNER', new_callable=lambda: _AliveRunner())
    def test_get_schedule_status_exposes_latest_recommendation(self, _runner, mocked_latest) -> None:
        status = get_fliggy_schedule_status(
            shop_id=1,
            credential={'selectors': {'schedule_enabled': True, 'schedule_interval_minutes': 60}},
            db=object(),
        )

        self.assertTrue(status['runner_started'])
        self.assertEqual(status['last_recommendation_status'], 'success')
        self.assertEqual(status['latest_recommendation']['suggested_price'], 312.0)
        self.assertEqual(status['last_recommendation_at'], '2026-04-01 10:05:00')
        mocked_latest.assert_called_once()


if __name__ == '__main__':
    unittest.main()
