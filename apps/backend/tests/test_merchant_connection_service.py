import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for key, value in {
    'DB_HOST': '127.0.0.1',
    'DB_PORT': '3306',
    'DB_NAME': 'demo',
    'DB_USER': 'demo',
    'DB_PASSWORD': 'demo',
}.items():
    os.environ.setdefault(key, value)

from app.services.merchant_connection_service import (
    _mask_username,
    get_merchant_credential,
    record_merchant_login_result,
    save_merchant_credential,
)


class FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class FakeDb:
    def __init__(self):
        self.rows = {}

    def execute(self, statement, params=None):
        params = params or {}
        sql = ' '.join(str(statement).split()).lower()
        key = (int(params.get('shop_id') or 0), str(params.get('platform') or 'fliggy'))
        if 'create table if not exists merchant_credentials' in sql:
            return FakeResult()
        if 'select tenant_id, shop_id, platform, username, password_cipher, login_url, price_url' in sql:
            row = self.rows.get(key)
            return FakeResult([row] if row else [])
        if 'insert into merchant_credentials' in sql:
            self.rows[key] = {
                'tenant_id': params['tenant_id'],
                'shop_id': params['shop_id'],
                'platform': params['platform'],
                'username': params['username'],
                'password_cipher': params['password_cipher'],
                'login_url': params['login_url'],
                'price_url': params['price_url'],
                'selector_json': params['selector_json'],
                'storage_state_name': params['storage_state_name'],
                'last_login_at': None,
                'last_login_status': '',
                'last_login_message': '',
            }
            return FakeResult()
        if 'update merchant_credentials set tenant_id = :tenant_id' in sql:
            row = self.rows[key]
            row.update(
                {
                    'tenant_id': params['tenant_id'],
                    'username': params['username'],
                    'password_cipher': params['password_cipher'],
                    'login_url': params['login_url'],
                    'price_url': params['price_url'],
                    'selector_json': params['selector_json'],
                    'storage_state_name': params['storage_state_name'],
                }
            )
            return FakeResult()
        if 'update merchant_credentials set last_login_at = now()' in sql:
            row = self.rows[key]
            row['last_login_at'] = '2026-03-15 16:00:00'
            row['last_login_status'] = params['status']
            row['last_login_message'] = params['message']
            return FakeResult()
        raise AssertionError(f'Unexpected SQL: {sql}')

    def commit(self):
        return None

    def rollback(self):
        return None


class MerchantConnectionServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.db = FakeDb()

    def test_mask_username(self) -> None:
        self.assertEqual(_mask_username('demo@example.com'), 'de**@example.com')
        self.assertEqual(_mask_username('13800138000'), '13*******00')

    @patch('app.services.merchant_connection_service.encrypt_merchant_password', return_value='dpapi:encrypted')
    def test_save_merchant_credential_masks_output(self, mocked_encrypt) -> None:
        result = save_merchant_credential(
            self.db,
            credential_data={
                'tenant_id': 1,
                'shop_id': 1,
                'platform': 'fliggy',
                'username': 'demo@example.com',
                'password': 'plain-secret',
                'login_url': 'https://merchant.example.com/login',
                'price_url': 'https://merchant.example.com/price',
                'selectors': {'room_rows': ['.row']},
                'storage_state_name': 'shop 1 state',
            },
        )

        mocked_encrypt.assert_called_once_with('plain-secret')
        self.assertTrue(result['exists'])
        self.assertEqual(result['username_masked'], 'de**@example.com')
        self.assertTrue(result['has_password'])
        self.assertEqual(result['storage_state_name'], 'shop-1-state.json')
        self.assertEqual(result['selectors']['room_rows'][0], '.row')
        self.assertNotIn('password', result)

    @patch('app.services.merchant_connection_service.decrypt_merchant_password', return_value='plain-secret')
    def test_get_merchant_credential_with_secret(self, mocked_decrypt) -> None:
        self.db.rows[(1, 'fliggy')] = {
            'tenant_id': 1,
            'shop_id': 1,
            'platform': 'fliggy',
            'username': 'demo@example.com',
            'password_cipher': 'dpapi:encrypted',
            'login_url': 'https://merchant.example.com/login',
            'price_url': 'https://merchant.example.com/price',
            'selector_json': '{"room_rows":[".row"]}',
            'storage_state_name': 'shop-1.json',
            'last_login_at': None,
            'last_login_status': '',
            'last_login_message': '',
        }

        result = get_merchant_credential(self.db, shop_id=1, include_secret=True)

        mocked_decrypt.assert_called_once_with('dpapi:encrypted')
        self.assertEqual(result['username'], 'demo@example.com')
        self.assertEqual(result['password'], 'plain-secret')
        self.assertEqual(result['selectors']['room_rows'][0], '.row')

    @patch('app.services.merchant_connection_service.encrypt_merchant_password', return_value='dpapi:new')
    def test_save_merchant_credential_keeps_old_password_when_empty(self, mocked_encrypt) -> None:
        self.db.rows[(1, 'fliggy')] = {
            'tenant_id': 1,
            'shop_id': 1,
            'platform': 'fliggy',
            'username': 'demo@example.com',
            'password_cipher': 'dpapi:old',
            'login_url': 'https://merchant.example.com/login',
            'price_url': 'https://merchant.example.com/price',
            'selector_json': '{"room_rows":[".row"]}',
            'storage_state_name': 'shop-1.json',
            'last_login_at': None,
            'last_login_status': '',
            'last_login_message': '',
        }

        result = save_merchant_credential(
            self.db,
            credential_data={
                'tenant_id': 1,
                'shop_id': 1,
                'platform': 'fliggy',
                'username': 'demo@example.com',
                'password': '',
                'login_url': 'https://merchant.example.com/login2',
            },
        )

        mocked_encrypt.assert_not_called()
        self.assertEqual(self.db.rows[(1, 'fliggy')]['password_cipher'], 'dpapi:old')
        self.assertEqual(result['login_url'], 'https://merchant.example.com/login2')

    @patch('app.services.merchant_connection_service.encrypt_merchant_password', return_value='dpapi:guest-encrypted')
    def test_save_guest_credential_uses_separate_platform(self, mocked_encrypt) -> None:
        result = save_merchant_credential(
            self.db,
            credential_data={
                'tenant_id': 1,
                'shop_id': 1,
                'platform': 'fliggy_guest',
                'username': 'guest@example.com',
                'password': 'guest-secret',
                'login_url': 'https://hotel.fliggy.com/',
                'price_url': 'https://hotel.fliggy.com/',
                'storage_state_name': 'guest shop 1',
            },
        )

        mocked_encrypt.assert_called_once_with('guest-secret')
        self.assertEqual(result['platform'], 'fliggy_guest')
        self.assertEqual(self.db.rows[(1, 'fliggy_guest')]['username'], 'guest@example.com')
        self.assertEqual(result['storage_state_name'], 'guest-shop-1.json')

    def test_record_merchant_login_result_updates_status(self) -> None:
        self.db.rows[(1, 'fliggy')] = {
            'tenant_id': 1,
            'shop_id': 1,
            'platform': 'fliggy',
            'username': 'demo@example.com',
            'password_cipher': 'dpapi:old',
            'login_url': 'https://merchant.example.com/login',
            'price_url': 'https://merchant.example.com/price',
            'selector_json': '',
            'storage_state_name': 'shop-1.json',
            'last_login_at': None,
            'last_login_status': '',
            'last_login_message': '',
        }

        result = record_merchant_login_result(
            self.db,
            shop_id=1,
            tenant_id=1,
            platform='fliggy',
            status='success',
            message='login ok',
        )

        self.assertEqual(result['last_login_status'], 'success')
        self.assertEqual(result['last_login_message'], 'login ok')
        self.assertEqual(result['last_login_at'], '2026-03-15 16:00:00')


if __name__ == '__main__':
    unittest.main()
