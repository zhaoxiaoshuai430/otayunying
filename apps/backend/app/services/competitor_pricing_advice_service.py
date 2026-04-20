from __future__ import annotations

import json
import re
from statistics import median
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.merchant_price_history_service import get_latest_merchant_price_snapshot
from app.services.pricing_policy import safe_float
from app.services.pricing_service import (
    _completion_endpoint,
    _extract_json_candidate,
    _normalize_inventory_snapshot,
    _select_provider_settings,
)


_ALLOWED_STRATEGIES = {'conservative', 'balanced', 'aggressive'}
_ROOM_TAG_KEYWORDS = (
    '大床', '双床', '单床', '圆床', '家庭', '亲子', '豪华', '高级', '商务', '行政',
    '标准', '套房', '影音', '景观', '江景', '城景', '浴缸', '无窗', '电竞', '智能',
    '安睡', '零压', '森林氧吧', '会展', '高铁', '主题', '轻奢', '精选', '雅致',
)
_BED_TAGS = {'大床', '双床', '单床', '圆床', '家庭', '亲子'}
_RISK_ORDER = {'L1': 1, 'L2': 2, 'L3': 3}


def _normalize_text(value: object | None) -> str:
    return ' '.join(str(value or '').strip().split())


def _normalize_match_key(value: object | None) -> str:
    return _normalize_text(value).lower()


def _compact_room_text(value: object | None) -> str:
    return re.sub(r'[^0-9a-zA-Z\u4e00-\u9fff]+', '', _normalize_match_key(value))


def _extract_room_tags(*values: object | None) -> set[str]:
    combined = ' '.join(_normalize_text(value) for value in values if _normalize_text(value))
    return {keyword for keyword in _ROOM_TAG_KEYWORDS if keyword in combined}


def _build_character_ngrams(value: str) -> set[str]:
    compact = _compact_room_text(value)
    if not compact:
        return set()
    if len(compact) <= 2:
        return {compact}
    return {compact[index:index + 2] for index in range(len(compact) - 1)}


def _round_price(value: object | None) -> float | None:
    try:
        price = round(float(value or 0), 2)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def _normalize_competitor_hotels(hotels: list[dict], competitor_hotel_name: str | None = None) -> list[dict]:
    target_key = _normalize_match_key(competitor_hotel_name)
    normalized_hotels: list[dict] = []

    for hotel in hotels:
        if not isinstance(hotel, dict):
            continue
        hotel_name = _normalize_text(hotel.get('hotel_name') or hotel.get('name'))
        if not hotel_name:
            continue
        if target_key and target_key not in _normalize_match_key(hotel_name):
            continue
        rooms = hotel.get('rooms') if isinstance(hotel.get('rooms'), list) else []
        normalized_rooms = []
        for room in rooms:
            if not isinstance(room, dict):
                continue
            price = _round_price(room.get('price'))
            if price is None:
                continue
            room_type = _normalize_text(room.get('room_type')) or _normalize_text(room.get('rate_name')) or '未命名房型'
            rate_name = _normalize_text(room.get('rate_name') or room_type) or room_type
            normalized_rooms.append(
                {
                    'room_type': room_type,
                    'rate_name': rate_name,
                    'price': price,
                    'breakfast': _normalize_text(room.get('breakfast')) or None,
                    'cancelable': _normalize_text(room.get('cancelable')) or None,
                }
            )
        if not normalized_rooms:
            continue
        normalized_hotels.append(
            {
                'hotel_name': hotel_name,
                'hotel_url': _normalize_text(hotel.get('hotel_url') or hotel.get('url')) or None,
                'rooms': normalized_rooms,
                'room_count': len(normalized_rooms),
            }
        )

    if not normalized_hotels:
        raise ValueError('没有可用于建议价分析的竞对房型价数据')
    return normalized_hotels


def _build_market_summary(hotels: list[dict]) -> dict:
    prices = [float(room['price']) for hotel in hotels for room in hotel.get('rooms', []) if float(room.get('price') or 0) > 0]
    if not prices:
        raise ValueError('竞对房型价中未提取到有效价格')
    return {
        'price_count': len(prices),
        'price_min': round(min(prices), 2),
        'price_max': round(max(prices), 2),
        'price_avg': round(sum(prices) / len(prices), 2),
        'price_median': round(median(prices), 2),
        'price_low_band': round(min(prices), 2),
        'price_high_band': round(max(prices), 2),
        'target_names': [hotel['hotel_name'] for hotel in hotels],
        'hotel_count': len(hotels),
        'room_count': sum(int(hotel.get('room_count') or 0) for hotel in hotels),
        'sample_prices': [round(price, 2) for price in sorted(prices)[:20]],
        'data_source': 'plugin_room_prices',
    }



