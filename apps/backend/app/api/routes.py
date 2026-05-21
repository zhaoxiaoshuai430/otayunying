from __future__ import annotations

from flask import Blueprint, g, request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import enforce_shop_id_match, require_tenant_shop
from app.api.errors import ApiError
from app.schemas.competitor import (
    FliggyGuestLoginRequest,
    FliggyMerchantLoginRequest,
    FliggyMerchantPriceCollectRequest,
    FliggyMerchantPricePreviewRequest,
    FliggyPlaywrightCollectRequest,
    MerchantCredentialUpsertRequest,
)
from app.schemas.pricing import (
    MerchantPriceMappingUpsertRequest,
    MerchantPricingConfirmRequest,
    MerchantPricingDirectSubmitRequest,
    MerchantPricingGenerateRequest,
    MerchantPricingPreviewRequest,
    PricingRecommendationRequest,
)
from app.services.competitor_service import (
    analyze_room_price_history,
    collect_fliggy_hotel_prices_playwright,
    get_competitor_trends,
    get_latest_competitor_prices,
    login_fliggy_guest_session,
    save_competitor_collection,
)
from app.services.fliggy_merchant_service import (
    collect_fliggy_merchant_prices,
    fetch_fliggy_merchant_price_preview,
    login_fliggy_merchant_session,
)
from app.services.merchant_connection_service import get_merchant_credential, save_merchant_credential
from app.services.merchant_price_mapping_service import list_merchant_price_mappings, upsert_merchant_price_mapping
from app.services.merchant_pricing_service import (
    confirm_merchant_pricing_recommendations,
    generate_merchant_pricing_suggestions,
    preview_merchant_pricing_recommendations,
    refresh_merchant_mapping_prices,
    submit_merchant_pricing_recommendations_direct,
)
from app.services.pricing_service import generate_price_recommendation

api_bp = Blueprint('api', __name__)


def _db() -> Session:
    db = getattr(g, 'db', None)
    if db is None:
        raise ApiError(500, 'db session not initialized')
    return db


def _json() -> dict:
    payload = request.get_json(silent=True)
    if payload is None:
        raise ApiError(400, 'Invalid JSON body')
    if not isinstance(payload, dict):
        raise ApiError(400, 'JSON body must be an object')
    return payload


def _q_int(name: str, default: int | None = None) -> int | None:
    raw = request.args.get(name)
    if raw is None or str(raw).strip() == '':
        return default
    try:
        return int(str(raw).strip())
    except ValueError as exc:
        raise ApiError(400, f'Query param {name} must be an integer') from exc


def _q_bounded_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    value = _q_int(name, default=default)
    if value is None:
        value = default
    if value < minimum or value > maximum:
        raise ApiError(400, f'Query param {name} must be between {minimum} and {maximum}')
    return value


def _q_bool(name: str, default: bool = False) -> bool:
    raw = request.args.get(name)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {'1', 'true', 'yes', 'y', 'on'}:
        return True
    if value in {'0', 'false', 'no', 'n', 'off'}:
        return False
    raise ApiError(400, f'Query param {name} must be a boolean')


def _q_str(name: str, default: str | None = None) -> str | None:
    raw = request.args.get(name)
    if raw is None:
        return default
    value = str(raw).strip()
    return value if value else default


def _payload_int(payload: dict, name: str, *, default: int, minimum: int, maximum: int) -> int:
    raw = payload.get(name, default)
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ApiError(400, f'{name} must be an integer') from exc
    if value < minimum or value > maximum:
        raise ApiError(400, f'{name} must be between {minimum} and {maximum}')
    return value


def _payload_float(payload: dict, name: str, *, default: float, minimum: float, maximum: float) -> float:
    raw = payload.get(name, default)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ApiError(400, f'{name} must be a number') from exc
    if value < minimum or value > maximum:
        raise ApiError(400, f'{name} must be between {minimum} and {maximum}')
    return value


@api_bp.route('/health', methods=['GET'])
def health() -> dict:
    return {'status': 'ok'}


