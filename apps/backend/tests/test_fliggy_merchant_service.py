import os
import sys
import json
import tempfile
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
except ModuleNotFoundError:  # pragma: no cover - minimal env
    create_app = None

from app.services.fliggy_merchant_service import (
    _collect_merchant_page,
    _collect_rate_items_from_text,
    _extract_price_items_from_page,
    _extract_price,
    _extract_price_override,
    _parse_rate_item_text,
    _looks_like_login_page,
    _load_storage_state_payload,
    _normalize_selector_map,
    _probe_authenticated_context,
    _resolve_usable_merchant_state,
    _storage_state_has_session_data,
    _evaluate_authenticated_page,
    _safe_storage_name,
    _wait_for_manual_authentication,
    fetch_fliggy_merchant_price_preview,
    preview_fliggy_merchant_prices,
)


class FakeLocator:
    def __init__(self, count: int, text: str = '', click_handler=None):
        self._count = count
        self._text = text
        self._click_handler = click_handler
        self.first = self

    def count(self) -> int:
        return self._count

    def inner_text(self, timeout: int = 0) -> str:
        return self._text

    def click(self, timeout: int = 0, force: bool = False) -> None:
        if callable(self._click_handler):
            self._click_handler()
        return None


class FakePage:
    def __init__(self, selectors=None, url: str = 'https://example.com/login', body_text: str = '', body_text_sequence=None):
        self._selectors = selectors or set()
        self.url = url
        self.body_text = body_text
        self.body_text_sequence = list(body_text_sequence or [])
        self.wait_calls = 0
        self.clicked_selectors = []

    def locator(self, selector: str) -> FakeLocator:
        if selector == 'body':
            if self.body_text_sequence:
                index = min(self.wait_calls, len(self.body_text_sequence) - 1)
                return FakeLocator(1, self.body_text_sequence[index])
            return FakeLocator(1, self.body_text)
        return FakeLocator(
            1 if selector in self._selectors else 0,
            click_handler=lambda: self.clicked_selectors.append(selector),
        )

    def goto(self, url: str, wait_until: str = '', timeout: int = 0) -> None:
        self.url = url

    def wait_for_timeout(self, timeout: int) -> None:
        self.wait_calls += 1
        return None

    def close(self) -> None:
        return None


class FakeContext:
    def __init__(self, probe_page: FakePage):
        self._probe_page = probe_page

    def new_page(self) -> FakePage:
        return self._probe_page


