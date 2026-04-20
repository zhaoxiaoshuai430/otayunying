from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


def ensure_competitor_hotels_table(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS competitor_hotels (
              id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
              tenant_id BIGINT UNSIGNED NOT NULL,
              shop_id BIGINT UNSIGNED NOT NULL,
              hotel_name VARCHAR(128) NOT NULL,
              hotel_url VARCHAR(2048) NOT NULL,
              enabled TINYINT(1) NOT NULL DEFAULT 1,
              sort_order INT NOT NULL DEFAULT 10,
              created_by BIGINT UNSIGNED NOT NULL DEFAULT 0,
              updated_by BIGINT UNSIGNED NOT NULL DEFAULT 0,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (id),
              KEY idx_competitor_hotels_tenant_shop (tenant_id, shop_id),
              KEY idx_competitor_hotels_shop_enabled (shop_id, enabled)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    )


def _normalize_hotel_name(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_hotel_url(value: object) -> str:
    return str(value or "").strip()


def _serialize_row(row: dict) -> dict:
    return {
        "id": int(row.get("id") or 0),
        "hotel_name": _normalize_hotel_name(row.get("hotel_name")),
        "hotel_url": _normalize_hotel_url(row.get("hotel_url")),
        "enabled": bool(int(row.get("enabled") or 0)),
        "sort_order": int(row.get("sort_order") or 0),
    }


def list_competitor_hotels(db: Session, *, tenant_id: int, shop_id: int, only_enabled: bool = False) -> list[dict]:
    try:
        ensure_competitor_hotels_table(db)
        where_sql = "tenant_id = :tenant_id AND shop_id = :shop_id"
        params = {"tenant_id": int(tenant_id), "shop_id": int(shop_id)}
        if only_enabled:
            where_sql += " AND enabled = 1"
        rows = (
            db.execute(
                text(
                    f"""
                    SELECT id, hotel_name, hotel_url, enabled, sort_order
                    FROM competitor_hotels
                    WHERE {where_sql}
                    ORDER BY sort_order ASC, id ASC
                    """
                ),
                params,
            )
            .mappings()
            .all()
        )
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc
    return [_serialize_row(dict(row)) for row in rows]


def replace_competitor_hotels(
    db: Session,
    *,
    tenant_id: int,
    shop_id: int,
    items: list[dict],
    actor_user_id: int = 0,
) -> list[dict]:
    normalized_items: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        hotel_name = _normalize_hotel_name(item.get("hotel_name") or item.get("name"))
        hotel_url = _normalize_hotel_url(item.get("hotel_url") or item.get("url"))
        if not hotel_name or not hotel_url:
            continue
        key = f"{hotel_name}|{hotel_url}"
        if key in seen:
            continue
        seen.add(key)
        normalized_items.append(
            {
                "hotel_name": hotel_name,
                "hotel_url": hotel_url,
                "enabled": 1 if bool(item.get("enabled", True)) else 0,
                "sort_order": int(item.get("sort_order") or ((index + 1) * 10)),
            }
        )

    try:
        ensure_competitor_hotels_table(db)
        db.execute(
            text(
                """
                DELETE FROM competitor_hotels
                WHERE tenant_id = :tenant_id
                  AND shop_id = :shop_id
                """
            ),
            {"tenant_id": int(tenant_id), "shop_id": int(shop_id)},
        )
        for item in normalized_items:
            db.execute(
                text(
                    """
                    INSERT INTO competitor_hotels (
                      tenant_id, shop_id, hotel_name, hotel_url, enabled, sort_order, created_by, updated_by
                    ) VALUES (
                      :tenant_id, :shop_id, :hotel_name, :hotel_url, :enabled, :sort_order, :actor_user_id, :actor_user_id
                    )
                    """
                ),
                {
                    "tenant_id": int(tenant_id),
                    "shop_id": int(shop_id),
                    "hotel_name": item["hotel_name"],
                    "hotel_url": item["hotel_url"],
                    "enabled": int(item["enabled"]),
                    "sort_order": int(item["sort_order"]),
                    "actor_user_id": int(actor_user_id or 0),
                },
            )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError(str(exc)) from exc

    return list_competitor_hotels(db=db, tenant_id=tenant_id, shop_id=shop_id, only_enabled=False)
