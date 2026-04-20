from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash


@dataclass(frozen=True)
class AuthUser:
    user_id: int
    tenant_id: int
    username: str
    is_admin: bool


def ensure_users_table(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS users (
              id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
              tenant_id BIGINT UNSIGNED NOT NULL,
              username VARCHAR(64) NOT NULL,
              password_hash VARCHAR(255) NOT NULL,
              status VARCHAR(32) NOT NULL DEFAULT 'enabled',
              is_admin TINYINT(1) NOT NULL DEFAULT 0,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (id),
              UNIQUE KEY uniq_users_tenant_username (tenant_id, username),
              KEY idx_users_tenant_status (tenant_id, status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    )

    alter_statements = [
        "ALTER TABLE users ADD COLUMN is_admin TINYINT(1) NOT NULL DEFAULT 0 AFTER status",
        "ALTER TABLE users ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'enabled' AFTER password_hash",
        "ALTER TABLE users ADD UNIQUE KEY uniq_users_tenant_username (tenant_id, username)",
        "ALTER TABLE users ADD KEY idx_users_tenant_status (tenant_id, status)",
    ]
    for statement in alter_statements:
        try:
            db.execute(text(statement))
        except Exception:
            db.rollback()


def ensure_user_shop_access_table(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS user_shop_access (
              user_id BIGINT UNSIGNED NOT NULL,
              tenant_id BIGINT UNSIGNED NOT NULL,
              shop_id BIGINT UNSIGNED NOT NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (user_id, shop_id),
              KEY idx_user_shop_tenant_shop (tenant_id, shop_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    )

    alter_statements = [
        "ALTER TABLE user_shop_access ADD COLUMN tenant_id BIGINT UNSIGNED NOT NULL AFTER user_id",
        "ALTER TABLE user_shop_access ADD KEY idx_user_shop_tenant_shop (tenant_id, shop_id)",
    ]
    for statement in alter_statements:
        try:
            db.execute(text(statement))
        except Exception:
            db.rollback()


def _normalize_username(raw: object) -> str:
    value = str(raw or '').strip()
    return value


def upsert_user(
    db: Session,
    *,
    tenant_id: int,
    username: str,
    password: str,
    is_admin: bool = False,
    status: str = 'enabled',
) -> int:
    if tenant_id < 1:
        raise ValueError('tenant_id must be positive')
    username_norm = _normalize_username(username)
    if not username_norm:
        raise ValueError('username must not be empty')
    if not str(password or ''):
        raise ValueError('password must not be empty')

    status_norm = str(status or 'enabled').strip().lower()
    if status_norm not in {'enabled', 'disabled'}:
        status_norm = 'enabled'

    try:
        ensure_users_table(db)
        row = (
            db.execute(
                text(
                    """
                    SELECT id
                    FROM users
                    WHERE tenant_id = :tenant_id AND username = :username
                    LIMIT 1
                    """
                ),
                {'tenant_id': int(tenant_id), 'username': username_norm},
            )
            .mappings()
            .first()
        )

        password_hash = generate_password_hash(password)
        if row and row.get('id') is not None:
            user_id = int(row['id'])
            db.execute(
                text(
                    """
                    UPDATE users
                    SET password_hash = :password_hash,
                        status = :status,
                        is_admin = :is_admin,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                    """
                ),
                {
                    'id': user_id,
                    'password_hash': password_hash,
                    'status': status_norm,
                    'is_admin': 1 if is_admin else 0,
                },
            )
        else:
            result = db.execute(
                text(
                    """
                    INSERT INTO users (tenant_id, username, password_hash, status, is_admin)
                    VALUES (:tenant_id, :username, :password_hash, :status, :is_admin)
                    """
                ),
                {
                    'tenant_id': int(tenant_id),
                    'username': username_norm,
                    'password_hash': password_hash,
                    'status': status_norm,
                    'is_admin': 1 if is_admin else 0,
                },
            )
            user_id = int(getattr(result, 'lastrowid', 0) or 0)
            if user_id < 1:
                row2 = (
                    db.execute(
                        text(
                            """
                            SELECT id
                            FROM users
                            WHERE tenant_id = :tenant_id AND username = :username
                            LIMIT 1
                            """
                        ),
                        {'tenant_id': int(tenant_id), 'username': username_norm},
                    )
                    .mappings()
                    .first()
                )
                user_id = int((row2 or {}).get('id') or 0)

        db.commit()
        if user_id < 1:
            raise RuntimeError('failed to create user')
        return user_id
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError(str(exc)) from exc


def set_user_shop_access(db: Session, *, user_id: int, tenant_id: int, shop_ids: list[int]) -> None:
    if user_id < 1:
        raise ValueError('user_id must be positive')
    if tenant_id < 1:
        raise ValueError('tenant_id must be positive')

    normalized_shop_ids = sorted({int(x) for x in shop_ids if int(x) > 0})

    try:
        ensure_user_shop_access_table(db)
        db.execute(
            text('DELETE FROM user_shop_access WHERE user_id = :user_id'),
            {'user_id': int(user_id)},
        )

        for shop_id in normalized_shop_ids:
            db.execute(
                text(
                    """
                    INSERT INTO user_shop_access (user_id, tenant_id, shop_id)
                    VALUES (:user_id, :tenant_id, :shop_id)
                    """
                ),
                {'user_id': int(user_id), 'tenant_id': int(tenant_id), 'shop_id': int(shop_id)},
            )

        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError(str(exc)) from exc


def authenticate_user(db: Session, *, tenant_id: int, username: str, password: str) -> AuthUser | None:
    if tenant_id < 1:
        return None

    username_norm = _normalize_username(username)
    if not username_norm:
        return None

    try:
        ensure_users_table(db)
        row = (
            db.execute(
                text(
                    """
                    SELECT id, tenant_id, username, password_hash, status, is_admin
                    FROM users
                    WHERE tenant_id = :tenant_id AND username = :username
                    LIMIT 1
                    """
                ),
                {'tenant_id': int(tenant_id), 'username': username_norm},
            )
            .mappings()
            .first()
        )
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc

    if not row:
        return None

    status = str(row.get('status') or 'enabled').strip().lower()
    if status != 'enabled':
        return None

    password_hash = str(row.get('password_hash') or '')
    if not password_hash:
        return None

    if not check_password_hash(password_hash, password):
        return None

    return AuthUser(
        user_id=int(row['id']),
        tenant_id=int(row['tenant_id']),
        username=str(row.get('username') or ''),
        is_admin=bool(int(row.get('is_admin') or 0)),
    )


def list_user_shop_ids(db: Session, *, user_id: int) -> list[int]:
    if user_id < 1:
        return []

    try:
        ensure_user_shop_access_table(db)
        rows = (
            db.execute(
                text(
                    """
                    SELECT shop_id
                    FROM user_shop_access
                    WHERE user_id = :user_id
                    ORDER BY shop_id ASC
                    """
                ),
                {'user_id': int(user_id)},
            )
            .mappings()
            .all()
        )
        return [int(r['shop_id']) for r in rows]
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc