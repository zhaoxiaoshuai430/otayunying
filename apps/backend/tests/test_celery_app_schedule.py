import os
import sys
import unittest
from datetime import timedelta
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

from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.tasks.competitor_trend_tasks import collect_competitor_room_prices_for_all_shops


class CeleryAppScheduleTestCase(unittest.TestCase):
    def test_competitor_room_price_beat_runs_every_two_hours(self) -> None:
        entry = celery_app.conf.beat_schedule['collect-competitor-room-prices-every-2-hours']

        self.assertEqual(entry['task'], 'app.tasks.competitor_trend.collect_all_shops')
        self.assertEqual(entry['schedule'], timedelta(minutes=120))

    def test_competitor_room_price_task_delegates_to_collector(self) -> None:
        with patch(
            'app.tasks.competitor_trend_tasks.collect_all_enabled_competitor_room_prices',
            return_value={'status': 'success'},
        ) as mocked_collect:
            result = collect_competitor_room_prices_for_all_shops()

        self.assertEqual(result, {'status': 'success'})
        mocked_collect.assert_called_once()
        self.assertIs(mocked_collect.call_args.kwargs['session_factory'], SessionLocal)


if __name__ == '__main__':
    unittest.main()
