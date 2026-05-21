from __future__ import annotations

from dataclasses import dataclass

LOW_RISK_LEVELS = {"L0", "L1"}
HIGH_RISK_LEVELS = {"L2", "L3"}


@dataclass
class ActionExecutionError(RuntimeError):
    """Domain error for action execution failures.

    Attributes:
        code: Stable error code for logs and retries.
        message: Human-readable error message.
    """

    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def normalize_risk_level(level: str | None) -> str:
    """Normalize arbitrary risk-level values.

    Args:
        level: Raw risk-level value.

    Returns:
        Normalized value in L0-L3. Invalid inputs map to L1.
    """
    if not level:
        return "L1"
    normalized = str(level).upper().strip()
    return normalized if normalized in LOW_RISK_LEVELS.union(HIGH_RISK_LEVELS) else "L1"


def is_high_risk(level: str | None) -> bool:
    """Check whether the given risk level requires approval."""
    return normalize_risk_level(level) in HIGH_RISK_LEVELS


def _execute_adjust_price(payload: dict, *, db=None) -> dict:
    """Persist one price adjustment into room_status_snapshots when possible.

    Args:
        payload: Action payload containing pricing fields.
        db: Optional SQLAlchemy session for persistence.

    Returns:
        Execution summary.

    Raises:
        ActionExecutionError: If the payload is invalid.
    """
    max_change_pct = int(payload.get("max_change_pct", 5) or 5)
    if max_change_pct > 30:
        raise ActionExecutionError(
            code="PRICE_CHANGE_TOO_LARGE",
            message=f"max_change_pct too large: {max_change_pct}",
        )

    raw_new_price = payload.get("new_price", payload.get("suggested_price_mid"))
    if raw_new_price is None and db is None:
        return {
            "action_type": "adjust_price",
            "result": "applied",
            "shop_id": int(payload.get("shop_id", 0) or 0),
            "new_price": None,
            "previous_price": None,
            "max_change_pct": max_change_pct,
            "strategy": str(payload.get("strategy") or "safe_incremental"),
            "source": str(payload.get("source") or "auto_pricing"),
            "persisted": False,
            "channel_response": None,
        }
    try:
        new_price = round(float(raw_new_price), 2)
    except (TypeError, ValueError) as exc:
        raise ActionExecutionError(code="INVALID_PRICE", message="new_price is required") from exc
    if new_price <= 0:
        raise ActionExecutionError(code="INVALID_PRICE", message="new_price must be positive")

    shop_id = int(payload.get("shop_id", 0) or 0)
    previous_price_raw = payload.get("previous_price", payload.get("current_price", 0))
    previous_price = round(float(previous_price_raw or 0), 2)
    result = {
        "action_type": "adjust_price",
        "result": "applied",
        "shop_id": shop_id,
        "new_price": new_price,
        "previous_price": previous_price if previous_price > 0 else None,
        "max_change_pct": max_change_pct,
        "strategy": str(payload.get("strategy") or "safe_incremental"),
        "source": str(payload.get("source") or "auto_pricing"),
        "persisted": False,
        "channel_response": None,
    }

    if db is None:
        return result

    if shop_id < 1:
        raise ActionExecutionError(code="INVALID_SHOP_ID", message="shop_id is required for persisted price updates")

    from sqlalchemy import text

    from app.services.fliggy_client import FliggyClient, FliggyClientError
    from app.services.room_status_service import ensure_room_status_table, get_latest_room_status
    from app.services.shop_service import get_room_status_defaults, get_shop_config

    shop_config = get_shop_config(db=db, shop_id=shop_id)
    defer_channel_push = bool(payload.get("defer_channel_push"))
    if shop_config.fliggy_price_push_enabled:
        if defer_channel_push:
            result["channel_push_deferred"] = True
        else:
            try:
                client = FliggyClient(shop_config=shop_config)
                result["channel_response"] = client.push_price(payload)
            except FliggyClientError as exc:
                raise ActionExecutionError(code="FLIGGY_PRICE_PUSH_FAILED", message=str(exc)) from exc

    latest = get_latest_room_status(db=db, shop_id=shop_id)
    if latest is None:
        defaults = get_room_status_defaults(db=db, shop_id=shop_id)
        total_rooms = int(defaults["total_rooms"])
        available_rooms = int(defaults["available_rooms"])
        rooms_sold = total_rooms - available_rooms
    else:
        total_rooms = int(latest["total_rooms"])
        available_rooms = int(latest["available_rooms"])
        rooms_sold = int(latest["rooms_sold"])

    total_rooms = int(payload.get("total_rooms") or total_rooms)
    available_rooms = int(payload.get("available_rooms") or available_rooms)
    if total_rooms < 1:
        total_rooms = 1
    if available_rooms < 0:
        available_rooms = 0
    if available_rooms > total_rooms:
        available_rooms = total_rooms
    if rooms_sold < 0 or rooms_sold > total_rooms:
        rooms_sold = total_rooms - available_rooms
    occupancy_rate = (total_rooms - available_rooms) / total_rooms if total_rooms else 0

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
            "shop_id": shop_id,
            "total_rooms": total_rooms,
            "available_rooms": available_rooms,
            "current_price": new_price,
            "rooms_sold": rooms_sold,
            "occupancy_rate": round(occupancy_rate, 4),
            "source": result["source"][:32],
        },
    )
    result["persisted"] = True
    return result