def _normalize_manual_room_terms(value: object | None) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        normalized = _normalize_text(value)
        raw_items = re.split(r'[\n,\uFF0C;\uFF1B]+', normalized) if normalized else []
    items: list[str] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        item = _normalize_text(raw_item)
        if not item or item in seen:
            continue
        seen.add(item)
        items.append(item)
        if len(items) >= 20:
            break
    return items


def _normalize_manual_room_snapshot(*, manual_room_mappings: list[dict] | None, inventory_snapshot: dict) -> tuple[dict, list[dict], dict]:
    items = manual_room_mappings if isinstance(manual_room_mappings, list) else []
    normalized_items: list[dict] = []
    seen: set[str] = set()

    for item in items:
        if not isinstance(item, dict) or item.get('enabled') is False:
            continue
        current_price = _round_price(item.get('current_price') or item.get('currentPrice'))
        display_name = _normalize_text(item.get('display_name') or item.get('displayName'))
        room_name = _normalize_text(item.get('room_type') or item.get('roomType') or display_name)
        rate_name = _normalize_text(item.get('rate_name') or item.get('rateName') or '???') or '???'
        competitor_room_names = _normalize_manual_room_terms(item.get('competitor_room_names') or item.get('competitorRoomNames'))
        if not display_name or current_price is None:
            continue
        dedupe_key = '|'.join([display_name, room_name, rate_name])
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized_items.append(
            {
                'display_name': display_name,
                'room_name': room_name or display_name,
                'rate_name': rate_name,
                'gid': None,
                'hid': None,
                'current_price': current_price,
                'competitor_room_names': competitor_room_names,
            }
        )

    if not normalized_items:
        raise ValueError('???????????????????')

    prices = [float(item['current_price']) for item in normalized_items]
    normalized_inventory = dict(inventory_snapshot)
    if normalized_inventory.get('current_price') is None:
        normalized_inventory['current_price'] = round(sum(prices) / len(prices), 2)

    summary = {
        'item_count': len(normalized_items),
        'price_count': len(normalized_items),
        'price_min': round(min(prices), 2),
        'price_max': round(max(prices), 2),
        'price_avg': round(sum(prices) / len(prices), 2),
        'latest_price': round(sum(prices) / len(prices), 2),
        'latest_collected_at': None,
        'source': 'manual_room_mappings',
        'items': normalized_items,
    }
    return normalized_inventory, normalized_items, summary

def _normalize_merchant_room_snapshot(db: Session, *, shop_id: int, inventory_snapshot: dict) -> tuple[dict, list[dict], dict]:
    snapshot = get_latest_merchant_price_snapshot(db=db, shop_id=shop_id, limit=200)
    items = snapshot.get('items') if isinstance(snapshot.get('items'), list) else []
    normalized_items: list[dict] = []
    seen: set[str] = set()

    for item in items:
        if not isinstance(item, dict):
            continue
        current_price = _round_price(item.get('observed_price'))
        if current_price is None:
            continue
        room_name = _normalize_text(item.get('room_name'))
        rate_name = _normalize_text(item.get('rate_name') or item.get('display_name'))
        display_name = _normalize_text(item.get('display_name') or rate_name or room_name)
        gid = _normalize_text(item.get('gid'))
        hid = _normalize_text(item.get('hid'))
        if not any([display_name, room_name, rate_name, gid, hid]):
            continue
        dedupe_key = '|'.join([display_name, room_name, rate_name, gid, hid])
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized_items.append(
            {
                'display_name': display_name or rate_name or room_name or f'房型{len(normalized_items) + 1}',
                'room_name': room_name or display_name or rate_name,
                'rate_name': rate_name or display_name or room_name or '标准价',
                'gid': gid or None,
                'hid': hid or None,
                'current_price': current_price,
            }
        )

    if not normalized_items:
        raise ValueError('未找到本店房型价格快照，请先在“商家改价”页点击“抓取并预览”')

    prices = [float(item['current_price']) for item in normalized_items]
    normalized_inventory = dict(inventory_snapshot)
    if normalized_inventory.get('current_price') is None:
        normalized_inventory['current_price'] = round(sum(prices) / len(prices), 2)

    summary = {
        'item_count': len(normalized_items),
        'price_count': len(normalized_items),
        'price_min': round(min(prices), 2),
        'price_max': round(max(prices), 2),
        'price_avg': round(sum(prices) / len(prices), 2),
        'latest_price': round(sum(prices) / len(prices), 2),
        'latest_collected_at': snapshot.get('collected_at'),
        'source': 'merchant_price_snapshot',
        'items': normalized_items,
    }
    return normalized_inventory, normalized_items, summary

