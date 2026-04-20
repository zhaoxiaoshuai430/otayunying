import unittest

from app.main import app


class AppRouteSmokeTestCase(unittest.TestCase):
    def test_app_imports_successfully(self) -> None:
        self.assertIsNotNone(app)

    def test_core_routes_are_registered(self) -> None:
        rules = {rule.rule for rule in app.url_map.iter_rules()}
        expected = {
            '/health',
            '/pricing/recommend',
            '/pricing/merchant-preview',
            '/pricing/merchant-generate',
            '/pricing/merchant-direct-submit',
            '/pricing/merchant-confirm',
            '/pricing/merchant-mappings',
            '/pricing/merchant-mappings/refresh-prices',
            '/competitor/latest-prices',
            '/competitor/trends',
            '/competitor/fliggy/session/login',
            '/competitor/fliggy/collect',
            '/competitor/rooms/analyze',
            '/merchant/credentials',
            '/merchant/fliggy/session/login',
            '/merchant/fliggy/prices/preview',
            '/merchant/fliggy/prices/collect',
            '/plugin/service-status',
            '/plugin/competitor/latest-prices',
            '/plugin/fliggy/collect',
            '/plugin/competitor/room-prices',
            '/plugin/pricing/merchant-preview',
            '/plugin/pricing/merchant-direct-submit',
            '/plugin/pricing/competitor-workflow-preview',
            '/plugin/pricing/competitor-advice-preview',
            '/plugin/pricing/uniform-direct-submit',
        }
        self.assertTrue(expected.issubset(rules), msg=f'missing routes: {sorted(expected - rules)}')


if __name__ == '__main__':
    unittest.main()