class FliggyMerchantServiceHelpersTestCase(unittest.TestCase):
    def test_safe_storage_name(self) -> None:
        self.assertEqual(_safe_storage_name('shop 1 state', shop_id=1), 'shop-1-state.json')
        self.assertEqual(_safe_storage_name('', shop_id=9), 'shop-9.json')

    def test_storage_state_has_session_data(self) -> None:
        self.assertFalse(_storage_state_has_session_data({'cookies': [], 'origins': []}))
        self.assertTrue(_storage_state_has_session_data({'cookies': [{'name': 'AccessToken'}], 'origins': []}))

    def test_load_storage_state_payload_handles_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_path = Path(tmp_dir) / 'broken.json'
            state_path.write_text('{broken', encoding='utf-8')
            self.assertEqual(_load_storage_state_payload(state_path), {})

    def test_resolve_usable_merchant_state_falls_back_to_legacy_shop_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            (state_dir / 'merchant-platform.json').write_text('{"cookies": [], "origins": []}', encoding='utf-8')
            (state_dir / 'shop-1.json').write_text(
                json.dumps({'cookies': [{'name': 'AccessToken', 'value': 'token'}], 'origins': []}, ensure_ascii=False),
                encoding='utf-8',
            )

            resolved_path, resolved_name = _resolve_usable_merchant_state(
                requested_name='merchant-platform.json',
                shop_id=1,
                state_dir=state_dir,
            )

            self.assertEqual(resolved_name, 'shop-1.json')
            self.assertEqual(resolved_path.name, 'shop-1.json')

    def test_resolve_usable_merchant_state_rejects_only_empty_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_dir = Path(tmp_dir)
            (state_dir / 'merchant-platform.json').write_text('{"cookies": [], "origins": []}', encoding='utf-8')

            with self.assertRaisesRegex(RuntimeError, 'merchant session invalid, login required'):
                _resolve_usable_merchant_state(
                    requested_name='merchant-platform.json',
                    shop_id=1,
                    state_dir=state_dir,
                )

    def test_extract_price(self) -> None:
        self.assertEqual(_extract_price('当前价 ¥568.00'), 568.0)
        self.assertIsNone(_extract_price('无价格'))

    def test_extract_price_override_ignores_breakfast_count(self) -> None:
        self.assertIsNone(_extract_price_override('\u65e9\u99102'))

    def test_extract_price_override_accepts_real_price(self) -> None:
        self.assertEqual(_extract_price_override('200'), 200.0)
        self.assertEqual(_extract_price_override('\u5f53\u524d\u4ef7 \xa5568.00'), 568.0)

    def test_normalize_selector_map(self) -> None:
        selectors = _normalize_selector_map({'current_price': '.price-now', 'room_rows': ['.row-a', '.row-b']})
        self.assertIn('.price-now', selectors['current_price'])
        self.assertEqual(selectors['room_rows'][0], '.row-a')
        self.assertTrue(selectors['submit'])

    def test_hwht_selector_seed_is_applied_by_url(self) -> None:
        selectors = _normalize_selector_map(None, login_url='https://ebooking.hwht.com/login', price_url='https://ebooking.hwht.com/price/manage')
        self.assertIn("button.aui-button--primary:has-text('登录')", selectors['submit'])
        self.assertIn("tr:has-text('标准价')", selectors['room_rows'])

    def test_looks_like_login_page(self) -> None:
        selectors = _normalize_selector_map(None)
        page = FakePage(selectors={selectors['username'][0], selectors['password'][0]})
        self.assertTrue(_looks_like_login_page(page, selectors))

    def test_evaluate_authenticated_page_accepts_current_page(self) -> None:
        selectors = _normalize_selector_map(None)
        page = FakePage(
            selectors={selectors['room_rows'][0]},
            url='https://merchant.example.com/price/manage',
        )

        authenticated, reason = _evaluate_authenticated_page(
            page,
            selectors=selectors,
            login_url='https://merchant.example.com/login',
            price_url='https://merchant.example.com/price/manage',
            success_reason='success-selector',
            price_reason='current-price-page',
            url_reason='current-url',
        )

        self.assertTrue(authenticated)
        self.assertEqual(reason, 'current-price-page')

    def test_evaluate_authenticated_page_rejects_logged_out_overlay(self) -> None:
        selectors = _normalize_selector_map(None)
        page = FakePage(
            url='https://merchant.example.com/price/manage',
            body_text='您已经退出登录，请重新登录后再试',
        )

        authenticated, reason = _evaluate_authenticated_page(
            page,
            selectors=selectors,
            login_url='https://merchant.example.com/login',
            price_url='https://merchant.example.com/price/manage',
            success_reason='success-selector',
            price_reason='current-price-page',
            url_reason='current-url',
        )

        self.assertFalse(authenticated)
        self.assertEqual(reason, 'redirected-to-login')

    def test_evaluate_authenticated_page_rejects_taobao_unified_login_text(self) -> None:
        selectors = _normalize_selector_map(None, price_url='https://ebooking.hwht.com/price/manage')
        page = FakePage(
            url='https://login.taobao.com/havanaone/login/login.htm?bizName=taobao',
            body_text='密码登录 短信登录 忘记账号 免费注册 手机扫码登录 淘宝APP',
        )

        authenticated, reason = _evaluate_authenticated_page(
            page,
            selectors=selectors,
            login_url='https://ebooking.hwht.com/',
            price_url='https://ebooking.hwht.com/price/manage',
            success_reason='success-selector',
            price_reason='current-price-page',
            url_reason='current-url',
        )

        self.assertFalse(authenticated)
        self.assertEqual(reason, 'redirected-to-login')

    def test_evaluate_authenticated_page_rejects_login_host_without_form_selectors(self) -> None:
        selectors = _normalize_selector_map(None, price_url='https://ebooking.hwht.com/price/manage')
        page = FakePage(
            url='https://login.taobao.com/havanaone/login/login.htm?bizName=taobao',
            body_text='网站无障碍',
        )

        authenticated, reason = _evaluate_authenticated_page(
            page,
            selectors=selectors,
            login_url='https://ebooking.hwht.com/',
            price_url='https://ebooking.hwht.com/price/manage',
            success_reason='success-selector',
            price_reason='current-price-page',
            url_reason='current-url',
        )

        self.assertFalse(authenticated)
        self.assertEqual(reason, 'redirected-to-login')

    def test_probe_authenticated_context_rejects_login_redirect(self) -> None:
        selectors = _normalize_selector_map(None)
        current_page = FakePage(url='https://merchant.example.com/login')
        probe_page = FakePage(
            selectors={selectors['username'][0], selectors['password'][0]},
            url='https://merchant.example.com/login',
        )
        context = FakeContext(probe_page)

        authenticated, reason = _probe_authenticated_context(
            context,
            current_page=current_page,
            selectors=selectors,
            login_url='https://merchant.example.com/login',
            price_url='https://merchant.example.com/price/manage',
            timeout_ms=5000,
            wait_ms=500,
        )

        self.assertFalse(authenticated)
        self.assertEqual(reason, 'redirected-to-login')

    def test_probe_authenticated_context_accepts_price_page(self) -> None:
        selectors = _normalize_selector_map(None)
        current_page = FakePage(url='https://merchant.example.com/login')
        probe_page = FakePage(
            selectors={selectors['room_rows'][0]},
            url='https://merchant.example.com/price/manage',
        )
        context = FakeContext(probe_page)

        authenticated, reason = _probe_authenticated_context(
            context,
            current_page=current_page,
            selectors=selectors,
            login_url='https://merchant.example.com/login',
            price_url='https://merchant.example.com/price/manage',
            timeout_ms=5000,
            wait_ms=500,
        )

        self.assertTrue(authenticated)
        self.assertEqual(reason, 'validation-price-page')

    @patch('app.services.fliggy_merchant_service.time.monotonic', side_effect=[0.0, 0.0, 0.5, 0.5])
    @patch('app.services.fliggy_merchant_service._evaluate_authenticated_page', side_effect=[(False, 'redirected-to-login'), (True, 'manual-price-page')])
    def test_wait_for_manual_authentication_accepts_late_success(self, mocked_evaluate, _mocked_time) -> None:
        selectors = _normalize_selector_map(None)
        current_page = FakePage(url='https://merchant.example.com/login')
        context = FakeContext(FakePage(url='https://merchant.example.com/price/manage'))

        authenticated, reason = _wait_for_manual_authentication(
            context,
            current_page=current_page,
            selectors=selectors,
            login_url='https://merchant.example.com/login',
            price_url='https://merchant.example.com/price/manage',
            timeout_ms=3000,
            wait_ms=500,
            poll_ms=500,
        )

        self.assertTrue(authenticated)
        self.assertEqual(reason, 'manual-price-page')
        self.assertEqual(mocked_evaluate.call_count, 2)

    def test_collect_rate_items_from_text(self) -> None:
        items = _collect_rate_items_from_text(
            '标准价-2份早餐\n200\n标准价-无早餐\n180\n标准价-1份早餐\n190\n'
        )

        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]['rate_name'], '标准价-2份早餐')
        self.assertEqual(items[1]['price'], 180.0)
        self.assertEqual(items[2]['display_name'], '标准价-1份早餐')

    def test_parse_rate_item_text_ignores_breakfast_count_in_mixed_line(self) -> None:
        item = _parse_rate_item_text('\u6807\u51c6\u4ef7-2\u4efd\u65e9\u9910 2444922898 \u5e73\u53f0\u7ed3\u7b97 200 \u65e9\u99102\n200 \u65e9\u99102', fallback_name='\u6807\u51c6\u53cc\u5e8a\u623f')
        self.assertEqual(item['rate_name'], '\u6807\u51c6\u4ef7-2\u4efd\u65e9\u9910')
        self.assertEqual(item['price'], 200.0)

    def test_collect_rate_items_from_hwht_text_ignores_gid_and_calendar_digits(self) -> None:
        sample = (
            '筛选房型\n日期选择\n16\n17\n18\n标准双床房（零压床垫+100%羽绒被+独立办公桌）\n双床\nCNY\n'
            '标准价-2份早餐\n2444922863\n平台结算\n\n200\n\n早餐2\n\n200\n'
            '标准价-无早餐\n2444922926\n平台结算\n\n180\n\n180\n'
            '标准价-1份早餐\n2444922975\n平台结算\n\n190\n\n早餐1\n\n190\n'
        )

        items = _collect_rate_items_from_text(sample)

        self.assertEqual([item['rate_name'] for item in items], ['标准价-2份早餐', '标准价-无早餐', '标准价-1份早餐'])
        self.assertEqual([item['price'] for item in items], [200.0, 180.0, 190.0])
        self.assertTrue(all(item['room_name'].startswith('标准双床房') for item in items))
        self.assertTrue(all(item['price'] < 10000 for item in items))

    @patch('app.services.fliggy_merchant_service.Path.exists', return_value=True)
    @patch('app.services.fliggy_merchant_service._collect_merchant_page_with_storage_state')
    @patch('app.services.fliggy_merchant_service._collect_merchant_page_via_cdp')
    @patch('app.services.fliggy_merchant_service._release_db_connection')
    @patch('app.services.fliggy_merchant_service._resolve_connection_context')
    def test_collect_merchant_page_prefer_cdp_falls_back_when_cdp_returns_empty_items(
        self,
        mocked_context,
        _mocked_release,
        mocked_cdp_collect,
        mocked_storage_collect,
        _mocked_exists,
    ) -> None:
        mocked_context.return_value = {
            'shop_name': '测试门店',
            'login_url': 'https://ebooking.hwht.com/',
            'price_url': 'https://ebooking.hwht.com/price/manage',
            'storage_state_name': 'shop-1.json',
            'selectors': None,
        }
        mocked_cdp_collect.return_value = (
            {
                'shop_id': 1,
                'status': 'success',
                'source': 'fliggy_merchant',
                'shop_name': '测试门店',
                'price_url': 'https://ebooking.hwht.com/price/manage',
                'current_price': None,
                'room_count': 0,
                'rooms': [],
                'collected_at': '2026-04-18 12:10:00',
            },
            [],
            None,
            'https://ebooking.hwht.com/price/manage',
        )
        mocked_storage_collect.return_value = (
            {
                'shop_id': 1,
                'status': 'success',
                'source': 'fliggy_merchant',
                'shop_name': '测试门店',
                'price_url': 'https://ebooking.hwht.com/price/manage',
                'storage_state_used': 'shop-1.json',
                'current_price': 188.0,
                'room_count': 1,
                'rooms': [{'display_name': '标准价-无早餐', 'price': 188.0}],
                'collected_at': '2026-04-18 12:10:02',
            },
            [{'display_name': '标准价-无早餐', 'price': 188.0}],
            188.0,
            'https://ebooking.hwht.com/price/manage',
        )

        base_result, items, current_price, result_price_url = _collect_merchant_page(
            db=object(),
            shop_id=1,
            collect_mode='prefer_cdp',
            debug_url='http://127.0.0.1:9222',
        )

        self.assertEqual(items, [{'display_name': '标准价-无早餐', 'price': 188.0}])
        self.assertEqual(current_price, 188.0)
        self.assertEqual(result_price_url, 'https://ebooking.hwht.com/price/manage')
        self.assertEqual(base_result['collect_mode'], 'storage_state')
        self.assertEqual(base_result['collect_mode_requested'], 'prefer_cdp')
        self.assertEqual(base_result['cdp_fallback_reason'], 'cdp-returned-empty-items')
        mocked_cdp_collect.assert_called_once()
        mocked_storage_collect.assert_called_once()

    @patch('app.services.fliggy_merchant_service.time.monotonic', return_value=0.0)
    def test_extract_price_items_from_page_waits_for_late_room_text(self, _mocked_time) -> None:
        sample = (
            '筛选房型\n日期选择\n16\n17\n18\n标准双床房（零压床垫+100%羽绒被+独立办公桌）\n双床\nCNY\n'
            '标准价-2份早餐\n2444922863\n平台结算\n\n200\n\n早餐2\n\n200\n'
            '标准价-无早餐\n2444922926\n平台结算\n\n180\n\n180\n'
        )
        selectors = _normalize_selector_map(None, price_url='https://ebooking.hwht.com/price/manage')
        page = FakePage(
            url='https://ebooking.hwht.com/price/manage',
            body_text_sequence=['', sample],
        )

        current_price, items = _extract_price_items_from_page(
            page,
            selector_map=selectors,
            content_wait_ms=800,
            poll_ms=100,
        )

        self.assertEqual(page.wait_calls, 1)
        self.assertEqual(len(items), 2)
        self.assertEqual(current_price, 180.0)
        self.assertEqual([item['rate_name'] for item in items], ['标准价-2份早餐', '标准价-无早餐'])

    @patch('app.services.fliggy_merchant_service.time.monotonic', return_value=0.0)
    def test_extract_price_items_from_page_clicks_expand_all_rooms_before_waiting(self, _mocked_time) -> None:
        sample = (
            '筛选房型\n日期选择\n16\n17\n18\n标准双床房（零压床垫+100%羽绒被+独立办公桌）\n双床\nCNY\n'
            '标准价-2份早餐\n2444922863\n平台结算\n\n200\n\n早餐2\n\n200\n'
        )
        selectors = _normalize_selector_map(None, price_url='https://ebooking.hwht.com/price/manage')
        page = FakePage(
            selectors={"text=展开全部房型"},
            url='https://ebooking.hwht.com/price/manage',
            body_text_sequence=['', sample],
        )

        current_price, items = _extract_price_items_from_page(
            page,
            selector_map=selectors,
            content_wait_ms=800,
            poll_ms=100,
        )

        self.assertIn("text=展开全部房型", page.clicked_selectors)
        self.assertGreaterEqual(page.wait_calls, 1)
        self.assertEqual(current_price, 200.0)
        self.assertEqual(len(items), 1)

    @patch('app.services.fliggy_merchant_service.create_merchant_pricing_audit')
    @patch('app.services.fliggy_merchant_service.save_merchant_price_history')
    @patch('app.services.fliggy_merchant_service._decorate_items_with_mapping')
    @patch('app.services.fliggy_merchant_service._collect_merchant_page')
    def test_preview_fliggy_merchant_prices_records_preview_audit(self, mocked_collect_page, mocked_decorate, mocked_save_history, mocked_audit) -> None:
        mocked_collect_page.return_value = (
            {
                'shop_id': 1,
                'shop_name': '测试门店',
                'price_url': 'https://merchant.example.com/price/manage',
                'storage_state_used': 'shop-1.json',
                'collect_mode': 'storage_state',
                'collect_mode_requested': 'prefer_cdp',
                'cdp_fallback_reason': 'cdp-returned-empty-items',
                'matched_page_url': 'https://ebooking.hwht.com/price/manage?from=tab',
                'debug_url': 'http://127.0.0.1:9222',
                'collected_at': '2026-03-15 18:30:00',
            },
            [{'display_name': '标准价-2份早餐', 'price': 200.0}],
            200.0,
            'https://merchant.example.com/price/manage',
        )
        mocked_decorate.return_value = (
            [{'display_name': '标准价-2份早餐', 'price': 200.0, 'is_mapped': True, 'gid': 'gid-1', 'hid': 'hid-1'}],
            {'total': 1, 'mapped': 1, 'partial': 0, 'unmapped': 0},
        )
        mocked_save_history.return_value = 1
        mocked_audit.return_value = {'audit_id': 7, 'audit_mode': 'preview', 'status': 'success'}

        result = preview_fliggy_merchant_prices(db=object(), shop_id=1)

        self.assertEqual(result['audit_mode'], 'preview')
        self.assertEqual(result['audit']['audit_id'], 7)
        self.assertEqual(result['mapping_summary']['mapped'], 1)
        self.assertEqual(result['collect_mode'], 'storage_state')
        self.assertEqual(result['collect_mode_requested'], 'prefer_cdp')
        self.assertEqual(result['cdp_fallback_reason'], 'cdp-returned-empty-items')
        self.assertEqual(result['matched_page_url'], 'https://ebooking.hwht.com/price/manage?from=tab')
        self.assertEqual(result['debug_url'], 'http://127.0.0.1:9222')
        mocked_audit.assert_called_once()

    @patch('app.services.fliggy_merchant_service.create_merchant_pricing_audit')
    @patch('app.services.fliggy_merchant_service.save_merchant_price_history')
    @patch('app.services.fliggy_merchant_service._decorate_items_with_mapping')
    @patch('app.services.fliggy_merchant_service._collect_merchant_page')
    def test_preview_fliggy_merchant_prices_allows_missing_storage_state_used(self, mocked_collect_page, mocked_decorate, mocked_save_history, mocked_audit) -> None:
        mocked_collect_page.return_value = (
            {
                'shop_id': 1,
                'shop_name': '????',


                'price_url': 'https://merchant.example.com/price/manage',
                'collect_mode': 'cdp_current_page',
                'collected_at': '2026-03-15 18:30:00',
            },
            [{'display_name': '???-2???', 'price': 200.0}],
            200.0,
            'https://merchant.example.com/price/manage',
        )
        mocked_decorate.return_value = (
            [{'display_name': '???-2???', 'price': 200.0, 'is_mapped': False, 'gid': '', 'hid': ''}],
            {'total': 1, 'mapped': 0, 'partial': 0, 'unmapped': 1},
        )
        mocked_save_history.return_value = 1
        mocked_audit.return_value = {'audit_id': 8, 'audit_mode': 'preview', 'status': 'success'}

        result = preview_fliggy_merchant_prices(db=object(), shop_id=1)

        self.assertIsNone(result['storage_state_used'])
        self.assertIsNone(mocked_audit.call_args.kwargs['payload']['storage_state_used'])

    @patch('app.services.fliggy_merchant_service.login_fliggy_merchant_session')
    @patch('app.services.fliggy_merchant_service.preview_fliggy_merchant_prices')
    @patch('app.services.fliggy_merchant_service.save_merchant_credential')
    @patch('app.services.fliggy_merchant_service._resolve_connection_context')
    def test_fetch_fliggy_merchant_price_preview_auto_logins_once(
        self,
        mocked_context,
        mocked_save_credential,
        mocked_preview,
        mocked_login,
    ) -> None:
        mocked_context.return_value = {
            'credential': {'tenant_id': 1},
            'login_url': 'https://ebooking.hwht.com/',
            'price_url': 'https://ebooking.hwht.com/price/manage',
            'storage_state_name': 'shop-1.json',
            'selectors': {'room_rows': ['tr:has-text(\'标准价\')']},
        }
        mocked_preview.side_effect = [
            RuntimeError('merchant session expired, login required'),
            {
                'shop_id': 1,
                'status': 'success',
                'audit_mode': 'preview',
                'audit': {'audit_id': 9},
                'shop_name': '测试门店',
                'price_url': 'https://ebooking.hwht.com/price/manage',
                'storage_state_used': 'shop-1.json',
                'current_price': 200.0,
                'item_count': 3,
                'items': [],
                'mapping_summary': {'total': 3, 'mapped': 0, 'partial': 0, 'unmapped': 3},
                'collected_at': '2026-03-16 15:00:00',
            },
        ]
        mocked_login.return_value = {'session_saved': True}
        mocked_save_credential.return_value = {'exists': True}

        result = fetch_fliggy_merchant_price_preview(
            db=object(),
            shop_id=1,
            username='demo@example.com',
            password='secret',
            auto_login=True,
            save_credential=True,
            login_headless=False,
        )

        self.assertTrue(result['auto_login_performed'])
        self.assertTrue(result['credential_saved'])
        self.assertEqual(mocked_preview.call_count, 2)
        mocked_login.assert_called_once()
        mocked_save_credential.assert_called_once()


    @patch('app.services.fliggy_merchant_service.login_fliggy_merchant_session')
    @patch('app.services.fliggy_merchant_service.preview_fliggy_merchant_prices')
    @patch('app.services.fliggy_merchant_service.save_merchant_credential')
    @patch('app.services.fliggy_merchant_service._resolve_connection_context')
    def test_fetch_fliggy_merchant_price_preview_cdp_only_skips_auto_login(
        self,
        mocked_context,
        mocked_save_credential,
        mocked_preview,
        mocked_login,
    ) -> None:
        mocked_context.return_value = {
            'credential': {'tenant_id': 1},
            'login_url': 'https://ebooking.hwht.com/',
            'price_url': 'https://ebooking.hwht.com/price/manage',
            'storage_state_name': 'shop-1.json',
            'selectors': {'room_rows': ['tr:has-text(\'标准价\')']},
        }
        mocked_preview.side_effect = RuntimeError('merchant session expired, login required')
        mocked_save_credential.return_value = {'exists': True}

        with self.assertRaises(RuntimeError):
            fetch_fliggy_merchant_price_preview(
                db=object(),
                shop_id=1,
                auto_login=True,
                save_credential=False,
                collect_mode='cdp_current_page',
                debug_url='http://127.0.0.1:9333',
            )

        mocked_login.assert_not_called()
        mocked_preview.assert_called_once()

