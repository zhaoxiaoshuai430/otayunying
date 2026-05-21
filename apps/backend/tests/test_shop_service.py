import os
import sys
import unittest
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

from app.services.shop_service import (
    _build_default_shop_config,
    _build_shop_write_payload,
    _row_to_shop_config,
    build_shop_public_dict,
)


class ShopServiceTestCase(unittest.TestCase):
    def _fake_settings(self) -> SimpleNamespace:
        return SimpleNamespace(
            fliggy_hotel_id='hotel-1',
            fliggy_room_status_hotel_id='room-hotel-1',
            fliggy_app_key='key-1',
            fliggy_app_secret='secret-1',
            fliggy_session='session-1',
            room_status_auto_enabled=True,
            room_status_total_rooms=28,
            room_status_available_rooms=7,
            room_status_current_price=458.0,
            daily_revenue_auto_enabled=True,
            fliggy_price_push_enabled=True,
            fliggy_price_push_method='taobao.xhotel.rate.update',
            fliggy_price_push_payload_json='{"gid":"gid-1"}',
        )

    def test_default_shop_config_comes_from_settings(self) -> None:
        with patch('app.services.shop_service.get_settings', return_value=self._fake_settings()):
            config = _build_default_shop_config()

        self.assertEqual(config.shop_id, 1)
        self.assertEqual(config.fliggy_hotel_id, 'hotel-1')
        self.assertTrue(config.room_status_auto_enabled)
        self.assertEqual(config.room_status_total_rooms, 28)
        self.assertEqual(config.room_status_current_price, 458.0)
        self.assertTrue(config.daily_revenue_auto_enabled)
        self.assertTrue(config.fliggy_price_push_enabled)
        self.assertEqual(config.fliggy_price_push_method, 'taobao.xhotel.rate.update')

    def test_shop_one_can_fallback_to_global_credentials(self) -> None:
        with patch('app.services.shop_service.get_settings', return_value=self._fake_settings()):
            config = _row_to_shop_config(
                {
                    'id': 1,
                    'name': 'Default Shop',
                    'status': 'enabled',
                    'fliggy_hotel_id': '',
                    'fliggy_room_status_hotel_id': '',
                    'fliggy_app_key': '',
                    'fliggy_app_secret': '',
                    'fliggy_session': '',
                    'room_status_auto_enabled': 1,
                    'room_status_total_rooms': 30,
                    'room_status_available_rooms': 8,
                    'room_status_current_price': 499.0,
                    'daily_revenue_auto_enabled': 1,
                    'fliggy_price_push_enabled': 0,
                    'fliggy_price_push_method': '',
                    'fliggy_price_push_payload_json': '',
                }
            )

        self.assertEqual(config.fliggy_app_key, 'key-1')
        self.assertEqual(config.fliggy_session, 'session-1')
        self.assertEqual(config.room_status_total_rooms, 30)
        self.assertEqual(config.fliggy_price_push_method, 'taobao.xhotel.rate.update')

    def test_row_to_shop_config_supports_legacy_fields_and_merchant_fields(self) -> None:
        with patch('app.services.shop_service.get_settings', return_value=self._fake_settings()):
            config = _row_to_shop_config(
                {
                    'id': 2,
                    'tenant_id': 9,
                    'shop_name': '旧店铺名',
                    'status': 'active',
                    'fliggy_hotel_id': 'hotel-2',
                    'fliggy_room_status_hotel_id': 'room-hotel-2',
                    'fliggy_app_key': 'key-2',
                    'fliggy_app_secret': 'secret-2',
                    'fliggy_session': 'session-2',
                    'room_status_auto_enabled': 0,
                    'room_status_total_rooms': 15,
                    'room_status_available_rooms': 4,
                    'room_status_current_price': 288.5,
                    'daily_revenue_auto_enabled': 0,
                    'fliggy_price_push_enabled': 1,
                    'fliggy_price_push_method': 'taobao.xhotel.rate.update',
                    'fliggy_price_push_payload_json': '{"gid":"gid-2"}',
                    'fliggy_merchant_login_url': 'https://merchant.example.com/login',
                    'fliggy_merchant_price_url': 'https://merchant.example.com/price',
                    'fliggy_merchant_storage_state': 'shop-2.json',
                    'fliggy_merchant_price_selectors_json': '{"room_rows":[".price-row"]}',
                }
            )

        self.assertEqual(config.tenant_id, 9)
        self.assertEqual(config.name, '旧店铺名')
        self.assertEqual(config.status, 'enabled')
        self.assertEqual(config.fliggy_merchant_login_url, 'https://merchant.example.com/login')
        self.assertEqual(config.fliggy_merchant_storage_state, 'shop-2.json')
        self.assertTrue(config.fliggy_price_push_enabled)

    def test_build_shop_write_payload_preserves_legacy_compatibility(self) -> None:
        payload = _build_shop_write_payload(
            existing_row={
                'tenant_id': 7,
                'platform': 'fliggy',
                'shop_name': '旧店铺',
                'shop_external_id': 'legacy-001',
                'status': 'active',
                'fliggy_app_secret': 'old-secret',
                'fliggy_session': 'old-session',
                'fliggy_merchant_login_url': 'https://merchant.example.com/login',
                'fliggy_merchant_price_url': 'https://merchant.example.com/price',
            },
            shop_data={
                'shop_id': 1,
                'name': '新店铺',
                'status': 'inactive',
                'fliggy_app_key': 'new-key',
                'fliggy_app_secret': '',
                'fliggy_session': '',
                'room_status_auto_enabled': True,
                'room_status_total_rooms': 10,
                'room_status_available_rooms': 12,
                'room_status_current_price': 321.128,
            },
        )

        self.assertEqual(payload['tenant_id'], 7)
        self.assertEqual(payload['platform'], 'fliggy')
        self.assertEqual(payload['shop_name'], '旧店铺')
        self.assertEqual(payload['shop_external_id'], 'legacy-001')
        self.assertEqual(payload['status'], 'disabled')
        self.assertEqual(payload['fliggy_app_secret'], 'old-secret')
        self.assertEqual(payload['fliggy_session'], 'old-session')
        self.assertEqual(payload['room_status_available_rooms'], 10)
        self.assertEqual(payload['room_status_current_price'], 321.13)
        self.assertEqual(payload['fliggy_merchant_login_url'], 'https://merchant.example.com/login')

    def test_public_shop_dict_never_returns_secrets(self) -> None:
        with patch('app.services.shop_service.get_settings', return_value=self._fake_settings()):
            config = _build_default_shop_config()
            result = build_shop_public_dict(config)

        self.assertNotIn('fliggy_app_secret', result)
        self.assertNotIn('fliggy_session', result)
        self.assertNotIn('fliggy_price_push_payload_json', result)
        self.assertTrue(result['has_fliggy_credentials'])
        self.assertTrue(result['has_fliggy_session'])
        self.assertTrue(result['has_fliggy_price_push_template'])


if __name__ == '__main__':
    unittest.main()
