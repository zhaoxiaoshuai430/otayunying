"""Shop configuration service for multi-hotel support."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings


@dataclass(frozen=True)
class ShopConfig:
    """Resolved configuration for a single managed hotel."""

    tenant_id: int
    shop_id: int
    name: str
    status: str
    source: str
    fliggy_hotel_id: str
    fliggy_room_status_hotel_id: str
    fliggy_app_key: str
    fliggy_app_secret: str
    fliggy_session: str
    room_status_auto_enabled: bool
    room_status_total_rooms: int
    room_status_available_rooms: int
    room_status_current_price: float
    daily_revenue_auto_enabled: bool
    fliggy_price_push_enabled: bool = False
    fliggy_price_push_method: str = ''
    fliggy_price_push_payload_json: str = ''
    fliggy_merchant_login_url: str = ''
    fliggy_merchant_price_url: str = ''
    fliggy_merchant_storage_state: str = ''
    fliggy_merchant_price_selectors_json: str = ''


def _normalize_status(status: object) -> str:
    raw = str(status or 'enabled').strip().lower()
    if raw in {'disabled', 'inactive'}:
        return 'disabled'
    return 'enabled'


def _looks_garbled_text(value: object) -> bool:
    text = str(value or '').strip()
    if not text:
        return False
    return '?' in text and any(ch != '?' for ch in text)


def _build_default_shop_config() -> ShopConfig:
    settings = get_settings()
    return ShopConfig(
        tenant_id=1,
        shop_id=1,
        name='Default Shop',
        status='enabled',
        source='settings_default',
        fliggy_hotel_id=str(getattr(settings, 'fliggy_hotel_id', '') or ''),
        fliggy_room_status_hotel_id=str(getattr(settings, 'fliggy_room_status_hotel_id', '') or ''),
        fliggy_app_key=str(getattr(settings, 'fliggy_app_key', '') or ''),
        fliggy_app_secret=str(getattr(settings, 'fliggy_app_secret', '') or ''),
        fliggy_session=str(getattr(settings, 'fliggy_session', '') or ''),
        room_status_auto_enabled=bool(getattr(settings, 'room_status_auto_enabled', False)),
        room_status_total_rooms=max(1, int(getattr(settings, 'room_status_total_rooms', 20) or 20)),
        room_status_available_rooms=max(0, int(getattr(settings, 'room_status_available_rooms', 5) or 5)),
        room_status_current_price=float(getattr(settings, 'room_status_current_price', 299.0) or 299.0),
        daily_revenue_auto_enabled=bool(getattr(settings, 'daily_revenue_auto_enabled', False)),
        fliggy_price_push_enabled=bool(getattr(settings, 'fliggy_price_push_enabled', False)),
        fliggy_price_push_method=str(getattr(settings, 'fliggy_price_push_method', '') or ''),
        fliggy_price_push_payload_json=str(getattr(settings, 'fliggy_price_push_payload_json', '') or ''),
        fliggy_merchant_login_url='',
        fliggy_merchant_price_url='',
        fliggy_merchant_storage_state='',
        fliggy_merchant_price_selectors_json='',
    )


def _column_names(db: Session, table_name: str) -> set[str]:
    try:
        rows = db.execute(text(f'SHOW COLUMNS FROM {table_name}')).mappings().all()
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc
    return {str(row.get('Field') or '').strip() for row in rows}


def _build_shop_select_sql(*, where_sql: str | None = None) -> str:
    where_clause = f'\n                WHERE {where_sql}' if where_sql else ''
    return (
        """
                SELECT tenant_id, id,
                       COALESCE(NULLIF(name, ''), NULLIF(shop_name, ''), CONCAT('Shop ', id)) AS name,
                       shop_name,
                       COALESCE(NULLIF(status, ''), 'enabled') AS status,
                       fliggy_hotel_id, fliggy_room_status_hotel_id,
                       fliggy_app_key, fliggy_app_secret, fliggy_session,
                       room_status_auto_enabled, room_status_total_rooms,
                       room_status_available_rooms, room_status_current_price,
                       daily_revenue_auto_enabled, fliggy_price_push_enabled,
                       fliggy_price_push_method, fliggy_price_push_payload_json,
                       fliggy_merchant_login_url, fliggy_merchant_price_url,
                       fliggy_merchant_storage_state, fliggy_merchant_price_selectors_json
                FROM shops"""
        + where_clause
    )


def ensure_shops_table(db: Session) -> None:
    """Create the shops table when it does not exist."""

    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS shops (
              id BIGINT UNSIGNED NOT NULL,
              tenant_id BIGINT UNSIGNED NOT NULL DEFAULT 1,
              name VARCHAR(128) NOT NULL DEFAULT 'Shop',
              platform VARCHAR(32) NOT NULL DEFAULT 'fliggy',
              shop_name VARCHAR(128) NOT NULL DEFAULT 'Shop',
              shop_external_id VARCHAR(128) NOT NULL DEFAULT '',
              status VARCHAR(32) NOT NULL DEFAULT 'enabled',
              fliggy_hotel_id VARCHAR(64) NOT NULL DEFAULT '',
              fliggy_room_status_hotel_id VARCHAR(64) NOT NULL DEFAULT '',
              fliggy_app_key VARCHAR(128) NOT NULL DEFAULT '',
              fliggy_app_secret VARCHAR(255) NOT NULL DEFAULT '',
              fliggy_session VARCHAR(255) NOT NULL DEFAULT '',
              room_status_auto_enabled TINYINT(1) NOT NULL DEFAULT 0,
              room_status_total_rooms INT UNSIGNED NOT NULL DEFAULT 20,
              room_status_available_rooms INT UNSIGNED NOT NULL DEFAULT 5,
              room_status_current_price DECIMAL(10, 2) NOT NULL DEFAULT 299.00,
              daily_revenue_auto_enabled TINYINT(1) NOT NULL DEFAULT 0,
              fliggy_price_push_enabled TINYINT(1) NOT NULL DEFAULT 0,
              fliggy_price_push_method VARCHAR(128) NOT NULL DEFAULT '',
              fliggy_price_push_payload_json LONGTEXT NULL,
              fliggy_merchant_login_url VARCHAR(2048) NOT NULL DEFAULT '',
              fliggy_merchant_price_url VARCHAR(2048) NOT NULL DEFAULT '',
              fliggy_merchant_storage_state VARCHAR(255) NOT NULL DEFAULT '',
              fliggy_merchant_price_selectors_json LONGTEXT NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (id),
              UNIQUE KEY uniq_shops_external (shop_external_id),
              KEY idx_shops_status (status),
              KEY idx_shops_tenant_status (tenant_id, status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    )

    alter_statements = [
        "ALTER TABLE shops ADD COLUMN tenant_id BIGINT UNSIGNED NOT NULL DEFAULT 1 AFTER id",
        "ALTER TABLE shops ADD COLUMN name VARCHAR(128) NOT NULL DEFAULT 'Shop' AFTER tenant_id",
        "ALTER TABLE shops ADD COLUMN platform VARCHAR(32) NOT NULL DEFAULT 'fliggy' AFTER name",
        "ALTER TABLE shops ADD COLUMN shop_name VARCHAR(128) NOT NULL DEFAULT 'Shop' AFTER platform",
        "ALTER TABLE shops ADD COLUMN shop_external_id VARCHAR(128) NOT NULL DEFAULT '' AFTER shop_name",
        "ALTER TABLE shops ADD UNIQUE KEY uniq_shops_external (shop_external_id)",
        "ALTER TABLE shops ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'enabled' AFTER shop_external_id",
        "ALTER TABLE shops ADD COLUMN fliggy_hotel_id VARCHAR(64) NOT NULL DEFAULT '' AFTER status",
        "ALTER TABLE shops ADD COLUMN fliggy_room_status_hotel_id VARCHAR(64) NOT NULL DEFAULT '' AFTER fliggy_hotel_id",
        "ALTER TABLE shops ADD COLUMN fliggy_app_key VARCHAR(128) NOT NULL DEFAULT '' AFTER fliggy_room_status_hotel_id",
        "ALTER TABLE shops ADD COLUMN fliggy_app_secret VARCHAR(255) NOT NULL DEFAULT '' AFTER fliggy_app_key",
        "ALTER TABLE shops ADD COLUMN fliggy_session VARCHAR(255) NOT NULL DEFAULT '' AFTER fliggy_app_secret",
        "ALTER TABLE shops ADD COLUMN room_status_auto_enabled TINYINT(1) NOT NULL DEFAULT 0 AFTER fliggy_session",
        "ALTER TABLE shops ADD COLUMN room_status_total_rooms INT UNSIGNED NOT NULL DEFAULT 20 AFTER room_status_auto_enabled",
        "ALTER TABLE shops ADD COLUMN room_status_available_rooms INT UNSIGNED NOT NULL DEFAULT 5 AFTER room_status_total_rooms",
        "ALTER TABLE shops ADD COLUMN room_status_current_price DECIMAL(10, 2) NOT NULL DEFAULT 299.00 AFTER room_status_available_rooms",
        "ALTER TABLE shops ADD COLUMN daily_revenue_auto_enabled TINYINT(1) NOT NULL DEFAULT 0 AFTER room_status_current_price",
        "ALTER TABLE shops ADD KEY idx_shops_tenant_status (tenant_id, status)",
        "ALTER TABLE shops ADD COLUMN fliggy_price_push_enabled TINYINT(1) NOT NULL DEFAULT 0 AFTER daily_revenue_auto_enabled",
        "ALTER TABLE shops ADD COLUMN fliggy_price_push_method VARCHAR(128) NOT NULL DEFAULT '' AFTER fliggy_price_push_enabled",
        "ALTER TABLE shops ADD COLUMN fliggy_price_push_payload_json LONGTEXT NULL AFTER fliggy_price_push_method",
        "ALTER TABLE shops ADD COLUMN fliggy_merchant_login_url VARCHAR(2048) NOT NULL DEFAULT '' AFTER fliggy_price_push_payload_json",
        "ALTER TABLE shops ADD COLUMN fliggy_merchant_price_url VARCHAR(2048) NOT NULL DEFAULT '' AFTER fliggy_merchant_login_url",
        "ALTER TABLE shops ADD COLUMN fliggy_merchant_storage_state VARCHAR(255) NOT NULL DEFAULT '' AFTER fliggy_merchant_price_url",
        "ALTER TABLE shops ADD COLUMN fliggy_merchant_price_selectors_json LONGTEXT NULL AFTER fliggy_merchant_storage_state",
    ]
    for statement in alter_statements:
        try:
            db.execute(text(statement))
        except Exception:
            db.rollback()


def _row_to_shop_config(row: dict) -> ShopConfig:
    settings_default = _build_default_shop_config()
    shop_id = int(row['id'])
    tenant_id = int(row.get('tenant_id') or 1)
    can_fallback = shop_id == settings_default.shop_id and tenant_id == settings_default.tenant_id

    def pick_text(key: str, default: str) -> str:
        value = str(row.get(key) or '').strip()
        return value or (default if can_fallback else '')

    def pick_int(key: str, default: int) -> int:
        value = row.get(key)
        if value in (None, ''):
            return default
        return int(value)

    def pick_float(key: str, default: float) -> float:
        value = row.get(key)
        if value in (None, ''):
            return default
        return float(value)

    resolved_name = str(row.get('name') or '').strip()
    fallback_name = str(row.get('shop_name') or '').strip()
    if not resolved_name or _looks_garbled_text(resolved_name):
        resolved_name = fallback_name or f'Shop {shop_id}'

    return ShopConfig(
        tenant_id=tenant_id,
        shop_id=shop_id,
        name=resolved_name,
        status=_normalize_status(row.get('status')),
        source='database',
        fliggy_hotel_id=pick_text('fliggy_hotel_id', settings_default.fliggy_hotel_id),
        fliggy_room_status_hotel_id=pick_text('fliggy_room_status_hotel_id', settings_default.fliggy_room_status_hotel_id),
        fliggy_app_key=pick_text('fliggy_app_key', settings_default.fliggy_app_key),
        fliggy_app_secret=pick_text('fliggy_app_secret', settings_default.fliggy_app_secret),
        fliggy_session=pick_text('fliggy_session', settings_default.fliggy_session),
        room_status_auto_enabled=bool(row.get('room_status_auto_enabled')),
        room_status_total_rooms=max(1, pick_int('room_status_total_rooms', settings_default.room_status_total_rooms)),
        room_status_available_rooms=max(0, pick_int('room_status_available_rooms', settings_default.room_status_available_rooms)),
        room_status_current_price=pick_float('room_status_current_price', settings_default.room_status_current_price),
        daily_revenue_auto_enabled=bool(row.get('daily_revenue_auto_enabled')),
        fliggy_price_push_enabled=bool(row.get('fliggy_price_push_enabled')),
        fliggy_price_push_method=pick_text('fliggy_price_push_method', settings_default.fliggy_price_push_method),
        fliggy_price_push_payload_json=pick_text('fliggy_price_push_payload_json', settings_default.fliggy_price_push_payload_json),
        fliggy_merchant_login_url=pick_text('fliggy_merchant_login_url', ''),
        fliggy_merchant_price_url=pick_text('fliggy_merchant_price_url', ''),
        fliggy_merchant_storage_state=pick_text('fliggy_merchant_storage_state', ''),
        fliggy_merchant_price_selectors_json=pick_text('fliggy_merchant_price_selectors_json', ''),
    )


def _existing_shop_row(db: Session, shop_id: int) -> dict[str, Any] | None:
    row = db.execute(text('SELECT * FROM shops WHERE id = :shop_id LIMIT 1'), {'shop_id': int(shop_id)}).mappings().first()
    return dict(row) if row else None


def _build_shop_write_payload(*, existing_row: dict[str, Any] | None, shop_data: dict[str, Any]) -> dict[str, Any]:
    """Build one write payload that works with both current and legacy shops schemas."""

    existing_row = existing_row or {}

    def existing_value(*keys: str, default: object = '') -> object:
        for key in keys:
            if existing_row.get(key) not in (None, ''):
                return existing_row.get(key)
        return default

    def pick_sensitive(key: str) -> str:
        value = str(shop_data.get(key) or '').strip()
        if value:
            return value
        return str(existing_value(key, default='') or '')

    def pick_text(key: str, *, fallback_keys: tuple[str, ...] = ()) -> str:
        value = str(shop_data.get(key) or '').strip()
        if value:
            return value
        return str(existing_value(key, *fallback_keys, default='') or '')

    room_total = max(1, int(shop_data.get('room_status_total_rooms') or existing_value('room_status_total_rooms', default=20) or 20))
    room_available = max(0, int(shop_data.get('room_status_available_rooms') or existing_value('room_status_available_rooms', default=0) or 0))
    room_available = min(room_available, room_total)

    shop_id = int(shop_data['shop_id'])
    name = str(shop_data['name']).strip()
    payload = {
        'id': shop_id,
        'tenant_id': int(shop_data.get('tenant_id') or existing_value('tenant_id', default=1) or 1),
        'name': name,
        'platform': pick_text('platform', fallback_keys=('platform',)) or 'fliggy',
        'shop_name': pick_text('shop_name', fallback_keys=('shop_name', 'name')) or name,
        'shop_external_id': pick_text('shop_external_id', fallback_keys=('shop_external_id',)) or f'fliggy-shop-{shop_id:03d}',
        'status': _normalize_status(shop_data.get('status') or existing_value('status', default='enabled')),
        'fliggy_hotel_id': pick_text('fliggy_hotel_id'),
        'fliggy_room_status_hotel_id': pick_text('fliggy_room_status_hotel_id'),
        'fliggy_app_key': pick_sensitive('fliggy_app_key'),
        'fliggy_app_secret': pick_sensitive('fliggy_app_secret'),
        'fliggy_session': pick_sensitive('fliggy_session'),
        'room_status_auto_enabled': 1 if shop_data.get('room_status_auto_enabled') else 0,
        'room_status_total_rooms': room_total,
        'room_status_available_rooms': room_available,
        'room_status_current_price': round(float(shop_data.get('room_status_current_price') or existing_value('room_status_current_price', default=0) or 0), 2),
        'daily_revenue_auto_enabled': 1 if shop_data.get('daily_revenue_auto_enabled') else 0,
        'fliggy_price_push_enabled': 1 if shop_data.get('fliggy_price_push_enabled') else 0,
        'fliggy_price_push_method': pick_text('fliggy_price_push_method'),
        'fliggy_price_push_payload_json': pick_text('fliggy_price_push_payload_json'),
        'fliggy_merchant_login_url': pick_text('fliggy_merchant_login_url'),
        'fliggy_merchant_price_url': pick_text('fliggy_merchant_price_url'),
        'fliggy_merchant_storage_state': pick_text('fliggy_merchant_storage_state'),
        'fliggy_merchant_price_selectors_json': pick_text('fliggy_merchant_price_selectors_json'),
    }
    return payload


def _filtered_shop_columns(columns: set[str], payload: dict[str, Any]) -> list[str]:
    ordered = [
        'id',
        'tenant_id',
        'name',
        'platform',
        'shop_name',
        'shop_external_id',
        'status',
        'fliggy_hotel_id',
        'fliggy_room_status_hotel_id',
        'fliggy_app_key',
        'fliggy_app_secret',
        'fliggy_session',
        'room_status_auto_enabled',
        'room_status_total_rooms',
        'room_status_available_rooms',
        'room_status_current_price',
        'daily_revenue_auto_enabled',
        'fliggy_price_push_enabled',
        'fliggy_price_push_method',
        'fliggy_price_push_payload_json',
        'fliggy_merchant_login_url',
        'fliggy_merchant_price_url',
        'fliggy_merchant_storage_state',
        'fliggy_merchant_price_selectors_json',
    ]
    return [column for column in ordered if column in columns and column in payload]


def get_shop_config(db: Session, shop_id: int) -> ShopConfig:
    """Load resolved config for a shop."""

    try:
        ensure_shops_table(db)
        row = db.execute(text(_build_shop_select_sql(where_sql='id = :shop_id') + '\n                LIMIT 1'), {'shop_id': int(shop_id)}).mappings().first()
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc

    if row:
        return _row_to_shop_config(dict(row))
    if int(shop_id) == 1:
        return _build_default_shop_config()
    raise ValueError(f'shop not found: {shop_id}')


def list_shop_configs(db: Session, *, only_enabled: bool = False) -> list[ShopConfig]:
    """List all known shops plus the legacy default shop when needed."""

    try:
        ensure_shops_table(db)
        rows = db.execute(text(_build_shop_select_sql() + '\n                ORDER BY id ASC')).mappings().all()
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc

    configs = [_row_to_shop_config(dict(row)) for row in rows]
    if not any(config.shop_id == 1 for config in configs):
        configs.insert(0, _build_default_shop_config())
    if only_enabled:
        return [config for config in configs if config.status == 'enabled']
    return configs


def get_room_status_defaults(db: Session, shop_id: int) -> dict[str, float | int]:
    """Return default room status snapshot values for a shop."""

    config = get_shop_config(db=db, shop_id=shop_id)
    available_rooms = max(0, min(config.room_status_available_rooms, config.room_status_total_rooms))
    return {
        'total_rooms': config.room_status_total_rooms,
        'available_rooms': available_rooms,
        'current_price': config.room_status_current_price,
    }


def build_shop_public_dict(config: ShopConfig, *, include_template: bool = False) -> dict:
    """Build API-safe shop summary without leaking secrets."""

    result = {
        'tenant_id': config.tenant_id,
        'shop_id': config.shop_id,
        'name': config.name,
        'status': config.status,
        'source': config.source,
        'fliggy_hotel_id': config.fliggy_hotel_id,
        'fliggy_room_status_hotel_id': config.fliggy_room_status_hotel_id,
        'room_status_auto_enabled': config.room_status_auto_enabled,
        'room_status_total_rooms': config.room_status_total_rooms,
        'room_status_available_rooms': config.room_status_available_rooms,
        'room_status_current_price': config.room_status_current_price,
        'daily_revenue_auto_enabled': config.daily_revenue_auto_enabled,
        'fliggy_price_push_enabled': config.fliggy_price_push_enabled,
        'fliggy_price_push_method': config.fliggy_price_push_method,
        'has_fliggy_price_push_template': bool(config.fliggy_price_push_payload_json),
        'has_fliggy_credentials': bool(config.fliggy_app_key and config.fliggy_app_secret),
        'has_fliggy_session': bool(config.fliggy_session),
        'fliggy_merchant_login_url': config.fliggy_merchant_login_url,
        'fliggy_merchant_price_url': config.fliggy_merchant_price_url,
        'fliggy_merchant_storage_state': config.fliggy_merchant_storage_state,
        'has_fliggy_merchant_selectors': bool(config.fliggy_merchant_price_selectors_json),
    }
    if include_template:
        result['fliggy_price_push_payload_json'] = config.fliggy_price_push_payload_json
        result['fliggy_merchant_price_selectors_json'] = config.fliggy_merchant_price_selectors_json
    return result


def upsert_shop(db: Session, shop_data: dict) -> dict:
    """Create or update a managed hotel config."""

    shop_id = int(shop_data['shop_id'])
    try:
        ensure_shops_table(db)
        existing_row = _existing_shop_row(db=db, shop_id=shop_id)
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc

    existing = _row_to_shop_config(existing_row) if existing_row else None
    tenant_id = int(shop_data.get('tenant_id') or (getattr(existing, 'tenant_id', 0) if existing else 0) or 1)
    if existing is not None and int(getattr(existing, 'tenant_id', 0) or 0) not in (0, tenant_id):
        raise ValueError(f'shop {shop_id} belongs to another tenant')

    shop_data = {**shop_data, 'tenant_id': tenant_id}
    payload = _build_shop_write_payload(existing_row=existing_row, shop_data=shop_data)

    try:
        columns = _column_names(db=db, table_name='shops')
        write_columns = _filtered_shop_columns(columns=columns, payload=payload)
        insert_columns = ', '.join(write_columns)
        value_columns = ', '.join(f':{column}' for column in write_columns)
        update_columns = [f'{column} = VALUES({column})' for column in write_columns if column != 'id']
        if 'updated_at' in columns:
            update_columns.append('updated_at = CURRENT_TIMESTAMP')

        db.execute(
            text(
                f"""
                INSERT INTO shops ({insert_columns})
                VALUES ({value_columns})
                ON DUPLICATE KEY UPDATE
                    {', '.join(update_columns)}
                """
            ),
            {column: payload[column] for column in write_columns},
        )
        db.commit()
        return build_shop_public_dict(get_shop_config(db=db, shop_id=shop_id))
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError(str(exc)) from exc


def get_shop_config_for_tenant(db: Session, *, tenant_id: int, shop_id: int) -> ShopConfig:
    """Load resolved config for a shop and enforce tenant ownership."""

    config = get_shop_config(db=db, shop_id=shop_id)
    if int(getattr(config, 'tenant_id', 0) or 0) != int(tenant_id):
        raise ValueError(f'shop not found: {shop_id}')
    return config


def list_shop_configs_for_tenant(db: Session, *, tenant_id: int, only_enabled: bool = False) -> list[ShopConfig]:
    """List all shops under a tenant."""

    try:
        ensure_shops_table(db)
        rows = db.execute(
            text(_build_shop_select_sql(where_sql='tenant_id = :tenant_id') + '\n                ORDER BY id ASC'),
            {'tenant_id': int(tenant_id)},
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc

    configs = [_row_to_shop_config(dict(row)) for row in rows]
    if int(tenant_id) == 1 and not any(config.shop_id == 1 for config in configs):
        configs.insert(0, _build_default_shop_config())
    if only_enabled:
        return [config for config in configs if config.status == 'enabled']
    return configs


