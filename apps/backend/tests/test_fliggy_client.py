import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.fliggy_client import FliggyClient
from app.services.shop_service import ShopConfig


class FliggyClientTestCase(unittest.TestCase):
    def test_shop_level_credentials_override_global_settings(self) -> None:
        fake_settings = SimpleNamespace(
            fliggy_app_key='global-key',
            fliggy_app_secret='global-secret',
            fliggy_session='global-session',
            fliggy_format='json',
            fliggy_version='2.0',
            fliggy_sign_method='md5',
            fliggy_price_push_method='taobao.xhotel.rate.update',
            fliggy_price_push_payload_json='{"gid":"global-gid"}',
        )
        shop_config = ShopConfig(
            tenant_id=1,
            shop_id=2,
            name='Shop 2',
            status='enabled',
            source='database',
            fliggy_hotel_id='hotel-2',
            fliggy_room_status_hotel_id='room-hotel-2',
            fliggy_app_key='shop-key',
            fliggy_app_secret='shop-secret',
            fliggy_session='shop-session',
            room_status_auto_enabled=True,
            room_status_total_rooms=20,
            room_status_available_rooms=5,
            room_status_current_price=399.0,
            daily_revenue_auto_enabled=True,
        )

        with patch('app.services.fliggy_client.get_settings', return_value=fake_settings):
            client = FliggyClient(shop_config=shop_config)
            params = client._build_base_params(method='taobao.test.method', use_session=True)

        self.assertEqual(params['app_key'], 'shop-key')
        self.assertEqual(params['session'], 'shop-session')

    def test_build_price_push_request_from_template(self) -> None:
        fake_settings = SimpleNamespace(
            fliggy_app_key='global-key',
            fliggy_app_secret='global-secret',
            fliggy_session='global-session',
            fliggy_format='json',
            fliggy_version='2.0',
            fliggy_sign_method='md5',
            fliggy_price_push_method='taobao.xhotel.rate.update',
            fliggy_price_push_payload_json='{"gid":"global-gid"}',
        )
        shop_config = ShopConfig(
            tenant_id=1,
            shop_id=2,
            name='Shop 2',
            status='enabled',
            source='database',
            fliggy_hotel_id='hotel-2',
            fliggy_room_status_hotel_id='room-hotel-2',
            fliggy_app_key='shop-key',
            fliggy_app_secret='shop-secret',
            fliggy_session='shop-session',
            room_status_auto_enabled=True,
            room_status_total_rooms=20,
            room_status_available_rooms=5,
            room_status_current_price=399.0,
            daily_revenue_auto_enabled=True,
            fliggy_price_push_enabled=True,
            fliggy_price_push_method='taobao.xhotel.rate.update',
            fliggy_price_push_payload_json='{"gid":"{{gid}}","rate_info":{"price":"{{new_price}}","start":"{{start_date}}","hid":"{{hid}}","name":"{{merchant_display_name}}"}}',
        )

        with patch('app.services.fliggy_client.get_settings', return_value=fake_settings):
            client = FliggyClient(shop_config=shop_config)
            method, biz_params = client.build_price_push_request(
                {
                    'shop_id': 2,
                    'new_price': 520,
                    'start_date': '2026-03-11',
                    'gid': 'price-gid-1',
                    'hid': 'hid-1',
                    'merchant_display_name': '标准价-2份早餐',
                }
            )

        self.assertEqual(method, 'taobao.xhotel.rate.update')
        self.assertEqual(biz_params['gid'], 'price-gid-1')
        self.assertEqual(biz_params['rate_info']['price'], 520)
        self.assertEqual(biz_params['rate_info']['start'], '2026-03-11')
        self.assertEqual(biz_params['rate_info']['hid'], 'hid-1')
        self.assertEqual(biz_params['rate_info']['name'], '标准价-2份早餐')


if __name__ == '__main__':
    unittest.main()
