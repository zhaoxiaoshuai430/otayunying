from __future__ import annotations

import secrets
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.services.shop_service import list_shop_configs_for_tenant
from app.services.user_service import authenticate_user, list_user_shop_ids

_PLUGIN_TOKEN_TTL_DAYS = 14


@dataclass(frozen=True)
class PluginAuthContext:
    token: str
    user_id: int
    tenant_id: int
    username: str
    is_admin: bool
    current_shop_id: int


def ensure_plugin_auth_tokens_table(db: Session) -> None:
    db.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS plugin_auth_tokens (
              id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
              token VARCHAR(128) NOT NULL,
              tenant_id BIGINT UNSIGNED NOT NULL,
              user_id BIGINT UNSIGNED NOT NULL,
              username VARCHAR(64) NOT NULL,
              is_admin TINYINT(1) NOT NULL DEFAULT 0,
              current_shop_id BIGINT UNSIGNED NOT NULL,
              expires_at DATETIME NOT NULL,
              last_seen_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (id),
              UNIQUE KEY uniq_plugin_auth_token (token),
              KEY idx_plugin_auth_user (user_id),
              KEY idx_plugin_auth_tenant_shop (tenant_id, current_shop_id),
              KEY idx_plugin_auth_expires (expires_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    )


def extract_bearer_token(raw_authorization: str | None) -> str:
    value = str(raw_authorization or "").strip()
    if not value:
        return ""
    parts = value.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    return str(parts[1] or "").strip()


def _build_shop_summary(config) -> dict:
    return {
        "shop_id": int(getattr(config, "shop_id", 0) or 0),
        "shop_name": str(getattr(config, "shop_name", "") or getattr(config, "name", "") or "").strip() or f"Shop {int(getattr(config, 'shop_id', 0) or 0)}",
        "status": str(getattr(config, "status", "") or "").strip() or "enabled",
    }


def _list_accessible_shop_summaries(db: Session, *, tenant_id: int, user_id: int, is_admin: bool) -> list[dict]:
    shop_configs = list_shop_configs_for_tenant(db=db, tenant_id=tenant_id, only_enabled=False)
    if is_admin:
        return [_build_shop_summary(config) for config in shop_configs]

    allowed_shop_ids = set(list_user_shop_ids(db=db, user_id=user_id))
    return [
        _build_shop_summary(config)
        for config in shop_configs
        if int(getattr(config, "shop_id", 0) or 0) in allowed_shop_ids
    ]


def _pick_default_shop_id(shops: list[dict]) -> int:
    enabled_shops = [item for item in shops if str(item.get("status") or "").strip().lower() == "enabled"]
    selected = enabled_shops[0] if enabled_shops else (shops[0] if shops else None)
    return int((selected or {}).get("shop_id") or 0)


def _insert_plugin_token(db: Session, *, tenant_id: int, user_id: int, username: str, is_admin: bool, current_shop_id: int) -> str:
    token = f"plugin_{secrets.token_urlsafe(24)}"
    db.execute(
        text(
            f"""
            INSERT INTO plugin_auth_tokens (
              token, tenant_id, user_id, username, is_admin, current_shop_id, expires_at, last_seen_at
            ) VALUES (
              :token, :tenant_id, :user_id, :username, :is_admin, :current_shop_id,
              DATE_ADD(NOW(), INTERVAL {_PLUGIN_TOKEN_TTL_DAYS} DAY), NOW()
            )
            """
        ),
        {
            "token": token,
            "tenant_id": int(tenant_id),
            "user_id": int(user_id),
            "username": str(username or "").strip(),
            "is_admin": 1 if is_admin else 0,
            "current_shop_id": int(current_shop_id),
        },
    )
    return token


def login_plugin_user(db: Session, *, tenant_id: int, username: str, password: str) -> dict:
    auth_user = authenticate_user(db=db, tenant_id=tenant_id, username=username, password=password)
    if auth_user is None:
        raise ValueError("用户名或密码错误")

    try:
        ensure_plugin_auth_tokens_table(db)
        shops = _list_accessible_shop_summaries(
            db=db,
            tenant_id=auth_user.tenant_id,
            user_id=auth_user.user_id,
            is_admin=auth_user.is_admin,
        )
        if not shops:
            raise ValueError("当前账号没有可访问的店铺")
        current_shop_id = _pick_default_shop_id(shops)
        if current_shop_id < 1:
            raise ValueError("当前账号没有可用店铺")
        token = _insert_plugin_token(
            db=db,
            tenant_id=auth_user.tenant_id,
            user_id=auth_user.user_id,
            username=auth_user.username,
            is_admin=auth_user.is_admin,
            current_shop_id=current_shop_id,
        )
        db.commit()
    except ValueError:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError(str(exc)) from exc

    current_shop = next((item for item in shops if int(item.get("shop_id") or 0) == current_shop_id), None)
    return {
        "token": token,
        "user": {
            "tenant_id": int(auth_user.tenant_id),
            "username": str(auth_user.username or "").strip(),
            "is_admin": bool(auth_user.is_admin),
        },
        "current_shop": current_shop or {"shop_id": current_shop_id, "shop_name": f"Shop {current_shop_id}", "status": "enabled"},
        "shops": shops,
    }


def resolve_plugin_token(db: Session, *, token: str) -> PluginAuthContext | None:
    normalized = str(token or "").strip()
    if not normalized:
        return None

    try:
        ensure_plugin_auth_tokens_table(db)
        row = (
            db.execute(
                text(
                    """
                    SELECT token, tenant_id, user_id, username, is_admin, current_shop_id
                    FROM plugin_auth_tokens
                    WHERE token = :token
                      AND expires_at > NOW()
                    LIMIT 1
                    """
                ),
                {"token": normalized},
            )
            .mappings()
            .first()
        )
        if not row:
            return None
        db.execute(
            text(
                """
                UPDATE plugin_auth_tokens
                SET last_seen_at = NOW()
                WHERE token = :token
                """
            ),
            {"token": normalized},
        )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError(str(exc)) from exc

    return PluginAuthContext(
        token=str(row.get("token") or "").strip(),
        user_id=int(row.get("user_id") or 0),
        tenant_id=int(row.get("tenant_id") or 0),
        username=str(row.get("username") or "").strip(),
        is_admin=bool(int(row.get("is_admin") or 0)),
        current_shop_id=int(row.get("current_shop_id") or 0),
    )


def build_plugin_auth_payload(db: Session, context: PluginAuthContext) -> dict:
    shops = _list_accessible_shop_summaries(
        db=db,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        is_admin=context.is_admin,
    )
    current_shop = next((item for item in shops if int(item.get("shop_id") or 0) == int(context.current_shop_id)), None)
    if current_shop is None and shops:
        current_shop = shops[0]
    return {
        "authenticated": True,
        "user": {
            "tenant_id": int(context.tenant_id),
            "username": str(context.username or "").strip(),
            "is_admin": bool(context.is_admin),
        },
        "current_shop": current_shop,
        "shops": shops,
    }


def switch_plugin_shop(db: Session, *, context: PluginAuthContext, shop_id: int) -> dict:
    target_shop_id = int(shop_id or 0)
    if target_shop_id < 1:
        raise ValueError("shop_id must be positive")

    shops = _list_accessible_shop_summaries(
        db=db,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        is_admin=context.is_admin,
    )
    target_shop = next((item for item in shops if int(item.get("shop_id") or 0) == target_shop_id), None)
    if target_shop is None:
        raise ValueError(f"shop not found: {target_shop_id}")

    try:
        ensure_plugin_auth_tokens_table(db)
        db.execute(
            text(
                """
                UPDATE plugin_auth_tokens
                SET current_shop_id = :shop_id,
                    last_seen_at = NOW()
                WHERE token = :token
                """
            ),
            {"shop_id": target_shop_id, "token": context.token},
        )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError(str(exc)) from exc

    return {
        "current_shop": target_shop,
        "shops": shops,
    }


def revoke_plugin_token(db: Session, *, token: str) -> None:
    normalized = str(token or "").strip()
    if not normalized:
        return
    try:
        ensure_plugin_auth_tokens_table(db)
        db.execute(text("DELETE FROM plugin_auth_tokens WHERE token = :token"), {"token": normalized})
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError(str(exc)) from exc
