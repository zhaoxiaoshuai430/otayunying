import os
import sys
import unittest
from datetime import date, timedelta
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

from app.services.competitor_service import (
    _build_collection_result_from_fliggy_rows,
    _extract_fliggy_rows_from_page,
    _is_fliggy_guest_authenticated,
    _is_fliggy_home_or_root_url,
    _open_fliggy_guest_login_entry,
    _pick_fliggy_cdp_target_page,
    _save_fliggy_guest_credential_if_supported,
    _should_navigate_fliggy_cdp_page,
    collect_fliggy_hotel_prices_playwright,
    normalize_fliggy_guest_start_url,
)


class FakeContext:
    def __init__(self, cookies=None):
        self._cookies = list(cookies or [])

    def cookies(self):
        return list(self._cookies)


class FakeLocator:
    def __init__(self, page, selector: str):
        self.page = page
        self.selector = selector
        self.first = self

    def count(self):
        return 1 if self.selector in self.page.present_selectors else 0

    def click(self, timeout=2000):
        self.page.clicked.append(self.selector)

    def get_attribute(self, name: str):
        return self.page.hrefs.get((self.selector, name))

    def is_visible(self):
        return self.selector in self.page.present_selectors


class FakePage:
    def __init__(
        self,
        present_selectors=None,
        *,
        url='https://www.fliggy.com/',
        cookies=None,
        hrefs=None,
        visibility_state='visible',
        evaluate_result=None,
    ):
        self.present_selectors = set(present_selectors or [])
        self.clicked = []
        self.waits = []
        self.url = url
        self.context = FakeContext(cookies=cookies)
        self.hrefs = dict(hrefs or {})
        self.goto_calls = []
        self.visibility_state = visibility_state
        self.evaluate_result = list(evaluate_result or [])

    def locator(self, selector: str):
        return FakeLocator(self, selector)

    def goto(self, url: str, timeout: int, wait_until: str):
        self.goto_calls.append((url, timeout, wait_until))
        self.url = url

    def wait_for_timeout(self, wait_ms: int):
        self.waits.append(wait_ms)

    def wait_for_load_state(self, state: str, timeout: int):
        self.waits.append((state, timeout))

    def evaluate(self, script: str):
        if 'document.visibilityState' in script:
            return self.visibility_state
        return list(self.evaluate_result)


class FakeBrowserContext:
    def __init__(self, pages):
        self.pages = list(pages)


class FakeBrowser:
    def __init__(self, contexts):
        self.contexts = list(contexts)


