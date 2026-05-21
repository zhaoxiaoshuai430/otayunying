import unittest
from unittest.mock import patch

from app.services.action_executor import (
    ActionExecutionError,
    execute_approved_action,
    execute_low_risk_action,
    is_high_risk,
    normalize_risk_level,
)
from app.services.shop_service import ShopConfig


class _FakeDb:
    def __init__(self):
        self.executed = []

    def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))
        return None


class ActionExecutorTestCase(unittest.TestCase):
    def test_risk_normalization(self) -> None:
        self.assertEqual(normalize_risk_level("l2"), "L2")
        self.assertEqual(normalize_risk_level("unknown"), "L1")
        self.assertTrue(is_high_risk("L3"))
        self.assertFalse(is_high_risk("L1"))

    def test_execute_low_risk_action_success(self) -> None:
        result = execute_low_risk_action("inventory_sync", {"synced_items": 7})
        self.assertEqual(result["action_type"], "inventory_sync")
        self.assertEqual(result["result"], "synced")
        self.assertEqual(result["synced_items"], 7)

    def test_execute_low_risk_adjust_price_without_db(self) -> None:
        result = execute_low_risk_action("adjust_price", {"shop_id": 1, "new_price": 520, "max_change_pct": 6})
        self.assertEqual(result["action_type"], "adjust_price")
        self.assertEqual(result["result"], "applied")
        self.assertEqual(result["new_price"], 520)
        self.assertFalse(result["persisted"])

    @patch('app.services.fliggy_client.FliggyClient')
    @patch('app.services.room_status_service.get_latest_room_status')
    @patch('app.services.room_status_service.ensure_room_status_table')
    @patch('app.services.shop_service.get_shop_config')
    def test_execute_adjust_price_with_real_fliggy_push(self, mocked_get_shop, _mocked_ensure_table, mocked_latest, mocked_client_cls) -> None:
        fake_db = _FakeDb()
        mocked_latest.return_value = {'total_rooms': 20, 'available_rooms': 4, 'rooms_sold': 16, 'current_price': 500}
        mocked_get_shop.return_value = ShopConfig(
            tenant_id=1,
            shop_id=1,
            name='店铺1',
            status='enabled',
            source='database',
            fliggy_hotel_id='hotel-1',
            fliggy_room_status_hotel_id='room-hotel-1',
            fliggy_app_key='key',
            fliggy_app_secret='secret',
            fliggy_session='session',
            room_status_auto_enabled=True,
            room_status_total_rooms=20,
            room_status_available_rooms=4,
            room_status_current_price=500.0,
            daily_revenue_auto_enabled=False,
            fliggy_price_push_enabled=True,
            fliggy_price_push_method='taobao.xhotel.rate.update',
            fliggy_price_push_payload_json='{"gid":"gid-1"}',
        )
        mocked_client = mocked_client_cls.return_value
        mocked_client.push_price.return_value = {'xhotel_rate_update_response': {'result': 'success'}}

        result = execute_low_risk_action(
            'adjust_price',
            {'shop_id': 1, 'new_price': 530, 'max_change_pct': 6, 'total_rooms': 20, 'available_rooms': 4},
            db=fake_db,
        )

        self.assertTrue(result['persisted'])
        self.assertIsNotNone(result['channel_response'])
        mocked_client.push_price.assert_called_once()
        self.assertTrue(fake_db.executed)

    def test_execute_low_risk_action_failure(self) -> None:
        with self.assertRaises(ActionExecutionError) as context:
            execute_low_risk_action("inventory_sync", {"force_fail": True})

        self.assertEqual(context.exception.code, "FORCED_FAILURE")

    def test_execute_approved_action_success(self) -> None:
        result = execute_approved_action("adjust_price", {"max_change_pct": 8, "strategy": "safe_incremental"})
        self.assertEqual(result["action_type"], "adjust_price")
        self.assertEqual(result["result"], "applied")
        self.assertEqual(result["max_change_pct"], 8)

    def test_execute_approved_action_failure(self) -> None:
        with self.assertRaises(ActionExecutionError) as context:
            execute_approved_action("unknown_action", {})

        self.assertEqual(context.exception.code, "UNSUPPORTED_APPROVED_ACTION")


if __name__ == "__main__":
    unittest.main()