def _flatten_competitor_rooms(hotels: list[dict]) -> list[dict]:
    flattened = []
    for hotel in hotels:
        hotel_name = hotel.get('hotel_name')
        hotel_url = hotel.get('hotel_url')
        for room in hotel.get('rooms', []):
            flattened.append(
                {
                    'hotel_name': hotel_name,
                    'hotel_url': hotel_url,
                    'room_type': room.get('room_type'),
                    'rate_name': room.get('rate_name'),
                    'price': float(room.get('price') or 0),
                    'breakfast': room.get('breakfast'),
                    'cancelable': room.get('cancelable'),
                }
            )
    return flattened


def _score_room_match(merchant_room: dict, competitor_room: dict) -> float:
    merchant_display = merchant_room.get('display_name') or merchant_room.get('room_name') or ''
    merchant_room_name = merchant_room.get('room_name') or merchant_display
    merchant_rate_name = merchant_room.get('rate_name') or merchant_display
    competitor_display = ' '.join(
        part for part in [competitor_room.get('room_type'), competitor_room.get('rate_name')] if _normalize_text(part)
    )
    merchant_compact = _compact_room_text(merchant_display)
    competitor_compact = _compact_room_text(competitor_display)
    if not merchant_compact or not competitor_compact:
        return 0.0

    score = 0.0
    if merchant_compact == competitor_compact:
        score += 8.0
    elif merchant_compact in competitor_compact or competitor_compact in merchant_compact:
        score += 5.0

    merchant_tags = _extract_room_tags(merchant_display, merchant_room_name, merchant_rate_name)
    competitor_tags = _extract_room_tags(competitor_room.get('room_type'), competitor_room.get('rate_name'))
    score += float(len(merchant_tags & competitor_tags)) * 2.5

    merchant_beds = merchant_tags & _BED_TAGS
    competitor_beds = competitor_tags & _BED_TAGS
    if merchant_beds and competitor_beds and not (merchant_beds & competitor_beds):
        score -= 3.0

    merchant_ngrams = _build_character_ngrams(merchant_display)
    competitor_ngrams = _build_character_ngrams(competitor_display)
    if merchant_ngrams and competitor_ngrams:
        overlap = len(merchant_ngrams & competitor_ngrams)
        union = len(merchant_ngrams | competitor_ngrams)
        if union > 0:
            score += round(overlap / union * 6, 2)
    return round(score, 2)


def _match_competitor_rooms(merchant_room: dict, competitor_rooms: list[dict]) -> tuple[list[dict], str]:
    manual_terms = _normalize_manual_room_terms(merchant_room.get('competitor_room_names'))
    if manual_terms:
        explicit_matches: list[dict] = []
        seen_keys: set[str] = set()
        for room in competitor_rooms:
            room_label = ' '.join(
                part for part in [_normalize_text(room.get('room_type')), _normalize_text(room.get('rate_name'))] if part
            )
            room_key = _compact_room_text(room_label)
            if not room_key:
                continue
            for term in manual_terms:
                term_key = _compact_room_text(term)
                if not term_key:
                    continue
                if term_key == room_key or term_key in room_key or room_key in term_key:
                    dedupe_key = '|'.join([_normalize_text(room.get('hotel_name')), room_key, str(room.get('price') or '')])
                    if dedupe_key not in seen_keys:
                        seen_keys.add(dedupe_key)
                        explicit_matches.append(room)
                    break
        if explicit_matches:
            return explicit_matches[:12], 'manual_mapping'

    scored = []
    for room in competitor_rooms:
        score = _score_room_match(merchant_room, room)
        if score <= 0:
            continue
        scored.append((score, room))
    scored.sort(key=lambda item: item[0], reverse=True)

    strong_matches = [room for score, room in scored if score >= 4.0][:12]
    if strong_matches:
        return strong_matches, 'smart_match'

    broad_matches = [room for score, room in scored if score >= 2.0][:12]
    if broad_matches:
        return broad_matches, 'broad_match'

    return competitor_rooms[:12], 'market_fallback'


