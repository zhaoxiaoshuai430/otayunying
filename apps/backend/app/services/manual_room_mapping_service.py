from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


def ensure_manual_room_mappings_table(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS manual_room_mappings (
              id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
              tenant_id BIGINT UNSIGNED NOT NULL,
              user_id BIGINT UNSIGNED NOT NULL,
              shop_id BIGINT UNSIGNED NOT NULL,
              display_name VARCHAR(255) NOT NULL,
              room_type VARCHAR(255) NOT NULL DEFAULT '',
              rate_name VARCHAR(255) NOT NULL DEFAULT '',
              current_price DECIMAL(10,2) NOT NULL,
              gid VARCHAR(128) NOT NULL DEFAULT '',
              hid VARCHAR(128) NOT NULL DEFAULT '',
              competitor_room_names_json LONGTEXT NOT NULL,
              enabled TINYINT(1) NOT NULL DEFAULT 1,
              sort_order INT NOT NULL DEFAULT 10,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (id),
              KEY idx_manual_room_mappings_scope (tenant_id, user_id, shop_id),
              KEY idx_manual_room_mappings_shop_enabled (shop_id, enabled)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    )


def _normalize_text(value: object, *, default: str = '') -> str:
    normalized = ' '.join(str(value or '').strip().split())
    return normalized or default


def _normalize_price(value: object) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    return round(price, 2)


def _normalize_competitor_room_names(value: object) -> list[str]:
    raw_items = value if isinstance(value, list) else []
    result: list[str] = []
    seen: set[str] = set()
    for raw_item in raw_items:
        item = _normalize_text(raw_item)
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
        if len(result) >= 20:
            break
    return result


def _loads_competitor_room_names(value: object) -> list[str]:
    try:
        decoded = json.loads(str(value or '[]'))
    except json.JSONDecodeError:
        decoded = []
    return _normalize_competitor_room_names(decoded)


def _normalize_mapping_item(item: dict, *, index: int) -> dict | None:
    display_name = _normalize_text(item.get('display_name') or item.get('displayName'))
    current_price = _normalize_price(item.get('current_price') if 'current_price' in item else item.get('currentPrice'))
    if not display_name or current_price is None:
        return None
    room_type = _normalize_text(item.get('room_type') or item.get('roomType'), default=display_name)
    rate_name = _normalize_text(item.get('rate_name') or item.get('rateName'), default='标准价')
    return {
        'display_name': display_name,
        'room_type': room_type,
        'rate_name': rate_name,
        'current_price': current_price,
        'gid': _normalize_text(item.get('gid'))[:128],
        'hid': _normalize_text(item.get('hid'))[:128],
        'competitor_room_names': _normalize_competitor_room_names(
            item.get('competitor_room_names') if 'competitor_room_names' in item else item.get('competitorRoomNames')
        ),
        'enabled': bool(item.get('enabled', True)),
        'sort_order': int(item.get('sort_order') or item.get('sortOrder') or ((index + 1) * 10)),
    }


def _serialize_row(row: dict) -> dict:
    return {
        'id': int(row.get('id') or 0),
        'display_name': _normalize_text(row.get('display_name')),
        'room_type': _normalize_text(row.get('room_type')),
        'rate_name': _normalize_text(row.get('rate_name'), default='标准价'),
        'current_price': float(row.get('current_price') or 0),
        'gid': _normalize_text(row.get('gid')),
        'hid': _normalize_text(row.get('hid')),
        'competitor_room_names': _loads_competitor_room_names(row.get('competitor_room_names_json')),
        'enabled': bool(int(row.get('enabled') or 0)),
        'sort_order': int(row.get('sort_order') or 0),
    }


def list_manual_room_mappings(
    db: Session,
    *,
    tenant_id: int,
    user_id: int,
    shop_id: int,
    only_enabled: bool = False,
) -> list[dict]:
    try:
        ensure_manual_room_mappings_table(db)
        where_sql = 'tenant_id = :tenant_id AND user_id = :user_id AND shop_id = :shop_id'
        params = {'tenant_id': int(tenant_id), 'user_id': int(user_id), 'shop_id': int(shop_id)}
        if only_enabled:
            where_sql += ' AND enabled = 1'
        rows = (
            db.execute(
                text(
                    f"""
                    SELECT id, display_name, room_type, rate_name, current_price, gid, hid,
                           competitor_room_names_json, enabled, sort_order
                    FROM manual_room_mappings
                    WHERE {where_sql}
                    ORDER BY sort_order ASC, id ASC
                    """
                ),
                params,
            )
            .mappings()
            .all()
        )
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc
    return [_serialize_row(dict(row)) for row in rows]


def replace_manual_room_mappings(
    db: Session,
    *,
    tenant_id: int,
    user_id: int,
    shop_id: int,
    items: list[dict],
) -> list[dict]:
    normalized_items: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        normalized = _normalize_mapping_item(item, index=index)
        if normalized is None:
            continue
        dedupe_key = '|'.join([normalized['display_name'], normalized['room_type'], normalized['rate_name']])
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized_items.append(normalized)
        if len(normalized_items) >= 50:
            break

    try:
        ensure_manual_room_mappings_table(db)
        db.execute(
            text(
                """
                DELETE FROM manual_room_mappings
                WHERE tenant_id = :tenant_id
                  AND user_id = :user_id
                  AND shop_id = :shop_id
                """
            ),
            {'tenant_id': int(tenant_id), 'user_id': int(user_id), 'shop_id': int(shop_id)},
        )
        for item in normalized_items:
            db.execute(
                text(
                    """
                    INSERT INTO manual_room_mappings (
                      tenant_id, user_id, shop_id, display_name, room_type, rate_name,
                      current_price, gid, hid, competitor_room_names_json, enabled, sort_order
                    ) VALUES (
                      :tenant_id, :user_id, :shop_id, :display_name, :room_type, :rate_name,
                      :current_price, :gid, :hid, :competitor_room_names_json, :enabled, :sort_order
                    )
                    """
                ),
                {
                    'tenant_id': int(tenant_id),
                    'user_id': int(user_id),
                    'shop_id': int(shop_id),
                    'display_name': item['display_name'],
                    'room_type': item['room_type'],
                    'rate_name': item['rate_name'],
                    'current_price': float(item['current_price']),
                    'gid': item['gid'],
                    'hid': item['hid'],
                    'competitor_room_names_json': json.dumps(item['competitor_room_names'], ensure_ascii=False),
                    'enabled': 1 if item['enabled'] else 0,
                    'sort_order': int(item['sort_order']),
                },
            )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError(str(exc)) from exc

    return list_manual_room_mappings(
        db=db,
        tenant_id=tenant_id,
        user_id=user_id,
        shop_id=shop_id,
        only_enabled=False,
    )