@api_bp.route('/pricing/recommend', methods=['POST'])
def recommend_pricing() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    try:
        payload = PricingRecommendationRequest.model_validate(_json())
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        enforce_shop_id_match(tenant_shop_id, payload.shop_id, field_name='payload.shop_id')
        result = generate_price_recommendation(
            db=db,
            shop_id=tenant_shop_id,
            inventory_snapshot=payload.inventory_snapshot.model_dump(),
            target_name=payload.target_name,
            days=payload.days,
            strategy=payload.strategy,
            limit=payload.limit,
            event_date=payload.event_date,
            target_occupancy_min=payload.target_occupancy_min,
            target_occupancy_max=payload.target_occupancy_max,
            expected_cancel_rate=payload.expected_cancel_rate,
            demand_heat=payload.demand_heat,
            competitor_price_cap_ratio=payload.competitor_price_cap_ratio,
        )
        return {'message': 'pricing recommendation generated', **result}
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@api_bp.route('/pricing/merchant-preview', methods=['POST'])
def preview_merchant_pricing_route() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    try:
        payload = MerchantPricingPreviewRequest.model_validate(_json())
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        enforce_shop_id_match(tenant_shop_id, payload.shop_id, field_name='payload.shop_id')
        result = preview_merchant_pricing_recommendations(
            db=db,
            shop_id=tenant_shop_id,
            price_url=payload.price_url,
            selectors=payload.selectors,
            headless=payload.headless,
            selected_items=[item.model_dump() for item in payload.selected_items],
        )
        return {'message': 'merchant pricing preview generated', **result}
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@api_bp.route('/pricing/merchant-generate', methods=['POST'])
def generate_merchant_pricing_route() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    try:
        payload = MerchantPricingGenerateRequest.model_validate(_json())
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        enforce_shop_id_match(tenant_shop_id, payload.shop_id, field_name='payload.shop_id')
        result = generate_merchant_pricing_suggestions(
            db=db,
            shop_id=tenant_shop_id,
            price_url=payload.price_url,
            selectors=payload.selectors,
            headless=payload.headless,
            selected_items=[item.model_dump() for item in payload.selected_items],
            preview_only=payload.preview_only,
            approver_user_id=payload.approver_user_id,
            comment=payload.comment,
        )
        message = 'merchant pricing suggestions generated'
        if not payload.preview_only:
            message = 'merchant pricing suggestions generated and submitted'
        return {'message': message, **result}
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@api_bp.route('/pricing/merchant-direct-submit', methods=['POST'])
def direct_submit_merchant_pricing_route() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    try:
        payload = MerchantPricingDirectSubmitRequest.model_validate(_json())
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        enforce_shop_id_match(tenant_shop_id, payload.shop_id, field_name='payload.shop_id')
        result = submit_merchant_pricing_recommendations_direct(
            db=db,
            shop_id=tenant_shop_id,
            price_url=payload.price_url,
            selectors=payload.selectors,
            headless=payload.headless,
            selected_items=[item.model_dump() for item in payload.selected_items],
            comment=payload.comment,
        )
        return {'message': 'merchant pricing directly submitted', **result}
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@api_bp.route('/pricing/merchant-confirm', methods=['POST'])
def confirm_merchant_pricing_route() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    try:
        payload = MerchantPricingConfirmRequest.model_validate(_json())
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        enforce_shop_id_match(tenant_shop_id, payload.shop_id, field_name='payload.shop_id')
        result = confirm_merchant_pricing_recommendations(
            db=db,
            shop_id=tenant_shop_id,
            approver_user_id=payload.approver_user_id,
            comment=payload.comment,
            confirmed_items=[item.model_dump(mode='json') for item in payload.confirmed_items],
        )
        return {'message': 'merchant pricing submitted', **result}
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@api_bp.route('/pricing/merchant-mappings', methods=['GET'])
def list_merchant_price_mappings_route() -> dict:
    db = _db()
    tenant_id, tenant_shop_id = require_tenant_shop(db)
    shop_id = _q_int('shop_id')
    platform = _q_str('platform', 'fliggy') or 'fliggy'
    only_enabled = _q_bool('only_enabled', False)

    try:
        enforce_shop_id_match(tenant_shop_id, shop_id)
        items = list_merchant_price_mappings(
            db=db,
            shop_id=tenant_shop_id,
            tenant_id=tenant_id,
            platform=platform,
            only_enabled=only_enabled,
        )
        return {'shop_id': tenant_shop_id, 'count': len(items), 'items': items}
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@api_bp.route('/pricing/merchant-mappings', methods=['POST'])
def save_merchant_price_mapping_route() -> dict:
    db = _db()
    tenant_id, tenant_shop_id = require_tenant_shop(db)
    try:
        payload = MerchantPriceMappingUpsertRequest.model_validate(_json())
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        enforce_shop_id_match(tenant_shop_id, payload.shop_id, field_name='payload.shop_id')
        mapping_data = payload.model_dump()
        mapping_data['shop_id'] = tenant_shop_id
        mapping_data['tenant_id'] = tenant_id
        result = upsert_merchant_price_mapping(db=db, mapping_data=mapping_data)
        return {'message': 'merchant price mapping saved', **result}
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@api_bp.route('/pricing/merchant-mappings/refresh-prices', methods=['POST'])
def refresh_merchant_price_mapping_prices_route() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    try:
        payload = MerchantPricingPreviewRequest.model_validate(_json())
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        enforce_shop_id_match(tenant_shop_id, payload.shop_id, field_name='payload.shop_id')
        result = refresh_merchant_mapping_prices(
            db=db,
            shop_id=tenant_shop_id,
            price_url=payload.price_url,
            selectors=payload.selectors,
            headless=payload.headless,
            collect_mode=payload.collect_mode,
            debug_url=payload.debug_url,
        )
        return {'message': 'merchant mapping prices refreshed', **result}
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@api_bp.route('/competitor/latest-prices', methods=['GET'])
def latest_prices() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    shop_id = _q_int('shop_id')
    limit = _q_bounded_int('limit', default=100, minimum=1, maximum=500)
    try:
        enforce_shop_id_match(tenant_shop_id, shop_id)
        return get_latest_competitor_prices(db=db, shop_id=tenant_shop_id, limit=limit)
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@api_bp.route('/competitor/trends', methods=['GET'])
def competitor_trends() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    shop_id = _q_int('shop_id', default=tenant_shop_id)
    days = _q_bounded_int('days', default=7, minimum=1, maximum=365)
    target_name = _q_str('target_name')
    limit = _q_bounded_int('limit', default=200, minimum=1, maximum=500)
    try:
        enforce_shop_id_match(tenant_shop_id, shop_id)
        return get_competitor_trends(db=db, shop_id=tenant_shop_id, days=days, target_name=target_name, limit=limit)
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@api_bp.route('/competitor/fliggy/session/login', methods=['POST'])
def login_fliggy_competitor_guest_route() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    try:
        payload = FliggyGuestLoginRequest.model_validate(_json())
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        enforce_shop_id_match(tenant_shop_id, payload.shop_id, field_name='payload.shop_id')
        result = login_fliggy_guest_session(
            db=db,
            shop_id=tenant_shop_id,
            login_url=payload.login_url,
            start_url=payload.start_url,
            username=payload.username,
            password=payload.password,
            storage_state_name=payload.storage_state_name,
            selectors=payload.selectors,
            headless=payload.headless,
        )
        return {'message': 'guest session saved', **result}
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@api_bp.route('/competitor/fliggy/collect', methods=['POST'])
def collect_fliggy_competitor() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    try:
        payload = FliggyPlaywrightCollectRequest.model_validate(_json())
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        enforce_shop_id_match(tenant_shop_id, payload.shop_id, field_name='payload.shop_id')
        result = collect_fliggy_hotel_prices_playwright(
            db=db,
            shop_id=tenant_shop_id,
            start_url=payload.start_url,
            max_pages=payload.max_pages,
            max_hotels=payload.max_hotels,
            headless=payload.headless,
            collect_mode=payload.collect_mode,
            debug_url=payload.debug_url,
            target_page_url_keyword=payload.target_page_url_keyword,
            login_url=payload.login_url,
            storage_state_name=payload.storage_state_name,
            username=payload.username,
            password=payload.password,
            login_headless=payload.login_headless,
            auto_login=payload.auto_login,
            save_credential=payload.save_credential,
            selectors=payload.selectors,
        )
        if payload.save_result:
            saved = save_competitor_collection(db=db, shop_id=tenant_shop_id, result=result, source='fliggy_playwright')
            result['saved_count'] = saved.get('saved_count', 0)
        return result
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@api_bp.route('/competitor/rooms/analyze', methods=['POST'])
def analyze_room_prices() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    payload = _json()
    try:
        enforce_shop_id_match(tenant_shop_id, payload.get('shop_id', tenant_shop_id), field_name='payload.shop_id')
        days = _payload_int(payload, 'days', default=30, minimum=1, maximum=365)
        my_price = _payload_float(payload, 'my_price', default=299, minimum=0, maximum=999999)
        my_total_rooms = _payload_int(payload, 'my_total_rooms', default=20, minimum=1, maximum=10000)
        my_available_rooms = _payload_int(payload, 'my_available_rooms', default=5, minimum=0, maximum=10000)
        if my_available_rooms > my_total_rooms:
            raise ApiError(400, 'my_available_rooms must be less than or equal to my_total_rooms')
        return analyze_room_price_history(
            db=db,
            shop_id=tenant_shop_id,
            days=days,
            hotel_name=payload.get('hotel_name'),
            my_hotel_name=payload.get('my_hotel_name', 'My Hotel'),
            my_price=my_price,
            my_total_rooms=my_total_rooms,
            my_available_rooms=my_available_rooms,
        )
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@api_bp.route('/merchant/credentials', methods=['GET'])
def merchant_credentials_get() -> dict:
    db = _db()
    tenant_id, tenant_shop_id = require_tenant_shop(db)
    shop_id = _q_int('shop_id', default=tenant_shop_id)
    try:
        enforce_shop_id_match(tenant_shop_id, shop_id)
        return get_merchant_credential(db=db, shop_id=tenant_shop_id, tenant_id=tenant_id)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@api_bp.route('/merchant/credentials', methods=['POST'])
