from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

_SUPPORTED_PLATFORMS = {'fliggy'}
_ACTIVE_STATUSES = {'active', 'enabled'}
_DISABLED_STATUSES = {'disabled', 'inactive'}
_ALLOWED_STATUSES = {'draft', 'active', 'disabled'}


def _normalize_platform(platform: object | None) -> str:
    value = str(platform or 'fliggy').strip().lower() or 'fliggy'
    if value not in _SUPPORTED_PLATFORMS:
        raise ValueError(f'unsupported merchant platform: {value}')
    return value


def _normalize_status(status: object | None) -> str:
    value = str(status or 'draft').strip().lower() or 'draft'
    if value in _ACTIVE_STATUSES:
        return 'active'
    if value in _DISABLED_STATUSES:
        return 'disabled'
    if value not in _ALLOWED_STATUSES:
        raise ValueError(f'unsupported mapping status: {value}')
    return value


def _drop_legacy_last_seen_price_column(db: Session) -> None:
    column_count = db.execute(
        text(
            """
            SELECT COUNT(*) AS column_count
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = 'merchant_price_mappings'
              AND column_name = 'last_seen_price'
            """
        )
    ).mappings().first()
    if not column_count or int(column_count.get('column_count') or 0) < 1:
        return
    db.execute(text('ALTER TABLE merchant_price_mappings DROP COLUMN last_seen_price'))