def _build_room_competitor_stats(merchant_room: dict, competitor_rooms: list[dict]) -> dict:
    matched_rooms, match_mode = _match_competitor_rooms(merchant_room, competitor_rooms)
    prices = [float(room.get('price') or 0) for room in matched_rooms if float(room.get('price') or 0) > 0]
    if not prices:
        raise ValueError('竞对房型价中未提取到有效价格')
    sample_hotels = []
    seen_hotels: set[str] = set()
    sample_labels = []
    for room in matched_rooms:
        hotel_name = _normalize_text(room.get('hotel_name'))
        if hotel_name and hotel_name not in seen_hotels:
            seen_hotels.add(hotel_name)
            sample_hotels.append(hotel_name)
        label = ' / '.join(
            part for part in [_normalize_text(room.get('room_type')), _normalize_text(room.get('rate_name'))] if part
        )
        if label and label not in sample_labels:
            sample_labels.append(label)
    return {
        'match_mode': match_mode,
        'matched_room_count': len(matched_rooms),
        'matched_hotel_count': len(seen_hotels),
        'sample_hotels': sample_hotels[:3],
        'sample_room_labels': sample_labels[:3],
        'price_min': round(min(prices), 2),
        'price_max': round(max(prices), 2),
        'price_avg': round(sum(prices) / len(prices), 2),
        'price_median': round(median(prices), 2),
    }


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def _build_room_reasoning(*, competitor_stats: dict, inventory_snapshot: dict, strategy: str, match_mode: str, suggested_price: float) -> tuple[list[str], str, str]:
    total_rooms = int(inventory_snapshot.get('total_rooms') or 1)
    available_rooms = int(inventory_snapshot.get('available_rooms') or 0)
    occupancy_rate = float(inventory_snapshot.get('occupancy_rate') or 0)
    match_text = {
        'manual_mapping': '???????????????',
        'smart_match': '按相似房型精确匹配竞对房型',
        'broad_match': '按相近房型宽松匹配竞对房型',
        'market_fallback': '未命中相似房型，回退到当前竞对市场整体样本',
    }.get(match_mode, '按竞对样本匹配')
    reasons = [
        f"竞对样本 {int(competitor_stats.get('matched_room_count') or 0)} 条，均价 ¥{float(competitor_stats.get('price_avg') or 0):.0f}，区间 ¥{float(competitor_stats.get('price_min') or 0):.0f}-¥{float(competitor_stats.get('price_max') or 0):.0f}。",
        f"当前整店可售 {available_rooms}/{total_rooms}，入住率 {occupancy_rate * 100:.0f}%，采用 {strategy} 策略。",
        f"{match_text}，建议价调整到 ¥{suggested_price:.0f}。",
    ]
    risk_level = {'conservative': 'L1', 'balanced': 'L2', 'aggressive': 'L2'}.get(strategy, 'L2')
    summary = f"{match_text}，结合库存与竞对区间后建议价 ¥{suggested_price:.0f}。"
    return reasons, summary, risk_level


