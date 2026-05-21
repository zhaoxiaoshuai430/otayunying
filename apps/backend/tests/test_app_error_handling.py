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

try:
    from app.main import create_app
except ModuleNotFoundError:  # pragma: no cover
    create_app = None


@unittest.skipIf(create_app is None, 'Flask is not installed')
class AppErrorHandlingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(session_factory=lambda: object())
        self.app.testing = False

        @self.app.get('/__boom_api__')
        def _boom_api():
            raise RuntimeError('db password leaked')

        @self.app.get('/__boom_page__')
        def _boom_page():
            raise RuntimeError('template exploded')

        self.client = self.app.test_client()

    def test_api_unexpected_error_hides_internal_detail(self) -> None:
        response = self.client.get('/__boom_api__', headers={'Accept': 'application/json'})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json(), {'detail': 'Internal server error'})
        self.assertNotIn('db password leaked', response.get_data(as_text=True))

    def test_page_unexpected_error_returns_json_when_html_console_removed(self) -> None:
        response = self.client.get('/__boom_page__', headers={'Accept': 'text/html'})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json(), {'detail': 'Internal server error'})
        self.assertNotIn('template exploded', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
