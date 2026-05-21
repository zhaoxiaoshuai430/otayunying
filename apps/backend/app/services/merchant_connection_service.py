from __future__ import annotations

import base64
import binascii
import ctypes
import json
import os
import re
from ctypes import POINTER, Structure, byref, c_byte
from ctypes import wintypes

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

_CIPHER_PREFIX = 'dpapi:'
_SUPPORTED_PLATFORMS = {'fliggy', 'fliggy_guest'}
_STORAGE_NAME_PATTERN = re.compile(r'[^a-zA-Z0-9._-]+')


class _DataBlob(Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', POINTER(c_byte))]


def _normalize_platform(platform: object | None) -> str:
    value = str(platform or 'fliggy').strip().lower() or 'fliggy'
    if value not in _SUPPORTED_PLATFORMS:
        raise ValueError(f'unsupported merchant platform: {value}')
    return value


def _mask_username(username: str) -> str:
    value = str(username or '').strip()
    if not value:
        return ''
    if '@' in value:
        prefix, suffix = value.split('@', 1)
        if len(prefix) <= 2:
            masked_prefix = prefix[:1] + '*'
        else:
            masked_prefix = prefix[:2] + '*' * max(2, len(prefix) - 2)
        return f'{masked_prefix}@{suffix}'
    if len(value) <= 3:
        return value[:1] + '*' * max(1, len(value) - 1)
    return value[:2] + '*' * max(2, len(value) - 4) + value[-2:]


def _normalize_storage_state_name(raw_name: object | None, *, shop_id: int) -> str:
    value = str(raw_name or '').strip() or f'shop-{shop_id}.json'
    value = _STORAGE_NAME_PATTERN.sub('-', value)
    if not value.endswith('.json'):
        value += '.json'
    return value


def _normalize_selectors_json(selectors: dict | str | None) -> str:
    if selectors in (None, '', {}):
        return ''
    payload = selectors
    if isinstance(selectors, str):
        text_value = selectors.strip()
        if not text_value:
            return ''
        payload = json.loads(text_value)
    if not isinstance(payload, dict):
        raise ValueError('selectors must be a JSON object')
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'))


def _parse_selectors(selectors_json: str) -> dict:
    value = str(selectors_json or '').strip()
    if not value:
        return {}
    payload = json.loads(value)
    return payload if isinstance(payload, dict) else {}


def _build_default_credential(*, tenant_id: int, shop_id: int, platform: str) -> dict:
    return {
        'tenant_id': tenant_id,
        'shop_id': shop_id,
        'platform': platform,
        'exists': False,
        'username_masked': '',
        'has_password': False,
        'login_url': '',
        'price_url': '',
        'storage_state_name': _normalize_storage_state_name('', shop_id=shop_id),
        'selectors': {},
        'has_selectors': False,
        'last_login_at': None,
        'last_login_status': '',
        'last_login_message': '',
    }


def _bytes_to_blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data, len(data))
    blob = _DataBlob(len(data), ctypes.cast(buffer, POINTER(c_byte)))
    return blob, buffer


def _crypt_protect_bytes(data: bytes) -> bytes:
    if os.name != 'nt':
        raise RuntimeError('merchant credential encryption currently requires Windows DPAPI')
    in_blob, in_buffer = _bytes_to_blob(data)
    out_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptProtectData(byref(in_blob), None, None, None, None, 0, byref(out_blob)):
        raise RuntimeError(f'failed to encrypt merchant password via DPAPI: {ctypes.GetLastError()}')
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        del in_buffer
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)


def _crypt_unprotect_bytes(data: bytes) -> bytes:
    if os.name != 'nt':
        raise RuntimeError('merchant credential encryption currently requires Windows DPAPI')
    in_blob, in_buffer = _bytes_to_blob(data)
    out_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptUnprotectData(byref(in_blob), None, None, None, None, 0, byref(out_blob)):
        raise RuntimeError(f'failed to decrypt merchant password via DPAPI: {ctypes.GetLastError()}')
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        del in_buffer
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)


def encrypt_merchant_password(password: str) -> str:
    value = str(password or '')
    if not value:
        return ''
    cipher = _crypt_protect_bytes(value.encode('utf-8'))
    return _CIPHER_PREFIX + base64.b64encode(cipher).decode('ascii')