def ensure_merchant_price_mapping_table(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS merchant_price_mappings (
              id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
              tenant_id BIGINT UNSIGNED NOT NULL DEFAULT 1,
              shop_id BIGINT UNSIGNED NOT NULL,
              platform VARCHAR(32) NOT NULL DEFAULT 'fliggy',
              room_name VARCHAR(255) NOT NULL,
              rate_name VARCHAR(255) NOT NULL DEFAULT '',
              merchant_room_key VARCHAR(128) NOT NULL DEFAULT '',
              merchant_rate_key VARCHAR(128) NOT NULL DEFAULT '',
              gid VARCHAR(128) NOT NULL DEFAULT '',
              hid VARCHAR(128) NOT NULL DEFAULT '',
              status VARCHAR(32) NOT NULL DEFAULT 'draft',
              notes VARCHAR(255) NOT NULL DEFAULT '',
              last_seen_at DATETIME NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (id),
              UNIQUE KEY uk_merchant_price_mapping_identity (shop_id, platform, room_name, rate_name),
              KEY idx_merchant_price_mapping_tenant_shop (tenant_id, shop_id),
              KEY idx_merchant_price_mapping_status (shop_id, status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    )
    try:
        _drop_legacy_last_seen_price_column(db)
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc


def _mapping_row_to_public(row: dict) -> dict:
    gid = str(row.get('gid') or '').strip()
    hid = str(row.get('hid') or '').strip()
    status = _normalize_status(row.get('status'))
    return {
        'mapping_id': int(row.get('id') or 0),
        'tenant_id': int(row.get('tenant_id') or 1),
        'shop_id': int(row['shop_id']),
        'platform': _normalize_platform(row.get('platform')),
        'room_name': str(row.get('room_name') or '').strip(),
        'rate_name': str(row.get('rate_name') or '').strip(),
        'merchant_room_key': str(row.get('merchant_room_key') or '').strip(),
        'merchant_rate_key': str(row.get('merchant_rate_key') or '').strip(),
        'gid': gid,
        'hid': hid,
        'status': status,
        'notes': str(row.get('notes') or '').strip(),
        'last_seen_at': str(row['last_seen_at']) if row.get('last_seen_at') else None,
        'is_complete': bool(gid and hid and status == 'active'),
    }


def _select_mapping_row(db: Session, *, shop_id: int, platform: str, room_name: str, rate_name: str) -> dict | None:
    row = db.execute(
        text(
            """
            SELECT id, tenant_id, shop_id, platform, room_name, rate_name, merchant_room_key,
                   merchant_rate_key, gid, hid, status, notes, last_seen_at
            FROM merchant_price_mappings
            WHERE shop_id = :shop_id AND platform = :platform AND room_name = :room_name AND rate_name = :rate_name
            LIMIT 1
            """
        ),
        {
            'shop_id': int(shop_id),
            'platform': platform,
            'room_name': room_name,
            'rate_name': rate_name,
        },
    ).mappings().first()
    return dict(row) if row else None


def get_merchant_price_mapping(
    db: Session,
    *,
    shop_id: int,
    tenant_id: int = 1,
    platform: str = 'fliggy',
    room_name: str,
    rate_name: str = '',
) -> dict | None:
    platform = _normalize_platform(platform)
    normalized_room_name = str(room_name or '').strip()
    normalized_rate_name = str(rate_name or '').strip()
    if not normalized_room_name:
        raise ValueError('room_name is required')

    ensure_merchant_price_mapping_table(db)
    try:
        row = _select_mapping_row(
            db=db,
            shop_id=shop_id,
            platform=platform,
            room_name=normalized_room_name,
            rate_name=normalized_rate_name,
        )
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc
    if row is None:
        return None
    mapping = _mapping_row_to_public(row)
    if int(mapping['tenant_id']) != int(tenant_id):
        raise ValueError(f'merchant price mapping not found for shop: {shop_id}')
    return mapping


def list_merchant_price_mappings(
    db: Session,
    *,
    shop_id: int,
    tenant_id: int = 1,
    platform: str = 'fliggy',
    only_enabled: bool = False,
) -> list[dict]:
    platform = _normalize_platform(platform)
    ensure_merchant_price_mapping_table(db)
    status_sql = " AND status IN ('active', 'enabled')" if only_enabled else ''
    try:
        rows = db.execute(
        text(
            f"""
                SELECT id, tenant_id, shop_id, platform, room_name, rate_name, merchant_room_key,
                       merchant_rate_key, gid, hid, status, notes, last_seen_at
                FROM merchant_price_mappings
                WHERE shop_id = :shop_id AND platform = :platform{status_sql}
                ORDER BY room_name ASC, rate_name ASC, id ASC
                """
            ),
            {'shop_id': int(shop_id), 'platform': platform},
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc

    items = [_mapping_row_to_public(dict(row)) for row in rows if int(row.get('tenant_id') or 1) == int(tenant_id)]
    return items


def upsert_merchant_price_mapping(db: Session, *, mapping_data: dict) -> dict:
    shop_id = int(mapping_data.get('shop_id') or 0)
    if shop_id < 1:
        raise ValueError('shop_id must be positive')

    tenant_id = int(mapping_data.get('tenant_id') or 1)
    platform = _normalize_platform(mapping_data.get('platform'))
    room_name = str(mapping_data.get('room_name') or '').strip()
    rate_name = str(mapping_data.get('rate_name') or '').strip()
    if not room_name:
        raise ValueError('room_name is required')
    status = _normalize_status(mapping_data.get('status'))

    ensure_merchant_price_mapping_table(db)
    try:
        existing_row = _select_mapping_row(
            db=db,
            shop_id=shop_id,
            platform=platform,
            room_name=room_name,
            rate_name=rate_name,
        )
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc

    if existing_row is not None and int(existing_row.get('tenant_id') or 0) not in (0, tenant_id):
        raise ValueError(f'merchant price mapping belongs to another tenant: {shop_id}')

    payload = {
        'tenant_id': tenant_id,
        'shop_id': shop_id,
        'platform': platform,
        'room_name': room_name,
        'rate_name': rate_name,
        'merchant_room_key': str(mapping_data.get('merchant_room_key') or (existing_row or {}).get('merchant_room_key') or '').strip(),
        'merchant_rate_key': str(mapping_data.get('merchant_rate_key') or (existing_row or {}).get('merchant_rate_key') or '').strip(),
        'gid': str(mapping_data.get('gid') or (existing_row or {}).get('gid') or '').strip(),
        'hid': str(mapping_data.get('hid') or (existing_row or {}).get('hid') or '').strip(),
        'status': status,
        'notes': str(mapping_data.get('notes') or (existing_row or {}).get('notes') or '').strip()[:255],
    }

    try:
        if existing_row is None:
            db.execute(
                text(
                    """
                    INSERT INTO merchant_price_mappings
                    (tenant_id, shop_id, platform, room_name, rate_name, merchant_room_key, merchant_rate_key,
                     gid, hid, status, notes, last_seen_at, created_at, updated_at)
                    VALUES
                    (:tenant_id, :shop_id, :platform, :room_name, :rate_name, :merchant_room_key, :merchant_rate_key,
                     :gid, :hid, :status, :notes, NOW(), NOW(), NOW())
                    """
                ),
                payload,
            )
        else:
            db.execute(
                text(
                    """
                    UPDATE merchant_price_mappings
                    SET tenant_id = :tenant_id,
                        merchant_room_key = :merchant_room_key,
                        merchant_rate_key = :merchant_rate_key,
                        gid = :gid,
                        hid = :hid,
                        status = :status,
                        notes = :notes,
                        last_seen_at = NOW(),
                        updated_at = NOW()
                    WHERE shop_id = :shop_id AND platform = :platform AND room_name = :room_name AND rate_name = :rate_name
                    """
                ),
                payload,
            )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError(str(exc)) from exc

    saved = get_merchant_price_mapping(
        db=db,
        shop_id=shop_id,
        tenant_id=tenant_id,
        platform=platform,
        room_name=room_name,
        rate_name=rate_name,
    )
    if saved is None:
        raise RuntimeError('failed to reload merchant price mapping')
    return saved
