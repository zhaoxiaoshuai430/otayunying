import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask, session

from app.api.deps import require_shop_id, require_tenant_id, require_tenant_shop
from app.api.errors import ApiError


class ApiDepsSessionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.app = Flask(__name__)
        self.app.secret_key = 'test-secret'

    def test_session_tenant_shop_take_precedence_over_headers(self) -> None:
        with self.app.test_request_context('/', headers={'X-Tenant-Id': '2', 'X-Shop-Id': '3'}):
            session['tenant_id'] = 10
            session['shop_id'] = 20
            self.assertEqual(require_tenant_id(), 10)
            self.assertEqual(require_shop_id(), 20)

    def test_header_fallback_works_when_enabled(self) -> None:
        fake_settings = SimpleNamespace(auth_allow_header_fallback=True)
        with patch('app.api.deps.get_settings', return_value=fake_settings):
            with self.app.test_request_context('/', headers={'X-Tenant-Id': '2', 'X-Shop-Id': '3'}):
                self.assertEqual(require_tenant_id(), 2)
                self.assertEqual(require_shop_id(), 3)

    def test_header_fallback_disabled_requires_login(self) -> None:
        fake_settings = SimpleNamespace(auth_allow_header_fallback=False)
        with patch('app.api.deps.get_settings', return_value=fake_settings):
            with self.app.test_request_context('/', headers={'X-Tenant-Id': '2', 'X-Shop-Id': '3'}):
                with self.assertRaises(ApiError) as ctx:
                    require_tenant_id()
                self.assertEqual(ctx.exception.status_code, 401)
                self.assertEqual(ctx.exception.detail, 'Login required')

    def test_require_tenant_shop_uses_session_context(self) -> None:
        class FakeConfig:
            status = 'enabled'

        with patch('app.api.deps.get_shop_config_for_tenant', return_value=FakeConfig()):
            with self.app.test_request_context('/'):
                session['tenant_id'] = 1
                session['shop_id'] = 2
                tenant_id, shop_id = require_tenant_shop(db=object())
                self.assertEqual(tenant_id, 1)
                self.assertEqual(shop_id, 2)


if __name__ == '__main__':
    unittest.main()