def decrypt_merchant_password(password_cipher: str) -> str:
    value = str(password_cipher or '').strip()
    if not value:
        return ''
    if not value.startswith(_CIPHER_PREFIX):
        raise ValueError('unsupported merchant password cipher format')
    try:
        cipher_bytes = base64.b64decode(value[len(_CIPHER_PREFIX):])
    except (ValueError, binascii.Error) as exc:
        raise ValueError('invalid merchant password cipher') from exc
    return _crypt_unprotect_bytes(cipher_bytes).decode('utf-8')


def ensure_merchant_credentials_table(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS merchant_credentials (
              id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
              tenant_id BIGINT UNSIGNED NOT NULL DEFAULT 1,
              shop_id BIGINT UNSIGNED NOT NULL,
              platform VARCHAR(32) NOT NULL DEFAULT 'fliggy',
              username VARCHAR(128) NOT NULL DEFAULT '',
              password_cipher LONGTEXT NOT NULL,
              login_url VARCHAR(2048) NOT NULL DEFAULT '',
              price_url VARCHAR(2048) NOT NULL DEFAULT '',
              selector_json LONGTEXT NULL,
              storage_state_name VARCHAR(255) NOT NULL DEFAULT '',
              last_login_at DATETIME NULL,
              last_login_status VARCHAR(32) NOT NULL DEFAULT '',
              last_login_message VARCHAR(255) NOT NULL DEFAULT '',
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (id),
              UNIQUE KEY uk_merchant_credentials_shop_platform (shop_id, platform),
              KEY idx_merchant_credentials_tenant_shop (tenant_id, shop_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    )


def _row_to_merchant_credential(row: dict, *, include_secret: bool = False) -> dict:
    username = str(row.get('username') or '').strip()
    password_cipher = str(row.get('password_cipher') or '').strip()
    selectors_json = str(row.get('selector_json') or '').strip()
    result = {
        'tenant_id': int(row.get('tenant_id') or 1),
        'shop_id': int(row['shop_id']),
        'platform': _normalize_platform(row.get('platform')),
        'exists': True,
        'username_masked': _mask_username(username),
        'has_password': bool(password_cipher),
        'login_url': str(row.get('login_url') or '').strip(),
        'price_url': str(row.get('price_url') or '').strip(),
        'storage_state_name': _normalize_storage_state_name(row.get('storage_state_name'), shop_id=int(row['shop_id'])),
        'selectors': _parse_selectors(selectors_json),
        'has_selectors': bool(selectors_json),
        'last_login_at': str(row['last_login_at']) if row.get('last_login_at') else None,
        'last_login_status': str(row.get('last_login_status') or '').strip(),
        'last_login_message': str(row.get('last_login_message') or '').strip(),
    }
    if include_secret:
        result['username'] = username
        result['password'] = decrypt_merchant_password(password_cipher) if password_cipher else ''
    return result


def _select_merchant_credential_row(db: Session, *, shop_id: int, platform: str) -> dict | None:
    row = db.execute(
        text(
            """
            SELECT tenant_id, shop_id, platform, username, password_cipher, login_url, price_url,
                   selector_json, storage_state_name, last_login_at, last_login_status, last_login_message
            FROM merchant_credentials
            WHERE shop_id = :shop_id AND platform = :platform
            LIMIT 1
            """
        ),
        {'shop_id': int(shop_id), 'platform': platform},
    ).mappings().first()
    return dict(row) if row else None


def get_merchant_credential(
    db: Session,
    *,
    shop_id: int,
    tenant_id: int = 1,
    platform: str = 'fliggy',
    include_secret: bool = False,
) -> dict:
    platform = _normalize_platform(platform)
    ensure_merchant_credentials_table(db)
    try:
        row = _select_merchant_credential_row(db=db, shop_id=shop_id, platform=platform)
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc
    if row is None:
        return _build_default_credential(tenant_id=tenant_id, shop_id=int(shop_id), platform=platform)
    credential = _row_to_merchant_credential(row, include_secret=include_secret)
    if int(credential['tenant_id']) != int(tenant_id):
        raise ValueError(f'merchant credential not found for shop: {shop_id}')
    return credential


def save_merchant_credential(db: Session, *, credential_data: dict) -> dict:
    shop_id = int(credential_data.get('shop_id') or 0)
    if shop_id < 1:
        raise ValueError('shop_id must be positive')

    tenant_id = int(credential_data.get('tenant_id') or 1)
    platform = _normalize_platform(credential_data.get('platform'))
    ensure_merchant_credentials_table(db)

    try:
        existing_row = _select_merchant_credential_row(db=db, shop_id=shop_id, platform=platform)
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc

    if existing_row is not None and int(existing_row.get('tenant_id') or 0) not in (0, tenant_id):
        raise ValueError(f'merchant credential belongs to another tenant: {shop_id}')

    username = str(credential_data.get('username') or (existing_row or {}).get('username') or '').strip()
    if not username:
        raise ValueError('username is required')

    raw_password = credential_data.get('password')
    if raw_password in (None, ''):
        password_cipher = str((existing_row or {}).get('password_cipher') or '').strip()
    else:
        password_cipher = encrypt_merchant_password(str(raw_password))

    selectors_json = _normalize_selectors_json(
        credential_data.get('selectors', credential_data.get('selector_json', (existing_row or {}).get('selector_json')))
    )
    payload = {
        'tenant_id': tenant_id,
        'shop_id': shop_id,
        'platform': platform,
        'username': username,
        'password_cipher': password_cipher,
        'login_url': str(credential_data.get('login_url') or (existing_row or {}).get('login_url') or '').strip(),
        'price_url': str(credential_data.get('price_url') or (existing_row or {}).get('price_url') or '').strip(),
        'selector_json': selectors_json,
        'storage_state_name': _normalize_storage_state_name(
            credential_data.get('storage_state_name') or (existing_row or {}).get('storage_state_name'),
            shop_id=shop_id,
        ),
    }

    try:
        if existing_row is None:
            db.execute(
                text(
                    """
                    INSERT INTO merchant_credentials
                    (tenant_id, shop_id, platform, username, password_cipher, login_url, price_url,
                     selector_json, storage_state_name, created_at, updated_at)
                    VALUES
                    (:tenant_id, :shop_id, :platform, :username, :password_cipher, :login_url, :price_url,
                     :selector_json, :storage_state_name, NOW(), NOW())
                    """
                ),
                payload,
            )
        else:
            db.execute(
                text(
                    """
                    UPDATE merchant_credentials
                    SET tenant_id = :tenant_id,
                        username = :username,
                        password_cipher = :password_cipher,
                        login_url = :login_url,
                        price_url = :price_url,
                        selector_json = :selector_json,
                        storage_state_name = :storage_state_name,
                        updated_at = NOW()
                    WHERE shop_id = :shop_id AND platform = :platform
                    """
                ),
                payload,
            )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError(str(exc)) from exc

    return get_merchant_credential(db=db, shop_id=shop_id, tenant_id=tenant_id, platform=platform)


def record_merchant_login_result(
    db: Session,
    *,
    shop_id: int,
    tenant_id: int = 1,
    platform: str = 'fliggy',
    status: str,
    message: str = '',
) -> dict:
    platform = _normalize_platform(platform)
    normalized_status = str(status or '').strip().lower() or 'unknown'
    ensure_merchant_credentials_table(db)
    try:
        row = _select_merchant_credential_row(db=db, shop_id=shop_id, platform=platform)
        if row is None or int(row.get('tenant_id') or 0) != int(tenant_id):
            raise ValueError(f'merchant credential not found for shop: {shop_id}')
        db.execute(
            text(
                """
                UPDATE merchant_credentials
                SET last_login_at = NOW(),
                    last_login_status = :status,
                    last_login_message = :message,
                    updated_at = NOW()
                WHERE shop_id = :shop_id AND platform = :platform
                """
            ),
            {
                'shop_id': int(shop_id),
                'platform': platform,
                'status': normalized_status,
                'message': str(message or '').strip()[:255],
            },
        )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError(str(exc)) from exc
    return get_merchant_credential(db=db, shop_id=shop_id, tenant_id=tenant_id, platform=platform)
