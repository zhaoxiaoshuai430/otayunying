from __future__ import annotations

from datetime import date, datetime


_STRATEGY_SHIFT = {
    'conservative': -0.02,
    'balanced': 0.0,
    'aggressive': 0.03,
}


def safe_float(value: object, default: float = 0.0) -> float:
    """Safely convert a value to float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value: float, lower: float, upper: float) -> float:
    """Clamp a float value to the provided range."""
    return max(lower, min(upper, value))


def normalize_event_date(value: object) -> date | None:
    """Normalize a date-like value to date."""
    if value is None or value == '':
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text_value = str(value).strip()
    if not text_value:
        return None
    try:
        return date.fromisoformat(text_value[:10])
    except ValueError:
        return None


def pick_price_point(context: dict, *keys: str, default: float = 0.0) -> float:
    """Return the first positive numeric field from the context."""
    for key in keys:
        value = safe_float(context.get(key))
        if value > 0:
            return value
    return default


def percentile(values: list[float], ratio: float) -> float:
    """Compute a simple percentile from a sorted series."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = clamp(ratio, 0.0, 1.0) * (len(ordered) - 1)
    lower = int(pos)
    upper = min(len(ordered) - 1, lower + 1)
    if lower == upper:
        return ordered[lower]
    weight = pos - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * weight)


def default_cancel_rate(days_to_event: int | None) -> float:
    """Return a fallback cancel-rate estimate based on lead time."""
    if days_to_event is None:
        return 0.08
    if days_to_event <= 7:
        return 0.20
    if days_to_event <= 14:
        return 0.12
    if days_to_event <= 30:
        return 0.05
    return 0.03


def classify_stage(days_to_event: int | None) -> str:
    """Classify the pre-event pricing stage."""
    if days_to_event is None:
        return 'normal'
    if days_to_event < 0:
        return 'post_event'
    if days_to_event <= 3:
        return 'lock_inventory'
    if days_to_event <= 14:
        return 'dynamic_markup'
    if days_to_event <= 30:
        return 'monitor'
    return 'normal'


def build_competitor_price_context(competitor_context: dict, fallback_price: float) -> dict:
    """Build a normalized competitor price band from heterogeneous sources."""
    sample_prices = competitor_context.get('sample_prices')
    values = [safe_float(item) for item in sample_prices] if isinstance(sample_prices, list) else []
    values = [round(item, 2) for item in values if item > 0]
    anchor = pick_price_point(competitor_context, 'price_median', 'market_avg', 'price_avg', default=fallback_price)
    low_band = pick_price_point(competitor_context, 'price_low_band', 'market_min', 'price_min', default=anchor * 0.95)
    high_band = pick_price_point(competitor_context, 'price_high_band', 'market_max', 'price_max', default=anchor * 1.05)
    price_avg = pick_price_point(competitor_context, 'price_avg', 'market_avg', 'price_median', default=anchor)
    if values:
        anchor = round(percentile(values, 0.5), 2)
        low_band = round(percentile(values, 0.25), 2)
        high_band = round(percentile(values, 0.75), 2)
        price_avg = round(sum(values) / len(values), 2)
    return {
        'anchor_price': round(max(1.0, anchor), 2),
        'price_avg': round(max(1.0, price_avg), 2),
        'low_band_price': round(max(1.0, min(low_band, high_band)), 2),
        'high_band_price': round(max(1.0, max(low_band, high_band)), 2),
        'sample_count': len(values) or int(competitor_context.get('price_count', 0) or competitor_context.get('data_points', 0) or 0),
    }


