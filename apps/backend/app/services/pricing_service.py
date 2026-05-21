from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.competitor_live_cache import get_live_competitor_prices, query_live_competitor_rows
from app.services.competitor_service import ensure_competitor_tables
from app.services.pricing_policy import (
    build_competitor_price_context,
    build_event_aware_recommendation,
    build_event_policy,
    safe_float,
)

DEFAULT_OPENAI_BASE_URL = 'https://api.openai.com/v1'
DEFAULT_TONGYI_BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
_NUMBER_PATTERN = re.compile(r'(\d+(?:\.\d{1,2})?)')
_ALLOWED_STRATEGIES = {'conservative', 'balanced', 'aggressive'}


def _extract_json_candidate(text_value: str) -> str:
    start = text_value.find('{')
    end = text_value.rfind('}')
    if start == -1 or end == -1 or start >= end:
        return text_value
    return text_value[start : end + 1]



def _completion_endpoint(base_url: str) -> str:
    normalized = str(base_url or '').strip().rstrip('/')
    if normalized.endswith('/chat/completions'):
        return normalized
    return f'{normalized}/chat/completions'



def _normalize_inventory_snapshot(snapshot: dict) -> dict:
    total_rooms = max(1, int(snapshot.get('total_rooms', 1) or 1))
    available_rooms = max(0, int(snapshot.get('available_rooms', 0) or 0))
    available_rooms = min(available_rooms, total_rooms)
    supplied_rate = snapshot.get('occupancy_rate')
    if supplied_rate is None:
        occupancy_rate = (total_rooms - available_rooms) / total_rooms
    else:
        occupancy_rate = min(1.0, max(0.0, safe_float(supplied_rate)))
    current_price = snapshot.get('current_price')
    normalized = {
        'total_rooms': total_rooms,
        'available_rooms': available_rooms,
        'occupancy_rate': round(occupancy_rate, 4),
    }
    if current_price is not None:
        normalized['current_price'] = round(max(0.0, safe_float(current_price)), 2)
    return normalized



def _query_competitor_price_rows(db: Session, *, shop_id: int, days: int, target_name: str | None, limit: int) -> list[dict]:
    ensure_competitor_tables(db)
    sql = '''
        SELECT target_name, signals_json, collected_at
        FROM competitor_snapshots
        WHERE shop_id = :shop_id
          AND fetch_status = 'success'
          AND collected_at >= DATE_SUB(NOW(), INTERVAL :days DAY)
    '''
    params = {'shop_id': shop_id, 'days': days, 'limit': limit}
    target = (target_name or '').strip()
    if target:
        sql += ' AND target_name = :target_name'
        params['target_name'] = target
    sql += ' ORDER BY collected_at DESC LIMIT :limit'
    return [dict(row) for row in db.execute(text(sql), params).mappings().all()]



def _extract_price_values(price_signals: list[object]) -> list[float]:
    prices: list[float] = []
    for signal in price_signals:
        text_value = str(signal or '').strip()
        if not text_value:
            continue
        for amount in _NUMBER_PATTERN.findall(text_value):
            price = safe_float(amount)
            if price > 0:
                prices.append(round(price, 2))
    return prices


def _load_competitor_price_rows(db: Session, *, shop_id: int, days: int, target_name: str | None, limit: int) -> tuple[list[dict], str, dict | None]:
    live_rows = query_live_competitor_rows(shop_id=shop_id, target_name=target_name, limit=limit)
    if live_rows:
        live_snapshot = get_live_competitor_prices(shop_id=shop_id, target_name=target_name, limit=limit)
        return live_rows, 'live_cache', live_snapshot
    return _query_competitor_price_rows(db, shop_id=shop_id, days=days, target_name=target_name, limit=limit), 'database', None


def _build_live_capture_context(live_snapshot: dict | None) -> dict | None:
    if not isinstance(live_snapshot, dict):
        return None
    hotels = live_snapshot.get('hotels') if isinstance(live_snapshot.get('hotels'), list) else []
    sample_hotels = []
    sample_hotel_names: list[str] = []
    for hotel in hotels[:3]:
        if not isinstance(hotel, dict):
            continue
        hotel_name = str(hotel.get('hotel_name') or '').strip()
        if hotel_name:
            sample_hotel_names.append(hotel_name)
        sample_hotels.append(
            {
                'hotel_name': hotel_name,
                'price': hotel.get('price'),
                'price_signals': list(hotel.get('price_signals') or [])[:3],
                'url': str(hotel.get('url') or '').strip(),
            }
        )
    return {
        'hotel_count': int(live_snapshot.get('count') or 0),
        'latest_collected_at': str(live_snapshot.get('latest_collected_at') or '').strip() or None,
        'matched_page_url': str(live_snapshot.get('matched_page_url') or '').strip() or None,
        'matched_page_title': str(live_snapshot.get('matched_page_title') or '').strip() or None,
        'target_page_url_keyword': str(live_snapshot.get('target_page_url_keyword') or '').strip() or None,
        'debug_url': str(live_snapshot.get('debug_url') or '').strip() or None,
        'collect_mode': str(live_snapshot.get('collect_mode') or '').strip() or 'cdp_current_page',
        'sample_hotels': sample_hotels,
        'sample_hotel_names': sample_hotel_names,
    }