def merchant_credentials_save() -> dict:
    db = _db()
    tenant_id, tenant_shop_id = require_tenant_shop(db)
    try:
        payload = MerchantCredentialUpsertRequest.model_validate(_json())
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        enforce_shop_id_match(tenant_shop_id, payload.shop_id, field_name='payload.shop_id')
        result = save_merchant_credential(
            db=db,
            credential_data={
                'tenant_id': tenant_id,
                'shop_id': tenant_shop_id,
                'username': payload.username,
                'password': payload.password,
                'login_url': payload.login_url,
                'price_url': payload.price_url,
                'storage_state_name': payload.storage_state_name,
                'selectors': payload.selectors,
            },
        )
        return {'message': 'merchant credentials saved', **result}
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@api_bp.route('/merchant/fliggy/session/login', methods=['POST'])
def merchant_login() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    try:
        payload = FliggyMerchantLoginRequest.model_validate(_json())
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        enforce_shop_id_match(tenant_shop_id, payload.shop_id, field_name='payload.shop_id')
        result = login_fliggy_merchant_session(
            db=db,
            shop_id=tenant_shop_id,
            username=payload.username,
            password=payload.password,
            login_url=payload.login_url,
            storage_state_name=payload.storage_state_name,
            selectors=payload.selectors,
            headless=payload.headless,
        )
        return {'message': 'merchant session saved', **result}
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@api_bp.route('/merchant/fliggy/prices/preview', methods=['POST'])
def merchant_preview_prices() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    try:
        payload = FliggyMerchantPricePreviewRequest.model_validate(_json())
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        enforce_shop_id_match(tenant_shop_id, payload.shop_id, field_name='payload.shop_id')
        result = fetch_fliggy_merchant_price_preview(
            db=db,
            shop_id=tenant_shop_id,
            price_url=payload.price_url,
            login_url=payload.login_url,
            storage_state_name=payload.storage_state_name,
            username=payload.username,
            password=payload.password,
            selectors=payload.selectors,
            headless=payload.headless,
            login_headless=payload.login_headless,
            auto_login=payload.auto_login,
            save_credential=payload.save_credential,
            collect_mode=payload.collect_mode,
            debug_url=payload.debug_url,
        )
        return {'message': 'merchant prices previewed', **result}
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@api_bp.route('/merchant/fliggy/prices/collect', methods=['POST'])
def merchant_collect_prices() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    try:
        payload = FliggyMerchantPriceCollectRequest.model_validate(_json())
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        enforce_shop_id_match(tenant_shop_id, payload.shop_id, field_name='payload.shop_id')
        result = collect_fliggy_merchant_prices(
            db=db,
            shop_id=tenant_shop_id,
            price_url=payload.price_url,
            selectors=payload.selectors,
            headless=payload.headless,
            save_result=payload.save_result,
            collect_mode=payload.collect_mode,
            debug_url=payload.debug_url,
        )
        return {'message': 'merchant prices collected', **result}
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc



