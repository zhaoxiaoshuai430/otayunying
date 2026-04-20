from __future__ import annotations

from flask import Blueprint, g, request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import enforce_shop_id_match, require_plugin_auth_context, require_tenant_shop
from app.api.errors import ApiError
from app.schemas.competitor import FliggyPlaywrightCollectRequest, HotelRoomCrawlRequest
from app.schemas.plugin import (
    PluginCompetitorHotelsSaveRequest,
    PluginLoginRequest,
    PluginSwitchShopRequest,
)
from app.schemas.pricing import (
    CompetitorDrivenPricingPreviewRequest,
    CompetitorPricingAdviceRequest,
    MerchantPricingDirectSubmitRequest,
    MerchantPricingPreviewRequest,
    MerchantUniformPriceSubmitRequest,
)
from app.services.competitor_pricing_advice_service import preview_competitor_pricing_advice
from app.services.competitor_hotel_config_service import list_competitor_hotels, replace_competitor_hotels
from app.services.competitor_live_cache import (
    build_live_competitor_prices_payload,
    store_live_competitor_result,
)
from app.services.competitor_service import (
    collect_fliggy_hotel_prices_from_extension_page,
    collect_fliggy_hotel_prices_playwright,
    crawl_multiple_hotels_room_prices,
    get_latest_competitor_prices,
    save_competitor_collection,
    save_room_prices,
)
from app.services.merchant_pricing_service import (
    list_merchant_pricing_items,
    preview_competitor_driven_pricing_workflow,
    preview_merchant_pricing_recommendations,
    submit_merchant_pricing_recommendations_direct,
    submit_uniform_merchant_pricing,
)
from app.services.plugin_auth_service import (
    build_plugin_auth_payload,
    extract_bearer_token,
    login_plugin_user,
    resolve_plugin_token,
    revoke_plugin_token,
    switch_plugin_shop,
)

plugin_bp = Blueprint('plugin_api', __name__, url_prefix='/plugin')

_PLUGIN_NAME = 'fliggy-ops'


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


@plugin_bp.route('/service-status', methods=['GET'])
def plugin_service_status() -> dict:
    return {
        'status': 'ok',
        'plugin': _PLUGIN_NAME,
        'mcp_enabled': True,
        'web_console_available': False,
    }


