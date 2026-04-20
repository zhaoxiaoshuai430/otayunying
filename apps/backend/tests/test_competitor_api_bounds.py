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

try:
    from app.main import create_app
except ModuleNotFoundError:  # pragma: no cover
    create_app = None


@unittest.skipIf(create_app is None, 'Flask is not installed')
class CompetitorApiBoundsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(session_factory=lambda: object())
        self.app.testing = True
        self.client = self.app.test_client()
        self.headers = {'X-Tenant-Id': '1', 'X-Shop-Id': '1'}

    def test_trends_rejects_negative_days(self) -> None:
        with patch('app.api.routes.require_tenant_shop', return_value=(1, 1)):
            response = self.client.get('/competitor/trends?days=-1&limit=10', headers=self.headers)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {'detail': 'Query param days must be between 1 and 365'})

    def test_latest_prices_rejects_excessive_limit(self) -> None:
        with patch('app.api.routes.require_tenant_shop', return_value=(1, 1)):
            response = self.client.get('/competitor/latest-prices?limit=9999', headers=self.headers)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {'detail': 'Query param limit must be between 1 and 500'})

    def test_rooms_analyze_rejects_negative_total_rooms(self) -> None:
        with patch('app.api.routes.require_tenant_shop', return_value=(1, 1)):
            response = self.client.post(
                '/competitor/rooms/analyze',
                json={
                    'shop_id': 1,
                    'days': 30,
                    'my_price': 299,
                    'my_total_rooms': -3,
                    'my_available_rooms': 1,
                },
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {'detail': 'my_total_rooms must be between 1 and 10000'})

    def test_rooms_analyze_rejects_available_rooms_greater_than_total(self) -> None:
        with patch('app.api.routes.require_tenant_shop', return_value=(1, 1)):
            response = self.client.post(
                '/competitor/rooms/analyze',
                json={
                    'shop_id': 1,
                    'days': 30,
                    'my_price': 299,
                    'my_total_rooms': 8,
                    'my_available_rooms': 9,
                },
                headers=self.headers,
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {'detail': 'my_available_rooms must be less than or equal to my_total_rooms'})


if __name__ == '__main__':
    unittest.main()
