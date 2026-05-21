from __future__ import annotations

from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.services.competitor_room_price_schedule_service import collect_all_enabled_competitor_room_prices


@celery_app.task(name="app.tasks.competitor_trend.collect_all_shops")
def collect_competitor_room_prices_for_all_shops() -> dict:
    return collect_all_enabled_competitor_room_prices(session_factory=SessionLocal)
