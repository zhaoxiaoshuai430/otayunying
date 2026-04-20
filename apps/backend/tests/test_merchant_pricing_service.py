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
except ModuleNotFoundError:  # pragma: no cover
    create_app = None

from app.services.merchant_pricing_service import (
    confirm_merchant_pricing_recommendations,
    generate_merchant_pricing_suggestions,
    list_merchant_pricing_items,
    preview_merchant_pricing_recommendations,
    submit_uniform_merchant_pricing,
    submit_merchant_pricing_recommendations_direct,
)


class MerchantPricingServiceTestCase(unittest.TestCase):
    @patch('app.services.merchant_pricing_service.preview_merchant_pricing_recommendations')
    def test_generate_merchant_pricing_suggestions_preview_only(self, mocked_preview) -> None:
        mocked_preview.return_value = {
            'shop_id': 1,
            'status': 'success',
            'item_count': 2,
            'items': [
                {'display_name': '测试价-1', 'submit_ready': True},
                {'display_name': '测试价-2', 'submit_ready': False},
            ],
        }

        result = generate_merchant_pricing_suggestions(db=object(), shop_id=1, preview_only=True)

        self.assertTrue(result['preview_only'])
        self.assertEqual(result['preview_item_count'], 2)
        self.assertEqual(result['ready_submit_count'], 1)
        self.assertEqual(result['skipped_submit_count'], 1)
        self.assertEqual(result['skipped_submit_items'][0]['display_name'], '测试价-2')

    @patch('app.services.merchant_pricing_service.confirm_merchant_pricing_recommendations')
    @patch('app.services.merchant_pricing_service.preview_merchant_pricing_recommendations')
    def test_generate_merchant_pricing_suggestions_submit(self, mocked_preview, mocked_confirm) -> None:
        mocked_preview.return_value = {
            'shop_id': 1,
            'status': 'success',
            'item_count': 2,
            'items': [
                {
                    'room_name': '',
                    'rate_name': '标准价-2份早餐',
                    'display_name': '标准价-2份早餐',
                    'current_price': 200.0,
                    'suggested_price': 210.0,
                    'final_price': 208.0,
                    'risk_level': 'L2',
                    'gid': 'gid-1',
                    'hid': 'hid-1',
                    'submit_ready': True,
                    'recommendation': {'price_recommendation': {'price_mid': 210.0}},
                },
                {
                    'display_name': '未映射房型',
                    'submit_ready': False,
                },
            ],
        }
        mocked_confirm.return_value = {
            'shop_id': 1,
            'status': 'success',
            'submitted_count': 1,
            'items': [{'action_id': 11}],
        }

        result = generate_merchant_pricing_suggestions(
            db=object(),
            shop_id=1,
            preview_only=False,
            approver_user_id=7,
            comment='测试提交',
        )

        self.assertFalse(result['preview_only'])
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['submitted_count'], 1)
        mocked_confirm.assert_called_once()
        confirm_kwargs = mocked_confirm.call_args.kwargs
        self.assertEqual(confirm_kwargs['approver_user_id'], 7)
        self.assertEqual(len(confirm_kwargs['confirmed_items']), 1)
        self.assertEqual(confirm_kwargs['confirmed_items'][0]['gid'], 'gid-1')

    @patch('app.services.merchant_pricing_service.create_merchant_pricing_audit')
    @patch('app.services.merchant_pricing_service.generate_auto_pricing_recommendation')
    @patch('app.services.merchant_pricing_service.get_merchant_price_history_summary')
    @patch('app.services.merchant_pricing_service.collect_auto_pricing_context')
    @patch('app.services.merchant_pricing_service.fetch_fliggy_merchant_price_preview')
    def test_preview_merchant_pricing_recommendations(self, mocked_preview, mocked_context, mocked_history, mocked_recommendation, mocked_audit) -> None:
        mocked_preview.return_value = {
            'shop_id': 1,
            'mapping_summary': {'total': 1, 'mapped': 1, 'partial': 0, 'unmapped': 0},
            'collected_at': '2026-03-15 17:20:00',
            'audit': {'audit_id': 8, 'audit_mode': 'preview', 'status': 'success'},
            'auto_login_performed': True,
            'credential_saved': True,
            'items': [
                {
                    'room_name': '',
                    'rate_name': '标准价-2份早餐',
                    'display_name': '标准价-2份早餐',
                    'price': 200.0,
                    'gid': 'gid-1',
                    'hid': 'hid-1',
                    'is_mapped': True,
                }
            ],
        }
        mocked_context.return_value = {
            'rule': {'strategy': 'balanced', 'lookback_days': 7, 'max_change_pct': 8, 'high_risk_change_pct': 10, 'require_manual_approval': False},
            'inventory_snapshot': {'total_rooms': 20, 'available_rooms': 5, 'current_price': 299.0},
        }
        mocked_history.return_value = {
            'price_count': 6,
            'price_min': 188.0,
            'price_max': 208.0,
            'price_avg': 198.0,
            'latest_price': 200.0,
            'latest_collected_at': '2026-03-15 16:00:00',
        }
        mocked_recommendation.return_value = {
            'suggested_price': 210.0,
            'recommendation': {'recommendation_source': 'fallback', 'price_recommendation': {'price_mid': 210.0}},
        }
        mocked_audit.return_value = {'audit_id': 9, 'audit_mode': 'dry_run', 'status': 'success', 'item_count': 1}

        result = preview_merchant_pricing_recommendations(db=object(), shop_id=1)

        self.assertEqual(result['item_count'], 1)
        self.assertEqual(result['items'][0]['suggested_price'], 210.0)
        self.assertEqual(result['items'][0]['final_price'], 210.0)
        self.assertTrue(result['items'][0]['submit_ready'])
        self.assertEqual(result['items'][0]['merchant_history']['price_count'], 6)
        self.assertEqual(mocked_recommendation.call_args.kwargs['merchant_history_context']['price_avg'], 198.0)
        self.assertEqual(result['audit_mode'], 'dry_run')
        self.assertEqual(result['audit']['audit_id'], 9)
        self.assertEqual(result['price_preview_audit']['audit_mode'], 'preview')
        self.assertTrue(result['auto_login_performed'])
        self.assertTrue(result['credential_saved'])
        self.assertTrue(mocked_preview.call_args.kwargs['auto_login'])
        self.assertFalse(mocked_preview.call_args.kwargs['login_headless'])
        mocked_audit.assert_called_once()

    @patch('app.services.merchant_pricing_service.create_merchant_pricing_audit')
    @patch('app.services.merchant_pricing_service.fetch_fliggy_merchant_price_preview')
    def test_list_merchant_pricing_items(self, mocked_preview, mocked_audit) -> None:
        mocked_preview.return_value = {
            'shop_id': 1,
            'mapping_summary': {'total': 2, 'mapped': 1, 'partial': 0, 'unmapped': 1},
            'collected_at': '2026-03-15 17:20:00',
            'audit': {'audit_id': 8, 'audit_mode': 'preview', 'status': 'success'},
            'auto_login_performed': True,
            'credential_saved': True,
            'collect_mode': 'storage_state',
            'collect_mode_requested': 'prefer_cdp',
            'cdp_fallback_reason': 'cdp-returned-empty-items',
            'matched_page_url': 'https://ebooking.hwht.com/price/manage?from=tab',
            'debug_url': 'http://127.0.0.1:9222',
            'items': [
                {
                    'room_name': '豪华大床房',
                    'rate_name': '标准价',
                    'display_name': '豪华大床房-标准价',
                    'price': 399.0,
                    'gid': 'gid-1',
                    'hid': 'hid-1',
                    'is_mapped': True,
                    'mapping_status': 'mapped',
                },
                {
                    'room_name': '未映射房型',
                    'rate_name': '标准价',
                    'display_name': '未映射房型-标准价',
                    'price': 359.0,
                    'gid': '',
                    'hid': '',
                    'is_mapped': False,
                    'mapping_status': 'unmapped',
                },
            ],
        }
        mocked_audit.return_value = {'audit_id': 21, 'audit_mode': 'preview', 'status': 'success', 'item_count': 2}

        result = list_merchant_pricing_items(db=object(), shop_id=1)

        self.assertEqual(result['item_count'], 2)
        self.assertTrue(result['items'][0]['submit_ready'])
        self.assertFalse(result['items'][1]['submit_ready'])
        self.assertEqual(result['audit']['audit_id'], 21)
        self.assertEqual(result['collect_mode'], 'storage_state')
        self.assertEqual(result['collect_mode_requested'], 'prefer_cdp')
        self.assertEqual(result['cdp_fallback_reason'], 'cdp-returned-empty-items')
        self.assertEqual(result['matched_page_url'], 'https://ebooking.hwht.com/price/manage?from=tab')
        self.assertEqual(result['debug_url'], 'http://127.0.0.1:9222')
        self.assertTrue(mocked_preview.call_args.kwargs['auto_login'])
        self.assertFalse(mocked_preview.call_args.kwargs['login_headless'])
        mocked_audit.assert_called_once()

    @patch('app.services.merchant_pricing_service.create_merchant_pricing_audit')
    @patch('app.services.merchant_pricing_service.submit_fliggy_merchant_price_updates')
    @patch('app.services.merchant_pricing_service.preview_merchant_pricing_recommendations')
    def test_direct_submit_merchant_portal_returns_partial_failure(self, mocked_preview, mocked_submit, mocked_audit) -> None:
        mocked_preview.return_value = {
            'shop_id': 1,
            'mapping_summary': {'total': 3, 'mapped': 3, 'partial': 0, 'unmapped': 0},
            'collected_at': '2026-03-15 17:20:00',
            'audit': {'audit_id': 8, 'audit_mode': 'preview', 'status': 'success'},
            'items': [
                {'display_name': 'rate-a', 'rate_name': 'rate-a', 'price': 200.0, 'gid': 'gid-1', 'hid': 'hid-1', 'submit_ready': True},
                {'display_name': 'rate-b', 'rate_name': 'rate-b', 'price': 220.0, 'gid': 'gid-2', 'hid': 'hid-2', 'submit_ready': True},
                {'display_name': 'rate-c', 'rate_name': 'rate-c', 'price': 240.0, 'gid': 'gid-3', 'hid': 'hid-3', 'submit_ready': True},
            ],
        }
        mocked_submit.return_value = {
            'status': 'partial_failed',
            'submitted_count': 3,
            'success_count': 2,
            'failed_count': 1,
            'submit_channel': 'merchant_portal',
            'price_url': 'https://price.example.com',
            'storage_state_used': 'shop-1.json',
            'auto_login_performed': True,
            'items': [
                {'display_name': 'rate-a', 'gid': 'gid-1', 'hid': 'hid-1', 'final_price': 210.0, 'status': 'success', 'message': '测试结果'},
                {'display_name': 'rate-b', 'gid': 'gid-2', 'hid': 'hid-2', 'final_price': 210.0, 'status': 'failed', 'message': '测试结果'},
                {'display_name': 'rate-c', 'gid': 'gid-3', 'hid': 'hid-3', 'final_price': 210.0, 'status': 'success', 'message': '测试结果'},
            ],
        }
        mocked_audit.return_value = {'audit_id': 10, 'audit_mode': 'formal_submit', 'status': 'partial_failed', 'action_count': 3}

        result = submit_merchant_pricing_recommendations_direct(db=object(), shop_id=1, comment='direct-submit')

        self.assertEqual(result['status'], 'partial_failed')
        self.assertEqual(result['success_count'], 2)
        self.assertEqual(result['failed_count'], 1)
        self.assertEqual(result['unsubmitted_count'], 0)
        self.assertFalse(result['stopped_on_first_failure'])
        self.assertEqual(result['submit_channel'], 'merchant_portal')
        mocked_preview.assert_called_once()
        mocked_submit.assert_called_once()
        self.assertEqual(result['items'][1]['status'], 'failed')

    @patch('app.services.merchant_pricing_service.create_merchant_pricing_audit')
    @patch('app.services.merchant_pricing_service.submit_fliggy_merchant_price_updates')
    @patch('app.services.merchant_pricing_service.fetch_fliggy_merchant_price_preview')
    def test_direct_submit_uses_confirmed_items_without_preview(self, mocked_preview, mocked_submit, mocked_audit) -> None:
        mocked_preview.side_effect = AssertionError('preview should not be called when confirmed_items are provided')
        mocked_submit.return_value = {
            'status': 'success',
            'submitted_count': 1,
            'success_count': 1,
            'failed_count': 0,
            'submit_channel': 'merchant_portal',
            'price_url': 'https://price.example.com',
            'storage_state_used': 'shop-1.json',
            'auto_login_performed': False,
            'items': [
                {'display_name': '测试房型-特惠', 'gid': 'gid-1', 'hid': 'hid-1', 'final_price': 218.0, 'status': 'success', 'message': '测试结果'}
            ],
        }
        mocked_audit.return_value = {'audit_id': 12, 'audit_mode': 'formal_submit', 'status': 'success', 'action_count': 1}

        result = submit_merchant_pricing_recommendations_direct(
            db=object(),
            shop_id=1,
            comment='direct-submit',
            confirmed_items=[
                {
                    'display_name': '测试房型-特惠',
                    'room_name': '测试房型',
                    'rate_name': '特惠价',
                    'current_price': 200.0,
                    'suggested_price': 210.0,
                    'final_price': 218.0,
                    'risk_level': 'L2',
                    'gid': 'gid-1',
                    'hid': 'hid-1',
                    'start_date': '2026-03-21',
                    'end_date': '2026-03-21',
                }
            ],
        )

        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['submitted_count'], 1)
        self.assertEqual(result['success_count'], 1)
        self.assertEqual(result['items'][0]['final_price'], 218.0)
        mocked_preview.assert_not_called()
        mocked_submit.assert_called_once()
        mocked_audit.assert_called_once()

    @patch('app.services.merchant_pricing_service.submit_merchant_pricing_recommendations_direct')
    @patch('app.services.merchant_pricing_service.preview_merchant_pricing_recommendations')
    @patch('app.services.merchant_pricing_service.fetch_fliggy_merchant_price_preview')
    def test_uniform_submit_uses_current_price_preview_without_generating_suggestions(self, mocked_fetch_preview, mocked_preview, mocked_submit) -> None:
        mocked_preview.side_effect = AssertionError('suggestion preview should not be called for uniform submit')
        mocked_fetch_preview.return_value = {
            'shop_id': 1,
            'status': 'success',
            'price_url': 'https://merchant.example.com/prices',
            'mapping_summary': {'total': 2, 'mapped': 1, 'partial': 0, 'unmapped': 1},
            'collected_at': '2026-03-15 17:20:00',
            'auto_login_performed': True,
            'credential_saved': True,
            'items': [
                {
                    'room_name': '豪华大床房',
                    'rate_name': '标准价',
                    'display_name': '豪华大床房-标准价',
                    'price': 399.0,
                    'gid': 'gid-1',
                    'hid': 'hid-1',
                    'is_mapped': True,
                },
                {
                    'room_name': '未映射房型',
                    'rate_name': '标准价',
                    'display_name': '未映射房型-标准价',
                    'price': 359.0,
                    'gid': '',
                    'hid': '',
                    'is_mapped': False,
                },
            ],
        }
        mocked_submit.return_value = {
            'shop_id': 1,
            'status': 'success',
            'submitted_count': 1,
            'success_count': 1,
            'failed_count': 0,
            'skipped_submit_count': 0,
            'skipped_submit_items': [],
            'submit_channel': 'merchant_portal',
            'price_url': 'https://merchant.example.com/prices',
            'storage_state_used': 'shop-1.json',
            'auto_login_performed': False,
            'items': [
                {'display_name': '豪华大床房-标准价', 'gid': 'gid-1', 'hid': 'hid-1', 'final_price': 429.0, 'status': 'success', 'message': '测试结果'}
            ],
        }

        result = submit_uniform_merchant_pricing(
            db=object(),
            shop_id=1,
            target_price=429,
            price_url='https://merchant.example.com/prices',
            comment='browser_extension_uniform_submit',
        )

        self.assertEqual(result['uniform_target_price'], 429.0)
        self.assertEqual(result['ready_submit_count'], 1)
        self.assertEqual(result['skipped_submit_count'], 1)
        self.assertEqual(result['skipped_submit_items'][0]['display_name'], '未映射房型-标准价')
        self.assertTrue(result['credential_saved'])
        self.assertTrue(result['auto_login_performed'])
        mocked_fetch_preview.assert_called_once()
        self.assertTrue(mocked_fetch_preview.call_args.kwargs['auto_login'])
        self.assertFalse(mocked_fetch_preview.call_args.kwargs['login_headless'])
        mocked_preview.assert_not_called()
        mocked_submit.assert_called_once()
        confirmed_items = mocked_submit.call_args.kwargs['confirmed_items']
        self.assertEqual(len(confirmed_items), 1)
        self.assertEqual(confirmed_items[0]['final_price'], 429.0)
        self.assertEqual(confirmed_items[0]['suggested_price'], 429.0)

    @patch('app.services.merchant_pricing_service.submit_merchant_pricing_recommendations_direct')
    @patch('app.services.merchant_pricing_service.preview_merchant_pricing_recommendations')
    @patch('app.services.merchant_pricing_service.fetch_fliggy_merchant_price_preview')
    def test_uniform_submit_filters_to_selected_items(self, mocked_fetch_preview, mocked_preview, mocked_submit) -> None:
        mocked_preview.side_effect = AssertionError('suggestion preview should not be called for uniform submit')
        mocked_fetch_preview.return_value = {
            'shop_id': 1,
            'status': 'success',
            'price_url': 'https://merchant.example.com/prices',
            'mapping_summary': {'total': 2, 'mapped': 2, 'partial': 0, 'unmapped': 0},
            'items': [
                {
                    'room_name': '豪华大床房',
                    'rate_name': '标准价',
                    'display_name': '豪华大床房-标准价',
                    'price': 399.0,
                    'gid': 'gid-1',
                    'hid': 'hid-1',
                    'is_mapped': True,
                },
                {
                    'room_name': '行政大床房',
                    'rate_name': '标准价',
                    'display_name': '行政大床房-标准价',
                    'price': 499.0,
                    'gid': 'gid-2',
                    'hid': 'hid-2',
                    'is_mapped': True,
                },
            ],
        }
        mocked_submit.return_value = {
            'shop_id': 1,
            'status': 'success',
            'submitted_count': 1,
            'success_count': 1,
            'failed_count': 0,
            'skipped_submit_count': 0,
            'skipped_submit_items': [],
            'submit_channel': 'merchant_portal',
            'price_url': 'https://merchant.example.com/prices',
            'storage_state_used': 'shop-1.json',
            'auto_login_performed': False,
            'items': [
                {'display_name': '行政大床房-标准价', 'gid': 'gid-2', 'hid': 'hid-2', 'final_price': 429.0, 'status': 'success', 'message': '测试结果'}
            ],
        }

        result = submit_uniform_merchant_pricing(
            db=object(),
            shop_id=1,
            target_price=429,
            selected_items=[
                {
                    'room_name': '行政大床房',
                    'rate_name': '标准价',
                    'display_name': '行政大床房-标准价',
                    'gid': 'gid-2',
                    'hid': 'hid-2',
                }
            ],
        )

        self.assertEqual(result['ready_submit_count'], 1)
        mocked_submit.assert_called_once()
        confirmed_items = mocked_submit.call_args.kwargs['confirmed_items']
        self.assertEqual(len(confirmed_items), 1)
        self.assertEqual(confirmed_items[0]['gid'], 'gid-2')

    @patch('app.services.merchant_pricing_service.create_merchant_pricing_audit')
    @patch('app.services.merchant_pricing_service.submit_fliggy_merchant_price_updates')
    def test_confirm_merchant_pricing_recommendations(self, mocked_submit, mocked_audit) -> None:
        mocked_submit.return_value = {
            'status': 'success',
            'submitted_count': 1,
            'success_count': 1,
            'failed_count': 0,
            'submit_channel': 'merchant_portal',
            'price_url': 'https://price.example.com',
            'storage_state_used': 'shop-1.json',
            'auto_login_performed': False,
            'items': [
                {'display_name': '标准价-2份早餐', 'gid': 'gid-1', 'hid': 'hid-1', 'final_price': 210.0, 'status': 'success', 'message': '测试结果'}
            ],
        }
        mocked_audit.return_value = {'audit_id': 10, 'audit_mode': 'formal_submit', 'status': 'success', 'action_count': 1}

        result = confirm_merchant_pricing_recommendations(
            db=object(),
            shop_id=1,
            approver_user_id=7,
            comment='测试提交',
            confirmed_items=[
                {
                    'display_name': '标准价-2份早餐',
                    'rate_name': '标准价-2份早餐',
                    'current_price': 200.0,
                    'suggested_price': 210.0,
                    'final_price': 210.0,
                    'risk_level': 'L2',
                    'gid': 'gid-1',
                    'hid': 'hid-1',
                    'start_date': '2026-03-15',
                    'end_date': '2026-03-15',
                }
            ],
        )

        self.assertEqual(result['submitted_count'], 1)
        self.assertEqual(result['success_count'], 1)
        self.assertEqual(result['items'][0]['final_price'], 210.0)
        self.assertEqual(result['audit_mode'], 'formal_submit')
        self.assertEqual(result['audit']['audit_id'], 10)
        self.assertEqual(result['submit_channel'], 'merchant_portal')
        mocked_submit.assert_called_once()
        mocked_audit.assert_called_once()

