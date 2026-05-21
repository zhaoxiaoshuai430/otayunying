from __future__ import annotations

import re
import threading
import time
from datetime import datetime

_LIVE_CACHE_TTL_SECONDS = 1800
_NUMBER_PATTERN = re.compile(r'(\d+(?:\.\d{1,2})?)')
_CACHE_LOCK = threading.Lock()
_COMPETITOR_LIVE_CACHE: dict[int, dict] = {}


def _now_ts() -> float:
    return time.time()


def _normalize_keyword(value: str | None) -> str:
    return ' '.join(str(value or '').strip().split()).lower()


def _extract_price_from_signals(price_signals: list[object]) -> float | None:
    for signal in price_signals:
        text_value = str(signal or '').strip()
        if not text_value:
            continue
        for amount in _NUMBER_PATTERN.findall(text_value):
            try:
                price = round(float(amount), 2)
            except (TypeError, ValueError):
                continue
            if price > 0:
                return price
    return None


def normalize_live_competitor_rows(*, result: dict, source: str) -> list[dict]:
    collected_at = str(result.get('collected_at') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    items = result.get('items') if isinstance(result.get('items'), list) else []
    rows: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name') or '').strip()
        if not name:
            continue
        signals = item.get('signals') if isinstance(item.get('signals'), dict) else {}
        price_signals = signals.get('price_signals') if isinstance(signals.get('price_signals'), list) else []
        rows.append(
            {
                'target_name': name,
                'target_url': str(item.get('url') or '').strip(),
                'signals_json': signals,
                'collected_at': collected_at,
                'source': source,
                'price': _extract_price_from_signals(price_signals),
                'price_signals': price_signals[:5],
                'fetch_status': str(item.get('fetch_status') or 'success').strip() or 'success',
            }
        )
    return rows


def _normalize_live_competitor_meta(*, result: dict, source: str) -> dict:
    return {
        'matched_page_url': str(result.get('matched_page_url') or '').strip(),
        'matched_page_title': str(result.get('matched_page_title') or '').strip(),
        'target_page_url_keyword': str(result.get('target_page_url_keyword') or '').strip(),
        'target_hotel_names': [
            str(item).strip()
            for item in (result.get('target_hotel_names') or [])
            if str(item).strip()
        ][:50],
        'debug_url': str(result.get('debug_url') or '').strip(),
        'collect_mode': str(result.get('collect_mode') or '').strip() or 'cdp_current_page',
        'source': str(source or result.get('source') or 'fliggy_live').strip() or 'fliggy_live',
    }


def build_live_competitor_prices_payload(
    *,
    shop_id: int,
    result: dict,
    target_name: str | None = None,
    source: str = 'fliggy_live',
) -> dict:
    rows = normalize_live_competitor_rows(result=result, source=source)
    keyword = _normalize_keyword(target_name)
    filtered_rows = [row for row in rows if not keyword or keyword in _normalize_keyword(row.get('target_name'))]
    latest_collected_at = str(result.get('collected_at') or (filtered_rows[0]['collected_at'] if filtered_rows else ''))
    sample_hotel_names = [
        str(row.get('target_name') or '').strip()
        for row in rows
        if str(row.get('target_name') or '').strip()
    ][:5]
    hotels = [
        {
            'hotel_name': str(row.get('target_name') or ''),
            'url': str(row.get('target_url') or ''),
            'price': row.get('price'),
            'price_signals': list(row.get('price_signals') or []),
            'collected_at': str(row.get('collected_at') or ''),
            'source': str(row.get('source') or source),
            'fetch_status': str(row.get('fetch_status') or 'success'),
        }
        for row in filtered_rows
    ]
    return {
        'shop_id': shop_id,
        'count': len(hotels),
        'target_name': (target_name or '').strip() or None,
        'latest_collected_at': latest_collected_at,
        'hotels': hotels,
        'source': source,
        'raw_row_count': len(rows),
        'filtered_out_count': max(0, len(rows) - len(hotels)),
        'sample_hotel_names': sample_hotel_names,
    }


def store_live_competitor_result(
    *,
    shop_id: int,
    result: dict,
    source: str = 'fliggy_live',
    ttl_seconds: int = _LIVE_CACHE_TTL_SECONDS,
) -> dict:
    rows = normalize_live_competitor_rows(result=result, source=source)
    collected_at = str(result.get('collected_at') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    expires_at_ts = _now_ts() + max(60, int(ttl_seconds or _LIVE_CACHE_TTL_SECONDS))
    entry = {
        'shop_id': shop_id,
        'source': source,
        'collected_at': collected_at,
        'rows': rows,
        'meta': _normalize_live_competitor_meta(result=result, source=source),
        'created_at_ts': _now_ts(),
        'expires_at_ts': expires_at_ts,
    }
    with _CACHE_LOCK:
        _COMPETITOR_LIVE_CACHE[shop_id] = entry
    return {
        'shop_id': shop_id,
        'source': source,
        'count': len(rows),
        'collected_at': collected_at,
        'expires_at': datetime.fromtimestamp(expires_at_ts).strftime('%Y-%m-%d %H:%M:%S'),
        'matched_page_url': entry['meta'].get('matched_page_url') or None,
        'matched_page_title': entry['meta'].get('matched_page_title') or None,
        'target_page_url_keyword': entry['meta'].get('target_page_url_keyword') or None,
        'debug_url': entry['meta'].get('debug_url') or None,
        'collect_mode': entry['meta'].get('collect_mode') or 'cdp_current_page',
    }


def _get_cache_entry(shop_id: int, *, max_age_seconds: int = _LIVE_CACHE_TTL_SECONDS) -> dict | None:
    with _CACHE_LOCK:
        entry = _COMPETITOR_LIVE_CACHE.get(int(shop_id))
        if not entry:
            return None
        if entry.get('expires_at_ts', 0) < _now_ts():
            _COMPETITOR_LIVE_CACHE.pop(int(shop_id), None)
            return None
        created_at_ts = float(entry.get('created_at_ts') or 0)
        if max_age_seconds > 0 and created_at_ts > 0 and (_now_ts() - created_at_ts) > max_age_seconds:
            return None
        return {
            'shop_id': int(entry.get('shop_id') or shop_id),
            'source': str(entry.get('source') or 'fliggy_live'),
            'collected_at': str(entry.get('collected_at') or ''),
            'rows': [dict(row) for row in (entry.get('rows') or []) if isinstance(row, dict)],
            'meta': dict(entry.get('meta') or {}),
            'created_at_ts': created_at_ts,
            'expires_at_ts': float(entry.get('expires_at_ts') or 0),
        }


def query_live_competitor_rows(
    *,
    shop_id: int,
    target_name: str | None = None,
    limit: int = 100,
    max_age_seconds: int = _LIVE_CACHE_TTL_SECONDS,
) -> list[dict]:
    entry = _get_cache_entry(shop_id=shop_id, max_age_seconds=max_age_seconds)
    if not entry:
        return []
    keyword = _normalize_keyword(target_name)
    rows = entry.get('rows') or []
    filtered = [row for row in rows if not keyword or keyword in _normalize_keyword(row.get('target_name'))]
    bounded_limit = max(1, int(limit or 100))
    return [dict(row) for row in filtered[:bounded_limit]]


def get_live_competitor_prices(
    *,
    shop_id: int,
    target_name: str | None = None,
    limit: int = 100,
    max_age_seconds: int = _LIVE_CACHE_TTL_SECONDS,
) -> dict | None:
    entry = _get_cache_entry(shop_id=shop_id, max_age_seconds=max_age_seconds)
    if not entry:
        return None
    all_rows = entry.get('rows') or []
    rows = query_live_competitor_rows(
        shop_id=shop_id,
        target_name=target_name,
        limit=limit,
        max_age_seconds=max_age_seconds,
    )
    sample_hotel_names = [
        str(row.get('target_name') or '').strip()
        for row in all_rows
        if str(row.get('target_name') or '').strip()
    ][:5]
    hotels = [
        {
            'hotel_name': str(row.get('target_name') or ''),
            'url': str(row.get('target_url') or ''),
            'price': row.get('price'),
            'price_signals': list(row.get('price_signals') or []),
            'collected_at': str(row.get('collected_at') or ''),
            'source': str(row.get('source') or entry.get('source') or 'fliggy_live'),
            'fetch_status': str(row.get('fetch_status') or 'success'),
        }
        for row in rows
    ]
    return {
        'shop_id': shop_id,
        'count': len(hotels),
        'target_name': (target_name or '').strip() or None,
        'target_hotel_names': [
            str(item).strip()
            for item in ((entry.get('meta') or {}).get('target_hotel_names') or [])
            if str(item).strip()
        ][:50],
        'latest_collected_at': str(entry.get('collected_at') or ''),
        'hotels': hotels,
        'raw_row_count': len(all_rows),
        'filtered_out_count': max(0, len(all_rows) - len(hotels)),
        'sample_hotel_names': sample_hotel_names,
        'source': str(entry.get('source') or 'fliggy_live'),
        'matched_page_url': str((entry.get('meta') or {}).get('matched_page_url') or ''),
        'matched_page_title': str((entry.get('meta') or {}).get('matched_page_title') or ''),
        'target_page_url_keyword': str((entry.get('meta') or {}).get('target_page_url_keyword') or ''),
        'debug_url': str((entry.get('meta') or {}).get('debug_url') or ''),
        'collect_mode': str((entry.get('meta') or {}).get('collect_mode') or 'cdp_current_page'),
    }