def _build_fallback_room_recommendation(*, merchant_room: dict, competitor_stats: dict, inventory_snapshot: dict, strategy: str) -> dict:
    current_price = float(merchant_room.get('current_price') or 0)
    competitor_avg = float(competitor_stats.get('price_avg') or current_price or 1)
    competitor_min = float(competitor_stats.get('price_min') or competitor_avg)
    competitor_max = float(competitor_stats.get('price_max') or competitor_avg)
    occupancy_rate = float(inventory_snapshot.get('occupancy_rate') or 0)
    availability_ratio = float(inventory_snapshot.get('available_rooms') or 0) / max(1, int(inventory_snapshot.get('total_rooms') or 1))

    inventory_adjustment = 0.0
    if occupancy_rate >= 0.82:
        inventory_adjustment += 0.05
    elif occupancy_rate >= 0.70:
        inventory_adjustment += 0.03
    elif occupancy_rate <= 0.40:
        inventory_adjustment -= 0.06
    elif occupancy_rate <= 0.55:
        inventory_adjustment -= 0.03

    if availability_ratio <= 0.12:
        inventory_adjustment += 0.02
    elif availability_ratio >= 0.45:
        inventory_adjustment -= 0.02

    strategy_adjustment = {'conservative': -0.03, 'balanced': 0.0, 'aggressive': 0.03}.get(strategy, 0.0)
    anchor_price = (current_price * 0.45) + (competitor_avg * 0.55)
    if competitor_stats.get('match_mode') == 'market_fallback':
        anchor_price = (current_price * 0.60) + (competitor_avg * 0.40)

    suggested_price = anchor_price * (1 + inventory_adjustment + strategy_adjustment)
    lower_bound = max(1.0, min(current_price * 0.90, competitor_min * 0.96))
    upper_bound = max(lower_bound, max(current_price * 1.18, competitor_max * 1.06))
    suggested_price = round(_clamp(suggested_price, lower_bound, upper_bound), 2)

    change_amount = round(suggested_price - current_price, 2)
    change_pct = round(change_amount / current_price * 100, 2) if current_price > 0 else None
    reasons, summary, default_risk = _build_room_reasoning(
        competitor_stats=competitor_stats,
        inventory_snapshot=inventory_snapshot,
        strategy=strategy,
        match_mode=str(competitor_stats.get('match_mode') or ''),
        suggested_price=suggested_price,
    )
    risk_level = default_risk
    if change_pct is not None and abs(change_pct) >= 12:
        risk_level = 'L3'
    elif change_pct is not None and abs(change_pct) <= 5:
        risk_level = 'L1'
    if competitor_stats.get('match_mode') == 'market_fallback' and risk_level == 'L1':
        risk_level = 'L2'

    return {
        'display_name': merchant_room['display_name'],
        'room_name': merchant_room['room_name'],
        'rate_name': merchant_room['rate_name'],
        'gid': merchant_room.get('gid'),
        'hid': merchant_room.get('hid'),
        'current_price': round(current_price, 2),
        'competitor_min_price': competitor_stats['price_min'],
        'competitor_max_price': competitor_stats['price_max'],
        'competitor_avg_price': competitor_stats['price_avg'],
        'competitor_median_price': competitor_stats['price_median'],
        'matched_room_count': competitor_stats['matched_room_count'],
        'matched_hotel_count': competitor_stats['matched_hotel_count'],
        'sample_hotels': competitor_stats['sample_hotels'],
        'sample_room_labels': competitor_stats['sample_room_labels'],
        'match_mode': competitor_stats['match_mode'],
        'suggested_price': suggested_price,
        'change_amount': change_amount,
        'change_pct': change_pct,
        'reasoning': summary,
        'reasons': reasons,
        'risk_level': risk_level,
        'source': 'fallback',
    }

def _build_prompt_profile() -> dict:
    return {
        'role': '酒店OTA运营专家',
        'objective': '结合本店房型当前价、竞对当前房型价和整店库存，为每个房型输出合理建议价。',
        'input_policy': [
            '只使用本店当前房型价、竞对当前房型价和整店库存',
            '不使用历史价格作为决策依据',
            '必须参考竞对最低价、最高价、平均价',
        ],
        'output_policy': [
            '每个房型都要返回 suggested_price',
            '每个房型都要返回 reasoning 和 risk_level',
            'risk_level 只允许 L1/L2/L3',
        ],
    }


def _build_room_prompt(*, prompt_profile: dict, inventory_snapshot: dict, market_summary: dict, room_inputs: list[dict], competitor_hotel_name: str | None, strategy: str) -> str:
    return json.dumps(
        {
            'task': '按房型输出酒店建议价。',
            'prompt_profile': prompt_profile,
            'target_competitor_hotel': competitor_hotel_name,
            'strategy': strategy,
            'inventory_snapshot': inventory_snapshot,
            'market_summary': market_summary,
            'room_inputs': room_inputs,
            'output_schema': {
                'room_recommendations': [
                    {
                        'display_name': 'string',
                        'room_name': 'string',
                        'rate_name': 'string',
                        'suggested_price': 'number',
                        'reasoning': 'string',
                        'risk_level': 'L1|L2|L3',
                    }
                ]
            },
            'requirements': [
                '仅返回 JSON 对象',
                '每个房型都必须输出 suggested_price',
                'suggested_price 必须大于 0',
                '必须参考每个房型的 competitor_min_price、competitor_avg_price、competitor_max_price',
                '库存紧张时可以高于 competitor_avg_price，但不要明显超过 competitor_max_price 的 108%',
                '库存宽松时建议更贴近 competitor_min_price 或 competitor_avg_price',
            ],
        },
        ensure_ascii=False,
    )