def _normalize_merchant_history_context(merchant_history_context: dict | None) -> dict:
    context = merchant_history_context if isinstance(merchant_history_context, dict) else {}
    price_count = max(0, int(context.get('price_count') or 0))
    return {
        'price_count': price_count,
        'price_min': round(max(0.0, safe_float(context.get('price_min'), 0.0)), 2) or None,
        'price_max': round(max(0.0, safe_float(context.get('price_max'), 0.0)), 2) or None,
        'price_avg': round(max(0.0, safe_float(context.get('price_avg'), 0.0)), 2) or None,
        'latest_price': round(max(0.0, safe_float(context.get('latest_price'), 0.0)), 2) or None,
        'latest_collected_at': str(context.get('latest_collected_at') or '').strip() or None,
    }



def _apply_merchant_history_bias(recommendation: dict, merchant_history_context: dict | None) -> dict:
    normalized_history = _normalize_merchant_history_context(merchant_history_context)
    if normalized_history['price_count'] <= 0:
        return recommendation

    merchant_avg = normalized_history.get('price_avg')
    latest_price = normalized_history.get('latest_price')
    merchant_min = normalized_history.get('price_min')
    merchant_max = normalized_history.get('price_max')
    if latest_price and merchant_avg:
        merchant_anchor = round((merchant_avg * 0.6) + (latest_price * 0.4), 2)
    else:
        merchant_anchor = merchant_avg or latest_price
    if not merchant_anchor:
        merged = dict(recommendation)
        merged['merchant_history_context'] = normalized_history
        return merged

    price_mid = round(max(1.0, safe_float(recommendation.get('price_mid'), merchant_anchor)), 2)
    weight = 0.15
    if normalized_history['price_count'] >= 7:
        weight = 0.35
    elif normalized_history['price_count'] >= 3:
        weight = 0.25
    adjusted_mid = round((price_mid * (1 - weight)) + (merchant_anchor * weight), 2)

    if merchant_min and merchant_max and merchant_max >= merchant_min:
        lower_guard = round(max(1.0, merchant_min * 0.96), 2)
        upper_guard = round(max(lower_guard, merchant_max * 1.08), 2)
        adjusted_mid = round(min(upper_guard, max(lower_guard, adjusted_mid)), 2)

    price_min = round(max(1.0, safe_float(recommendation.get('price_min'), adjusted_mid)), 2)
    price_max = round(max(adjusted_mid, safe_float(recommendation.get('price_max'), adjusted_mid)), 2)
    width_low = max(0.0, price_mid - price_min)
    width_high = max(0.0, price_max - price_mid)

    merged = dict(recommendation)
    merged['price_mid'] = adjusted_mid
    merged['price_min'] = round(max(1.0, adjusted_mid - width_low), 2)
    merged['price_max'] = round(max(adjusted_mid, adjusted_mid + width_high), 2)
    merged['merchant_history_context'] = normalized_history

    reasons = merged.get('reasons') if isinstance(merged.get('reasons'), list) else []
    history_reason = f"商家历史价 {normalized_history['price_count']} 条，均价 ¥{merchant_avg or merchant_anchor:.0f}，最新价 ¥{latest_price or merchant_anchor:.0f}。"
    if history_reason not in reasons:
        merged['reasons'] = [*reasons, history_reason][:5]
    summary = str(merged.get('context_summary') or '').strip()
    merged['context_summary'] = (summary + ' 已结合商家历史价做平滑修正。').strip() if summary else '已结合商家历史价做平滑修正。'
    return merged



