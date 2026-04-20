import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, patch

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
except ModuleNotFoundError:  # pragma: no cover
    create_app = None


@unittest.skipIf(create_app is None, 'Flask is not installed')
class PluginApiRoutesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(session_factory=lambda: object())
        self.app.testing = True
        self.client = self.app.test_client()
        self.headers = {'X-Tenant-Id': '1', 'X-Shop-Id': '1'}

    def test_service_status_is_public(self) -> None:
        response = self.client.get('/plugin/service-status')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                'status': 'ok',
                'plugin': 'fliggy-ops',
                'mcp_enabled': True,
                'web_console_available': False,
            },
        )

    def test_plugin_auth_me_without_token_returns_unauthenticated(self) -> None:
        response = self.client.get('/plugin/auth/me')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {'authenticated': False})

    def test_plugin_auth_login_uses_service(self) -> None:
        expected = {
            'token': 'plugin_token',
            'user': {'tenant_id': 1, 'username': 'demo', 'is_admin': False},
            'current_shop': {'shop_id': 11, 'shop_name': '演示店铺', 'status': 'enabled'},
            'shops': [{'shop_id': 11, 'shop_name': '演示店铺', 'status': 'enabled'}],
        }
        with patch('app.api.plugin_routes.login_plugin_user', return_value=expected) as mocked_login:
            response = self.client.post(
                '/plugin/auth/login',
                json={
                    'tenant_id': 1,
                    'username': 'demo',
                    'password': 'secret',
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)
        mocked_login.assert_called_once_with(
            db=ANY,
            tenant_id=1,
            username='demo',
            password='secret',
        )

    def test_plugin_competitor_hotels_get_uses_service(self) -> None:
        context = SimpleNamespace(tenant_id=1, current_shop_id=11)
        expected = [
            {'id': 1, 'hotel_name': '杭州君悦酒店', 'hotel_url': 'https://example.com/hotel-a', 'enabled': True, 'sort_order': 10}
        ]
        with (
            patch('app.api.plugin_routes.require_plugin_auth_context', return_value=context),
            patch('app.api.plugin_routes.list_competitor_hotels', return_value=expected) as mocked_list,
        ):
            response = self.client.get('/plugin/competitor/hotels')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {'shop_id': 11, 'items': expected})
        mocked_list.assert_called_once_with(
            db=ANY,
            tenant_id=1,
            shop_id=11,
            only_enabled=False,
        )

    def test_plugin_competitor_hotels_post_uses_service(self) -> None:
        context = SimpleNamespace(tenant_id=1, current_shop_id=11, user_id=101)
        expected = [
            {'id': 1, 'hotel_name': '杭州君悦酒店', 'hotel_url': 'https://example.com/hotel-a', 'enabled': True, 'sort_order': 10}
        ]
        with (
            patch('app.api.plugin_routes.require_plugin_auth_context', return_value=context),
            patch('app.api.plugin_routes.replace_competitor_hotels', return_value=expected) as mocked_replace,
        ):
            response = self.client.post(
                '/plugin/competitor/hotels',
                json={
                    'items': [
                        {
                            'hotel_name': '杭州君悦酒店',
                            'hotel_url': 'https://example.com/hotel-a',
                            'enabled': True,
                            'sort_order': 10,
                        }
                    ]
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {'shop_id': 11, 'saved_count': 1, 'items': expected},
        )
        mocked_replace.assert_called_once_with(
            db=ANY,
            tenant_id=1,
            shop_id=11,
            items=[
                {
                    'hotel_name': '杭州君悦酒店',
                    'hotel_url': 'https://example.com/hotel-a',
                    'enabled': True,
                    'sort_order': 10,
                }
            ],
            actor_user_id=101,
        )

    def test_plugin_latest_prices_uses_existing_service(self) -> None:
        expected = {'shop_id': 1, 'count': 1, 'hotels': [{'name': 'A'}]}
        with (
            patch('app.api.plugin_routes.require_tenant_shop', return_value=(1, 1)),
            patch('app.api.plugin_routes.get_latest_competitor_prices', return_value=expected),
        ):
            response = self.client.get('/plugin/competitor/latest-prices?limit=5', headers=self.headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)

    def test_plugin_latest_prices_live_capture_and_save(self) -> None:
        collect_result = {
            'items': [
                {
                    'name': '杭州君悦酒店',
                    'url': 'https://example.com/hotel-a',
                    'signals': {'price_signals': ['¥598起']},
                    'fetch_status': 'success',
                }
            ],
            'collected_at': '2026-04-09 10:00:00',
            'matched_page_url': 'https://hotel.fliggy.com/hotel_list3.htm?city=330100',
        }
        expected = {
            'shop_id': 1,
            'count': 1,
            'latest_collected_at': '2026-04-09 10:00:00',
            'hotels': [{'hotel_name': '杭州君悦酒店', 'price': 598.0}],
            'source': 'fliggy_live_latest_prices',
        }
        with (
            patch('app.api.plugin_routes.require_tenant_shop', return_value=(1, 1)),
            patch('app.api.plugin_routes.collect_fliggy_hotel_prices_playwright', return_value=collect_result) as mocked_collect,
            patch('app.api.plugin_routes.build_live_competitor_prices_payload', return_value=dict(expected)) as mocked_build,
            patch('app.api.plugin_routes.store_live_competitor_result', return_value={'count': 1, 'expires_at': '2026-04-09 10:30:00'}) as mocked_cache,
            patch('app.api.plugin_routes.save_competitor_collection', return_value={'saved_count': 1}) as mocked_save,
        ):
            response = self.client.post(
                '/plugin/competitor/latest-prices',
                json={
                    'shop_id': 1,
                    'start_url': 'https://hotel.fliggy.com/hotel_list3.htm?city=330100',
                    'max_pages': 1,
                    'max_hotels': 5,
                    'save_result': True,
                    'collect_mode': 'cdp_current_page',
                    'debug_url': 'http://127.0.0.1:9222',
                },
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['saved_count'], 1)
        self.assertEqual(payload['cache_info']['count'], 1)
        self.assertEqual(payload['matched_page_url'], 'https://hotel.fliggy.com/hotel_list3.htm?city=330100')
        mocked_collect.assert_called_once()
        self.assertEqual(mocked_collect.call_args.kwargs['collect_mode'], 'cdp_current_page')
        mocked_build.assert_called_once()
        mocked_cache.assert_called_once()
        mocked_save.assert_called_once()
        self.assertEqual(mocked_save.call_args.kwargs['source'], 'fliggy_playwright')

    def test_plugin_fliggy_collect_saves_when_enabled(self) -> None:
        result = {'shop_id': 1, 'count': 0, 'hotels': []}
        with (
            patch('app.api.plugin_routes.require_tenant_shop', return_value=(1, 1)),
            patch('app.api.plugin_routes.collect_fliggy_hotel_prices_playwright', return_value=result),
            patch('app.api.plugin_routes.save_competitor_collection', return_value={'saved_count': 2}),
        ):
            response = self.client.post(
                '/plugin/fliggy/collect',
                json={
                    'shop_id': 1,
                    'start_url': 'https://hotel.fliggy.com/',
                    'max_pages': 1,
                    'max_hotels': 5,
                    'save_result': True,
                    'collect_mode': 'cdp_current_page',
                    'debug_url': 'http://127.0.0.1:9222',
                },
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {'shop_id': 1, 'count': 0, 'hotels': [], 'saved_count': 2})

    def test_plugin_fliggy_collect_extension_page_bypasses_cdp(self) -> None:
        result = {'shop_id': 1, 'count': 1, 'items': [{'name': '测试酒店'}], 'collect_mode': 'extension_page'}
        with (
            patch('app.api.plugin_routes.require_tenant_shop', return_value=(1, 1)),
            patch('app.api.plugin_routes.collect_fliggy_hotel_prices_from_extension_page', return_value=result) as mocked_collect,
            patch('app.api.plugin_routes.collect_fliggy_hotel_prices_playwright') as mocked_cdp,
            patch('app.api.plugin_routes.save_competitor_collection', return_value={'saved_count': 1}) as mocked_save,
        ):
            response = self.client.post(
                '/plugin/fliggy/collect',
                json={
                    'shop_id': 1,
                    'start_url': 'https://hotel.fliggy.com/hotel_list.htm',
                    'max_pages': 1,
                    'max_hotels': 5,
                    'save_result': True,
                    'collect_mode': 'extension_page',
                    'page_snapshot': {
                        'page_context': {
                            'startUrl': 'https://hotel.fliggy.com/hotel_list.htm',
                            'pageType': 'hotel_list',
                        },
                        'candidate_rows': [
                            {
                                'name': '测试酒店',
                                'text': '测试酒店 ￥399',
                                'href': 'https://hotel.fliggy.com/item.htm?id=1',
                                'price': 399,
                                'price_text': '￥399',
                                'price_signals': ['￥399'],
                            }
                        ],
                    },
                },
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['saved_count'], 1)
        mocked_collect.assert_called_once()
        mocked_cdp.assert_not_called()
        self.assertEqual(mocked_save.call_args.kwargs['source'], 'fliggy_extension')

    def test_plugin_competitor_room_prices_uses_existing_services(self) -> None:
        crawl_results = [
            {
                'hotel_name': '郑州中油花园酒店',
                'hotel_url': 'https://hotel.fliggy.com/hotel_detail.htm?id=1',
                'collected_at': '2026-04-09 11:00:00',
                'room_count': 2,
                'rooms': [
                    {'room_type': '豪华大床房', 'rate_name': '标准价', 'price': 399.0, 'breakfast': '含早', 'cancelable': '可取消'},
                    {'room_type': '豪华双床房', 'rate_name': '连住价', 'price': 429.0, 'breakfast': '无早', 'cancelable': '不可取消'},
                ],
            }
        ]
        with (
            patch('app.api.plugin_routes.require_tenant_shop', return_value=(1, 1)),
            patch('app.api.plugin_routes.crawl_multiple_hotels_room_prices', return_value=crawl_results) as mocked_crawl,
            patch('app.api.plugin_routes.save_room_prices', return_value=2) as mocked_save,
        ):
            response = self.client.post(
                '/plugin/competitor/room-prices',
                json={
                    'shop_id': 1,
                    'hotels': [
                        {
                            'name': '郑州中油花园酒店',
                            'url': 'https://hotel.fliggy.com/hotel_detail.htm?id=1',
                        }
                    ],
                    'headless': True,
                    'save_result': True,
                    'debug_url': 'http://127.0.0.1:9222',
                },
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['shop_id'], 1)
        self.assertEqual(payload['hotel_count'], 1)
        self.assertEqual(payload['total_rooms'], 2)
        self.assertEqual(payload['saved_count'], 2)
        self.assertEqual(payload['hotels'][0]['rooms'][0]['rate_name'], '标准价')
        mocked_crawl.assert_called_once()
        self.assertEqual(mocked_crawl.call_args.kwargs['debug_url'], 'http://127.0.0.1:9222')
        mocked_save.assert_called_once()
        self.assertEqual(mocked_save.call_args.kwargs['shop_id'], 1)
    def test_plugin_merchant_pricing_preview_uses_existing_service(self) -> None:
        expected = {'shop_id': 1, 'status': 'success', 'item_count': 1, 'items': [{'display_name': '豪华大床房'}]}
        with (
            patch('app.api.plugin_routes.require_tenant_shop', return_value=(1, 1)),
            patch('app.api.plugin_routes.preview_merchant_pricing_recommendations', return_value=expected) as mocked_preview,
        ):
            response = self.client.post(
                '/plugin/pricing/merchant-preview',
                json={
                    'shop_id': 1,
                    'headless': True,
                    'selected_items': [],
                    'collect_mode': 'cdp_current_page',
                    'debug_url': 'http://127.0.0.1:9222',
                },
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)
        mocked_preview.assert_called_once()
        self.assertEqual(mocked_preview.call_args.kwargs['collect_mode'], 'cdp_current_page')
        self.assertEqual(mocked_preview.call_args.kwargs['debug_url'], 'http://127.0.0.1:9222')

    def test_plugin_merchant_pricing_items_uses_existing_service(self) -> None:
        expected = {'shop_id': 1, 'status': 'success', 'item_count': 1, 'items': [{'display_name': '豪华大床房'}]}
        with (
            patch('app.api.plugin_routes.require_tenant_shop', return_value=(1, 1)),
            patch('app.api.plugin_routes.list_merchant_pricing_items', return_value=expected) as mocked_list,
        ):
            response = self.client.post(
                '/plugin/pricing/merchant-items',
                json={
                    'shop_id': 1,
                    'headless': True,
                    'selected_items': [],
                    'collect_mode': 'cdp_current_page',
                    'debug_url': 'http://127.0.0.1:9222',
                },
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)
        mocked_list.assert_called_once()
        self.assertEqual(mocked_list.call_args.kwargs['collect_mode'], 'cdp_current_page')
        self.assertEqual(mocked_list.call_args.kwargs['debug_url'], 'http://127.0.0.1:9222')

    def test_plugin_merchant_pricing_direct_submit_uses_existing_service(self) -> None:
        expected = {'shop_id': 1, 'status': 'success', 'success_count': 1, 'failed_count': 0, 'items': [{'display_name': '豪华大床房'}]}
        with (
            patch('app.api.plugin_routes.require_tenant_shop', return_value=(1, 1)),
            patch('app.api.plugin_routes.submit_merchant_pricing_recommendations_direct', return_value=expected) as mocked_submit,
        ):
            response = self.client.post(
                '/plugin/pricing/merchant-direct-submit',
                json={
                    'shop_id': 1,
                    'headless': True,
                    'comment': 'browser_extension_suggested_submit',
                    'selected_items': [],
                    'collect_mode': 'cdp_current_page',
                    'debug_url': 'http://127.0.0.1:9222',
                },
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)
        mocked_submit.assert_called_once()
        self.assertEqual(mocked_submit.call_args.kwargs['collect_mode'], 'cdp_current_page')
        self.assertEqual(mocked_submit.call_args.kwargs['debug_url'], 'http://127.0.0.1:9222')

    def test_plugin_merchant_pricing_direct_submit_accepts_confirmed_items(self) -> None:
        expected = {'shop_id': 1, 'status': 'success', 'success_count': 1, 'failed_count': 0, 'items': [{'display_name': '豪华大床房'}]}
        with (
            patch('app.api.plugin_routes.require_tenant_shop', return_value=(1, 1)),
            patch('app.api.plugin_routes.submit_merchant_pricing_recommendations_direct', return_value=expected) as mocked_submit,
        ):
            response = self.client.post(
                '/plugin/pricing/merchant-direct-submit',
                json={
                    'shop_id': 1,
                    'headless': True,
                    'comment': 'browser_extension_current_submit',
                    'confirmed_items': [
                        {
                            'display_name': '豪华大床房',
                            'room_name': '豪华大床房',
                            'rate_name': '标准价',
                            'current_price': 399,
                            'final_price': 429,
                            'suggested_price': 429,
                            'risk_level': 'L2',
                            'gid': 'g1',
                            'hid': 'h1',
                        }
                    ],
                },
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)
        mocked_submit.assert_called_once()
        self.assertEqual(mocked_submit.call_args.kwargs['confirmed_items'][0]['final_price'], 429)

    def test_plugin_competitor_workflow_preview_uses_new_service(self) -> None:
        expected = {
            'shop_id': 1,
            'status': 'success',
            'competitor_hotel_name': '杭州君悦酒店',
            'ready_submit_count': 2,
            'workflow_summary': {'price_recommendation': {'price_mid': 458}},
            'items': [{'display_name': '豪华大床房'}],
        }
        with (
            patch('app.api.plugin_routes.require_tenant_shop', return_value=(1, 1)),
            patch('app.api.plugin_routes.preview_competitor_driven_pricing_workflow', return_value=expected) as mocked_preview,
        ):
            response = self.client.post(
                '/plugin/pricing/competitor-workflow-preview',
                json={
                    'shop_id': 1,
                    'competitor_hotel_name': '杭州君悦酒店',
                    'headless': True,
                },
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)
        mocked_preview.assert_called_once()
        self.assertEqual(mocked_preview.call_args.kwargs['competitor_hotel_name'], '杭州君悦酒店')

    def test_plugin_competitor_pricing_advice_preview_uses_new_service(self) -> None:
        expected = {
            'shop_id': 1,
            'competitor_hotel_name': '杭州君悦酒店',
            'recommendation_source': 'tongyi',
            'advice_summary': {'suggested_price': 458.0, 'change_amount': 29.0},
        }
        with (
            patch('app.api.plugin_routes.require_tenant_shop', return_value=(1, 1)),
            patch('app.api.plugin_routes.preview_competitor_pricing_advice', return_value=expected) as mocked_preview,
        ):
            response = self.client.post(
                '/plugin/pricing/competitor-advice-preview',
                json={
                    'shop_id': 1,
                    'competitor_hotel_name': '杭州君悦酒店',
                    'strategy': 'balanced',
                    'inventory_snapshot': {
                        'total_rooms': 100,
                        'available_rooms': 28,
                        'current_price': 429,
                    },
                    'competitor_hotels': [
                        {
                            'hotel_name': '杭州君悦酒店',
                            'hotel_url': 'https://example.com/hotel-a',
                            'rooms': [
                                {
                                    'room_type': '豪华大床房',
                                    'rate_name': '标准价',
                                    'price': 458,
                                    'breakfast': '含早',
                                    'cancelable': '可取消',
                                }
                            ],
                        }
                    ],
                },
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)
        mocked_preview.assert_called_once()
        self.assertEqual(mocked_preview.call_args.kwargs['shop_id'], 1)
        self.assertEqual(mocked_preview.call_args.kwargs['strategy'], 'balanced')
        self.assertEqual(mocked_preview.call_args.kwargs['inventory_snapshot']['current_price'], 429.0)
        self.assertEqual(mocked_preview.call_args.kwargs['competitor_hotel_name'], '杭州君悦酒店')
    def test_plugin_uniform_direct_submit_uses_new_service(self) -> None:
        expected = {
            'shop_id': 1,
            'status': 'success',
            'uniform_target_price': 429,
            'success_count': 2,
            'failed_count': 0,
            'items': [{'display_name': '豪华大床房'}],
        }
        with (
            patch('app.api.plugin_routes.require_tenant_shop', return_value=(1, 1)),
            patch('app.api.plugin_routes.submit_uniform_merchant_pricing', return_value=expected) as mocked_submit,
        ):
            response = self.client.post(
                '/plugin/pricing/uniform-direct-submit',
                json={
                    'shop_id': 1,
                    'target_price': 429,
                    'price_url': 'https://example.com/merchant',
                    'headless': True,
                    'selected_items': [
                        {
                            'display_name': '豪华大床房',
                            'room_name': '豪华大床房',
                            'rate_name': '标准价',
                            'gid': 'g1',
                            'hid': 'h1',
                        }
                    ],
                    'comment': 'browser_extension_uniform_submit',
                },
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)
        mocked_submit.assert_called_once()
        self.assertEqual(mocked_submit.call_args.kwargs['target_price'], 429.0)
        self.assertEqual(mocked_submit.call_args.kwargs['selected_items'][0]['gid'], 'g1')


if __name__ == '__main__':
    unittest.main()