def build_event_policy(
    *,
    inventory_snapshot: dict,
    competitor_context: dict,
    strategy: str,
    event_date: object = None,
    plan_date: object = None,
    target_occupancy_min: float = 0.15,
    target_occupancy_max: float = 0.20,
    expected_cancel_rate: float | None = None,
    demand_heat: float | None = None,
    competitor_price_cap_ratio: float = 1.15,
) -> dict:
    """Build shared policy context for event-aware hotel pricing."""
    total_rooms = max(1, int(inventory_snapshot.get('total_rooms', 1) or 1))
    available_rooms = clamp(float(inventory_snapshot.get('available_rooms', 0) or 0), 0.0, float(total_rooms))
    current_price = max(1.0, safe_float(inventory_snapshot.get('current_price'), 0.0) or 0.0)
    if current_price <= 0:
        current_price = max(1.0, pick_price_point(competitor_context, 'price_median', 'market_avg', 'price_avg', default=299.0))
    booked_rooms = total_rooms - available_rooms

    normalized_plan_date = normalize_event_date(plan_date) or date.today()
    normalized_event_date = normalize_event_date(event_date)
    days_to_event = None
    if normalized_event_date is not None:
        days_to_event = (normalized_event_date - normalized_plan_date).days

    target_min = clamp(safe_float(target_occupancy_min, 0.15), 0.05, 0.95)
    target_max = clamp(safe_float(target_occupancy_max, 0.20), target_min, 0.95)
    target_mid = round((target_min + target_max) / 2, 4)
    cancel_rate = clamp(safe_float(expected_cancel_rate, default_cancel_rate(days_to_event)), 0.0, 0.6)
    heat = clamp(safe_float(demand_heat, 0.0), 0.0, 1.0)
    stage = classify_stage(days_to_event)
    effective_booked_rooms = booked_rooms * (1 - cancel_rate)
    effective_occupancy_rate = round(effective_booked_rooms / total_rooms, 4)
    vacancy_rate = round(available_rooms / total_rooms, 4)
    remaining_inventory_ratio = vacancy_rate
    occupancy_gap = round(effective_occupancy_rate - target_mid, 4)

    market = build_competitor_price_context(competitor_context, current_price)
    competitor_cap_ratio = clamp(safe_float(competitor_price_cap_ratio, 1.15), 1.0, 1.3)
    competitor_cap_price = round(max(market['anchor_price'], market['price_avg']) * competitor_cap_ratio, 2)

    stage_shift = 0.0
    stage_action = 'hold'
    if stage == 'monitor':
        if effective_occupancy_rate > target_max:
            stage_shift = 0.03
            stage_action = 'preheat_markup'
        elif effective_occupancy_rate < target_min:
            stage_shift = -0.02
            stage_action = 'watch_conversion'
    elif stage == 'dynamic_markup':
        if effective_occupancy_rate >= target_max + 0.10:
            stage_shift = 0.10
            stage_action = 'strong_markup'
        elif effective_occupancy_rate >= target_max:
            stage_shift = 0.08
            stage_action = 'step_markup'
        elif effective_occupancy_rate >= target_mid:
            stage_shift = 0.05
            stage_action = 'soft_markup'
        elif effective_occupancy_rate <= target_min - 0.05:
            stage_shift = -0.04
            stage_action = 'recover_demand'
        elif effective_occupancy_rate <= target_min:
            stage_shift = -0.02
            stage_action = 'hold_or_minor_discount'
    elif stage == 'lock_inventory':
        if remaining_inventory_ratio <= 0.15:
            stage_shift = 0.10 if heat >= 0.6 else 0.06
            stage_action = 'premium_tail_inventory'
        elif effective_occupancy_rate > target_max:
            stage_shift = 0.04
            stage_action = 'lock_inventory'
        elif effective_occupancy_rate < target_min:
            stage_shift = -0.02
            stage_action = 'protect_conversion'
    elif stage == 'normal':
        if effective_occupancy_rate >= 0.85:
            stage_shift = 0.08
            stage_action = 'high_occ_markup'
        elif effective_occupancy_rate >= 0.65:
            stage_shift = 0.03
            stage_action = 'mild_markup'
        elif effective_occupancy_rate <= 0.35:
            stage_shift = -0.08
            stage_action = 'boost_conversion'
        elif effective_occupancy_rate <= 0.50:
            stage_shift = -0.03
            stage_action = 'soft_discount'

    heat_shift = 0.0
    if stage in {'monitor', 'dynamic_markup', 'lock_inventory'}:
        if heat >= 0.8:
            heat_shift = 0.03
        elif heat >= 0.6:
            heat_shift = 0.02
        elif heat >= 0.3:
            heat_shift = 0.01

    market_shift = 0.0
    if current_price < market['low_band_price'] and effective_occupancy_rate > target_max:
        market_shift = 0.02
    elif current_price > competitor_cap_price and effective_occupancy_rate < target_min:
        market_shift = -0.05
    elif current_price > market['high_band_price'] and effective_occupancy_rate < target_mid:
        market_shift = -0.03

    return {
        'plan_date': normalized_plan_date.isoformat(),
        'event_date': normalized_event_date.isoformat() if normalized_event_date else None,
        'days_to_event': days_to_event,
        'stage': stage,
        'stage_action': stage_action,
        'target_occupancy_min': round(target_min, 4),
        'target_occupancy_max': round(target_max, 4),
        'target_occupancy_mid': target_mid,
        'expected_cancel_rate': round(cancel_rate, 4),
        'demand_heat': round(heat, 4),
        'current_price': round(current_price, 2),
        'booked_rooms': round(booked_rooms, 2),
        'effective_booked_rooms': round(effective_booked_rooms, 2),
        'effective_occupancy_rate': effective_occupancy_rate,
        'remaining_inventory_ratio': remaining_inventory_ratio,
        'occupancy_gap': occupancy_gap,
        'competitor_anchor_price': market['anchor_price'],
        'competitor_avg_price': market['price_avg'],
        'competitor_low_band_price': market['low_band_price'],
        'competitor_high_band_price': market['high_band_price'],
        'competitor_sample_count': market['sample_count'],
        'competitor_price_cap_ratio': round(competitor_cap_ratio, 4),
        'competitor_cap_price': competitor_cap_price,
        'strategy_shift': round(_STRATEGY_SHIFT.get(strategy, 0.0), 4),
        'stage_shift': round(stage_shift, 4),
        'heat_shift': round(heat_shift, 4),
        'market_shift': round(market_shift, 4),
    }