@unittest.skipIf(create_app is None, 'Flask is not installed')
class MerchantPricingRouteTestCase(unittest.TestCase):
    @patch('app.api.routes.generate_merchant_pricing_suggestions')
    def test_generate_route(self, mocked_generate) -> None:
        mocked_generate.return_value = {
            'shop_id': 1,
            'status': 'success',
            'preview_only': True,
            'preview_item_count': 1,
            'ready_submit_count': 1,
            'skipped_submit_count': 0,
            'preview': {'item_count': 1, 'items': []},
        }
        app = create_app(session_factory=lambda: object())
        app.testing = True
        client = app.test_client()

        with patch('app.api.routes.require_tenant_shop', return_value=(1, 1)):
            resp = client.post(
                '/pricing/merchant-generate',
                json={'shop_id': 1, 'selected_items': [], 'preview_only': True},
                headers={'X-Tenant-Id': '1', 'X-Shop-Id': '1'},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['message'], 'merchant pricing suggestions generated')
        self.assertTrue(data['preview_only'])
        self.assertEqual(data['ready_submit_count'], 1)

    @patch('app.api.routes.submit_merchant_pricing_recommendations_direct')
    def test_direct_submit_route(self, mocked_submit) -> None:
        mocked_submit.return_value = {
            'shop_id': 1,
            'status': 'success',
            'submitted_count': 1,
            'success_count': 1,
            'failed_count': 0,
            'items': [],
        }
        app = create_app(session_factory=lambda: object())
        app.testing = True
        client = app.test_client()

        with patch('app.api.routes.require_tenant_shop', return_value=(1, 1)):
            resp = client.post(
                '/pricing/merchant-direct-submit',
                json={'shop_id': 1, 'selected_items': []},
                headers={'X-Tenant-Id': '1', 'X-Shop-Id': '1'},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['message'], 'merchant pricing directly submitted')
        self.assertEqual(data['submitted_count'], 1)
        self.assertEqual(data['success_count'], 1)

    @patch('app.api.routes.preview_merchant_pricing_recommendations')
    def test_preview_route(self, mocked_preview) -> None:
        mocked_preview.return_value = {
            'shop_id': 1,
            'status': 'success',
            'audit_mode': 'dry_run',
            'audit': {'audit_id': 9},
            'item_count': 1,
            'items': [],
        }
        app = create_app(session_factory=lambda: object())
        app.testing = True
        client = app.test_client()

        with patch('app.api.routes.require_tenant_shop', return_value=(1, 1)):
            resp = client.post(
                '/pricing/merchant-preview',
                json={'shop_id': 1, 'selected_items': []},
                headers={'X-Tenant-Id': '1', 'X-Shop-Id': '1'},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['message'], 'merchant pricing preview generated')
        self.assertEqual(data['item_count'], 1)
        self.assertEqual(data['audit_mode'], 'dry_run')

    @patch('app.api.routes.list_merchant_price_mappings')
    def test_list_mapping_route(self, mocked_list) -> None:
        mocked_list.return_value = [
            {
                'mapping_id': 3,
                'room_name': 'room-a',
                'rate_name': 'rate-a',
                'gid': 'gid-1',
                'hid': 'hid-1',
                'status': 'active',
                'is_complete': True,
            }
        ]
        app = create_app(session_factory=lambda: object())
        app.testing = True
        client = app.test_client()

        with patch('app.api.routes.require_tenant_shop', return_value=(1, 1)):
            resp = client.get('/pricing/merchant-mappings?shop_id=1', headers={'X-Tenant-Id': '1', 'X-Shop-Id': '1'})

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['items'][0]['gid'], 'gid-1')

    @patch('app.api.routes.upsert_merchant_price_mapping')
    def test_save_mapping_route(self, mocked_upsert) -> None:
        mocked_upsert.return_value = {
            'mapping_id': 3,
            'shop_id': 1,
            'platform': 'fliggy',
            'room_name': 'room-a',
            'rate_name': 'rate-a',
            'gid': 'gid-1',
            'hid': 'hid-1',
            'status': 'active',
            'is_complete': True,
        }
        app = create_app(session_factory=lambda: object())
        app.testing = True
        client = app.test_client()

        with patch('app.api.routes.require_tenant_shop', return_value=(1, 1)):
            resp = client.post(
                '/pricing/merchant-mappings',
                json={
                    'shop_id': 1,
                    'room_name': 'room-a',
                    'rate_name': 'rate-a',
                    'gid': 'gid-1',
                    'hid': 'hid-1',
                    'status': 'active',
                },
                headers={'X-Tenant-Id': '1', 'X-Shop-Id': '1'},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['message'], 'merchant price mapping saved')
        self.assertTrue(data['is_complete'])

    @patch('app.api.routes.confirm_merchant_pricing_recommendations')
    def test_confirm_route(self, mocked_confirm) -> None:
        mocked_confirm.return_value = {
            'shop_id': 1,
            'status': 'success',
            'audit_mode': 'formal_submit',
            'audit': {'audit_id': 10},
            'submitted_count': 1,
            'items': [],
        }
        app = create_app(session_factory=lambda: object())
        app.testing = True
        client = app.test_client()

        with patch('app.api.routes.require_tenant_shop', return_value=(1, 1)):
            resp = client.post(
                '/pricing/merchant-confirm',
                json={
                    'shop_id': 1,
                    'approver_user_id': 7,
                    'confirmed_items': [
                        {
                            'display_name': '标准价-2份早餐',
                            'current_price': 200,
                            'final_price': 210,
                            'gid': 'gid-1',
                            'hid': 'hid-1',
                        }
                    ],
                },
                headers={'X-Tenant-Id': '1', 'X-Shop-Id': '1'},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['message'], 'merchant pricing submitted')
        self.assertEqual(data['submitted_count'], 1)
        self.assertEqual(data['audit_mode'], 'formal_submit')


if __name__ == '__main__':
    unittest.main()


