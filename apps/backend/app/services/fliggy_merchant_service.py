from __future__ import annotations

import json
import logging
import os
import re
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.competitor_service import save_room_prices
from app.services.merchant_connection_service import (
    get_merchant_credential,
    record_merchant_login_result,
    save_merchant_credential,
)
from app.services.merchant_pricing_audit_service import create_merchant_pricing_audit
from app.services.merchant_price_history_service import save_merchant_price_history
from app.services.merchant_price_mapping_service import list_merchant_price_mappings
from app.services.room_status_service import save_room_status
from app.services.shop_service import get_room_status_defaults, get_shop_config

_BROWSERS_DIR = str(Path(__file__).resolve().parents[2] / '.browsers')
if Path(_BROWSERS_DIR).is_dir():
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', _BROWSERS_DIR)

_PRICE_PATTERN = re.compile(r'(\d+(?:\.\d{1,2})?)')
_INT_PATTERN = re.compile(r'(\d+)')
_RATE_NAME_KEYWORDS = ('标准价', '无早餐', '份早餐', '门市价', '协议价', '促销价')
_BREAKFAST_COUNT_PATTERN = re.compile(r'^早餐\d+$')
_LOGIN_PAGE_HINTS = (
    '账号登录',
    '邮箱/登录名',
    '验证码',
    '请输入验证码',
    '忘记密码',
    '密码登录',
    '短信登录',
    '扫码登录',
    '手机扫码登录',
    '忘记账号',
    '免费注册',
    '淘宝APP',
    '登录页面',
)
_LOGGED_OUT_HINTS = ('您已经退出登录', '用户信息查询失败')
_SESSION_LOGIN_REQUIRED_ERRORS = {
    'merchant session not found, login first',
    'merchant session expired, login required',
}
_ROOM_TYPE_HINTS = ('大床', '双床', '床', '套房', '亲子', '影音', '豪华', '商务', '标准')
_ROOM_NAME_BLACKLIST = {
    'CNY',
    'MENU',
    '平台结算',
    '筛选房型',
    '日期选择',
    '日历展示',
    '向后查询',
    '展开全部房型',
    '批量修改房价',
    '今天',
    '知道了',
    '切换企业',
    '查看其它协议信息',
}
_WEEKDAY_PATTERN = re.compile(r'^周[一二三四五六日天]$')
_HWHT_DEFAULT_LOGIN_URL = 'https://ebooking.hwht.com/'
_HWHT_DEFAULT_PRICE_URL = 'https://ebooking.hwht.com/price/manage'
_MERCHANT_COLLECT_MODE_PREFER_CDP = 'prefer_cdp'
_MERCHANT_COLLECT_MODE_STORAGE_STATE = 'storage_state'
_MERCHANT_COLLECT_MODE_CDP_CURRENT_PAGE = 'cdp_current_page'
_MERCHANT_CDP_DEFAULT_DEBUG_URL = 'http://127.0.0.1:9222'
_LOGGER = logging.getLogger(__name__)
_HWHT_EXPAND_ROOM_SELECTORS = (
    "label:has-text('展开全部房型')",
    "text=展开全部房型",
    ".aui-checkbox:has-text('展开全部房型')",
)

DEFAULT_SELECTOR_MAP = {
    'username': ["input[name='username']", "input[type='text']", "input[placeholder*='账号']", "input[placeholder*='用户名']"],
    'password': ["input[type='password']", "input[name='password']", "input[placeholder*='密码']"],
    'submit': ["button[type='submit']", "button:has-text('登录')", "button:has-text('立即登录')", 'text=登录'],
    'success': ['text=酒店管理', 'text=商品管理', 'text=房态', 'text=价格管理', 'text=房价管理', "[data-testid='merchant-home']"],
    'current_price': ["[data-testid='current-price']", '.current-price', '.price', "[class*='price']"],
    'room_rows': ['.rate-plan-item', 'table tbody tr', '.room-row', '.rate-plan-row', '.price-row'],
    'room_name': ['.room-name', '.name', 'td:nth-child(1)'],
    'room_price': ['.room-price', '.price', 'td:nth-child(2)'],
    'room_stock': ['.room-stock', '.stock', 'td:nth-child(3)'],
}

HWHT_SELECTOR_MAP = {
    'username': [
        ".aui-form-item:has(label:has-text('邮箱/登录名')) input.aui-input__inner",
        ".aui-form-item input.aui-input__inner[type='input']",
    ],
    'password': [
        ".aui-form-item:has(label:has-text('密码')) input.aui-input__inner[type='password']",
        ".aui-form-item input.aui-input__inner[type='password']",
    ],
    'submit': ["button.aui-button--primary:has-text('登录')"],
    'success': ['text=价格管理', 'text=房价管理', 'text=价格日历', 'text=库存管理'],
    'room_rows': [
        '.rate-plan-item',
        "tr:has-text('标准价')",
        "[role='row']:has-text('标准价')",
        ".ant-table-row:has-text('标准价')",
        ".el-table__row:has-text('标准价')",
        ".aui-table tr:has-text('标准价')",
        ".table tr:has-text('标准价')",
        "[class*='row']:has-text('标准价')",
    ],
    'room_name': ['td:nth-child(1)', '.name', "[class*='name']"],
    'room_price': ['td:last-child', 'td:nth-child(2)', '.price', "[class*='price']"],
    'room_stock': ['td:nth-child(3)', '.stock', "[class*='stock']"],
}


def _state_dir() -> Path:
    path = Path(__file__).resolve().parents[2] / '.playwright' / 'merchant_states'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_storage_state_payload(path: Path) -> dict:
    try:
        content = path.read_text(encoding='utf-8')
    except OSError:
        return {}
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _storage_state_has_session_data(payload: dict | None) -> bool:
    normalized = payload if isinstance(payload, dict) else {}
    cookies = normalized.get('cookies') if isinstance(normalized.get('cookies'), list) else []
    origins = normalized.get('origins') if isinstance(normalized.get('origins'), list) else []
    return bool(cookies or origins)


def _resolve_usable_merchant_state(
    *,
    requested_name: str,
    shop_id: int,
    state_dir: Path | None = None,
) -> tuple[Path, str]:
    resolved_state_dir = state_dir or _state_dir()
    requested_path = resolved_state_dir / requested_name
    legacy_name = _safe_storage_name('', shop_id=shop_id)
    candidates: list[Path] = [requested_path]
    if legacy_name != requested_name:
        candidates.append(resolved_state_dir / legacy_name)

    existing_candidates = [candidate for candidate in candidates if candidate.exists()]
    for candidate in existing_candidates:
        if _storage_state_has_session_data(_load_storage_state_payload(candidate)):
            return candidate, candidate.name

    if existing_candidates:
        raise RuntimeError('merchant session invalid, login required')
    raise RuntimeError('merchant session not found, login first')