def _call_room_pricing_model(*, provider: str, api_key: str, model: str, base_url: str, prompt: str, timeout_sec: int) -> dict:
    system_prompt = (
        '你是一位专业的酒店OTA运营专家。'
        '请仅返回 JSON 对象，格式为 '
        '{"room_recommendations": ['
        '{"display_name": string, "room_name": string, "rate_name": string, '
        '"suggested_price": number, "reasoning": string, "risk_level": "L1|L2|L3"}'
        ']}。'
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
    request = Request(
        _completion_endpoint(base_url),
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        },
        method='POST',
    )
    try:
        with urlopen(request, timeout=timeout_sec) as response:
            raw_payload = response.read().decode('utf-8', errors='ignore')
    except HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='ignore')
        raise RuntimeError(f'{provider} pricing request failed: {detail or exc.reason}') from exc
    except URLError as exc:
        raise RuntimeError(f'{provider} pricing request failed: {exc.reason}') from exc
    except TimeoutError as exc:
        raise RuntimeError(f'{provider} pricing request timed out') from exc

    try:
        parsed_payload = json.loads(raw_payload)
        content = parsed_payload['choices'][0]['message']['content']
        if isinstance(content, list):
            content = ''.join(str(part.get('text') or '') for part in content if isinstance(part, dict))
        normalized = _extract_json_candidate(str(content or '').strip())
        return json.loads(normalized)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f'{provider} pricing response is invalid: {raw_payload[:500]}') from exc


def _normalize_llm_room_recommendations(payload: dict) -> list[dict]:
    if not isinstance(payload, dict):
        raise RuntimeError('room pricing response must be a json object')
    raw_items = payload.get('room_recommendations') if isinstance(payload.get('room_recommendations'), list) else []
    normalized_items = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        suggested_price = _round_price(item.get('suggested_price'))
        if suggested_price is None:
            continue
        display_name = _normalize_text(item.get('display_name'))
        room_name = _normalize_text(item.get('room_name'))
        rate_name = _normalize_text(item.get('rate_name'))
        risk_level = str(item.get('risk_level') or 'L2').strip().upper()
        if risk_level not in _RISK_ORDER:
            risk_level = 'L2'
        reasoning = _normalize_text(item.get('reasoning')) or f'建议价调整到 ¥{suggested_price:.0f}。'
        normalized_items.append(
            {
                'display_name': display_name,
                'room_name': room_name,
                'rate_name': rate_name,
                'suggested_price': suggested_price,
                'reasoning': reasoning,
                'risk_level': risk_level,
            }
        )
    if not normalized_items:
        raise RuntimeError('room pricing response does not contain valid room recommendations')
    return normalized_items


def _merge_llm_room_recommendations(base_items: list[dict], llm_items: list[dict], provider: str) -> list[dict]:
    keyed_by_display = {_normalize_match_key(item.get('display_name')): item for item in llm_items if _normalize_match_key(item.get('display_name'))}
    keyed_by_room_rate = {
        f"{_normalize_match_key(item.get('room_name'))}|{_normalize_match_key(item.get('rate_name'))}": item
        for item in llm_items
        if _normalize_match_key(item.get('room_name')) or _normalize_match_key(item.get('rate_name'))
    }
    merged_items = []
    for index, base_item in enumerate(base_items):
        llm_item = keyed_by_display.get(_normalize_match_key(base_item.get('display_name')))
        if llm_item is None:
            room_rate_key = f"{_normalize_match_key(base_item.get('room_name'))}|{_normalize_match_key(base_item.get('rate_name'))}"
            llm_item = keyed_by_room_rate.get(room_rate_key)
        if llm_item is None and index < len(llm_items):
            llm_item = llm_items[index]
        if llm_item is None:
            merged_items.append(base_item)
            continue
        current_price = float(base_item.get('current_price') or 0)
        suggested_price = float(llm_item.get('suggested_price') or base_item.get('suggested_price') or current_price)
        change_amount = round(suggested_price - current_price, 2)
        change_pct = round(change_amount / current_price * 100, 2) if current_price > 0 else None
        merged_items.append(
            {
                **base_item,
                'suggested_price': round(suggested_price, 2),
                'change_amount': change_amount,
                'change_pct': change_pct,
                'reasoning': str(llm_item.get('reasoning') or base_item.get('reasoning') or '').strip() or base_item.get('reasoning'),
                'reasons': [str(llm_item.get('reasoning') or '').strip()] + [reason for reason in list(base_item.get('reasons') or []) if reason][:2],
                'risk_level': str(llm_item.get('risk_level') or base_item.get('risk_level') or 'L2').strip().upper(),
                'source': provider,
            }
        )
    return merged_items


def _pick_highest_risk(items: list[dict]) -> str:
    highest = 'L1'
    for item in items:
        risk_level = str(item.get('risk_level') or 'L1').strip().upper()
        if _RISK_ORDER.get(risk_level, 1) > _RISK_ORDER.get(highest, 1):
            highest = risk_level
    return highest