def _aggregate_competitor_context(rows: list[dict], inventory_snapshot: dict) -> dict:
    prices: list[float] = []
    target_names: set[str] = set()
    latest_collected_at = ''
    for row in rows:
        target_name = str(row.get('target_name') or '').strip()
        if target_name:
            target_names.add(target_name)
        raw_signals = row.get('signals_json')
        if isinstance(raw_signals, str) and raw_signals.strip():
            try:
                parsed = json.loads(raw_signals)
            except json.JSONDecodeError:
                parsed = {}
        else:
            parsed = raw_signals if isinstance(raw_signals, dict) else {}
        signal_prices = parsed.get('price_signals') if isinstance(parsed.get('price_signals'), list) else []
        prices.extend(_extract_price_values(signal_prices))
        if not latest_collected_at and row.get('collected_at'):
            latest_collected_at = str(row['collected_at'])

    current_price = inventory_snapshot.get('current_price')
    fallback_price = round(safe_float(current_price, 299.0), 2) if current_price else 299.0
    market = build_competitor_price_context({'sample_prices': prices, 'price_count': len(prices)}, fallback_price)
    price_min = min(prices) if prices else round(max(1.0, market['low_band_price'] * 0.95), 2)
    price_max = max(prices) if prices else round(max(price_min, market['high_band_price'] * 1.05), 2)

    return {
        'price_count': len(prices),
        'price_min': round(price_min, 2),
        'price_max': round(price_max, 2),
        'price_avg': market['price_avg'],
        'price_median': market['anchor_price'],
        'price_low_band': market['low_band_price'],
        'price_high_band': market['high_band_price'],
        'target_names': sorted(target_names),
        'latest_collected_at': latest_collected_at,
    }



def _build_rule_based_recommendation(
    *,
    inventory_snapshot: dict,
    competitor_context: dict,
    strategy: str,
    event_date: object = None,
    target_occupancy_min: float = 0.15,
    target_occupancy_max: float = 0.20,
    expected_cancel_rate: float | None = None,
    demand_heat: float | None = None,
    competitor_price_cap_ratio: float = 1.15,
) -> dict:
    policy_context = build_event_policy(
        inventory_snapshot=inventory_snapshot,
        competitor_context=competitor_context,
        strategy=strategy,
        event_date=event_date,
        target_occupancy_min=target_occupancy_min,
        target_occupancy_max=target_occupancy_max,
        expected_cancel_rate=expected_cancel_rate,
        demand_heat=demand_heat,
        competitor_price_cap_ratio=competitor_price_cap_ratio,
    )
    return build_event_aware_recommendation(policy_context=policy_context, strategy=strategy)



def _build_llm_prompt(
    *,
    inventory_snapshot: dict,
    competitor_context: dict,
    policy_context: dict,
    merchant_history_context: dict,
    target_name: str | None,
    strategy: str,
) -> str:
    return json.dumps(
        {
            'task': '根据竞对价格数据、节前库存目标和退订风险，给出酒店定价建议，包含最低价、中间价和最高价。',
            'target_name': target_name,
            'strategy': strategy,
            'inventory_snapshot': inventory_snapshot,
            'competitor_context': competitor_context,
            'policy_context': policy_context,
            'merchant_history_context': merchant_history_context,
            'output_schema': {
                'price_min': 'number',
                'price_max': 'number',
                'price_mid': 'number',
                'currency': 'CNY',
                'reasons': ['string'],
                'risk_level': 'L1|L2|L3',
                'context_summary': 'string',
            },
            'requirements': [
                '仅返回 JSON 对象',
                'price_min <= price_mid <= price_max',
                '必须参考 policy_context 中的阶段、目标入住率、退订率和竞对价格上限',
                'price_max 不得明显高于 policy_context.competitor_cap_price',
                'reasons 至少 2 条，说明定价依据和建议理由',
                'risk_level 仅限 L1/L2/L3',
            ],
        },
        ensure_ascii=False,
    )