def _safe_storage_name(raw_name: str | None, *, shop_id: int) -> str:
    value = str(raw_name or '').strip() or f'shop-{shop_id}.json'
    value = re.sub(r'[^a-zA-Z0-9._-]+', '-', value)
    if not value.endswith('.json'):
        value += '.json'
    return value


def _normalize_merchant_collect_mode(raw_mode: str | None) -> str:
    normalized = str(raw_mode or '').strip().lower() or _MERCHANT_COLLECT_MODE_PREFER_CDP
    if normalized not in {
        _MERCHANT_COLLECT_MODE_PREFER_CDP,
        _MERCHANT_COLLECT_MODE_STORAGE_STATE,
        _MERCHANT_COLLECT_MODE_CDP_CURRENT_PAGE,
    }:
        raise ValueError(f'unsupported collect_mode: {raw_mode}')
    return normalized


def _iter_browser_pages(browser) -> list:
    contexts = getattr(browser, 'contexts', [])
    if callable(contexts):
        contexts = contexts()
    pages: list = []
    for context in contexts or []:
        context_pages = getattr(context, 'pages', [])
        if callable(context_pages):
            context_pages = context_pages()
        for page in context_pages or []:
            pages.append(page)
    return pages


def _is_active_browser_page(page) -> bool:
    try:
        return str(page.evaluate("() => document.visibilityState") or '').lower() == 'visible'
    except Exception:
        return False


def _looks_like_merchant_price_url(current_url: str | None, price_url: str) -> bool:
    current_value = str(current_url or '').strip()
    target_value = str(price_url or '').strip()
    if not current_value.startswith(('http://', 'https://')) or not target_value.startswith(('http://', 'https://')):
        return False
    current_parsed = urlparse(current_value)
    target_parsed = urlparse(target_value)
    if current_parsed.netloc.lower() != target_parsed.netloc.lower():
        return False
    target_path = target_parsed.path.rstrip('/').lower()
    current_path = current_parsed.path.rstrip('/').lower()
    if target_path and target_path != '/':
        return current_path.startswith(target_path)
    return True


def _looks_like_login_url(current_url: str | None, login_url: str) -> bool:
    current_value = str(current_url or '').strip()
    login_value = str(login_url or '').strip()
    if not current_value.startswith(('http://', 'https://')):
        return False
    if login_value.startswith(('http://', 'https://')) and current_value.rstrip('/') == login_value.rstrip('/'):
        return True

    parsed = urlparse(current_value)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    return (
        host.startswith('login.')
        or host.startswith('passport.')
        or '/login' in path
        or '/signin' in path
        or '/passport' in path
        or '/havanaone/login' in path
    )


def _pick_merchant_cdp_target_page(browser, *, price_url: str):
    direct_matches: list = []
    host_matches: list = []
    target_host = urlparse(price_url).netloc.lower()
    for page in _iter_browser_pages(browser):
        current_url = str(getattr(page, 'url', '') or '').strip()
        if not current_url.startswith(('http://', 'https://')):
            continue
        if _looks_like_merchant_price_url(current_url, price_url):
            direct_matches.append(page)
            continue
        if urlparse(current_url).netloc.lower() == target_host:
            host_matches.append(page)

    matches = direct_matches or host_matches
    if not matches:
        raise RuntimeError('no merchant price page found in chrome debug session')

    for page in matches:
        if _is_active_browser_page(page):
            return page
    return matches[0]


def _selector_seed(*, login_url: str = '', price_url: str = '') -> dict[str, list[str]]:
    merged = deepcopy(DEFAULT_SELECTOR_MAP)
    url_text = f'{login_url} {price_url}'.lower()
    if 'ebooking.hwht.com' in url_text:
        for key, values in HWHT_SELECTOR_MAP.items():
            merged[key] = [*values, *merged.get(key, [])]
    return merged


def _resolve_default_urls(*, login_url: str | None = None, price_url: str | None = None) -> dict[str, str]:
    resolved_login_url = str(login_url or '').strip()
    resolved_price_url = str(price_url or '').strip()
    combined = f'{resolved_login_url} {resolved_price_url}'.lower()
    should_use_hwht_defaults = (not resolved_login_url and not resolved_price_url) or ('ebooking.hwht.com' in combined)
    if should_use_hwht_defaults:
        return {
            'login_url': resolved_login_url or _HWHT_DEFAULT_LOGIN_URL,
            'price_url': resolved_price_url or _HWHT_DEFAULT_PRICE_URL,
        }
    return {'login_url': resolved_login_url, 'price_url': resolved_price_url}


def _normalize_selector_map(raw_value: dict | str | None, *, login_url: str = '', price_url: str = '') -> dict[str, list[str]]:
    merged = _selector_seed(login_url=login_url, price_url=price_url)
    if raw_value in (None, '', {}):
        return merged
    payload = raw_value if not isinstance(raw_value, str) else json.loads(raw_value)
    if not isinstance(payload, dict):
        return merged
    for key, value in payload.items():
        if isinstance(value, str):
            candidates = [value.strip()] if value.strip() else []
        elif isinstance(value, list):
            candidates = [str(item).strip() for item in value if str(item).strip()]
        else:
            continue
        if candidates:
            merged[str(key)] = candidates
    return merged


def _extract_price(text: str | None) -> float | None:
    if not text:
        return None
    matches = _PRICE_PATTERN.findall(str(text).replace(',', ''))
    if not matches:
        return None
    try:
        return round(float(matches[-1]), 2)
    except ValueError:
        return None


def _extract_int(text: str | None) -> int | None:
    if not text:
        return None
    matches = _INT_PATTERN.findall(str(text))
    if not matches:
        return None
    return int(matches[-1])


def _clean_text(text: str | None) -> str:
    value = str(text or '').replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', value).strip()


def _extract_session_username_from_browser_state(storage_payload: dict | None, cookies: list[dict] | None = None) -> tuple[str, str]:
    payload = storage_payload if isinstance(storage_payload, dict) else {}
    login_person = payload.get('login_person_info') if isinstance(payload.get('login_person_info'), dict) else {}
    hotel_supplier = login_person.get('hotelSupplier') if isinstance(login_person.get('hotelSupplier'), dict) else {}
    candidates = [
        ('local_storage.current_account', payload.get('CURRENT_ACCOUNT')),
        ('local_storage.login_person_email', login_person.get('email')),
        ('local_storage.login_person_account', login_person.get('account')),
        ('local_storage.hotel_supplier_account', hotel_supplier.get('account')),
    ]
    for source, raw_value in candidates:
        value = _clean_text(raw_value)
        if value:
            return value, source

    for cookie in cookies or []:
        if str(cookie.get('name') or '').strip() != 'memberLoginKey':
            continue
        value = _clean_text(cookie.get('value'))
        if value:
            return value, 'cookie.memberLoginKey'
    return '', ''


def _is_rate_name(text: str) -> bool:
    value = _clean_text(text)
    if not value:
        return False
    if _BREAKFAST_COUNT_PATTERN.fullmatch(value):
        return False
    return any(keyword in value for keyword in _RATE_NAME_KEYWORDS)


