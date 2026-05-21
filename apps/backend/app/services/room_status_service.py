"""Room status snapshots: total_rooms, available_rooms, current_price, occupancy, rooms_sold."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.shop_service import get_room_status_defaults, get_shop_config


def ensure_room_status_table(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS room_status_snapshots (
              id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
              shop_id BIGINT UNSIGNED NOT NULL,
              total_rooms INT UNSIGNED NOT NULL DEFAULT 1,
              available_rooms INT UNSIGNED NOT NULL DEFAULT 0,
              current_price DECIMAL(10, 2) NOT NULL DEFAULT 0,
              rooms_sold INT UNSIGNED NOT NULL DEFAULT 0,
              occupancy_rate DECIMAL(5, 4) NOT NULL DEFAULT 0,
              source VARCHAR(32) NOT NULL DEFAULT 'config',
              captured_at DATETIME NOT NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (id),
              KEY idx_room_status_shop_time (shop_id, captured_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    )


def save_room_status(
    db: Session,
    *,
    shop_id: int,
    total_rooms: int,
    available_rooms: int,
    current_price: float,
    rooms_sold: int | None = None,
    source: str = 'config',
) -> None:
    if total_rooms < 1:
        total_rooms = 1
    if available_rooms > total_rooms:
        available_rooms = total_rooms
    if rooms_sold is None:
        rooms_sold = total_rooms - available_rooms
    rooms_sold = max(0, min(rooms_sold, total_rooms))
    occupancy = (total_rooms - available_rooms) / total_rooms if total_rooms else 0

    ensure_room_status_table(db)
    db.execute(
        text(
            """
            INSERT INTO room_status_snapshots
            (shop_id, total_rooms, available_rooms, current_price, rooms_sold, occupancy_rate, source, captured_at)
            VALUES
            (:shop_id, :total_rooms, :available_rooms, :current_price, :rooms_sold, :occupancy_rate, :source, NOW())
            """
        ),
        {
            'shop_id': shop_id,
            'total_rooms': total_rooms,
            'available_rooms': available_rooms,
            'current_price': round(float(current_price), 2),
            'rooms_sold': rooms_sold,
            'occupancy_rate': round(occupancy, 4),
            'source': str(source)[:32],
        },
    )
    db.commit()


def get_latest_room_status(db: Session, *, shop_id: int) -> dict | None:
    ensure_room_status_table(db)
    row = db.execute(
        text(
            """
            SELECT total_rooms, available_rooms, current_price, rooms_sold, occupancy_rate, source, captured_at
            FROM room_status_snapshots
            WHERE shop_id = :shop_id
            ORDER BY captured_at DESC
            LIMIT 1
            """
        ),
        {'shop_id': shop_id},
    ).mappings().first()
    if not row:
        return None
    return {
        'total_rooms': int(row['total_rooms']),
        'available_rooms': int(row['available_rooms']),
        'current_price': float(row['current_price']),
        'rooms_sold': int(row['rooms_sold']),
        'occupancy_rate': float(row['occupancy_rate']),
        'source': str(row['source']),
        'captured_at': str(row['captured_at']),
    }


def fetch_room_status_from_fliggy(db: Session, shop_id: int) -> dict | None:
    """Call Fliggy baseinfo and parse total_rooms / current_price if possible."""
    from app.services.fliggy_client import FliggyClient, FliggyClientError

    settings = get_settings()
    shop_config = get_shop_config(db=db, shop_id=shop_id)
    if not shop_config.fliggy_app_key or not shop_config.fliggy_app_secret:
        return None
    hotel_id = shop_config.fliggy_room_status_hotel_id or shop_config.fliggy_hotel_id
    if not hotel_id:
        return None

    client = FliggyClient(shop_config=shop_config)
    try:
        result = client.call(
            method=settings.fliggy_sync_method_hotel_baseinfo,
            biz_params={'hid': str(hotel_id), 'need_hotel_dynamic_info': True},
            use_session=True,
        )
    except FliggyClientError:
        return None

    total_rooms = 0
    current_price = 0.0
    resp = result.get('xhotel_baseinfo_get_response') or result.get('hotel_base_info_get_response') or result
    if isinstance(resp, dict):
        hotel = resp.get('hotel') or resp.get('data') or resp
        if isinstance(hotel, dict):
            rooms = hotel.get('room_types') or hotel.get('rooms') or hotel.get('room_infos') or []
            if isinstance(rooms, list):
                for room in rooms:
                    if isinstance(room, dict):
                        total_rooms += int(room.get('room_count') or room.get('count') or room.get('total_rooms') or 0)
                        price_raw = room.get('price') or room.get('rate') or room.get('current_price')
                        if price_raw is not None:
                            try:
                                current_price = float(price_raw)
                                break
                            except (TypeError, ValueError):
                                pass
            if total_rooms == 0:
                total_rooms = int(hotel.get('total_room_count') or hotel.get('room_count') or 0)
            if current_price == 0:
                current_price = float(hotel.get('min_price') or hotel.get('current_price') or 0)

    if total_rooms == 0 and current_price == 0:
        return None

    defaults = get_room_status_defaults(db=db, shop_id=shop_id)
    return {
        'total_rooms': total_rooms or int(defaults['total_rooms']),
        'current_price': current_price or float(defaults['current_price']),
    }
