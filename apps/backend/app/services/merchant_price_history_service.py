from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


def ensure_merchant_price_history_table(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS merchant_price_history (
              id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
              shop_id BIGINT UNSIGNED NOT NULL,
              room_name VARCHAR(255) NOT NULL DEFAULT '',
              rate_name VARCHAR(255) NOT NULL DEFAULT '',
              display_name VARCHAR(255) NOT NULL DEFAULT '',
              gid VARCHAR(128) NOT NULL DEFAULT '',
              hid VARCHAR(128) NOT NULL DEFAULT '',
              observed_price DECIMAL(10, 2) NOT NULL,
              source VARCHAR(32) NOT NULL DEFAULT 'merchant_preview',
              collected_at DATETIME NOT NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (id),
              KEY idx_merchant_price_history_shop_time (shop_id, collected_at),
              KEY idx_merchant_price_history_shop_room_rate (shop_id, room_name, rate_name, collected_at),
              KEY idx_merchant_price_history_shop_gid_hid (shop_id, gid, hid, collected_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    )



def _normalize_price_item(item: dict) -> dict | None:
    observed_price = item.get('observed_price')
    if observed_price in (None, ''):
        observed_price = item.get('price')
    if observed_price in (None, ''):
        observed_price = item.get('current_price')
    try:
        price = round(float(observed_price), 2)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    room_name = str(item.get('room_name') or item.get('room_type') or '').strip()
    rate_name = str(item.get('rate_name') or '').strip()
    display_name = str(item.get('display_name') or rate_name or room_name or '').strip()
    gid = str(item.get('gid') or '').strip()
    hid = str(item.get('hid') or '').strip()
    if not any([room_name, rate_name, display_name, gid, hid]):
        return None
    return {
        'room_name': room_name,
        'rate_name': rate_name,
        'display_name': display_name,
        'gid': gid,
        'hid': hid,
        'observed_price': price,
    }



def save_merchant_price_history(
    db: Session,
    *,
    shop_id: int,
    items: list[dict],
    source: str = 'merchant_preview',
    collected_at: str | None = None,
) -> int:
    ensure_merchant_price_history_table(db)
    normalized_items = [normalized for item in items if isinstance(item, dict) for normalized in [_normalize_price_item(item)] if normalized]
    if not normalized_items:
        return 0
    collected_value = str(collected_at or datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    inserted = 0
    try:
        for item in normalized_items:
            db.execute(
                text(
                    """
                    INSERT INTO merchant_price_history
                    (shop_id, room_name, rate_name, display_name, gid, hid, observed_price, source, collected_at, created_at)
                    VALUES
                    (:shop_id, :room_name, :rate_name, :display_name, :gid, :hid, :observed_price, :source, :collected_at, NOW())
                    """
                ),
                {
                    'shop_id': int(shop_id),
                    'room_name': item['room_name'][:255],
                    'rate_name': item['rate_name'][:255],
                    'display_name': item['display_name'][:255],
                    'gid': item['gid'][:128],
                    'hid': item['hid'][:128],
                    'observed_price': item['observed_price'],
                    'source': str(source or 'merchant_preview')[:32],
                    'collected_at': collected_value,
                },
            )
            inserted += 1
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError(str(exc)) from exc
    return inserted



def get_merchant_price_history_summary(
    db: Session,
    *,
    shop_id: int,
    room_name: str = '',
    rate_name: str = '',
    gid: str = '',
    hid: str = '',
    days: int = 30,
) -> dict:
    ensure_merchant_price_history_table(db)
    normalized_room_name = str(room_name or '').strip()
    normalized_rate_name = str(rate_name or '').strip()
    normalized_gid = str(gid or '').strip()
    normalized_hid = str(hid or '').strip()
    params = {
        'shop_id': int(shop_id),
        'days': max(1, int(days or 30)),
        'room_name': normalized_room_name,
        'rate_name': normalized_rate_name,
        'gid': normalized_gid,
        'hid': normalized_hid,
    }
    clauses = ["shop_id = :shop_id", "collected_at >= DATE_SUB(NOW(), INTERVAL :days DAY)"]
    identity_clauses: list[str] = []
    if normalized_gid and normalized_hid:
        identity_clauses.append('(gid = :gid AND hid = :hid)')
    if normalized_room_name and normalized_rate_name:
        identity_clauses.append('(room_name = :room_name AND rate_name = :rate_name)')
    elif normalized_rate_name:
        identity_clauses.append('(rate_name = :rate_name)')
    elif normalized_room_name:
        identity_clauses.append('(room_name = :room_name)')
    if not identity_clauses:
        return {
            'price_count': 0,
            'price_min': None,
            'price_max': None,
            'price_avg': None,
            'latest_price': None,
            'latest_collected_at': None,
        }
    clauses.append('(' + ' OR '.join(identity_clauses) + ')')
    where_sql = ' AND '.join(clauses)
    try:
        agg_row = db.execute(
            text(
                f"""
                SELECT COUNT(*) AS price_count,
                       MIN(observed_price) AS price_min,
                       MAX(observed_price) AS price_max,
                       ROUND(AVG(observed_price), 2) AS price_avg
                FROM merchant_price_history
                WHERE {where_sql}
                """
            ),
            params,
        ).mappings().first()
        latest_row = db.execute(
            text(
                f"""
                SELECT observed_price, collected_at
                FROM merchant_price_history
                WHERE {where_sql}
                ORDER BY collected_at DESC, id DESC
                LIMIT 1
                """
            ),
            params,
        ).mappings().first()
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc
    agg = dict(agg_row or {})
    latest = dict(latest_row or {})
    price_count = int(agg.get('price_count') or 0)
    return {
        'price_count': price_count,
        'price_min': float(agg['price_min']) if agg.get('price_min') is not None else None,
        'price_max': float(agg['price_max']) if agg.get('price_max') is not None else None,
        'price_avg': float(agg['price_avg']) if agg.get('price_avg') is not None else None,
        'latest_price': float(latest['observed_price']) if latest.get('observed_price') is not None else None,
        'latest_collected_at': str(latest['collected_at']) if latest.get('collected_at') else None,
    }


def get_latest_merchant_price_snapshot(
    db: Session,
    *,
    shop_id: int,
    limit: int = 50,
) -> dict:
    ensure_merchant_price_history_table(db)
    normalized_limit = max(1, min(int(limit or 50), 200))
    try:
        latest_row = db.execute(
            text(
                """
                SELECT collected_at
                FROM merchant_price_history
                WHERE shop_id = :shop_id
                ORDER BY collected_at DESC, id DESC
                LIMIT 1
                """
            ),
            {'shop_id': int(shop_id)},
        ).mappings().first()
        if latest_row is None or not latest_row.get('collected_at'):
            return {
                'shop_id': int(shop_id),
                'collected_at': None,
                'item_count': 0,
                'items': [],
            }
        collected_at = latest_row['collected_at']
        rows = db.execute(
            text(
                """
                SELECT room_name, rate_name, display_name, gid, hid, observed_price, source, collected_at
                FROM merchant_price_history
                WHERE shop_id = :shop_id AND collected_at = :collected_at
                ORDER BY id ASC
                LIMIT :limit
                """
            ),
            {
                'shop_id': int(shop_id),
                'collected_at': collected_at,
                'limit': normalized_limit,
            },
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc

    items = [
        {
            'room_name': str(row.get('room_name') or '').strip(),
            'rate_name': str(row.get('rate_name') or '').strip(),
            'display_name': str(row.get('display_name') or row.get('rate_name') or row.get('room_name') or '').strip(),
            'gid': str(row.get('gid') or '').strip(),
            'hid': str(row.get('hid') or '').strip(),
            'observed_price': float(row['observed_price']) if row.get('observed_price') is not None else None,
            'source': str(row.get('source') or '').strip(),
            'collected_at': str(row['collected_at']) if row.get('collected_at') else None,
        }
        for row in rows
    ]
    return {
        'shop_id': int(shop_id),
        'collected_at': str(collected_at),
        'item_count': len(items),
        'items': items,
    }