def _looks_like_room_name(text: str) -> bool:
    value = _clean_text(text)
    if not value or _is_rate_name(value):
        return False
    if value in _ROOM_NAME_BLACKLIST or _WEEKDAY_PATTERN.fullmatch(value):
        return False
    if value in _ROOM_TYPE_HINTS:
        return False
    if value.isdigit() and len(value) <= 4:
        return False
    return ('（' in value) or ('(' in value) or any(hint in value for hint in _ROOM_TYPE_HINTS)

def _extract_reasonable_price(text: str | None) -> float | None:
    if not text:
        return None
    raw_matches = _PRICE_PATTERN.findall(str(text).replace(',', ''))
    if not raw_matches:
        return None

    candidates: list[float] = []
    for raw_match in raw_matches:
        if raw_match.isdigit() and len(raw_match) >= 7:
            continue
        try:
            candidates.append(round(float(raw_match), 2))
        except ValueError:
            continue

    if not candidates:
        return None

    larger_candidates = [candidate for candidate in candidates if candidate > 31]
    if larger_candidates:
        return min(larger_candidates)
    return candidates[-1]


def _extract_effective_price(lines: list[str]) -> float | None:
    candidates: list[tuple[str, float]] = []
    for line in lines:
        value = _clean_text(line)
        if not value or _is_rate_name(value) or _BREAKFAST_COUNT_PATTERN.fullmatch(value):
            continue
        if value in _ROOM_NAME_BLACKLIST:
            continue
        if value.isdigit() and len(value) >= 7:
            continue
        price = _extract_reasonable_price(value)
        if price is None:
            continue
        candidates.append((value, price))
    for raw_value, price in candidates:
        if raw_value.isdigit() and int(raw_value) <= 31:
            has_larger_price = any(candidate_price > 31 for _, candidate_price in candidates)
            if has_larger_price:
                continue
        return price
    return None


def _normalize_rate_name(text: str) -> str:
    value = _clean_text(text)
    value = re.sub(r'\s+\d{7,}.*$', '', value)
    value = re.sub(r'(?:\u00a5|CNY)?\s*\d+(?:\.\d{1,2})?$', '', value).strip(' -:')
    return value


