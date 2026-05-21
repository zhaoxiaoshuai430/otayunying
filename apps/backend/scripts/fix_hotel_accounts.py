from __future__ import annotations

import os
import sys

from sqlalchemy import text

# Ensure project root is on sys.path when running as a script (backend/scripts).
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.db.session import SessionLocal
from app.services.shop_service import upsert_shop
from app.services.user_service import set_user_shop_access, upsert_user


def main() -> int:
    db = SessionLocal()
    try:
        upsert_shop(
            db,
            {
                "tenant_id": 2,
                "shop_id": 2,
                "name": "郑州华智酒店",
                "shop_name": "郑州华智酒店",
                "platform": "fliggy",
                "status": "enabled",
            },
        )
        upsert_shop(
            db,
            {
                "tenant_id": 3,
                "shop_id": 3,
                "name": "郑州中油花园酒店",
                "shop_name": "郑州中油花园酒店",
                "platform": "fliggy",
                "status": "enabled",
            },
        )

        hzjd_id = upsert_user(
            db,
            tenant_id=2,
            username="hzjd",
            password="12345678",
            is_admin=False,
            status="enabled",
        )
        zyjd_id = upsert_user(
            db,
            tenant_id=3,
            username="zyjd",
            password="12345678",
            is_admin=False,
            status="enabled",
        )

        set_user_shop_access(db, user_id=hzjd_id, tenant_id=2, shop_ids=[2])
        set_user_shop_access(db, user_id=zyjd_id, tenant_id=3, shop_ids=[3])

        rows = (
            db.execute(
                text(
                    """
                    SELECT u.tenant_id, u.username, u.status AS user_status,
                           a.shop_id, s.tenant_id AS shop_tenant_id,
                           s.name AS shop_name, s.status AS shop_status
                    FROM users u
                    LEFT JOIN user_shop_access a ON a.user_id = u.id
                    LEFT JOIN shops s ON s.id = a.shop_id
                    WHERE u.username IN ('hzjd', 'zyjd')
                    ORDER BY u.username
                    """
                )
            )
            .mappings()
            .all()
        )
        print("OK")
        for row in rows:
            print(dict(row))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
