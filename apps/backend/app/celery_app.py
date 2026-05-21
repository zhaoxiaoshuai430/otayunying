from __future__ import annotations

from datetime import timedelta

from celery import Celery

from app.core.config import get_settings


def create_celery_app() -> Celery:
    settings = get_settings()
    app = Celery(
        settings.app_name,
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=["app.tasks.competitor_trend_tasks"],
    )
    interval_minutes = max(1, int(settings.competitor_room_price_schedule_interval_minutes or 120))
    app.conf.update(
        timezone="Asia/Shanghai",
        enable_utc=False,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        beat_schedule={
            "collect-competitor-room-prices-every-2-hours": {
                "task": "app.tasks.competitor_trend.collect_all_shops",
                "schedule": timedelta(minutes=interval_minutes),
            }
        },
    )
    return app


celery_app = create_celery_app()