def _normalize_llm_recommendation(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise RuntimeError('pricing recommendation must be a json object')
    price_min = round(max(1.0, safe_float(payload.get('price_min'), 0.0)), 2)
    price_mid = round(max(price_min, safe_float(payload.get('price_mid'), price_min)), 2)
    price_max = round(max(price_mid, safe_float(payload.get('price_max'), price_mid)), 2)
    reasons_raw = payload.get('reasons') if isinstance(payload.get('reasons'), list) else []
    reasons = [str(item).strip() for item in reasons_raw if str(item).strip()][:5]
    if len(reasons) < 2:
        raise RuntimeError('pricing recommendation reasons are insufficient')
    risk_level = str(payload.get('risk_level') or 'L2').strip().upper()
    if risk_level not in {'L1', 'L2', 'L3'}:
        risk_level = 'L2'
    context_summary = str(payload.get('context_summary') or '').strip()
    return {
        'price_min': price_min,
        'price_max': price_max,
        'price_mid': price_mid,
        'currency': 'CNY',
        'reasons': reasons,
        'risk_level': risk_level,
        'context_summary': context_summary or f'建议中间价 ¥{price_mid:.0f}。',
    }



def _apply_policy_guards(recommendation: dict, policy_context: dict) -> dict:
    guarded = dict(recommendation)
    cap_price = max(1.0, safe_float(policy_context.get('competitor_cap_price'), guarded.get('price_max', 1.0)))
    floor_price = max(1.0, safe_float(policy_context.get('competitor_low_band_price'), guarded.get('price_min', 1.0)) * 0.95)
    guarded['price_mid'] = round(min(cap_price, max(floor_price, safe_float(guarded.get('price_mid'), floor_price))), 2)
    guarded['price_min'] = round(min(guarded['price_mid'], max(1.0, safe_float(guarded.get('price_min'), floor_price))), 2)
    guarded['price_max'] = round(max(guarded['price_mid'], min(cap_price, safe_float(guarded.get('price_max'), cap_price))), 2)
    guarded['policy_context'] = policy_context
    return guarded



def _call_chat_completions_for_pricing(*, provider: str, api_key: str, model: str, base_url: str, prompt: str, timeout_sec: int) -> dict:
    system_prompt = (
        '你是一位专业的酒店收益管理 AI。'
        '请仅返回 JSON 对象，格式为 '
        '{"price_min": number, "price_max": number, "price_mid": number, '
        '"currency": "CNY", "reasons": [string], "risk_level": "L1|L2|L3", "context_summary": string}。'
    )
    payload = {
        'model': model,
        'temperature': 0.2,
        'response_format': {'type': 'json_object'},
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': prompt},
        ],
    }
    req = Request(
        _completion_endpoint(base_url),
        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        method='POST',
    )
    req.add_header('Authorization', f'Bearer {api_key}')
    req.add_header('Content-Type', 'application/json')
    try:
        with urlopen(req, timeout=timeout_sec) as response:
            raw = response.read().decode('utf-8')
    except HTTPError as exc:
        raise RuntimeError(f'{provider} http error: {exc.code}') from exc
    except URLError as exc:
        raise RuntimeError(f'{provider} network error: {exc.reason}') from exc
    except TimeoutError as exc:
        raise RuntimeError(f'{provider} request timeout') from exc

    try:
        parsed = json.loads(raw)
        content = parsed['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f'invalid {provider} pricing response') from exc

    try:
        recommendation = json.loads(_extract_json_candidate(content))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f'{provider} pricing response is not valid json') from exc
    return _normalize_llm_recommendation(recommendation)



def _select_provider_settings(settings) -> tuple[str, str, str, str]:
    provider = str(getattr(settings, 'llm_provider', 'openai') or 'openai').strip().lower()
    if provider == 'tongyi':
        api_key = str(getattr(settings, 'tongyi_api_key', '') or getattr(settings, 'openai_api_key', '')).strip()
        model = str(getattr(settings, 'tongyi_model', '') or 'qwen-plus').strip()
        base_url = str(getattr(settings, 'tongyi_base_url', '') or DEFAULT_TONGYI_BASE_URL).strip().rstrip('/')
        return provider, api_key, model, base_url
    api_key = str(getattr(settings, 'openai_api_key', '')).strip()
    model = str(getattr(settings, 'openai_model', '') or 'gpt-4o-mini').strip()
    base_url = str(getattr(settings, 'openai_base_url', '') or DEFAULT_OPENAI_BASE_URL).strip().rstrip('/')
    return 'openai', api_key, model, base_url



def _build_suggested_action(*, recommendation: dict, inventory_snapshot: dict, competitor_context: dict, merchant_history_context: dict, strategy: str, target_name: str | None) -> dict:
    current_price = safe_float(inventory_snapshot.get('current_price'), recommendation['price_mid'])
    anchor = max(current_price, 1.0)
    delta_pct = int(round(min(30.0, abs(recommendation['price_mid'] - anchor) / anchor * 100)))
    policy_context = recommendation.get('policy_context', {}) if isinstance(recommendation.get('policy_context'), dict) else {}
    risk_level = str(recommendation.get('risk_level') or 'L2')
    if risk_level == 'L1':
        risk_level = 'L2'
    payload = {
        'strategy': strategy,
        'stage': policy_context.get('stage'),
        'stage_action': policy_context.get('stage_action'),
        'max_change_pct': max(3, delta_pct or 5),
        'suggested_price_min': recommendation['price_min'],
        'suggested_price_max': recommendation['price_max'],
        'suggested_price_mid': recommendation['price_mid'],
        'target_name': target_name or '',
        'inventory_snapshot': inventory_snapshot,
        'competitor_context': competitor_context,
        'merchant_history_context': merchant_history_context,
        'target_occupancy_min': policy_context.get('target_occupancy_min'),
        'target_occupancy_max': policy_context.get('target_occupancy_max'),
        'expected_cancel_rate': policy_context.get('expected_cancel_rate'),
        'competitor_cap_price': policy_context.get('competitor_cap_price'),
        'booking_policy': 'prefer_non_refundable' if policy_context.get('stage') == 'lock_inventory' else 'flexible',
    }
    return {
        'action_type': 'adjust_price',
        'risk_level': risk_level,
        'payload': payload,
    }



