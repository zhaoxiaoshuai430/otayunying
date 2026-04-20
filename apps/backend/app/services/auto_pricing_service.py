from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.services.pricing_service import generate_price_recommendation
from app.services.room_status_service import get_latest_room_status
from app.services.shop_service import get_room_status_defaults

_DEFAULT_RULE = {
    'enabled': False,
    'target_name': None,
    'strategy': 'balanced',
    'lookback_days': 7,
    'min_price': None,
    'max_price': None,
    'max_change_pct': 8,
    'high_risk_change_pct': 10,
    'require_manual_approval': False,
    'event_date': None,
    'target_occupancy_min': 0.15,
    'target_occupancy_max': 0.20,
    'expected_cancel_rate': None,
    'demand_heat': None,
    'competitor_price_cap_ratio': 1.15,
}


def ensure_auto_pricing_tables(db: Session) -> None:
    """Ensure the merchant pricing rule table exists."""
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS auto_pricing_rules (
              id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
              shop_id BIGINT UNSIGNED NOT NULL,
              enabled TINYINT(1) NOT NULL DEFAULT 0,
              target_name VARCHAR(128) NULL,
              strategy VARCHAR(32) NOT NULL DEFAULT 'balanced',
              lookback_days INT UNSIGNED NOT NULL DEFAULT 7,
              min_price DECIMAL(10, 2) NULL,
              max_price DECIMAL(10, 2) NULL,
              max_change_pct INT UNSIGNED NOT NULL DEFAULT 8,
              high_risk_change_pct INT UNSIGNED NOT NULL DEFAULT 10,
              require_manual_approval TINYINT(1) NOT NULL DEFAULT 0,
              event_date DATE NULL,
              target_occupancy_min DECIMAL(5, 4) NOT NULL DEFAULT 0.1500,
              target_occupancy_max DECIMAL(5, 4) NOT NULL DEFAULT 0.2000,
              expected_cancel_rate DECIMAL(5, 4) NULL,
              demand_heat DECIMAL(5, 4) NULL,
              competitor_price_cap_ratio DECIMAL(5, 4) NOT NULL DEFAULT 1.1500,
              last_run_at DATETIME NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (id),
              UNIQUE KEY uk_auto_pricing_rules_shop (shop_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    )


def _build_default_rule(shop_id: int) -> dict:
    return {'shop_id': shop_id, 'exists': False, **_DEFAULT_RULE}


def _normalize_rule_row(row: dict) -> dict:
    return {
        'shop_id': int(row['shop_id']),
        'exists': True,
        'enabled': bool(int(row.get('enabled') or 0)),
        'target_name': str(row.get('target_name') or '').strip() or None,
        'strategy': str(row.get('strategy') or 'balanced'),
        'lookback_days': int(row.get('lookback_days') or 7),
        'min_price': float(row['min_price']) if row.get('min_price') is not None else None,
        'max_price': float(row['max_price']) if row.get('max_price') is not None else None,
        'max_change_pct': int(row.get('max_change_pct') or 8),
        'high_risk_change_pct': int(row.get('high_risk_change_pct') or 10),
        'require_manual_approval': bool(int(row.get('require_manual_approval') or 0)),
        'event_date': str(row['event_date']) if row.get('event_date') else None,
        'target_occupancy_min': float(row.get('target_occupancy_min') or 0.15),
        'target_occupancy_max': float(row.get('target_occupancy_max') or 0.20),
        'expected_cancel_rate': float(row['expected_cancel_rate']) if row.get('expected_cancel_rate') is not None else None,
        'demand_heat': float(row['demand_heat']) if row.get('demand_heat') is not None else None,
        'competitor_price_cap_ratio': float(row.get('competitor_price_cap_ratio') or 1.15),
        'last_run_at': str(row['last_run_at']) if row.get('last_run_at') else None,
    }


def get_auto_pricing_rule(db: Session, *, shop_id: int) -> dict:
    """Load the persisted merchant pricing rule for one shop."""
    ensure_auto_pricing_tables(db)
    row = db.execute(
        text(
            """
            SELECT shop_id, enabled, target_name, strategy, lookback_days, min_price, max_price,
                   max_change_pct, high_risk_change_pct, require_manual_approval, event_date,
                   target_occupancy_min, target_occupancy_max, expected_cancel_rate, demand_heat,
                   competitor_price_cap_ratio, last_run_at
            FROM auto_pricing_rules
            WHERE shop_id = :shop_id
            LIMIT 1
            """
        ),
        {'shop_id': shop_id},
    ).mappings().first()
    if not row:
        return _build_default_rule(shop_id)
    return _normalize_rule_row(dict(row))


def _build_inventory_snapshot(db: Session, *, shop_id: int) -> dict:
    latest = get_latest_room_status(db=db, shop_id=shop_id)
    if latest:
        return {
            'total_rooms': int(latest['total_rooms']),
            'available_rooms': int(latest['available_rooms']),
            'current_price': float(latest['current_price']),
        }
    defaults = get_room_status_defaults(db=db, shop_id=shop_id)
    return {
        'total_rooms': int(defaults['total_rooms']),
        'available_rooms': int(defaults['available_rooms']),
        'current_price': float(defaults['current_price']),
    }


def collect_auto_pricing_context(
    db: Session,
    *,
    shop_id: int,
    trigger_type: str,
    dry_run: bool,
) -> dict:
    """Collect the rule and inventory snapshot for merchant pricing suggestions."""
    rule = get_auto_pricing_rule(db=db, shop_id=shop_id)
    if not rule['enabled'] and not dry_run:
        return {
            'shop_id': shop_id,
            'trigger_type': trigger_type,
            'dry_run': dry_run,
            'status': 'skipped',
            'reason': 'auto pricing rule disabled',
            'rule': rule,
        }
    return {
        'shop_id': shop_id,
        'trigger_type': trigger_type,
        'dry_run': dry_run,
        'status': 'ok',
        'rule': rule,
        'inventory_snapshot': _build_inventory_snapshot(db=db, shop_id=shop_id),
    }


def generate_auto_pricing_recommendation(
    db: Session,
    *,
    shop_id: int,
    rule: dict,
    inventory_snapshot: dict,
    merchant_history_context: dict | None = None,
) -> dict:
    """Generate one recommendation payload for the merchant pricing flow."""
    recommendation = generate_price_recommendation(
        db=db,
        shop_id=shop_id,
        inventory_snapshot=inventory_snapshot,
        target_name=rule['target_name'],
        days=rule['lookback_days'],
        strategy=rule['strategy'],
        event_date=rule['event_date'],
        target_occupancy_min=rule['target_occupancy_min'],
        target_occupancy_max=rule['target_occupancy_max'],
        expected_cancel_rate=rule['expected_cancel_rate'],
        demand_heat=rule['demand_heat'],
        competitor_price_cap_ratio=rule['competitor_price_cap_ratio'],
        merchant_history_context=merchant_history_context,
    )
    recommendation_card = recommendation.get('price_recommendation') or {}
    suggested_price = round(float(recommendation_card.get('price_mid') or inventory_snapshot['current_price']), 2)
    return {
        'shop_id': shop_id,
        'suggested_price': suggested_price,
        'recommendation': recommendation,
    }


def _clamp_price(*, current_price: float, suggested_price: float, min_price: float | None, max_price: float | None, max_change_pct: int) -> float:
    final_price = max(1.0, float(suggested_price))
    if min_price is not None:
        final_price = max(final_price, float(min_price))
    if max_price is not None:
        final_price = min(final_price, float(max_price))

    base_price = max(1.0, float(current_price or 1.0))
    ratio = max_change_pct / 100.0
    lower_bound = base_price * (1 - ratio)
    upper_bound = base_price * (1 + ratio)
    final_price = min(upper_bound, max(lower_bound, final_price))
    return round(final_price, 2)


def evaluate_auto_pricing_risk(
    *,
    rule: dict,
    inventory_snapshot: dict,
    suggested_price: float,
) -> dict:
    """Clamp the decision and calculate risk for the merchant pricing flow."""
    current_price = round(float(inventory_snapshot['current_price']), 2)
    final_price = _clamp_price(
        current_price=current_price,
        suggested_price=float(suggested_price),
        min_price=rule['min_price'],
        max_price=rule['max_price'],
        max_change_pct=rule['max_change_pct'],
    )
    change_pct = round(abs(final_price - current_price) / max(current_price, 1.0) * 100, 2)
    require_manual_approval = bool(rule['require_manual_approval'] or change_pct >= rule['high_risk_change_pct'])
    risk_level = 'L2' if require_manual_approval else 'L1'
    return {
        'current_price': current_price,
        'final_price': final_price,
        'change_pct': change_pct,
        'risk_level': risk_level,
        'require_manual_approval': require_manual_approval,
    }


def build_auto_pricing_action_payload(
    *,
    shop_id: int,
    trigger_type: str,
    defer_channel_push: bool = False,
    rule: dict,
    inventory_snapshot: dict,
    recommendation: dict,
    suggested_price: float,
    current_price: float,
    final_price: float,
    change_pct: float,
) -> dict:
    recommendation_card = recommendation.get('price_recommendation') or {}
    return {
        'shop_id': shop_id,
        'strategy': rule['strategy'],
        'target_name': rule['target_name'],
        'previous_price': current_price,
        'current_price': current_price,
        'new_price': final_price,
        'suggested_price_mid': suggested_price,
        'max_change_pct': rule['max_change_pct'],
        'change_pct': change_pct,
        'total_rooms': inventory_snapshot['total_rooms'],
        'available_rooms': inventory_snapshot['available_rooms'],
        'source': 'auto_pricing',
        'trigger_type': trigger_type,
        'recommendation_source': recommendation.get('recommendation_source'),
        'price_min': recommendation_card.get('price_min'),
        'price_max': recommendation_card.get('price_max'),
        'defer_channel_push': bool(defer_channel_push),
    }
