from __future__ import annotations

from flask import g, request, session
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.core.config import get_settings
from app.services.plugin_auth_service import extract_bearer_token, resolve_plugin_token
from app.services.shop_service import get_shop_config_for_tenant


def _parse_positive_int(raw: object, *, name: str) -> int:
    value = str(raw or '').strip()
    if not value:
        raise ApiError(400, f'Missing {name}')
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ApiError(400, f'{name} must be an integer') from exc
    if parsed < 1:
        raise ApiError(400, f'{name} must be positive')
    return parsed


def _session_int(key: str) -> int | None:
    raw = session.get(key)
    if raw is None:
        return None
    try:
        parsed = int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise ApiError(401, f'Invalid session {key}') from exc
    if parsed < 1:
        raise ApiError(401, f'Invalid session {key}')
    return parsed


def _plugin_auth_context():
    if hasattr(g, '_plugin_auth_context'):
        return getattr(g, '_plugin_auth_context')

    token = extract_bearer_token(request.headers.get('Authorization'))
    if not token:
        setattr(g, '_plugin_auth_context', None)
        return None

    db = getattr(g, 'db', None)
    if db is None:
        raise ApiError(500, 'db session not initialized')
    try:
        context = resolve_plugin_token(db=db, token=token)
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc
    if context is None:
        raise ApiError(401, 'Invalid plugin token')
    setattr(g, '_plugin_auth_context', context)
    return context


def require_plugin_auth_context():
    context = _plugin_auth_context()
    if context is None:
        raise ApiError(401, 'Login required')
    return context


def require_tenant_id() -> int:
    plugin_context = _plugin_auth_context()
    if plugin_context is not None:
        return int(plugin_context.tenant_id)

    tenant_id = _session_int('tenant_id')
    if tenant_id is not None:
        return tenant_id

    cfg = get_settings()
    if not bool(getattr(cfg, 'auth_allow_header_fallback', True)):
        raise ApiError(401, 'Login required')
    return _parse_positive_int(request.headers.get('X-Tenant-Id'), name='X-Tenant-Id header')


def require_shop_id() -> int:
    plugin_context = _plugin_auth_context()
    if plugin_context is not None:
        return int(plugin_context.current_shop_id)

    shop_id = _session_int('shop_id')
    if shop_id is not None:
        return shop_id

    cfg = get_settings()
    if not bool(getattr(cfg, 'auth_allow_header_fallback', True)):
        raise ApiError(401, 'Login required')
    return _parse_positive_int(request.headers.get('X-Shop-Id'), name='X-Shop-Id header')


def require_tenant_shop(db: Session) -> tuple[int, int]:
    """Resolve tenant/shop from session or request headers and enforce ownership + enabled status."""

    tenant_id = require_tenant_id()
    shop_id = require_shop_id()

    try:
        config = get_shop_config_for_tenant(db=db, tenant_id=tenant_id, shop_id=shop_id)
    except ValueError as exc:
        raise ApiError(404, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc

    if str(getattr(config, 'status', '') or '').strip().lower() != 'enabled':
        raise ApiError(403, f'shop disabled: {shop_id}')

    return tenant_id, shop_id


def enforce_shop_id_match(tenant_shop_id: int, provided_shop_id: object | None, *, field_name: str = 'shop_id') -> None:
    """Ensure provided shop_id matches current tenant shop id when present."""

    if provided_shop_id is None:
        return
    try:
        normalized = int(provided_shop_id)
    except (TypeError, ValueError) as exc:
        raise ApiError(400, f'{field_name} must be an integer') from exc
    if normalized != int(tenant_shop_id):
        raise ApiError(400, f'{field_name} must match X-Shop-Id')