@plugin_bp.route('/auth/login', methods=['POST'])
def plugin_auth_login() -> dict:
    db = _db()
    try:
        payload = PluginLoginRequest.model_validate(_json())
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        return login_plugin_user(
            db=db,
            tenant_id=int(payload.tenant_id),
            username=str(payload.username),
            password=str(payload.password),
        )
    except ValueError as exc:
        raise ApiError(401, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@plugin_bp.route('/auth/logout', methods=['POST'])
def plugin_auth_logout() -> dict:
    db = _db()
    token = extract_bearer_token(request.headers.get('Authorization'))
    if token:
        try:
            revoke_plugin_token(db=db, token=token)
        except RuntimeError as exc:
            raise ApiError(500, str(exc)) from exc
    return {'message': 'logged out'}


@plugin_bp.route('/auth/me', methods=['GET'])
def plugin_auth_me() -> dict:
    db = _db()
    token = extract_bearer_token(request.headers.get('Authorization'))
    if not token:
        return {'authenticated': False}
    try:
        context = resolve_plugin_token(db=db, token=token)
        if context is None:
            return {'authenticated': False}
        return build_plugin_auth_payload(db=db, context=context)
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@plugin_bp.route('/auth/shops', methods=['GET'])
def plugin_auth_shops() -> dict:
    db = _db()
    context = require_plugin_auth_context()
    try:
        payload = build_plugin_auth_payload(db=db, context=context)
        return {'items': payload.get('shops') or [], 'current_shop': payload.get('current_shop')}
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@plugin_bp.route('/auth/switch-shop', methods=['POST'])
def plugin_auth_switch_shop() -> dict:
    db = _db()
    context = require_plugin_auth_context()
    try:
        payload = PluginSwitchShopRequest.model_validate(_json())
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc
    try:
        return switch_plugin_shop(db=db, context=context, shop_id=int(payload.shop_id))
    except ValueError as exc:
        raise ApiError(404, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@plugin_bp.route('/competitor/hotels', methods=['GET', 'POST'])
def plugin_competitor_hotels() -> dict:
    db = _db()
    context = require_plugin_auth_context()
    if request.method == 'GET':
        try:
            items = list_competitor_hotels(
                db=db,
                tenant_id=int(context.tenant_id),
                shop_id=int(context.current_shop_id),
                only_enabled=False,
            )
            return {'shop_id': int(context.current_shop_id), 'items': items}
        except RuntimeError as exc:
            raise ApiError(500, str(exc)) from exc

    try:
        payload = PluginCompetitorHotelsSaveRequest.model_validate(_json())
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc
    try:
        items = replace_competitor_hotels(
            db=db,
            tenant_id=int(context.tenant_id),
            shop_id=int(context.current_shop_id),
            items=[item.model_dump() for item in payload.items],
            actor_user_id=int(context.user_id),
        )
        return {'shop_id': int(context.current_shop_id), 'saved_count': len(items), 'items': items}
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@plugin_bp.route('/competitor/latest-prices', methods=['GET', 'POST'])
def plugin_competitor_latest_prices() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    if request.method == 'GET':
        shop_id = _q_int('shop_id')
        limit = _q_bounded_int('limit', default=100, minimum=1, maximum=500)
        try:
            enforce_shop_id_match(tenant_shop_id, shop_id)
            return get_latest_competitor_prices(db=db, shop_id=tenant_shop_id, limit=limit)
        except RuntimeError as exc:
            raise ApiError(500, str(exc)) from exc

    try:
        payload = FliggyPlaywrightCollectRequest.model_validate(_json())
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        enforce_shop_id_match(tenant_shop_id, payload.shop_id, field_name='payload.shop_id')
        collect_mode = str(payload.collect_mode or '').strip().lower() or 'cdp_current_page'
        if collect_mode == 'extension_page':
            result = collect_fliggy_hotel_prices_from_extension_page(
                shop_id=tenant_shop_id,
                start_url=payload.start_url,
                max_hotels=payload.max_hotels,
                target_hotel_names=payload.target_hotel_names,
                page_snapshot=payload.page_snapshot,
            )
            save_source = 'fliggy_extension'
        else:
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
                save_credential=payload.save_credential,
                selectors=payload.selectors,
                target_hotel_names=payload.target_hotel_names,
                runtime_settings={
                    'schedule_enabled': False,
                    'debug_url': str(payload.debug_url or ''),
                    'target_page_url_keyword': str(payload.target_page_url_keyword or ''),
                    'max_pages': int(payload.max_pages),
                    'max_hotels': int(payload.max_hotels),
                    'target_hotel_names': list(payload.target_hotel_names or []),
                },
            )
            save_source = 'fliggy_playwright'

        live_result = {
            **result,
            'matched_page_url': result.get('matched_page_url') or result.get('debug_url') or payload.start_url,
            'target_page_url_keyword': str(payload.target_page_url_keyword or ''),
            'debug_url': payload.debug_url,
            'collect_mode': collect_mode,
            'target_hotel_names': list(payload.target_hotel_names or []),
        }
        cache_info = store_live_competitor_result(
            shop_id=tenant_shop_id,
            result=live_result,
            source='fliggy_live_latest_prices',
        )
        response = build_live_competitor_prices_payload(
            shop_id=tenant_shop_id,
            result=live_result,
            source='fliggy_live_latest_prices',
        )
        response['matched_page_url'] = live_result.get('matched_page_url')
        response['target_page_url_keyword'] = live_result.get('target_page_url_keyword')
        response['debug_url'] = str(payload.debug_url or '')
        response['collect_mode'] = collect_mode
        response['cache_info'] = cache_info
        if payload.save_result:
            saved = save_competitor_collection(db=db, shop_id=tenant_shop_id, result=result, source=save_source)
            response['saved_count'] = saved.get('saved_count', 0)
        return response
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@plugin_bp.route('/fliggy/collect', methods=['POST'])
def plugin_fliggy_collect() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    try:
        payload = FliggyPlaywrightCollectRequest.model_validate(_json())
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        enforce_shop_id_match(tenant_shop_id, payload.shop_id, field_name='payload.shop_id')
        collect_mode = str(payload.collect_mode or '').strip().lower() or 'cdp_current_page'
        if collect_mode == 'extension_page':
            result = collect_fliggy_hotel_prices_from_extension_page(
                shop_id=tenant_shop_id,
                start_url=payload.start_url,
                max_hotels=payload.max_hotels,
                target_hotel_names=payload.target_hotel_names,
                page_snapshot=payload.page_snapshot,
            )
            save_source = 'fliggy_extension'
        else:
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
                save_credential=payload.save_credential,
                selectors=payload.selectors,
                target_hotel_names=payload.target_hotel_names,
                runtime_settings=None,
            )
            save_source = 'fliggy_playwright'
        if payload.save_result:
            saved = save_competitor_collection(db=db, shop_id=tenant_shop_id, result=result, source=save_source)
            result['saved_count'] = saved.get('saved_count', 0)
        return result
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc

@plugin_bp.route('/competitor/room-prices', methods=['POST'])
def plugin_competitor_room_prices() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    try:
        payload = HotelRoomCrawlRequest.model_validate(_json())
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        enforce_shop_id_match(tenant_shop_id, payload.shop_id, field_name='payload.shop_id')
        hotels = [item.model_dump() for item in payload.hotels]
        crawl_results = crawl_multiple_hotels_room_prices(
            hotels=hotels,
            headless=payload.headless,
            debug_url=payload.debug_url,
        )
        total_rooms = sum(
            len(result.get('rooms') or [])
            for result in crawl_results
            if isinstance(result, dict)
        )
        response = {
            'shop_id': tenant_shop_id,
            'hotel_count': len(crawl_results),
            'total_rooms': total_rooms,
            'hotels': crawl_results,
        }
        if payload.save_result:
            response['saved_count'] = save_room_prices(
                db=db,
                shop_id=tenant_shop_id,
                crawl_results=crawl_results,
            )
        return response
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@plugin_bp.route('/pricing/merchant-preview', methods=['POST'])
def plugin_merchant_pricing_preview() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    raw_payload = _json()
    try:
        payload = MerchantPricingPreviewRequest.model_validate(raw_payload)
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        enforce_shop_id_match(tenant_shop_id, payload.shop_id, field_name='payload.shop_id')
        return preview_merchant_pricing_recommendations(
            db=db,
            shop_id=tenant_shop_id,
            price_url=payload.price_url,
            selectors=payload.selectors,
            headless=payload.headless,
            selected_items=[item.model_dump() for item in payload.selected_items],
            collect_mode=payload.collect_mode,
            debug_url=payload.debug_url,
        )
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@plugin_bp.route('/pricing/merchant-items', methods=['POST'])
def plugin_merchant_pricing_items() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    raw_payload = _json()
    try:
        payload = MerchantPricingPreviewRequest.model_validate(raw_payload)
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        enforce_shop_id_match(tenant_shop_id, payload.shop_id, field_name='payload.shop_id')
        return list_merchant_pricing_items(
            db=db,
            shop_id=tenant_shop_id,
            price_url=payload.price_url,
            selectors=payload.selectors,
            headless=payload.headless,
            selected_items=[item.model_dump() for item in payload.selected_items],
            collect_mode=payload.collect_mode,
            debug_url=payload.debug_url,
        )
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@plugin_bp.route('/pricing/merchant-direct-submit', methods=['POST'])
def plugin_merchant_pricing_direct_submit() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    raw_payload = _json()
    try:
        payload = MerchantPricingDirectSubmitRequest.model_validate(raw_payload)
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    confirmed_items = raw_payload.get('confirmed_items')
    if not isinstance(confirmed_items, list):
        confirmed_items = None

    try:
        enforce_shop_id_match(tenant_shop_id, payload.shop_id, field_name='payload.shop_id')
        return submit_merchant_pricing_recommendations_direct(
            db=db,
            shop_id=tenant_shop_id,
            price_url=payload.price_url,
            selectors=payload.selectors,
            headless=payload.headless,
            selected_items=[item.model_dump() for item in payload.selected_items],
            confirmed_items=confirmed_items,
            collect_mode=payload.collect_mode,
            debug_url=payload.debug_url,
            comment=payload.comment,
        )
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@plugin_bp.route('/pricing/competitor-workflow-preview', methods=['POST'])
def plugin_competitor_workflow_preview() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    try:
        payload = CompetitorDrivenPricingPreviewRequest.model_validate(_json())
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        enforce_shop_id_match(tenant_shop_id, payload.shop_id, field_name='payload.shop_id')
        return preview_competitor_driven_pricing_workflow(
            db=db,
            shop_id=tenant_shop_id,
            competitor_hotel_name=payload.competitor_hotel_name,
            price_url=payload.price_url,
            selectors=payload.selectors,
            headless=payload.headless,
        )
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc


@plugin_bp.route('/pricing/competitor-advice-preview', methods=['POST'])
def plugin_competitor_pricing_advice_preview() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    try:
        payload = CompetitorPricingAdviceRequest.model_validate(_json())
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        enforce_shop_id_match(tenant_shop_id, payload.shop_id, field_name='payload.shop_id')
        return preview_competitor_pricing_advice(
            db=db,
            shop_id=tenant_shop_id,
            inventory_snapshot=payload.inventory_snapshot.model_dump(),
            competitor_hotels=[item.model_dump() for item in payload.competitor_hotels],
            manual_room_mappings=[item.model_dump() for item in payload.manual_room_mappings],
            competitor_hotel_name=payload.competitor_hotel_name,
            strategy=payload.strategy,
            event_date=payload.event_date,
            target_occupancy_min=float(payload.target_occupancy_min),
            target_occupancy_max=float(payload.target_occupancy_max),
            expected_cancel_rate=payload.expected_cancel_rate,
            demand_heat=payload.demand_heat,
            competitor_price_cap_ratio=float(payload.competitor_price_cap_ratio),
        )
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc

@plugin_bp.route('/pricing/uniform-direct-submit', methods=['POST'])
def plugin_uniform_direct_submit() -> dict:
    db = _db()
    _, tenant_shop_id = require_tenant_shop(db)
    try:
        payload = MerchantUniformPriceSubmitRequest.model_validate(_json())
    except ValidationError as exc:
        raise ApiError(400, str(exc)) from exc

    try:
        enforce_shop_id_match(tenant_shop_id, payload.shop_id, field_name='payload.shop_id')
        return submit_uniform_merchant_pricing(
            db=db,
            shop_id=tenant_shop_id,
            target_price=float(payload.target_price),
            price_url=payload.price_url,
            selectors=payload.selectors,
            headless=payload.headless,
            selected_items=[item.model_dump() for item in payload.selected_items],
            comment=payload.comment,
        )
    except ValueError as exc:
        raise ApiError(400, str(exc)) from exc
    except RuntimeError as exc:
        raise ApiError(500, str(exc)) from exc