def build_event_aware_recommendation(*, policy_context: dict, strategy: str) -> dict:
    """Convert policy context into a concrete recommendation band."""
    current_price = max(1.0, safe_float(policy_context.get('current_price'), 1.0))
    anchor_price = max(1.0, safe_float(policy_context.get('competitor_anchor_price'), current_price))
    low_band = max(1.0, safe_float(policy_context.get('competitor_low_band_price'), anchor_price * 0.95))
    high_band = max(low_band, safe_float(policy_context.get('competitor_high_band_price'), anchor_price * 1.05))
    competitor_cap_price = max(high_band, safe_float(policy_context.get('competitor_cap_price'), high_band))
    stage = str(policy_context.get('stage') or 'normal')
    stage_action = str(policy_context.get('stage_action') or 'hold')
    total_shift = (
        safe_float(policy_context.get('strategy_shift'))
        + safe_float(policy_context.get('stage_shift'))
        + safe_float(policy_context.get('heat_shift'))
        + safe_float(policy_context.get('market_shift'))
    )
    base_price = (current_price * 0.6) + (anchor_price * 0.4)
    if stage in {'monitor', 'dynamic_markup'} and safe_float(policy_context.get('occupancy_gap')) > 0:
        base_price = max(base_price, anchor_price)
    if stage == 'lock_inventory' and stage_action == 'premium_tail_inventory':
        base_price = max(base_price, high_band)
    mid_price = round(max(1.0, base_price * (1 + total_shift)), 2)

    if stage == 'monitor' and stage_action == 'preheat_markup':
        mid_price = max(mid_price, round(current_price * 1.02, 2))
    elif stage == 'dynamic_markup' and stage_action in {'soft_markup', 'step_markup', 'strong_markup'}:
        floor_ratio = 1.05 if stage_action == 'soft_markup' else 1.08
        mid_price = max(mid_price, round(current_price * floor_ratio, 2))
    elif stage == 'lock_inventory' and stage_action == 'premium_tail_inventory':
        mid_price = max(mid_price, round(current_price * 1.06, 2))

    mid_price = min(mid_price, competitor_cap_price)
    if stage_action in {'recover_demand', 'hold_or_minor_discount', 'protect_conversion'}:
        mid_price = max(mid_price, round(low_band * 0.97, 2))

    width = 0.06
    if stage == 'dynamic_markup':
        width = 0.08
    elif stage == 'monitor':
        width = 0.05
    elif stage == 'lock_inventory':
        width = 0.05 if stage_action == 'premium_tail_inventory' else 0.06

    price_min = round(max(1.0, min(mid_price, low_band * 0.98, mid_price * (1 - width / 2))), 2)
    price_max = round(max(mid_price + 1, min(competitor_cap_price, mid_price * (1 + width / 2))), 2)

    delta_ratio = abs(mid_price - current_price) / max(current_price, 1.0)
    if delta_ratio >= 0.12:
        risk_level = 'L3'
    elif delta_ratio >= 0.05:
        risk_level = 'L2'
    else:
        risk_level = 'L1'

    reasons = [
        (
            f"阶段 {stage}，距节日 {policy_context.get('days_to_event')} 天，"
            f"目标入住率 {policy_context.get('target_occupancy_min', 0):.0%}-{policy_context.get('target_occupancy_max', 0):.0%}，"
            f"当前有效入住率 {policy_context.get('effective_occupancy_rate', 0):.0%}。"
        ),
        (
            f"已按预估退订率 {policy_context.get('expected_cancel_rate', 0):.0%} 修正库存，"
            f"有效已售 {policy_context.get('effective_booked_rooms', 0):.1f} 间，动作 {stage_action}。"
        ),
        (
            f"竞对锚点 ¥{anchor_price:.0f}，价格带 ¥{low_band:.0f}-¥{high_band:.0f}，"
            f"上限控制在竞对均价的 {policy_context.get('competitor_price_cap_ratio', 1.15):.0%} 内。"
        ),
    ]
    if safe_float(policy_context.get('demand_heat')) > 0:
        reasons.append(f"需求热度 {policy_context.get('demand_heat', 0):.0%}，已叠加热度修正。")

    return {
        'price_min': price_min,
        'price_max': price_max,
        'price_mid': round(min(max(price_min, mid_price), price_max), 2),
        'currency': 'CNY',
        'reasons': reasons,
        'risk_level': risk_level,
        'context_summary': (
            f"节前阶段 {stage}，有效入住率 {policy_context.get('effective_occupancy_rate', 0):.0%}，"
            f"建议价锚定竞对 ¥{anchor_price:.0f} 并控制在上限 ¥{competitor_cap_price:.0f} 内。"
        ),
        'policy_context': policy_context,
    }
