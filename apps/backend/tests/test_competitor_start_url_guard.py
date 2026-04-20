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

from app.services.competitor_service import _is_fliggy_home_or_root_url


class CompetitorStartUrlGuardTestCase(unittest.TestCase):
    def test_detects_fliggy_home_page_urls(self) -> None:
        self.assertTrue(_is_fliggy_home_or_root_url('https://hotel.fliggy.com/'))
        self.assertTrue(_is_fliggy_home_or_root_url('https://hotel.fliggy.com'))
        self.assertFalse(_is_fliggy_home_or_root_url('https://hotel.fliggy.com/search?q=shanghai'))


if __name__ == '__main__':
    unittest.main()
