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

from app.services.merchant_portal_pricing_service import _score_price_update_row


class MerchantPortalPricingServiceTestCase(unittest.TestCase):
    def test_score_price_update_row_rejects_same_room_different_rate_when_gid_missing(self) -> None:
        item = {
            'gid': '2444922926',
            'hid': '1137517223',
            'room_name': '标准双床房（零压床垫+100%羽绒被+独立办公桌）',
            'rate_name': '标准价-无早餐',
            'display_name': '标准价-无早餐',
        }
        row_text = (
            '标准双床房（零压床垫+100%羽绒被+独立办公桌）'
            '标准价-2份早餐-2444922863 '
            '有效期 - 周有效 周一 周二 周三 周四 周五 周六 周日'
        )

        score, matched_by = _score_price_update_row(item, row_text)

        self.assertEqual(score, 0)
        self.assertEqual(matched_by, '')

    def test_score_price_update_row_accepts_exact_rate_match_without_gid(self) -> None:
        item = {
            'gid': '2444922926',
            'hid': '1137517223',
            'room_name': '标准双床房（零压床垫+100%羽绒被+独立办公桌）',
            'rate_name': '标准价-无早餐',
            'display_name': '标准价-无早餐',
        }
        row_text = (
            '标准双床房（零压床垫+100%羽绒被+独立办公桌）'
            '标准价-无早餐 '
            '有效期 - 周有效 周一 周二 周三 周四 周五 周六 周日'
        )

        score, matched_by = _score_price_update_row(item, row_text)

        self.assertGreater(score, 0)
        self.assertEqual(matched_by, 'rate_name')


if __name__ == '__main__':
    unittest.main()
