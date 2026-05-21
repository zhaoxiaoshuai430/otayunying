from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Callable

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.competitor_hotel_config_service import ensure_competitor_hotels_table
from app.services.competitor_service import (
    crawl_multiple_hotels_room_prices,
    normalize_crawled_room_price_result,
    save_room_prices,
)
from app.services.merchant_connection_service import get_merchant_credential


def list_enabled_competitor_hotel_groups(
    db: Session,
    *,
    max_hotels_per_shop: int = 20,
) -> list[dict]:
    ensure_competitor_hotels_table(db)
    limit = max(1, int(max_hotels_per_shop or 20))
    try:
        rows = db.execute(
            text(
                """
                SELECT tenant_id, shop_id, hotel_name, hotel_url, sort_order, id
                FROM competitor_hotels
                WHERE enabled = 1
                ORDER BY tenant_id ASC, shop_id ASC, sort_order ASC, id ASC
                """
            )
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc

    grouped: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for row in rows:
        tenant_id = int(row.get("tenant_id") or 0)
        shop_id = int(row.get("shop_id") or 0)
        hotel_name = " ".join(str(row.get("hotel_name") or "").strip().split())
        hotel_url = str(row.get("hotel_url") or "").strip()
        if tenant_id < 1 or shop_id < 1 or not hotel_name or not hotel_url:
            continue
        hotels = grouped[(tenant_id, shop_id)]
        if len(hotels) >= limit:
            continue
        hotels.append({"name": hotel_name, "url": hotel_url})

    return [
        {"tenant_id": tenant_id, "shop_id": shop_id, "hotels": hotels}
        for (tenant_id, shop_id), hotels in sorted(grouped.items())
        if hotels
    ]


def list_enabled_competitor_hotel_subscriptions(
    db: Session,
    *,
    max_hotels_per_shop: int = 20,
) -> list[dict]:
    groups = list_enabled_competitor_hotel_groups(db, max_hotels_per_shop=max_hotels_per_shop)
    subscriptions: list[dict] = []
    for group in groups:
        tenant_id = int(group.get("tenant_id") or 0)
        shop_id = int(group.get("shop_id") or 0)
        credential = get_merchant_credential(
            db=db,
            shop_id=shop_id,
            tenant_id=tenant_id,
            platform="fliggy_guest",
        )
        storage_state_name = str(credential.get("storage_state_name") or "").strip()
        for hotel in list(group.get("hotels") or []):
            hotel_name = " ".join(str(hotel.get("name") or "").strip().split())
            hotel_url = str(hotel.get("url") or "").strip()
            if tenant_id < 1 or shop_id < 1 or not hotel_name or not hotel_url:
                continue
            subscriptions.append(
                {
                    "tenant_id": tenant_id,
                    "shop_id": shop_id,
                    "hotel_name": hotel_name,
                    "hotel_url": hotel_url,
                    "storage_state_name": storage_state_name,
                }
            )
    return subscriptions


def build_competitor_fetch_jobs(subscriptions: list[dict]) -> list[dict]:
    jobs_by_key: dict[str, dict] = {}
    for item in subscriptions:
        hotel_url = str(item.get("hotel_url") or "").strip()
        hotel_name = " ".join(str(item.get("hotel_name") or "").strip().split())
        shop_id = int(item.get("shop_id") or 0)
        tenant_id = int(item.get("tenant_id") or 0)
        storage_state_name = str(item.get("storage_state_name") or "").strip()
        if tenant_id < 1 or shop_id < 1 or not hotel_url or not hotel_name:
            continue
        job_key = f"{hotel_url}\n{storage_state_name or shop_id}"
        job = jobs_by_key.get(job_key)
        if job is None:
            job = {
                "hotel_url": hotel_url,
                "crawl_name": hotel_name,
                "crawl_shop_id": shop_id,
                "storage_state_name": storage_state_name,
                "subscriptions": [],
            }
            jobs_by_key[job_key] = job
        if not str(job.get("crawl_name") or "").strip():
            job["crawl_name"] = hotel_name
        job["subscriptions"].append(
            {
                "tenant_id": tenant_id,
                "shop_id": shop_id,
                "hotel_name": hotel_name,
                "hotel_url": hotel_url,
                "storage_state_name": storage_state_name,
            }
        )

    return [jobs_by_key[key] for key in sorted(jobs_by_key)]


def collect_competitor_room_price_job(
    *,
    hotel_url: str,
    crawl_name: str,
    crawl_shop_id: int,
    storage_state_name: str,
    headless: bool,
    debug_url: str,
) -> dict:
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    crawl_results = crawl_multiple_hotels_room_prices(
        hotels=[{"name": crawl_name, "url": hotel_url}],
        headless=headless,
        debug_url=debug_url,
        shop_id=int(crawl_shop_id),
        collect_mode="storage_state",
        storage_state_name=storage_state_name,
    )
    result = normalize_crawled_room_price_result(
        crawl_results[0] if crawl_results else {"hotel_name": crawl_name, "hotel_url": hotel_url, "rooms": []},
        hotel_name=crawl_name,
        hotel_url=hotel_url,
    )
    failed_hotels = []
    if result.get("error"):
        failed_hotels.append(
            {
                "hotel_name": str(result.get("hotel_name") or crawl_name),
                "error": str(result.get("error") or ""),
            }
        )
    return {
        "hotel_url": hotel_url,
        "crawl_name": crawl_name,
        "started_at": started_at,
        "hotel_count": 1,
        "total_rooms": len(result.get("rooms") or []),
        "failed_count": len(failed_hotels),
        "failed_hotels": failed_hotels,
        "crawl_result": result,
    }


def _build_shop_distribution_payloads(fetch_jobs: list[dict]) -> dict[int, list[dict]]:
    shop_payloads: dict[int, list[dict]] = defaultdict(list)
    for job in fetch_jobs:
        crawl_result = normalize_crawled_room_price_result(job.get("crawl_result"))
        for subscription in list(job.get("subscriptions") or []):
            shop_id = int(subscription.get("shop_id") or 0)
            hotel_name = " ".join(str(subscription.get("hotel_name") or "").strip().split())
            hotel_url = str(subscription.get("hotel_url") or "").strip()
            if shop_id < 1 or not hotel_name or not hotel_url:
                continue
            shop_payloads[shop_id].append(
                normalize_crawled_room_price_result(
                    crawl_result,
                    hotel_name=hotel_name,
                    hotel_url=hotel_url,
                )
            )
    return shop_payloads


def collect_competitor_room_prices_for_shop(
    db: Session,
    *,
    shop_id: int,
    crawl_results: list[dict],
) -> dict:
    saved_count = save_room_prices(db=db, shop_id=int(shop_id), crawl_results=crawl_results)
    total_rooms = sum(
        len(item.get("rooms") or [])
        for item in crawl_results
        if isinstance(item, dict)
    )
    failed_hotels = [
        {
            "hotel_name": str(item.get("hotel_name") or ""),
            "error": str(item.get("error") or ""),
        }
        for item in crawl_results
        if isinstance(item, dict) and item.get("error")
    ]
    return {
        "shop_id": int(shop_id),
        "started_at": min((str(item.get("collected_at") or "") for item in crawl_results if isinstance(item, dict)), default=""),
        "hotel_count": len(crawl_results),
        "total_rooms": total_rooms,
        "saved_count": int(saved_count),
        "failed_count": len(failed_hotels),
        "failed_hotels": failed_hotels,
    }


def collect_all_enabled_competitor_room_prices(*, session_factory: Callable[[], Session]) -> dict:
    settings = get_settings()
    if not bool(settings.competitor_room_price_schedule_enabled):
        return {"status": "skipped", "reason": "schedule_disabled", "shop_count": 0, "results": []}

    db = session_factory()
    try:
        subscriptions = list_enabled_competitor_hotel_subscriptions(
            db,
            max_hotels_per_shop=int(settings.competitor_room_price_schedule_max_hotels_per_shop or 20),
        )
    finally:
        db.close()

    fetch_jobs = build_competitor_fetch_jobs(subscriptions)
    fetched_results = []
    for job in fetch_jobs:
        try:
            fetched_results.append(
                {
                    **job,
                    **collect_competitor_room_price_job(
                        hotel_url=str(job.get("hotel_url") or ""),
                        crawl_name=str(job.get("crawl_name") or ""),
                        crawl_shop_id=int(job.get("crawl_shop_id") or 0),
                        storage_state_name=str(job.get("storage_state_name") or ""),
                        headless=bool(settings.competitor_room_price_schedule_headless),
                        debug_url=str(settings.competitor_room_price_schedule_debug_url or ""),
                    ),
                }
            )
        except Exception as exc:
            fetched_results.append(
                {
                    **job,
                    "hotel_url": str(job.get("hotel_url") or ""),
                    "crawl_name": str(job.get("crawl_name") or ""),
                    "hotel_count": 1,
                    "total_rooms": 0,
                    "failed_count": 1,
                    "failed_hotels": [{"hotel_name": str(job.get("crawl_name") or ""), "error": str(exc)}],
                    "crawl_result": normalize_crawled_room_price_result(
                        {"hotel_name": str(job.get("crawl_name") or ""), "hotel_url": str(job.get("hotel_url") or ""), "error": str(exc), "rooms": []}
                    ),
                    "error": str(exc),
                }
            )

    shop_payloads = _build_shop_distribution_payloads(fetched_results)
    results = []
    for shop_id in sorted(shop_payloads):
        shop_db = session_factory()
        try:
            results.append(
                collect_competitor_room_prices_for_shop(
                    shop_db,
                    shop_id=shop_id,
                    crawl_results=list(shop_payloads.get(shop_id) or []),
                )
            )
        except Exception as exc:
            results.append(
                {
                    "shop_id": shop_id,
                    "hotel_count": len(list(shop_payloads.get(shop_id) or [])),
                    "total_rooms": 0,
                    "saved_count": 0,
                    "failed_count": len(list(shop_payloads.get(shop_id) or [])),
                    "error": str(exc),
                }
            )
        finally:
            shop_db.close()

    return {
        "status": "success",
        "shop_count": len(shop_payloads),
        "fetch_job_count": len(fetch_jobs),
        "hotel_count": sum(int(item.get("hotel_count") or 0) for item in results),
        "total_rooms": sum(int(item.get("total_rooms") or 0) for item in results),
        "saved_count": sum(int(item.get("saved_count") or 0) for item in results),
        "failed_count": sum(int(item.get("failed_count") or 0) for item in results),
        "results": results,
    }