class CompetitorGuestLoginFlowTestCase(unittest.TestCase):
    def test_detects_fliggy_www_home_page(self) -> None:
        self.assertTrue(_is_fliggy_home_or_root_url('https://www.fliggy.com/'))
        self.assertTrue(_is_fliggy_home_or_root_url('https://fliggy.com'))

    def test_open_homepage_login_entry_clicks_entry_selector(self) -> None:
        page = FakePage(present_selectors={"a:has-text('\u767b\u5f55')"})
        opened = _open_fliggy_guest_login_entry(
            page,
            {'entry': ["a:has-text('\u767b\u5f55')"], 'password': []},
            login_url='https://www.fliggy.com/',
            wait_ms=800,
        )
        self.assertTrue(opened)
        self.assertEqual(page.clicked, ["a:has-text('\u767b\u5f55')"])

    def test_open_homepage_login_entry_falls_back_to_entry_href(self) -> None:
        selector = "a:has-text('\u767b\u5f55')"
        page = FakePage(
            present_selectors={selector},
            hrefs={(selector, 'href'): 'https://login.taobao.com/member/login.jhtml'},
        )
        opened = _open_fliggy_guest_login_entry(
            page,
            {'entry': [selector], 'password': []},
            login_url='https://www.fliggy.com/',
            wait_ms=800,
        )
        self.assertTrue(opened)
        self.assertEqual(page.goto_calls[0][0], 'https://login.taobao.com/member/login.jhtml')

    @patch('app.services.competitor_service._guest_body_text', return_value='')
    def test_homepage_without_auth_cookie_is_not_treated_as_logged_in(self, _mocked_body_text) -> None:
        page = FakePage(present_selectors={"text=\u6211\u7684\u8ba2\u5355", "a:has-text('\u767b\u5f55')"})
        authenticated = _is_fliggy_guest_authenticated(
            page,
            {
                'success': ["text=\u6211\u7684\u8ba2\u5355"],
                'entry': ["a:has-text('\u767b\u5f55')"],
                'password': [],
                'submit': [],
            },
            login_url='https://www.fliggy.com/',
        )
        self.assertFalse(authenticated)

    def test_extract_fliggy_rows_filters_non_hotel_cards(self) -> None:
        page = FakePage(
            evaluate_result=[
                {
                    'name': '国内机票特价',
                    'text': '国内机票特价\n郑州-上海\n¥299起',
                    'href': 'https://flight.fliggy.com/',
                },
                {
                    'name': '郑州建业艾美酒店',
                    'text': '郑州建业艾美酒店\n4.7分 1500条点评 地图\n¥588起',
                    'href': 'https://hotel.fliggy.com/hotel_detail.htm?id=1',
                },
                {
                    'name': '郑州中油花园酒店（CBD会展中心店）',
                    'text': '郑州中油花园酒店（CBD会展中心店）\n4.8分 999条点评 早餐\n¥468',
                    'href': 'https://hotel.fliggy.com/hotel_detail.htm?id=2',
                },
            ]
        )

        result = _extract_fliggy_rows_from_page(page)

        self.assertEqual(result['raw_row_count'], 3)
        self.assertEqual(result['filtered_row_count'], 1)
        self.assertEqual(len(result['rows']), 2)
        self.assertEqual(result['rows'][0]['hotel_name'], '郑州建业艾美酒店')
        self.assertEqual(result['filtered_examples'][0]['reason'], 'non_hotel_keyword:机票')
        self.assertEqual(result['filter_summary']['non_hotel_keyword:机票'], 1)

    def test_extract_fliggy_rows_normalizes_hotel_name_suffix(self) -> None:
        page = FakePage(
            evaluate_result=[
                {
                    'name': '郑州建业艾美酒店\uE123 会员价 立减20元',
                    'text': '郑州建业艾美酒店\uE123 会员价 立减20元\n4.7分 1500条点评 地图\n¥588起',
                    'href': 'https://hotel.fliggy.com/hotel_detail.htm?id=1',
                }
            ]
        )

        result = _extract_fliggy_rows_from_page(page)

        self.assertEqual(result['rows'][0]['hotel_name'], '郑州建业艾美酒店')

    def test_extract_fliggy_rows_keeps_weak_structure_hotel_card(self) -> None:
        page = FakePage(
            evaluate_result=[
                {
                    'name': '',
                    'text': '杭州西湖国宾馆\n4.8分 2000条点评 早餐\n¥899起',
                    'href': '',
                }
            ]
        )

        result = _extract_fliggy_rows_from_page(page)

        self.assertEqual(len(result['rows']), 1)
        self.assertEqual(result['rows'][0]['hotel_name'], '杭州西湖国宾馆')
        self.assertEqual(result['filtered_row_count'], 0)

    def test_extract_fliggy_rows_prefers_multiple_hotel_cards_over_noise(self) -> None:
        page = FakePage(
            evaluate_result=[
                {
                    'name': '热门推荐',
                    'text': '热门推荐\n限时优惠\n¥299起',
                    'href': 'https://hotel.fliggy.com/topic',
                },
                {
                    'name': '杭州西湖国宾馆',
                    'text': '杭州西湖国宾馆\n4.8分 2000条点评 早餐\n¥899起',
                    'href': 'https://hotel.fliggy.com/hotel_detail.htm?id=11',
                },
                {
                    'name': '杭州君悦酒店',
                    'text': '杭州君悦酒店\n4.7分 1800条点评 地图\n¥1099起',
                    'href': 'https://hotel.fliggy.com/hotel_detail.htm?id=12',
                }
            ]
        )

        result = _extract_fliggy_rows_from_page(page)

        self.assertEqual(len(result['rows']), 2)
        self.assertEqual(result['rows'][0]['hotel_name'], '杭州西湖国宾馆')
        self.assertEqual(result['rows'][1]['hotel_name'], '杭州君悦酒店')
        self.assertEqual(result['filtered_row_count'], 1)
        self.assertEqual(result['filter_summary']['weak_hotel_signal'], 1)

    def test_build_collection_result_includes_filter_stats(self) -> None:
        result = _build_collection_result_from_fliggy_rows(
            shop_id=1,
            start_url='https://hotel.fliggy.com/hotel_list3.htm?city=410100',
            rows=[
                {
                    'hotel_name': '郑州建业艾美酒店',
                    'price': 588.0,
                    'url': 'https://hotel.fliggy.com/hotel_detail.htm?id=1',
                    'raw_text': '郑州建业艾美酒店 ¥588起',
                }
            ],
            stats={
                'raw_row_count': 3,
                'filtered_row_count': 2,
                'filter_summary': {'non_hotel_keyword:机票': 1, 'weak_hotel_signal': 1},
                'filtered_examples': [{'name': '国内机票特价', 'reason': 'non_hotel_keyword:机票'}],
            },
        )

        self.assertEqual(result['count'], 1)
        self.assertEqual(result['raw_row_count'], 3)
        self.assertEqual(result['kept_row_count'], 1)
        self.assertEqual(result['filtered_row_count'], 2)
        self.assertEqual(result['filter_summary']['weak_hotel_signal'], 1)
        self.assertEqual(result['filtered_examples'][0]['reason'], 'non_hotel_keyword:机票')

    def test_pick_cdp_target_page_prefers_visible_matching_page(self) -> None:
        hidden_page = FakePage(url='https://hotel.fliggy.com/hotel_list3.htm?city=330100', visibility_state='hidden')
        visible_page = FakePage(url='https://hotel.fliggy.com/hotel_list3.htm?city=410100', visibility_state='visible')
        browser = FakeBrowser([FakeBrowserContext([FakePage(url='https://www.baidu.com/'), hidden_page, visible_page])])

        selected = _pick_fliggy_cdp_target_page(browser, target_page_url_keyword='410100')

        self.assertIs(selected, visible_page)

    def test_normalize_fliggy_guest_start_url_refreshes_dates(self) -> None:
        result = normalize_fliggy_guest_start_url(
            'https://hotel.fliggy.com/hotel_list3.htm?city=410700&cityName=%E6%96%B0%E4%B9%A1%E5%B8%82&checkIn=2026-01-01&checkOut=2026-01-02'
        )

        self.assertIn('city=410700', result)
        self.assertIn('checkIn=' + date.today().isoformat(), result)
        self.assertIn('checkOut=' + (date.today() + timedelta(days=1)).isoformat(), result)

    def test_should_not_navigate_cdp_page_away_from_current_visible_list(self) -> None:
        self.assertFalse(
            _should_navigate_fliggy_cdp_page(
                current_url='https://hotel.fliggy.com/hotel_list3.htm?city=410100&checkIn=2026-01-01&checkOut=2026-01-02',
                start_url='https://hotel.fliggy.com/hotel_list3.htm?city=410700&cityName=%E6%96%B0%E4%B9%A1%E5%B8%82&checkIn=2026-01-01&checkOut=2026-01-02',
            )
        )

    @patch('app.services.competitor_service._collect_fliggy_hotel_prices_via_cdp')
    def test_collect_routes_to_cdp_current_page_mode(self, mocked_collect_cdp) -> None:
        mocked_collect_cdp.return_value = {
            'shop_id': 1,
            'count': 1,
            'items': [{'name': 'Hotel A'}],
            'collected_at': '2026-03-20 11:40:00',
            'raw_row_count': 1,
            'kept_row_count': 1,
            'filtered_row_count': 0,
            'filter_summary': {},
            'filtered_examples': [],
        }

        result = collect_fliggy_hotel_prices_playwright(
            shop_id=1,
            start_url='https://hotel.fliggy.com/hotel_list3.htm?city=410100',
            max_pages=1,
            max_hotels=10,
            headless=True,
            collect_mode='cdp_current_page',
            debug_url='http://127.0.0.1:9222',
            target_page_url_keyword='410100',
        )

        self.assertEqual(result['collect_mode'], 'cdp_current_page')
        self.assertFalse(result['auto_login_performed'])
        self.assertFalse(result['public_access_fallback'])
        mocked_collect_cdp.assert_called_once()
        self.assertIn('checkIn=' + date.today().isoformat(), mocked_collect_cdp.call_args.kwargs['start_url'])
        self.assertIn('city=410100', mocked_collect_cdp.call_args.kwargs['start_url'])

    @patch('app.services.competitor_service._collect_fliggy_hotel_prices_via_cdp')
    def test_collect_normalizes_prefer_cdp_alias_to_current_page(
        self,
        mocked_collect_cdp,
    ) -> None:
        mocked_collect_cdp.return_value = {
            'shop_id': 1,
            'count': 1,
            'items': [{'name': 'Hotel A'}],
            'collected_at': '2026-03-20 11:40:00',
            'raw_row_count': 1,
            'kept_row_count': 1,
            'filtered_row_count': 0,
            'filter_summary': {},
            'filtered_examples': [],
        }

        result = collect_fliggy_hotel_prices_playwright(
            shop_id=1,
            start_url='https://hotel.fliggy.com/hotel_list3.htm?city=410100',
            max_pages=1,
            max_hotels=10,
            headless=True,
            collect_mode='prefer_cdp',
            debug_url='http://127.0.0.1:9222',
            target_page_url_keyword='410100',
        )

        self.assertEqual(result['collect_mode'], 'cdp_current_page')
        self.assertFalse(result['auto_login_performed'])
        self.assertFalse(result['public_access_fallback'])
        mocked_collect_cdp.assert_called_once()
    @patch('app.services.competitor_service._collect_fliggy_hotel_prices_via_cdp')
    def test_collect_raises_when_logged_in_browser_capture_fails(
        self,
        mocked_collect_cdp,
    ) -> None:
        mocked_collect_cdp.side_effect = RuntimeError('failed to connect chromium debug url: http://127.0.0.1:9222')

        with self.assertRaisesRegex(RuntimeError, 'failed to connect chromium debug url'):
            collect_fliggy_hotel_prices_playwright(
                shop_id=1,
                start_url='https://hotel.fliggy.com/hotel_list3.htm?city=410100',
                max_pages=1,
                max_hotels=10,
                headless=True,
                collect_mode='prefer_cdp',
                debug_url='http://127.0.0.1:9222',
            )

        mocked_collect_cdp.assert_called_once()
    @patch('app.services.competitor_service._collect_fliggy_hotel_prices_playwright_once')
    def test_collect_supports_storage_state_mode(
        self,
        mocked_collect_once,
    ) -> None:
        mocked_collect_once.return_value = {
            'shop_id': 1,
            'count': 1,
            'items': [{'name': 'Hotel A'}],
            'collected_at': '2026-03-20 11:40:00',
            'raw_row_count': 1,
            'kept_row_count': 1,
            'filtered_row_count': 0,
            'filter_summary': {},
            'filtered_examples': [],
        }

        result = collect_fliggy_hotel_prices_playwright(
            shop_id=1,
            start_url='https://hotel.fliggy.com/hotel_list3.htm?city=410100',
            max_pages=1,
            max_hotels=10,
            headless=True,
            collect_mode='storage_state',
            storage_state_name='guest-shop-1.json',
        )

        self.assertEqual(result['collect_mode'], 'storage_state')
        mocked_collect_once.assert_called_once()
        self.assertEqual(mocked_collect_once.call_args.kwargs['storage_state_path'].name, 'guest-shop-1.json')

    @patch('app.services.competitor_service.save_merchant_credential')
    def test_guest_credential_save_keeps_storage_state_when_dpapi_is_unavailable(
        self,
        mocked_save,
    ) -> None:
        mocked_save.side_effect = [
            RuntimeError('merchant credential encryption currently requires Windows DPAPI'),
            {'storage_state_name': 'guest-shop-1.json'},
        ]

        saved, error = _save_fliggy_guest_credential_if_supported(
            db=object(),
            tenant_id=1,
            shop_id=1,
            username='guest@example.com',
            password='guest-secret',
            login_url='https://hotel.fliggy.com/',
            start_url='https://hotel.fliggy.com/',
            storage_state_name='guest-shop-1.json',
            selectors={},
        )

        self.assertFalse(saved)
        self.assertIn('Windows DPAPI', error)
        self.assertEqual(mocked_save.call_count, 2)
        self.assertEqual(mocked_save.call_args.kwargs['credential_data']['password'], '')
        self.assertEqual(mocked_save.call_args.kwargs['credential_data']['storage_state_name'], 'guest-shop-1.json')


if __name__ == '__main__':
    unittest.main()