def _extract_price_override(text: str | None) -> float | None:
    lines = [_clean_text(line) for line in str(text or '').splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return None

    if len(lines) == 1:
        value = lines[0]
        if _is_rate_name(value) or _BREAKFAST_COUNT_PATTERN.fullmatch(value):
            return None
        if any(keyword in value for keyword in ('\u4f59\u623f', '\u53ef\u552e', '\u5e93\u5b58')):
            return None

    return _extract_effective_price(lines)

def _has_any_selector(locator_owner, selectors: list[str]) -> bool:
    for selector in selectors:
        try:
            if locator_owner.locator(selector).first.count() > 0:
                return True
        except Exception:
            continue
    return False


def _first_text(locator_owner, selectors: list[str]) -> str:
    for selector in selectors:
        try:
            locator = locator_owner.locator(selector).first
            if locator.count() > 0:
                text_value = locator.inner_text(timeout=1500).strip()
                if text_value:
                    return text_value
        except Exception:
            continue
    return ''


def _fill_first(page, selectors: list[str], value: str) -> bool:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0:
                locator.fill(value, timeout=2000)
                return True
        except Exception:
            continue
    return False


def _click_first(page, selectors: list[str]) -> bool:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0:
                locator.click(timeout=2000)
                return True
        except Exception:
            continue
    return False


def _wait_for_any_selector(page, selectors: list[str], *, timeout_ms: int = 5000, poll_ms: int = 250) -> bool:
    deadline = time.monotonic() + max(timeout_ms, 0) / 1000
    while True:
        if _has_any_selector(page, selectors):
            return True
        if time.monotonic() >= deadline:
            return False
        try:
            page.wait_for_timeout(poll_ms)
        except Exception:
            return False

def _looks_like_login_page(page, selectors: dict[str, list[str]]) -> bool:
    return _has_any_selector(page, selectors['username']) and _has_any_selector(page, selectors['password'])


def _get_body_text(page) -> str:
    try:
        return _clean_text(page.locator('body').inner_text(timeout=1500))
    except Exception:
        return ''


def _evaluate_authenticated_page(
    page,
    *,
    selectors: dict[str, list[str]],
    login_url: str,
    price_url: str,
    success_reason: str,
    price_reason: str,
    url_reason: str,
) -> tuple[bool, str]:
    if _has_any_selector(page, selectors['success']):
        return True, success_reason
    if _has_any_selector(page, selectors['room_rows']) or _has_any_selector(page, selectors['current_price']):
        return True, price_reason
    body_text = _get_body_text(page)
    if any(hint in body_text for hint in _LOGGED_OUT_HINTS):
        return False, 'redirected-to-login'
    if any(hint in body_text for hint in _LOGIN_PAGE_HINTS):
        return False, 'redirected-to-login'
    if _looks_like_login_url(getattr(page, 'url', ''), login_url):
        return False, 'redirected-to-login'
    if page.url.rstrip('/') == price_url.rstrip('/') and not _looks_like_login_page(page, selectors):
        return True, url_reason
    if page.url.rstrip('/') == login_url.rstrip('/') or _looks_like_login_page(page, selectors):
        return False, 'redirected-to-login'
    return False, 'validation-page-unrecognized'


def _probe_authenticated_context(
    context,
    *,
    current_page,
    selectors: dict[str, list[str]],
    login_url: str,
    price_url: str,
    timeout_ms: int,
    wait_ms: int,
) -> tuple[bool, str]:
    authenticated, reason = _evaluate_authenticated_page(
        current_page,
        selectors=selectors,
        login_url=login_url,
        price_url=price_url,
        success_reason='success-selector',
        price_reason='current-price-page',
        url_reason='current-url',
    )
    if authenticated:
        return authenticated, reason

    if not price_url.startswith(('http://', 'https://')):
        return False, 'missing-validation-url'

    probe_page = context.new_page()
    try:
        probe_page.goto(price_url, wait_until='domcontentloaded', timeout=timeout_ms)
        try:
            probe_page.wait_for_timeout(wait_ms)
        except Exception:
            pass
        return _evaluate_authenticated_page(
            probe_page,
            selectors=selectors,
            login_url=login_url,
            price_url=price_url,
            success_reason='validation-success-selector',
            price_reason='validation-price-page',
            url_reason='validation-url',
        )
    finally:
        try:
            probe_page.close()
        except Exception:
            pass

def _wait_for_manual_authentication(
    context,
    *,
    current_page,
    selectors: dict[str, list[str]],
    login_url: str,
    price_url: str,
    timeout_ms: int,
    wait_ms: int,
    poll_ms: int = 1500,
) -> tuple[bool, str]:
    deadline = time.monotonic() + max(timeout_ms, 0) / 1000
    last_reason = 'manual-login-timeout'
    while True:
        authenticated, reason = _evaluate_authenticated_page(
            current_page,
            selectors=selectors,
            login_url=login_url,
            price_url=price_url,
            success_reason='manual-success-selector',
            price_reason='manual-price-page',
            url_reason='manual-url',
        )
        if authenticated:
            return True, reason
        last_reason = reason
        if time.monotonic() >= deadline:
            return False, last_reason
        remaining_ms = max(200, int((deadline - time.monotonic()) * 1000))
        try:
            current_page.wait_for_timeout(min(max(poll_ms, 200), remaining_ms))
        except Exception:
            pass

def _read_session_identity(context, *, price_url: str, timeout_ms: int, wait_ms: int) -> dict:
    probe_page = context.new_page()
    try:
        if price_url.startswith(('http://', 'https://')):
            probe_page.goto(price_url, wait_until='domcontentloaded', timeout=timeout_ms)
            try:
                probe_page.wait_for_timeout(wait_ms)
                probe_page.wait_for_load_state('networkidle', timeout=min(timeout_ms, 5000))
            except Exception:
                pass
        storage_payload = probe_page.evaluate(
            """
            () => {
              try {
                const raw = localStorage.getItem('itravel_ebooking');
                if (!raw) return {};
                const parsed = JSON.parse(raw);
                return parsed && typeof parsed === 'object' ? parsed : {};
              } catch (error) {
                return {};
              }
            }
            """
        )
        cookie_targets = [price_url] if price_url.startswith(('http://', 'https://')) else None
        cookies = context.cookies(cookie_targets) if cookie_targets else context.cookies()
        session_username, identity_source = _extract_session_username_from_browser_state(storage_payload, cookies)
        login_person = storage_payload.get('login_person_info') if isinstance(storage_payload, dict) and isinstance(storage_payload.get('login_person_info'), dict) else {}
        hotel_supplier = login_person.get('hotelSupplier') if isinstance(login_person.get('hotelSupplier'), dict) else {}
        return {
            'session_username': session_username,
            'identity_source': identity_source,
            'hotel_name': _clean_text(hotel_supplier.get('hotelName') or login_person.get('name')),
        }
    except Exception:
        return {
            'session_username': '',
            'identity_source': '',
            'hotel_name': '',
        }
    finally:
        try:
            probe_page.close()
        except Exception:
            pass


def _parse_rate_item_text(text: str, *, fallback_name: str = '', fallback_stock: int | None = None) -> dict | None:
    lines = [_clean_text(line) for line in str(text or '').splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return None

    rate_name = ''
    room_name = _clean_text(fallback_name)
    price = _extract_effective_price(lines)
    available_rooms = fallback_stock

    for line in lines:
        if _is_rate_name(line) and not rate_name:
            rate_name = _normalize_rate_name(line)
            continue
        if available_rooms is None and any(keyword in line for keyword in ('余房', '可售', '库存', '间')):
            available_rooms = _extract_int(line)
        if not room_name and _looks_like_room_name(line):
            room_name = line

    if room_name.isdigit() and len(room_name) <= 4:
        room_name = ''
    if price is None or (not room_name and not rate_name):
        return None

    display_name = rate_name or room_name or f'未命名价型-{price:.2f}'
    return {
        'room_type': room_name,
        'room_name': room_name,
        'rate_name': rate_name,
        'display_name': display_name,
        'price': price,
        'available_rooms': available_rooms,
        'breakfast': None,
        'cancelable': None,
        'raw_text': _clean_text(' | '.join(lines)),
    }

def _dedupe_price_items(items: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[tuple[str, str, float]] = set()
    for item in items:
        key = (
            _clean_text(item.get('room_name')),
            _clean_text(item.get('rate_name') or item.get('display_name')),
            round(float(item.get('price') or 0), 2),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _collect_rate_items_from_text(body_text: str) -> list[dict]:
    lines = [_clean_text(line) for line in str(body_text or '').splitlines()]
    lines = [line for line in lines if line]
    items: list[dict] = []
    current_room_name = ''
    index = 0
    while index < len(lines):
        line = lines[index]
        if _looks_like_room_name(line):
            current_room_name = line
            index += 1
            continue
        if not _is_rate_name(line):
            index += 1
            continue
        collected = [line]
        price = _extract_effective_price(collected)
        next_index = index + 1
        while price is None and next_index < min(len(lines), index + 8):
            candidate = lines[next_index]
            if next_index > index + 1 and _is_rate_name(candidate):
                break
            collected.append(candidate)
            price = _extract_effective_price(collected)
            next_index += 1
        if price is None:
            index += 1
            continue
        item = _parse_rate_item_text('\n'.join(collected), fallback_name=current_room_name)
        if item is not None:
            items.append(item)
        index = next_index
    return _dedupe_price_items(items)


def _collect_room_rows(page, selectors: dict[str, list[str]]) -> list[dict]:
    rows: list[dict] = []
    for row_selector in selectors['room_rows']:
        try:
            locators = page.locator(row_selector)
            count = min(locators.count(), 80)
        except Exception:
            count = 0
        if count == 0:
            continue
        for index in range(count):
            row = locators.nth(index)
            raw_text = ''
            try:
                raw_text = row.inner_text(timeout=1000).strip()
            except Exception:
                pass
            parsed = _parse_rate_item_text(
                raw_text,
                fallback_name=_first_text(row, selectors['room_name']) or f'房型{index + 1}',
                fallback_stock=_extract_int(_first_text(row, selectors['room_stock'])),
            )
            if parsed is None:
                continue
            row_price_text = _first_text(row, selectors['room_price'])
            row_price = _extract_price_override(row_price_text)
            if row_price is not None:
                parsed['price'] = row_price
            rows.append(parsed)
        if rows:
            break
    return _dedupe_price_items(rows)


def _collect_price_items(page, selectors: dict[str, list[str]]) -> list[dict]:
    dom_items = _collect_room_rows(page, selectors)
    body_text = ''
    try:
        body_text = page.locator('body').inner_text(timeout=3000)
    except Exception:
        body_text = ''
    text_items = _collect_rate_items_from_text(body_text)
    if not dom_items:
        return text_items
    return _dedupe_price_items([*dom_items, *text_items])


def _persist_price_capture(db: Session, *, shop_id: int, shop_name: str, price_url: str, current_price: float | None, rooms: list[dict], source: str) -> dict:
    defaults = get_room_status_defaults(db=db, shop_id=shop_id)
    snapshot_price = current_price if current_price is not None else float(defaults['current_price'])
    available_rooms = int(defaults['available_rooms'])
    room_candidates = [item.get('available_rooms') for item in rooms if item.get('available_rooms') is not None]
    if room_candidates:
        available_rooms = max(0, sum(int(item or 0) for item in room_candidates))
    save_room_status(
        db,
        shop_id=shop_id,
        total_rooms=int(defaults['total_rooms']),
        available_rooms=available_rooms,
        current_price=float(snapshot_price),
        source=source,
    )
    saved_count = 0
    if rooms:
        saved_count = int(save_room_prices(db=db, shop_id=shop_id, crawl_results=[{
            'hotel_name': shop_name,
            'hotel_url': price_url,
            'collected_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'rooms': rooms,
        }]) or 0)
    return {'snapshot_saved': True, 'saved_count': saved_count, 'available_rooms': available_rooms}


def _try_record_login_result(db: Session, *, shop_id: int, status: str, message: str) -> None:
    try:
        record_merchant_login_result(db=db, shop_id=shop_id, status=status, message=message)
    except Exception:
        return None


def _resolve_connection_context(db: Session, *, shop_id: int) -> dict:
    shop_config = get_shop_config(db=db, shop_id=shop_id)
    credential = get_merchant_credential(db=db, shop_id=shop_id)
    selectors_override = credential.get('selectors') if credential.get('has_selectors') else None
    resolved_urls = _resolve_default_urls(
        login_url=credential.get('login_url') or shop_config.fliggy_merchant_login_url,
        price_url=credential.get('price_url') or shop_config.fliggy_merchant_price_url,
    )
    return {
        'shop_name': str(shop_config.name or '').strip(),
        'tenant_id': int(credential.get('tenant_id') or 1),
        'credential': credential,
        'login_url': resolved_urls['login_url'],
        'price_url': resolved_urls['price_url'],
        'storage_state_name': str(credential.get('storage_state_name') or shop_config.fliggy_merchant_storage_state or '').strip(),
        'selectors': selectors_override or shop_config.fliggy_merchant_price_selectors_json,
    }


def _release_db_connection(db: Session) -> None:
    try:
        db.rollback()
    except Exception:
        return None


def _scan_price_items_from_page(page, *, selector_map: dict[str, list[str]]) -> tuple[float | None, list[dict]]:
    current_price_text = _first_text(page, selector_map['current_price'])
    current_price = _extract_price(current_price_text)
    items = _collect_price_items(page, selector_map)
    if current_price is None and items:
        current_price = min(float(item.get('price') or 0) for item in items if item.get('price') is not None)
    return current_price, items


def _try_expand_hwht_room_rows(page) -> bool:
    for selector in _HWHT_EXPAND_ROOM_SELECTORS:
        try:
            locator = page.locator(selector).first
            if locator.count() == 0:
                continue
            locator.click(timeout=1500, force=True)
            try:
                page.wait_for_timeout(400)
            except Exception:
                pass
            return True
        except Exception:
            continue
    return False


def _extract_price_items_from_page(
    page,
    *,
    selector_map: dict[str, list[str]],
    content_wait_ms: int = 0,
    poll_ms: int = 250,
) -> tuple[float | None, list[dict]]:
    current_price, items = _scan_price_items_from_page(page, selector_map=selector_map)
    if items or content_wait_ms <= 0:
        return current_price, items
    expanded = _try_expand_hwht_room_rows(page)
    if expanded:
        current_price, items = _scan_price_items_from_page(page, selector_map=selector_map)
        if items:
            return current_price, items

    deadline = time.monotonic() + max(content_wait_ms, 0) / 1000
    while True:
        if time.monotonic() >= deadline:
            return current_price, items
        remaining_ms = max(100, int((deadline - time.monotonic()) * 1000))
        try:
            page.wait_for_timeout(min(max(poll_ms, 100), remaining_ms))
        except Exception:
            return current_price, items
        current_price, items = _scan_price_items_from_page(page, selector_map=selector_map)
        if items:
            return current_price, items


def _collect_merchant_page_via_cdp(
    *,
    shop_id: int,
    shop_name: str,
    resolved_login_url: str,
    resolved_price_url: str,
    selector_map: dict[str, list[str]],
    debug_url: str,
) -> tuple[dict, list[dict], float | None, str]:
    settings = get_settings()
    timeout_ms = max(5000, int(settings.fliggy_playwright_timeout_sec) * 1000)
    wait_ms = max(500, int(settings.fliggy_playwright_wait_after_load_ms))
    content_wait_ms = min(timeout_ms, max(wait_ms * 3, 4000))
    resolved_debug_url = str(debug_url or '').strip() or _MERCHANT_CDP_DEFAULT_DEBUG_URL

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover
        raise RuntimeError('playwright not installed. run: py -3 -m pip install playwright') from exc

    matched_page_url = ''
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.connect_over_cdp(resolved_debug_url)
        except Exception as exc:
            raise RuntimeError(f'failed to connect chromium debug url: {resolved_debug_url}') from exc

        page = _pick_merchant_cdp_target_page(browser, price_url=resolved_price_url)
        matched_page_url = str(getattr(page, 'url', '') or '').strip()
        page_context = getattr(page, 'context', None)
        if callable(page_context):
            page_context = page_context()
        if page_context is None:
            raise RuntimeError('connected browser page missing context')

        capture_page = page
        created_capture_page = False
        try:
            try:
                page.wait_for_timeout(wait_ms)
                page.wait_for_load_state('domcontentloaded', timeout=min(timeout_ms, 8000))
            except Exception:
                pass

            if not _looks_like_merchant_price_url(getattr(page, 'url', ''), resolved_price_url):
                capture_page = page_context.new_page()
                created_capture_page = True
                capture_page.goto(resolved_price_url, wait_until='domcontentloaded', timeout=timeout_ms)
                try:
                    capture_page.wait_for_timeout(wait_ms)
                    capture_page.wait_for_load_state('networkidle', timeout=min(timeout_ms, 5000))
                except PlaywrightTimeoutError:
                    pass

            authenticated, reason = _probe_authenticated_context(
                page_context,
                current_page=capture_page,
                selectors=selector_map,
                login_url=resolved_login_url,
                price_url=resolved_price_url,
                timeout_ms=timeout_ms,
                wait_ms=wait_ms,
            )
            if not authenticated:
                if reason == 'redirected-to-login':
                    raise RuntimeError('merchant session expired, login required')
                raise RuntimeError(f'merchant price page not ready: {reason}')

            authenticated, reason = _evaluate_authenticated_page(
                capture_page,
                selectors=selector_map,
                login_url=resolved_login_url,
                price_url=resolved_price_url,
                success_reason='price-page-success-selector',
                price_reason='price-page-rows',
                url_reason='price-page-url',
            )
            if not authenticated:
                if reason == 'redirected-to-login':
                    raise RuntimeError('merchant session expired, login required')
                raise RuntimeError(f'merchant price page not ready: {reason}')
            current_price, items = _extract_price_items_from_page(
                capture_page,
                selector_map=selector_map,
                content_wait_ms=content_wait_ms,
            )
        finally:
            if created_capture_page:
                try:
                    capture_page.close()
                except Exception:
                    pass

    base_result = {
        'shop_id': shop_id,
        'status': 'success',
        'source': 'fliggy_merchant',
        'shop_name': shop_name,
        'price_url': resolved_price_url,
        'current_price': current_price,
        'room_count': len(items),
        'rooms': items,
        'collected_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'debug_url': resolved_debug_url,
        'matched_page_url': matched_page_url,
    }
    return base_result, items, current_price, resolved_price_url


def _collect_merchant_page_with_storage_state(
    *,
    shop_id: int,
    shop_name: str,
    resolved_login_url: str,
    resolved_price_url: str,
    selector_map: dict[str, list[str]],
    state_path: Path,
    state_name: str,
    headless: bool,
) -> tuple[dict, list[dict], float | None, str]:
    settings = get_settings()
    timeout_ms = max(5000, int(settings.fliggy_playwright_timeout_sec) * 1000)
    wait_ms = max(500, int(settings.fliggy_playwright_wait_after_load_ms))
    content_wait_ms = min(timeout_ms, max(wait_ms * 3, 4000))

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover
        raise RuntimeError('playwright not installed. run: py -3 -m pip install playwright') from exc

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=headless)
        except Exception as exc:  # pragma: no cover
            raise RuntimeError('failed to launch chromium. run: py -3 -m playwright install chromium') from exc
        context = browser.new_context(storage_state=str(state_path), user_agent=settings.competitor_crawl_user_agent)
        page = context.new_page()
        try:
            page.goto(resolved_price_url, wait_until='domcontentloaded', timeout=timeout_ms)
            try:
                page.wait_for_timeout(wait_ms)
                page.wait_for_load_state('networkidle', timeout=min(timeout_ms, 5000))
            except PlaywrightTimeoutError:
                pass
            authenticated, reason = _evaluate_authenticated_page(
                page,
                selectors=selector_map,
                login_url=resolved_login_url,
                price_url=resolved_price_url,
                success_reason='price-page-success-selector',
                price_reason='price-page-rows',
                url_reason='price-page-url',
            )
            if not authenticated:
                if reason == 'redirected-to-login':
                    raise RuntimeError('merchant session expired, login required')
                raise RuntimeError(f'merchant price page not ready: {reason}')
            current_price, items = _extract_price_items_from_page(
                page,
                selector_map=selector_map,
                content_wait_ms=content_wait_ms,
            )
        finally:
            browser.close()

    base_result = {
        'shop_id': shop_id,
        'status': 'success',
        'source': 'fliggy_merchant',
        'shop_name': shop_name,
        'price_url': resolved_price_url,
        'storage_state_used': state_name,
        'current_price': current_price,
        'room_count': len(items),
        'rooms': items,
        'collected_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    return base_result, items, current_price, resolved_price_url


def _collect_merchant_page(
    db: Session,
    *,
    shop_id: int,
    price_url: str | None = None,
    selectors: dict | str | None = None,
    headless: bool = True,
    collect_mode: str = _MERCHANT_COLLECT_MODE_PREFER_CDP,
    debug_url: str | None = None,
) -> tuple[dict, list[dict], float | None, str]:
    context_data = _resolve_connection_context(db=db, shop_id=shop_id)
    resolved_urls = _resolve_default_urls(
        login_url=context_data['login_url'],
        price_url=price_url or context_data['price_url'],
    )
    resolved_price_url = resolved_urls['price_url']
    if not resolved_price_url.startswith(('http://', 'https://')):
        raise ValueError('price_url is required and must start with http:// or https://')

    state_name = _safe_storage_name(context_data['storage_state_name'], shop_id=shop_id)
    selector_map = _normalize_selector_map(
        selectors or context_data['selectors'],
        login_url=str(context_data['login_url']),
        price_url=resolved_price_url,
    )
    _release_db_connection(db)
    resolved_collect_mode = _normalize_merchant_collect_mode(collect_mode)
    resolved_debug_url = str(debug_url or '').strip() or _MERCHANT_CDP_DEFAULT_DEBUG_URL

    if resolved_collect_mode == _MERCHANT_COLLECT_MODE_CDP_CURRENT_PAGE:
        result = _collect_merchant_page_via_cdp(
            shop_id=shop_id,
            shop_name=context_data['shop_name'],
            resolved_login_url=resolved_urls['login_url'],
            resolved_price_url=resolved_price_url,
            selector_map=selector_map,
            debug_url=resolved_debug_url,
        )
        base_result, items, current_price, result_price_url = result
        base_result['collect_mode'] = _MERCHANT_COLLECT_MODE_CDP_CURRENT_PAGE
        return base_result, items, current_price, result_price_url

    cdp_fallback_reason = ''
    if resolved_collect_mode == _MERCHANT_COLLECT_MODE_PREFER_CDP:
        try:
            result = _collect_merchant_page_via_cdp(
                shop_id=shop_id,
                shop_name=context_data['shop_name'],
                resolved_login_url=resolved_urls['login_url'],
                resolved_price_url=resolved_price_url,
                selector_map=selector_map,
                debug_url=resolved_debug_url,
            )
            base_result, items, current_price, result_price_url = result
            if not items:
                cdp_fallback_reason = 'cdp-returned-empty-items'
            else:
                base_result['collect_mode_requested'] = _MERCHANT_COLLECT_MODE_PREFER_CDP
                base_result['collect_mode'] = _MERCHANT_COLLECT_MODE_CDP_CURRENT_PAGE
                return base_result, items, current_price, result_price_url
        except RuntimeError as exc:
            cdp_fallback_reason = str(exc)

    state_path, state_name = _resolve_usable_merchant_state(requested_name=state_name, shop_id=shop_id)

    base_result, items, current_price, result_price_url = _collect_merchant_page_with_storage_state(
        shop_id=shop_id,
        shop_name=context_data['shop_name'],
        resolved_login_url=resolved_urls['login_url'],
        resolved_price_url=resolved_price_url,
        selector_map=selector_map,
        state_path=state_path,
        state_name=state_name,
        headless=headless,
    )
    base_result['collect_mode'] = _MERCHANT_COLLECT_MODE_STORAGE_STATE
    if resolved_collect_mode == _MERCHANT_COLLECT_MODE_PREFER_CDP:
        base_result['collect_mode_requested'] = _MERCHANT_COLLECT_MODE_PREFER_CDP
    if cdp_fallback_reason:
        base_result['cdp_fallback_reason'] = cdp_fallback_reason
    return base_result, items, current_price, result_price_url


def _find_mapping_for_item(item: dict, mappings: list[dict]) -> dict | None:
    room_name = _clean_text(item.get('room_name'))
    rate_name = _clean_text(item.get('rate_name') or item.get('display_name'))
    for mapping in mappings:
        mapping_room = _clean_text(mapping.get('room_name'))
        mapping_rate = _clean_text(mapping.get('rate_name'))
        if mapping_rate == rate_name and (not room_name or not mapping_room or mapping_room == room_name):
            return mapping
    for mapping in mappings:
        mapping_room = _clean_text(mapping.get('room_name'))
        if room_name and mapping_room == room_name and not _clean_text(mapping.get('rate_name')):
            return mapping
    return None


def _decorate_items_with_mapping(db: Session, *, shop_id: int, items: list[dict]) -> tuple[list[dict], dict]:
    mappings = list_merchant_price_mappings(db=db, shop_id=shop_id, platform='fliggy', only_enabled=False)
    mapped = 0
    partial = 0
    decorated: list[dict] = []
    for item in items:
        mapping = _find_mapping_for_item(item, mappings)
        mapping_status = 'unmapped'
        mapping_id = None
        gid = ''
        hid = ''
        is_mapped = False
        if mapping is not None:
            mapping_id = mapping.get('mapping_id')
            gid = str(mapping.get('gid') or '')
            hid = str(mapping.get('hid') or '')
            is_mapped = bool(mapping.get('is_complete'))
            if is_mapped:
                mapping_status = 'mapped'
                mapped += 1
            else:
                mapping_status = 'partial'
                partial += 1
        decorated.append({
            **item,
            'mapping_status': mapping_status,
            'mapping_id': mapping_id,
            'gid': gid,
            'hid': hid,
            'is_mapped': is_mapped,
        })
    summary = {
        'total': len(decorated),
        'mapped': mapped,
        'partial': partial,
        'unmapped': max(0, len(decorated) - mapped - partial),
    }
    return decorated, summary


def login_fliggy_merchant_session(
    db: Session,
    *,
    shop_id: int,
    username: str,
    password: str,
    login_url: str | None = None,
    storage_state_name: str | None = None,
    selectors: dict | str | None = None,
    headless: bool = True,
) -> dict:
    context_data = _resolve_connection_context(db=db, shop_id=shop_id)
    saved_credential = get_merchant_credential(db=db, shop_id=shop_id, include_secret=True)
    resolved_username = str(username or saved_credential.get('username') or '').strip()
    resolved_password = str(password or saved_credential.get('password') or '').strip()
    resolved_login_url = str(login_url or context_data['login_url'] or '').strip()
    resolved_price_url = str(context_data['price_url'] or '').strip()
    if not resolved_username or not resolved_password:
        raise ValueError('username/password required, or save merchant credentials first')
    if not resolved_login_url.startswith(('http://', 'https://')):
        raise ValueError('login_url is required and must start with http:// or https://')

    selector_map = _normalize_selector_map(
        selectors or context_data['selectors'],
        login_url=resolved_login_url,
        price_url=resolved_price_url,
    )
    state_name = _safe_storage_name(storage_state_name or context_data['storage_state_name'], shop_id=shop_id)
    state_path = _state_dir() / state_name
    _release_db_connection(db)
    settings = get_settings()
    timeout_ms = max(5000, int(settings.fliggy_playwright_timeout_sec) * 1000)
    wait_ms = max(500, int(settings.fliggy_playwright_wait_after_load_ms))

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover
        raise RuntimeError('playwright not installed. run: py -3 -m pip install playwright') from exc

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=headless)
        except Exception as exc:  # pragma: no cover
            raise RuntimeError('failed to launch chromium. run: py -3 -m playwright install chromium') from exc
        context = browser.new_context(user_agent=settings.competitor_crawl_user_agent)
        page = context.new_page()
        try:
            page.goto(resolved_login_url, wait_until='domcontentloaded', timeout=timeout_ms)
            _wait_for_any_selector(page, selector_map['username'], timeout_ms=min(timeout_ms, 8000))
            _wait_for_any_selector(page, selector_map['password'], timeout_ms=min(timeout_ms, 8000))
            _fill_first(page, selector_map['username'], resolved_username)
            _fill_first(page, selector_map['password'], resolved_password)
            _click_first(page, selector_map['submit'])
            try:
                page.wait_for_timeout(wait_ms)
                page.wait_for_load_state('networkidle', timeout=min(timeout_ms, 8000))
            except PlaywrightTimeoutError:
                pass

            authenticated, verified_by = _probe_authenticated_context(
                context,
                current_page=page,
                selectors=selector_map,
                login_url=resolved_login_url,
                price_url=resolved_price_url,
                timeout_ms=timeout_ms,
                wait_ms=wait_ms,
            )
            if not authenticated and not headless:
                authenticated, verified_by = _wait_for_manual_authentication(
                    context,
                    current_page=page,
                    selectors=selector_map,
                    login_url=resolved_login_url,
                    price_url=resolved_price_url,
                    timeout_ms=max(timeout_ms, 120000),
                    wait_ms=max(wait_ms, 1500),
                )
            if not authenticated:
                body_text = _get_body_text(page)
                if '请输入验证码' in body_text or '验证码' in body_text:
                    verified_by = '登录态已过期，且当前平台要求验证码，无法自动续登，请先到“商家连接”重新登录一次'
                _try_record_login_result(db=db, shop_id=shop_id, status='failed', message=verified_by)
                raise RuntimeError(str(verified_by))

            storage_payload = context.storage_state()
            if not _storage_state_has_session_data(storage_payload):
                _try_record_login_result(db=db, shop_id=shop_id, status='failed', message='empty-storage-state')
                raise RuntimeError('merchant login did not produce a usable session, please retry')
            state_path.write_text(json.dumps(storage_payload, ensure_ascii=False), encoding='utf-8')
            session_identity = _read_session_identity(
                context,
                price_url=resolved_price_url,
                timeout_ms=timeout_ms,
                wait_ms=wait_ms,
            )
        finally:
            browser.close()

    persisted_username = str(session_identity.get('session_username') or '').strip() or resolved_username
    save_merchant_credential(
        db=db,
        credential_data={
            'tenant_id': int(saved_credential.get('tenant_id') or 1),
            'shop_id': shop_id,
            'username': persisted_username,
            'password': resolved_password,
            'login_url': resolved_login_url,
            'price_url': resolved_price_url or context_data['price_url'],
            'storage_state_name': state_name,
            'selectors': selectors or context_data['selectors'],
        },
    )
    _try_record_login_result(db=db, shop_id=shop_id, status='success', message=verified_by)

    return {
        'shop_id': shop_id,
        'status': 'success',
        'login_url': resolved_login_url,
        'price_url': resolved_price_url,
        'storage_state_path': str(state_path),
        'storage_state_name': state_name,
        'session_saved': True,
        'headless': headless,
        'verified_by': verified_by,
        'session_username': persisted_username,
        'identity_source': str(session_identity.get('identity_source') or '').strip(),
        'hotel_name': str(session_identity.get('hotel_name') or '').strip(),
    }


def collect_fliggy_merchant_prices(
    db: Session,
    *,
    shop_id: int,
    price_url: str | None = None,
    selectors: dict | str | None = None,
    headless: bool = True,
    save_result: bool = True,
    collect_mode: str = _MERCHANT_COLLECT_MODE_PREFER_CDP,
    debug_url: str | None = None,
) -> dict:
    result, items, current_price, resolved_price_url = _collect_merchant_page(
        db=db,
        shop_id=shop_id,
        price_url=price_url,
        selectors=selectors,
        headless=headless,
        collect_mode=collect_mode,
        debug_url=debug_url,
    )
    if save_result:
        result.update(
            _persist_price_capture(
                db,
                shop_id=shop_id,
                shop_name=str(result['shop_name']),
                price_url=resolved_price_url,
                current_price=current_price,
                rooms=items,
                source='merchant',
            )
        )
    history_saved_count = save_merchant_price_history(
        db=db,
        shop_id=shop_id,
        items=items,
        source='merchant_collect',
        collected_at=result.get('collected_at'),
    )
    result['history_saved_count'] = history_saved_count
    return result


def preview_fliggy_merchant_prices(
    db: Session,
    *,
    shop_id: int,
    price_url: str | None = None,
    selectors: dict | str | None = None,
    headless: bool = True,
    collect_mode: str = _MERCHANT_COLLECT_MODE_PREFER_CDP,
    debug_url: str | None = None,
) -> dict:
    result, items, current_price, _ = _collect_merchant_page(
        db=db,
        shop_id=shop_id,
        price_url=price_url,
        selectors=selectors,
        headless=headless,
        collect_mode=collect_mode,
        debug_url=debug_url,
    )
    history_saved_count = save_merchant_price_history(
        db=db,
        shop_id=shop_id,
        items=items,
        source='merchant_preview',
        collected_at=result.get('collected_at'),
    )
    preview_items, mapping_summary = _decorate_items_with_mapping(db=db, shop_id=shop_id, items=items)
    storage_state_used = result.get('storage_state_used') or result.get('storage_state_name')
    audit = create_merchant_pricing_audit(
        db=db,
        shop_id=shop_id,
        stage='merchant_price_preview',
        audit_mode='preview',
        status='success',
        item_count=len(preview_items),
        payload={
            'price_url': result['price_url'],
            'storage_state_used': storage_state_used,
            'mapping_summary': mapping_summary,
            'source': 'fliggy_merchant_preview',
            'history_saved_count': history_saved_count,
        },
    )
    diagnostics = {
        'collect_mode': result.get('collect_mode'),
        'collect_mode_requested': result.get('collect_mode_requested'),
        'cdp_fallback_reason': result.get('cdp_fallback_reason'),
        'storage_state_used': storage_state_used,
        'matched_page_url': result.get('matched_page_url'),
        'debug_url': result.get('debug_url'),
    }
    if not preview_items:
        _LOGGER.warning(
            'merchant preview returned zero items: %s',
            json.dumps(
                {
                    'shop_id': shop_id,
                    'price_url': result.get('price_url'),
                    **diagnostics,
                },
                ensure_ascii=False,
            ),
        )
    return {
        'shop_id': shop_id,
        'status': 'success',
        'audit_mode': 'preview',
        'audit': audit,
        'source': 'fliggy_merchant_preview',
        'shop_name': result['shop_name'],
        'price_url': result['price_url'],
        'storage_state_used': storage_state_used,
        'current_price': current_price,
        'item_count': len(preview_items),
        'items': preview_items,
        'mapping_summary': mapping_summary,
        'collected_at': result['collected_at'],
        'history_saved_count': history_saved_count,
        **diagnostics,
    }


def fetch_fliggy_merchant_price_preview(
    db: Session,
    *,
    shop_id: int,
    price_url: str | None = None,
    login_url: str | None = None,
    storage_state_name: str | None = None,
    username: str = '',
    password: str = '',
    selectors: dict | str | None = None,
    headless: bool = True,
    login_headless: bool = False,
    auto_login: bool = False,
    save_credential: bool = True,
    collect_mode: str = _MERCHANT_COLLECT_MODE_PREFER_CDP,
    debug_url: str | None = None,
) -> dict:
    context_data = _resolve_connection_context(db=db, shop_id=shop_id)
    resolved_urls = _resolve_default_urls(
        login_url=login_url or context_data['login_url'],
        price_url=price_url or context_data['price_url'],
    )
    resolved_storage_state_name = _safe_storage_name(storage_state_name or context_data['storage_state_name'], shop_id=shop_id)
    resolved_selectors = selectors if selectors not in (None, '') else context_data['selectors']
    resolved_username = str(username or '').strip()
    resolved_password = str(password or '')
    credential_saved = False
    auto_login_performed = False

    should_save_credential = bool(save_credential) and any(
        (
            resolved_username,
            resolved_password,
            resolved_urls['login_url'],
            resolved_urls['price_url'],
            resolved_storage_state_name,
            resolved_selectors not in (None, {}, ''),
        )
    )
    if should_save_credential:
        context_tenant_id = int(
            context_data.get('tenant_id')
            or (context_data.get('credential') or {}).get('tenant_id')
            or 1
        )
        credential_data = {
            'tenant_id': context_tenant_id,
            'shop_id': shop_id,
            'username': resolved_username,
            'password': resolved_password,
            'login_url': resolved_urls['login_url'],
            'price_url': resolved_urls['price_url'],
            'storage_state_name': resolved_storage_state_name,
            'selectors': resolved_selectors,
        }
        if not credential_data['username']:
            existing_secret = get_merchant_credential(db=db, shop_id=shop_id, include_secret=True)
            credential_data['username'] = str(existing_secret.get('username') or '').strip()
            if not credential_data['password']:
                credential_data['password'] = str(existing_secret.get('password') or '')
        if credential_data['username']:
            save_merchant_credential(db=db, credential_data=credential_data)
            credential_saved = True

    try:
        result = preview_fliggy_merchant_prices(
            db=db,
            shop_id=shop_id,
            price_url=resolved_urls['price_url'],
            selectors=resolved_selectors,
            headless=headless,
            collect_mode=collect_mode,
            debug_url=debug_url,
        )
    except RuntimeError as exc:
        if (
            not auto_login
            or _normalize_merchant_collect_mode(collect_mode) == _MERCHANT_COLLECT_MODE_CDP_CURRENT_PAGE
            or str(exc) not in _SESSION_LOGIN_REQUIRED_ERRORS
        ):
            raise
        login_result = login_fliggy_merchant_session(
            db=db,
            shop_id=shop_id,
            username=resolved_username,
            password=resolved_password,
            login_url=resolved_urls['login_url'],
            storage_state_name=resolved_storage_state_name,
            selectors=resolved_selectors,
            headless=login_headless,
        )
        auto_login_performed = bool(login_result.get('session_saved'))
        result = preview_fliggy_merchant_prices(
            db=db,
            shop_id=shop_id,
            price_url=resolved_urls['price_url'],
            selectors=resolved_selectors,
            headless=headless,
            collect_mode=collect_mode,
            debug_url=debug_url,
        )

    return {
        **result,
        'auto_login_performed': auto_login_performed,
        'credential_saved': credential_saved,
    }