def generate_price_recommendation(
    db: Session,
    *,
    shop_id: int,
    inventory_snapshot: dict,
    target_name: str | None = None,
    days: int = 7,
    strategy: str = 'balanced',
    limit: int = 50,
    event_date: object = None,
    target_occupancy_min: float = 0.15,
    target_occupancy_max: float = 0.20,
    expected_cancel_rate: float | None = None,
    demand_heat: float | None = None,
    competitor_price_cap_ratio: float = 1.15,
    merchant_history_context: dict | None = None,
) -> dict:
    if days < 1 or days > 90:
        raise ValueError('days must be between 1 and 90')
    if limit < 1 or limit > 200:
        raise ValueError('limit must be between 1 and 200')
    if strategy not in _ALLOWED_STRATEGIES:
        raise ValueError('strategy must be conservative, balanced, or aggressive')

    normalized_inventory = _normalize_inventory_snapshot(inventory_snapshot)
    try:
        rows, competitor_data_source, live_snapshot = _load_competitor_price_rows(
            db,
            shop_id=shop_id,
            days=days,
            target_name=target_name,
            limit=limit,
        )
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc
    competitor_context = _aggregate_competitor_context(rows, normalized_inventory)
    competitor_context['data_source'] = competitor_data_source
    live_capture = _build_live_capture_context(live_snapshot)
    if live_capture:
        competitor_context['live_capture'] = live_capture
    normalized_merchant_history = _normalize_merchant_history_context(merchant_history_context)

    fallback_recommendation = _build_rule_based_recommendation(
        inventory_snapshot=normalized_inventory,
        competitor_context=competitor_context,
        strategy=strategy,
        event_date=event_date,
        target_occupancy_min=target_occupancy_min,
        target_occupancy_max=target_occupancy_max,
        expected_cancel_rate=expected_cancel_rate,
        demand_heat=demand_heat,
        competitor_price_cap_ratio=competitor_price_cap_ratio,
    )
    fallback_recommendation = _apply_merchant_history_bias(fallback_recommendation, normalized_merchant_history)
    policy_context = dict(fallback_recommendation.get('policy_context') or {})
    source = 'fallback'
    recommendation = fallback_recommendation
    settings = get_settings()
    provider, api_key, model, base_url = _select_provider_settings(settings)
    if api_key and model:
        try:
            recommendation = _call_chat_completions_for_pricing(
                provider=provider,
                api_key=api_key,
                model=model,
                base_url=base_url,
                prompt=_build_llm_prompt(
                    inventory_snapshot=normalized_inventory,
                    competitor_context=competitor_context,
                    policy_context=policy_context,
                    merchant_history_context=normalized_merchant_history,
                    target_name=target_name,
                    strategy=strategy,
                ),
                timeout_sec=int(getattr(settings, 'fliggy_timeout_sec', 20) or 20),
            )
            recommendation = _apply_policy_guards(recommendation, policy_context)
            recommendation = _apply_merchant_history_bias(recommendation, normalized_merchant_history)
            source = provider
        except RuntimeError:
            recommendation = fallback_recommendation
            source = 'fallback'

    recommendation['suggested_action'] = _build_suggested_action(
        recommendation=recommendation,
        inventory_snapshot=normalized_inventory,
        competitor_context=competitor_context,
        merchant_history_context=normalized_merchant_history,
        strategy=strategy,
        target_name=target_name,
    )
    recommendation['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    return {
        'shop_id': shop_id,
        'target_name': (target_name or '').strip() or None,
        'days': days,
        'strategy': strategy,
        'inventory_snapshot': normalized_inventory,
        'competitor_context': competitor_context,
        'merchant_history_context': normalized_merchant_history,
        'event_policy': policy_context,
        'price_recommendation': recommendation,
        'recommendation_source': source,
    }





