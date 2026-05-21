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

from app.services.merchant_price_mapping_service import (
    get_merchant_price_mapping,
    list_merchant_price_mappings,
    upsert_merchant_price_mapping,
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
        self.next_id = 1

    def execute(self, statement, params=None):
        params = params or {}
        sql = ' '.join(str(statement).split()).lower()
        key = (
            int(params.get('shop_id') or 0),
            str(params.get('platform') or 'fliggy'),
            str(params.get('room_name') or '').strip(),
            str(params.get('rate_name') or '').strip(),
        )
        if 'create table if not exists merchant_price_mappings' in sql:
            return FakeResult()
        if 'information_schema.columns' in sql and 'last_seen_price' in sql:
            return FakeResult([{'column_count': 0}])
        if 'alter table merchant_price_mappings drop column last_seen_price' in sql:
            return FakeResult()
        if 'select id, tenant_id, shop_id, platform, room_name, rate_name, merchant_room_key' in sql and 'limit 1' in sql:
            row = self.rows.get(key)
            return FakeResult([row] if row else [])
        if 'select id, tenant_id, shop_id, platform, room_name, rate_name, merchant_room_key' in sql and 'order by room_name asc' in sql:
            rows = [row for row in self.rows.values() if int(row['shop_id']) == int(params['shop_id']) and row['platform'] == params['platform']]
            if "status in ('active', 'enabled')" in sql:
                rows = [row for row in rows if row['status'] in {'active', 'enabled'}]
            rows = sorted(rows, key=lambda item: (item['room_name'], item['rate_name'], item['id']))
            return FakeResult(rows)
        if 'insert into merchant_price_mappings' in sql:
            self.rows[key] = {
                'id': self.next_id,
                'tenant_id': params['tenant_id'],
                'shop_id': params['shop_id'],
                'platform': params['platform'],
                'room_name': params['room_name'],
                'rate_name': params['rate_name'],
                'merchant_room_key': params['merchant_room_key'],
                'merchant_rate_key': params['merchant_rate_key'],
                'gid': params['gid'],
                'hid': params['hid'],
                'status': params['status'],
                'notes': params['notes'],
                'last_seen_at': '2026-03-15 16:20:00',
            }
            self.next_id += 1
            return FakeResult()
        if 'update merchant_price_mappings set tenant_id = :tenant_id' in sql:
            row = self.rows[key]
            row.update(
                {
                    'tenant_id': params['tenant_id'],
                    'merchant_room_key': params['merchant_room_key'],
                    'merchant_rate_key': params['merchant_rate_key'],
                    'gid': params['gid'],
                    'hid': params['hid'],
                    'status': params['status'],
                    'notes': params['notes'],
                    'last_seen_at': '2026-03-15 16:25:00',
                }
            )
            return FakeResult()
        raise AssertionError(f'Unexpected SQL: {sql}')

    def commit(self):
        return None

    def rollback(self):
        return None


class MerchantPriceMappingServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.db = FakeDb()

    def test_upsert_mapping_creates_complete_active_mapping(self) -> None:
        result = upsert_merchant_price_mapping(
            self.db,
            mapping_data={
                'tenant_id': 1,
                'shop_id': 1,
                'platform': 'fliggy',
                'room_name': '豪华大床房',
                'rate_name': '标准价-2份早餐',
                'merchant_room_key': 'room-1',
                'merchant_rate_key': 'rate-1',
                'gid': 'gid-1',
                'hid': 'hid-1',
                'status': 'enabled',
                'notes': '首个映射',
            },
        )

        self.assertEqual(result['status'], 'active')
        self.assertTrue(result['is_complete'])
        self.assertEqual(result['gid'], 'gid-1')
        self.assertEqual(result['notes'], '首个映射')
        self.assertNotIn('last_seen_price', result)

    def test_upsert_mapping_updates_existing_row(self) -> None:
        upsert_merchant_price_mapping(
            self.db,
            mapping_data={
                'tenant_id': 1,
                'shop_id': 1,
                'platform': 'fliggy',
                'room_name': '豪华大床房',
                'rate_name': '标准价-2份早餐',
                'gid': 'gid-1',
                'hid': '',
                'status': 'draft',
            },
        )

        result = upsert_merchant_price_mapping(
            self.db,
            mapping_data={
                'tenant_id': 1,
                'shop_id': 1,
                'platform': 'fliggy',
                'room_name': '豪华大床房',
                'rate_name': '标准价-2份早餐',
                'hid': 'hid-1',
                'status': 'active',
                'notes': '已确认',
            },
        )

        self.assertEqual(result['hid'], 'hid-1')
        self.assertTrue(result['is_complete'])
        self.assertEqual(result['notes'], '已确认')

    def test_list_only_enabled_mappings(self) -> None:
        upsert_merchant_price_mapping(
            self.db,
            mapping_data={
                'tenant_id': 1,
                'shop_id': 1,
                'platform': 'fliggy',
                'room_name': '豪华大床房',
                'rate_name': '标准价-2份早餐',
                'gid': 'gid-1',
                'hid': 'hid-1',
                'status': 'active',
            },
        )
        upsert_merchant_price_mapping(
            self.db,
            mapping_data={
                'tenant_id': 1,
                'shop_id': 1,
                'platform': 'fliggy',
                'room_name': '豪华双床房',
                'rate_name': '标准价-无早餐',
                'status': 'disabled',
            },
        )

        items = list_merchant_price_mappings(self.db, shop_id=1, only_enabled=True)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['room_name'], '豪华大床房')

    def test_get_mapping_returns_none_when_missing(self) -> None:
        result = get_merchant_price_mapping(
            self.db,
            shop_id=1,
            tenant_id=1,
            platform='fliggy',
            room_name='不存在的房型',
            rate_name='标准价',
        )

        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