@unittest.skipIf(create_app is None, 'Flask is not installed')
class FliggyMerchantRouteTestCase(unittest.TestCase):
    @patch('app.api.routes.login_fliggy_merchant_session')
    def test_login_route(self, mocked_login) -> None:
        mocked_login.return_value = {'shop_id': 1, 'status': 'success', 'session_saved': True}
        app = create_app(session_factory=lambda: object())
        app.testing = True
        client = app.test_client()

        with patch('app.api.routes.require_tenant_shop', return_value=(1, 1)):
            resp = client.post(
                '/merchant/fliggy/session/login',
                json={
                    'shop_id': 1,
                    'login_url': 'https://example.com/login',
                    'username': 'demo',
                    'password': 'demo-pass',
                    'storage_state_name': 'shop-1.json',
                    'headless': False,
                },
                headers={'X-Tenant-Id': '1', 'X-Shop-Id': '1'},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['message'], 'merchant session saved')
        self.assertTrue(data['session_saved'])

    @patch('app.api.routes.fetch_fliggy_merchant_price_preview')
    def test_preview_route(self, mocked_preview) -> None:
        mocked_preview.return_value = {
            'shop_id': 1,
            'status': 'success',
            'audit_mode': 'preview',
            'audit': {'audit_id': 7},
            'item_count': 2,
            'mapping_summary': {'total': 2, 'mapped': 1, 'partial': 0, 'unmapped': 1},
            'items': [],
        }
        app = create_app(session_factory=lambda: object())
        app.testing = True
        client = app.test_client()

        with patch('app.api.routes.require_tenant_shop', return_value=(1, 1)):
            resp = client.post(
                '/merchant/fliggy/prices/preview',
                json={
                    'shop_id': 1,
                    'price_url': 'https://example.com/pricing',
                    'headless': True,
                    'collect_mode': 'prefer_cdp',
                    'debug_url': 'http://127.0.0.1:9222',
                },
                headers={'X-Tenant-Id': '1', 'X-Shop-Id': '1'},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['message'], 'merchant prices previewed')
        self.assertEqual(data['item_count'], 2)
        self.assertEqual(data['mapping_summary']['mapped'], 1)
        self.assertEqual(data['audit_mode'], 'preview')
        self.assertEqual(mocked_preview.call_args.kwargs['collect_mode'], 'prefer_cdp')
        self.assertEqual(mocked_preview.call_args.kwargs['debug_url'], 'http://127.0.0.1:9222')

    @patch('app.api.routes.collect_fliggy_merchant_prices')
    def test_collect_route(self, mocked_collect) -> None:
        mocked_collect.return_value = {'shop_id': 1, 'status': 'success', 'current_price': 568.0, 'saved_count': 2}
        app = create_app(session_factory=lambda: object())
        app.testing = True
        client = app.test_client()

        with patch('app.api.routes.require_tenant_shop', return_value=(1, 1)):
            resp = client.post(
                '/merchant/fliggy/prices/collect',
                json={
                    'shop_id': 1,
                    'price_url': 'https://example.com/pricing',
                    'headless': True,
                    'save_result': True,
                    'collect_mode': 'cdp_current_page',
                    'debug_url': 'http://127.0.0.1:9333',
                },
                headers={'X-Tenant-Id': '1', 'X-Shop-Id': '1'},
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['message'], 'merchant prices collected')
        self.assertEqual(data['current_price'], 568.0)
        self.assertEqual(mocked_collect.call_args.kwargs['collect_mode'], 'cdp_current_page')
        self.assertEqual(mocked_collect.call_args.kwargs['debug_url'], 'http://127.0.0.1:9333')


if __name__ == '__main__':
    unittest.main()





