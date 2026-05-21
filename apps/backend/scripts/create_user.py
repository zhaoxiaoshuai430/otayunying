from __future__ import annotations

import argparse
import os
import sys

# Ensure project root is on sys.path when running as a script (backend/scripts).
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from app.db.session import SessionLocal
from app.services.user_service import set_user_shop_access, upsert_user


def _parse_shop_ids(raw: str) -> list[int]:
    value = str(raw or '').strip()
    if not value:
        return []
    result: list[int] = []
    for part in value.split(','):
        part = part.strip()
        if not part:
            continue
        result.append(int(part))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description='Create/update a login user (tenant/shop aware).')
    parser.add_argument('--tenant-id', type=int, required=True)
    parser.add_argument('--username', type=str, required=True)
    parser.add_argument('--password', type=str, required=True)
    parser.add_argument('--shops', type=str, default='', help='Comma-separated shop_ids, e.g. 1,2,3')
    parser.add_argument('--admin', action='store_true', help='Admin user can access all shops under tenant')
    args = parser.parse_args()

    shop_ids = _parse_shop_ids(args.shops)

    db = SessionLocal()
    try:
        user_id = upsert_user(
            db,
            tenant_id=int(args.tenant_id),
            username=str(args.username),
            password=str(args.password),
            is_admin=bool(args.admin),
        )

        if shop_ids:
            set_user_shop_access(db, user_id=user_id, tenant_id=int(args.tenant_id), shop_ids=shop_ids)

        print('OK')
        print(f'user_id={user_id}')
        print(f'tenant_id={int(args.tenant_id)}')
        print(f'username={str(args.username).strip()}')
        print(f'admin={1 if args.admin else 0}')
        print(f'shops={shop_ids}')
        return 0
    finally:
        db.close()


if __name__ == '__main__':
    raise SystemExit(main())