def _build_overall_recommendation(room_recommendations: list[dict]) -> dict:
    suggested_prices = [float(item.get('suggested_price') or 0) for item in room_recommendations if float(item.get('suggested_price') or 0) > 0]
    current_prices = [float(item.get('current_price') or 0) for item in room_recommendations if float(item.get('current_price') or 0) > 0]
    if not suggested_prices:
        raise ValueError('未生成有效的房型建议价')
    avg_suggested = round(sum(suggested_prices) / len(suggested_prices), 2)
    avg_current = round(sum(current_prices) / len(current_prices), 2) if current_prices else None
    return {
        'price_min': round(min(suggested_prices), 2),
        'price_max': round(max(suggested_prices), 2),
        'price_mid': avg_suggested,
        'currency': 'CNY',
        'reasons': [
            f"共生成 {len(room_recommendations)} 个房型建议价，均价 ¥{avg_suggested:.0f}。",
            f"高风险房型等级 {_pick_highest_risk(room_recommendations)}，建议先核对重点房型后再执行。",
        ],
        'risk_level': _pick_highest_risk(room_recommendations),
        'context_summary': (
            f"已按 {len(room_recommendations)} 个本店房型输出建议价。"
            + (f" 本店房型当前均价 ¥{avg_current:.0f}。" if avg_current is not None else '')
        ).strip(),
    }


def _build_advice_summary(*, price_recommendation: dict, market_summary: dict, merchant_snapshot_summary: dict, inventory_snapshot: dict, room_recommendations: list[dict]) -> dict:
    suggested_price = round(float(price_recommendation.get('price_mid') or 0), 2)
    reference_current = inventory_snapshot.get('current_price')
    if reference_current is None:
        reference_current = merchant_snapshot_summary.get('price_avg')
    change_amount = None
    change_pct = None
    if reference_current is not None:
        reference_value = round(float(reference_current), 2)
        change_amount = round(suggested_price - reference_value, 2)
        if reference_value > 0:
            change_pct = round(change_amount / reference_value * 100, 2)
    competitor_avg = market_summary.get('price_avg')
    competitor_gap = round(suggested_price - float(competitor_avg), 2) if competitor_avg is not None else None
    return {
        'suggested_price': suggested_price,
        'price_min': price_recommendation.get('price_min'),
        'price_max': price_recommendation.get('price_max'),
        'change_amount': change_amount,
        'change_pct': change_pct,
        'competitor_min_price': market_summary.get('price_min'),
        'competitor_max_price': market_summary.get('price_max'),
        'competitor_avg_price': market_summary.get('price_avg'),
        'competitor_median_price': market_summary.get('price_median'),
        'competitor_low_band_price': market_summary.get('price_low_band'),
        'competitor_high_band_price': market_summary.get('price_high_band'),
        'competitor_gap': competitor_gap,
        'hotel_count': market_summary.get('hotel_count'),
        'room_count': market_summary.get('room_count'),
        'merchant_room_count': merchant_snapshot_summary.get('item_count'),
        'recommended_room_count': len(room_recommendations),
        'target_hotels': market_summary.get('target_names') or [],
        'reason_summary': price_recommendation.get('context_summary'),
        'reasons': price_recommendation.get('reasons') or [],
        'risk_level': price_recommendation.get('risk_level'),
    }

