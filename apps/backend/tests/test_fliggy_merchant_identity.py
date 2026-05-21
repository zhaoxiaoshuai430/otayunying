import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for key, value in {
    'DB_HOST': '127.0.0.1',
    'DB_PORT': '3306',
    'DB_NAME': 'demo',
    'DB_USER': 'demo',
    'DB_PASSWORD': 'demo',
}.items():
    os.environ.setdefault(key, value)

from app.services.fliggy_merchant_service import _extract_session_username_from_browser_state


class FliggyMerchantIdentityTestCase(unittest.TestCase):
    def test_extract_session_username_prefers_current_account(self) -> None:
        username, source = _extract_session_username_from_browser_state(
            {
                'CURRENT_ACCOUNT': 'merchant@example.com',
                'login_person_info': {
                    'email': 'other@example.com',
                    'account': 'EBK0001',
                },
            },
            [{'name': 'memberLoginKey', 'value': 'EBK9999'}],
        )

        self.assertEqual(username, 'merchant@example.com')
        self.assertEqual(source, 'local_storage.current_account')

    def test_extract_session_username_falls_back_to_cookie(self) -> None:
        username, source = _extract_session_username_from_browser_state({}, [{'name': 'memberLoginKey', 'value': 'EBK0001'}])

        self.assertEqual(username, 'EBK0001')
        self.assertEqual(source, 'cookie.memberLoginKey')


if __name__ == '__main__':
    unittest.main()
