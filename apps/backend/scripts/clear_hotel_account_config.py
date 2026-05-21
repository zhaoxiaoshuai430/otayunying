from __future__ import annotations

import os
import sys

from sqlalchemy import text

# Ensure project root is on sys.path when running as a script (backend/scripts).
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.db.session import SessionLocal
from app.services.competitor_hotel_config_service import replace_competitor_hotels
from app.services.manual_room_mapping_service import replace_manual_room_mappings


TARGET_ACCOUNTS = (
    {"tenant_id": 2, "username": "hzjd", "shop_id": 2},
    {"tenant_id": 3, "username": "zyjd", "shop_id": 3},
)


def _find_user_id(db, *, tenant_id: int, username: str) -> int:
    row = (
        db.execute(
            text(
                """
                SELECT id
                FROM users
                WHERE tenant_id = :tenant_id AND username = :username
                LIMIT 1
                """
            ),
            {"tenant_id": int(tenant_id), "username": username},
        )
        .mappings()
        .first()
    )
    return int((row or {}).get("id") or 0)


def main() -> int:
    db = SessionLocal()
    try:
        for account in TARGET_ACCOUNTS:
            tenant_id = int(account["tenant_id"])
            username = str(account["username"])
            shop_id = int(account["shop_id"])
            user_id = _find_user_id(db, tenant_id=tenant_id, username=username)
            if user_id < 1:
                print(f"SKIP {username}: user not found")
                continue

            replace_competitor_hotels(
                db,
                tenant_id=tenant_id,
                shop_id=shop_id,
                items=[],
                actor_user_id=user_id,
            )
            replace_manual_room_mappings(
                db,
                tenant_id=tenant_id,
                user_id=user_id,
                shop_id=shop_id,
                items=[],
            )
            print(f"OK {username}: tenant_id={tenant_id}, user_id={user_id}, shop_id={shop_id}, cleared")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