def preview_competitor_pricing_advice(
    db: Session,
    *,
    shop_id: int,
    inventory_snapshot: dict,
    competitor_hotels: list[dict],
    manual_room_mappings: list[dict] | None = None,
    competitor_hotel_name: str | None = None,
    strategy: str = 'balanced',
    event_date: object = None,
    target_occupancy_min: float = 0.15,
    target_occupancy_max: float = 0.20,
    expected_cancel_rate: float | None = None,
    demand_heat: float | None = None,
    competitor_price_cap_ratio: float = 1.15,
) -> dict:
    del event_date, target_occupancy_min, target_occupancy_max, expected_cancel_rate, demand_heat, competitor_price_cap_ratio
    if strategy not in _ALLOWED_STRATEGIES:
        raise ValueError('strategy must be conservative, balanced, or aggressive')

    normalized_inventory = _normalize_inventory_snapshot(inventory_snapshot)
    analyzed_hotels = _normalize_competitor_hotels(competitor_hotels, competitor_hotel_name)
    market_summary = _build_market_summary(analyzed_hotels)
    if manual_room_mappings:
        normalized_inventory, merchant_rooms, merchant_snapshot_summary = _normalize_manual_room_snapshot(
            manual_room_mappings=manual_room_mappings,
            inventory_snapshot=normalized_inventory,
        )
    else:
        normalized_inventory, merchant_rooms, merchant_snapshot_summary = _normalize_merchant_room_snapshot(
            db=db,
            shop_id=shop_id,
            inventory_snapshot=normalized_inventory,
        )

    competitor_rooms = _flatten_competitor_rooms(analyzed_hotels)
    room_recommendations = []
    room_prompt_inputs = []
    for merchant_room in merchant_rooms:
        competitor_stats = _build_room_competitor_stats(merchant_room, competitor_rooms)
        fallback_item = _build_fallback_room_recommendation(
            merchant_room=merchant_room,
            competitor_stats=competitor_stats,
            inventory_snapshot=normalized_inventory,
            strategy=strategy,
        )
        room_recommendations.append(fallback_item)
        room_prompt_inputs.append(
            {
                'display_name': merchant_room['display_name'],
                'room_name': merchant_room['room_name'],
                'rate_name': merchant_room['rate_name'],
                'current_price': merchant_room['current_price'],
                'competitor_min_price': competitor_stats['price_min'],
                'competitor_avg_price': competitor_stats['price_avg'],
                'competitor_max_price': competitor_stats['price_max'],
                'matched_room_count': competitor_stats['matched_room_count'],
                'matched_hotel_count': competitor_stats['matched_hotel_count'],
                'match_mode': competitor_stats['match_mode'],
            }
        )

    prompt_profile = _build_prompt_profile()
    recommendation_source = 'fallback'
    settings = get_settings()
    provider, api_key, model, base_url = _select_provider_settings(settings)
    if api_key and model:
        try:
            llm_payload = _call_room_pricing_model(
                provider=provider,
                api_key=api_key,
                model=model,
                base_url=base_url,
                prompt=_build_room_prompt(
                    prompt_profile=prompt_profile,
                    inventory_snapshot=normalized_inventory,
                    market_summary=market_summary,
                    room_inputs=room_prompt_inputs,
                    competitor_hotel_name=_normalize_text(competitor_hotel_name) or None,
                    strategy=strategy,
                ),
                timeout_sec=int(getattr(settings, 'fliggy_timeout_sec', 20) or 20),
            )
            room_recommendations = _merge_llm_room_recommendations(
                room_recommendations,
                _normalize_llm_room_recommendations(llm_payload),
                provider,
            )
            recommendation_source = provider
        except RuntimeError:
            recommendation_source = 'fallback'

    price_recommendation = _build_overall_recommendation(room_recommendations)
    advice_summary = _build_advice_summary(
        price_recommendation=price_recommendation,
        market_summary=market_summary,
        merchant_snapshot_summary=merchant_snapshot_summary,
        inventory_snapshot=normalized_inventory,
        room_recommendations=room_recommendations,
    )

    return {
        'shop_id': int(shop_id),
        'competitor_hotel_name': _normalize_text(competitor_hotel_name) or None,
        'strategy': strategy,
        'inventory_snapshot': normalized_inventory,
        'prompt_profile': prompt_profile,
        'competitor_context': market_summary,
        'merchant_history_context': {
            'price_count': merchant_snapshot_summary.get('price_count'),
            'price_min': merchant_snapshot_summary.get('price_min'),
            'price_max': merchant_snapshot_summary.get('price_max'),
            'price_avg': merchant_snapshot_summary.get('price_avg'),
            'latest_price': merchant_snapshot_summary.get('latest_price'),
            'latest_collected_at': merchant_snapshot_summary.get('latest_collected_at'),
        },
        'merchant_room_snapshot': merchant_snapshot_summary,
        'price_recommendation': price_recommendation,
        'recommendation_source': recommendation_source,
        'advice_summary': advice_summary,
        'room_recommendations': room_recommendations,
        'analyzed_hotels': [
            {
                'hotel_name': hotel['hotel_name'],
                'hotel_url': hotel.get('hotel_url'),
                'room_count': int(hotel.get('room_count') or 0),
                'price_min': min(float(room['price']) for room in hotel.get('rooms', [])),
                'price_max': max(float(room['price']) for room in hotel.get('rooms', [])),
                'price_median': round(median([float(room['price']) for room in hotel.get('rooms', [])]), 2),
            }
            for hotel in analyzed_hotels
        ],
    }