def execute_low_risk_action(action_type: str, payload: dict, *, db=None) -> dict:
    """Execute a low-risk action in MVP mode.

    Args:
        action_type: Logical action type.
        payload: Action payload.
        db: Optional SQLAlchemy session for persistence.

    Returns:
        Execution result summary.

    Raises:
        ActionExecutionError: If action is unsupported or execution fails.
    """
    normalized_type = str(action_type or "").strip()
    if not normalized_type:
        raise ActionExecutionError(code="INVALID_ACTION", message="action_type is required")

    if payload.get("force_fail"):
        raise ActionExecutionError(code="FORCED_FAILURE", message="execution forced to fail by payload")

    if normalized_type == "adjust_price":
        return _execute_adjust_price(payload, db=db)

    if normalized_type == "auto_reply":
        template = str(payload.get("template") or "friendly_faq")
        return {
            "action_type": normalized_type,
            "result": "replied",
            "template": template,
        }

    if normalized_type == "inventory_sync":
        return {
            "action_type": normalized_type,
            "result": "synced",
            "synced_items": int(payload.get("synced_items", 12) or 12),
        }

    if normalized_type == "order_sync":
        return {
            "action_type": normalized_type,
            "result": "synced",
            "synced_orders": int(payload.get("synced_orders", 20) or 20),
        }

    if normalized_type == "tag_update":
        return {
            "action_type": normalized_type,
            "result": "updated",
            "updated_targets": int(payload.get("updated_targets", 1) or 1),
        }

    raise ActionExecutionError(code="UNSUPPORTED_ACTION", message=f"unsupported action_type: {normalized_type}")


def execute_approved_action(action_type: str, payload: dict, *, db=None) -> dict:
    """Execute high-risk action after manual approval.

    Args:
        action_type: Approved action type.
        payload: Action payload from action record.
        db: Optional SQLAlchemy session for persistence.

    Returns:
        Execution result summary.

    Raises:
        ActionExecutionError: If approved action cannot be executed.
    """
    normalized_type = str(action_type or "").strip()
    if not normalized_type:
        raise ActionExecutionError(code="INVALID_ACTION", message="action_type is required")

    if payload.get("force_fail"):
        raise ActionExecutionError(code="FORCED_FAILURE", message="execution forced to fail by payload")

    if normalized_type == "adjust_price":
        return _execute_adjust_price(payload, db=db)

    if normalized_type == "refund_review":
        return {
            "action_type": normalized_type,
            "result": "processed",
            "auto_execute": bool(payload.get("auto_execute", False)),
        }

    if normalized_type == "batch_publish":
        return {
            "action_type": normalized_type,
            "result": "published",
            "item_count": int(payload.get("item_count", 1) or 1),
        }

    if normalized_type == "batch_unpublish":
        return {
            "action_type": normalized_type,
            "result": "unpublished",
            "item_count": int(payload.get("item_count", 1) or 1),
        }

    raise ActionExecutionError(
        code="UNSUPPORTED_APPROVED_ACTION",
        message=f"unsupported approved action_type: {normalized_type}",
    )
