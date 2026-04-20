from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

_ALLOWED_AUDIT_MODES = {"preview", "dry_run", "formal_submit"}


def _json_dumps(payload: dict | list | None) -> str:
    """Serialize one audit payload safely."""
    return json.dumps(payload or {}, ensure_ascii=False, default=str)


def _json_loads(payload_json: object) -> dict | list:
    raw_value = str(payload_json or '').strip()
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, (dict, list)) else {}


def ensure_merchant_pricing_audit_table(db: Session) -> None:
    """Create the merchant pricing audit table when it does not exist."""
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS merchant_pricing_audits (
              id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
              shop_id BIGINT UNSIGNED NOT NULL,
              stage VARCHAR(32) NOT NULL,
              audit_mode VARCHAR(32) NOT NULL,
              status VARCHAR(32) NOT NULL DEFAULT 'success',
              item_count INT NOT NULL DEFAULT 0,
              action_count INT NOT NULL DEFAULT 0,
              payload_json LONGTEXT NOT NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (id),
              KEY idx_merchant_pricing_audits_shop_time (shop_id, created_at),
              KEY idx_merchant_pricing_audits_stage (shop_id, stage, audit_mode)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    )


def create_merchant_pricing_audit(
    db: Session,
    *,
    shop_id: int,
    stage: str,
    audit_mode: str,
    status: str,
    item_count: int,
    action_count: int = 0,
    payload: dict | list | None = None,
) -> dict:
    """Persist one merchant pricing audit entry and return the normalized result."""
    normalized_mode = str(audit_mode or '').strip().lower()
    if normalized_mode not in _ALLOWED_AUDIT_MODES:
        raise ValueError(f'unsupported audit_mode: {audit_mode}')
    normalized_stage = str(stage or '').strip().lower() or 'unknown'
    normalized_status = str(status or '').strip().lower() or 'unknown'
    normalized_item_count = max(0, int(item_count or 0))
    normalized_action_count = max(0, int(action_count or 0))

    ensure_merchant_pricing_audit_table(db)
    try:
        result = db.execute(
            text(
                """
                INSERT INTO merchant_pricing_audits
                (shop_id, stage, audit_mode, status, item_count, action_count, payload_json, created_at)
                VALUES
                (:shop_id, :stage, :audit_mode, :status, :item_count, :action_count, :payload_json, NOW())
                """
            ),
            {
                'shop_id': int(shop_id),
                'stage': normalized_stage,
                'audit_mode': normalized_mode,
                'status': normalized_status,
                'item_count': normalized_item_count,
                'action_count': normalized_action_count,
                'payload_json': _json_dumps(payload),
            },
        )
        audit_id = int(result.lastrowid)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError(str(exc)) from exc

    return {
        'audit_id': audit_id,
        'shop_id': int(shop_id),
        'stage': normalized_stage,
        'audit_mode': normalized_mode,
        'status': normalized_status,
        'item_count': normalized_item_count,
        'action_count': normalized_action_count,
    }


def get_latest_merchant_pricing_audit(
    db: Session,
    *,
    shop_id: int,
    stage: str,
    audit_mode: str | None = None,
) -> dict | None:
    """Load the latest merchant pricing audit entry for one stage."""
    normalized_stage = str(stage or '').strip().lower()
    if not normalized_stage:
        raise ValueError('stage is required')

    normalized_mode = str(audit_mode or '').strip().lower()
    if normalized_mode and normalized_mode not in _ALLOWED_AUDIT_MODES:
        raise ValueError(f'unsupported audit_mode: {audit_mode}')

    ensure_merchant_pricing_audit_table(db)
    sql = """
        SELECT id, shop_id, stage, audit_mode, status, item_count, action_count, payload_json, created_at
        FROM merchant_pricing_audits
        WHERE shop_id = :shop_id
          AND stage = :stage
    """
    params = {'shop_id': int(shop_id), 'stage': normalized_stage}
    if normalized_mode:
        sql += ' AND audit_mode = :audit_mode'
        params['audit_mode'] = normalized_mode
    sql += ' ORDER BY created_at DESC, id DESC LIMIT 1'

    row = db.execute(text(sql), params).mappings().first()
    if not row:
        return None

    payload = _json_loads(row.get('payload_json'))
    return {
        'audit_id': int(row['id']),
        'shop_id': int(row['shop_id']),
        'stage': str(row['stage']),
        'audit_mode': str(row['audit_mode']),
        'status': str(row['status']),
        'item_count': int(row.get('item_count') or 0),
        'action_count': int(row.get('action_count') or 0),
        'payload': payload,
        'created_at': str(row['created_at']) if row.get('created_at') else None,
    }
