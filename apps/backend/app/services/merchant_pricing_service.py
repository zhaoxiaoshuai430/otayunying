from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.auto_pricing_service import (
    collect_auto_pricing_context,
    evaluate_auto_pricing_risk,
    generate_auto_pricing_recommendation,
)
from app.services.competitor_pricing_advice_service import preview_competitor_pricing_advice
from app.services.fliggy_merchant_service import fetch_fliggy_merchant_price_preview
from app.services.merchant_portal_pricing_service import submit_fliggy_merchant_price_updates
from app.services.merchant_price_history_service import get_merchant_price_history_summary
from app.services.merchant_price_mapping_service import list_merchant_price_mappings, upsert_merchant_price_mapping
from app.services.merchant_pricing_audit_service import create_merchant_pricing_audit


def _normalize_item_key(item: dict) -> tuple[str, str, str, str, str]:
    return (
        str(item.get('room_name') or '').strip(),
        str(item.get('rate_name') or '').strip(),
        str(item.get('display_name') or '').strip(),
        str(item.get('gid') or '').strip(),
        str(item.get('hid') or '').strip(),
    )


def _clean_text(value: object | None) -> str:
    return ' '.join(str(value or '').strip().split()).lower()


def _normalize_competitor_hotel_name(value: object | None) -> str | None:
    normalized = ' '.join(str(value or '').strip().split())
    return normalized or None


def _positive_price(value: object | None) -> float | None:
    try:
        price = round(float(value or 0), 2)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def _find_mapping_for_item(item: dict, mappings: list[dict]) -> dict | None:
    room_name = _clean_text(item.get('room_name'))
    rate_name = _clean_text(item.get('rate_name') or item.get('display_name'))
    for mapping in mappings:
        mapping_room = _clean_text(mapping.get('room_name'))
        mapping_rate = _clean_text(mapping.get('rate_name'))
        if mapping_rate == rate_name and (not room_name or not mapping_room or mapping_room == room_name):
            return mapping
    for mapping in mappings:
        mapping_room = _clean_text(mapping.get('room_name'))
        if room_name and mapping_room == room_name and not _clean_text(mapping.get('rate_name')):
            return mapping
    return None


def _decorate_local_merchant_items(db: Session, *, shop_id: int, items: list[dict]) -> tuple[list[dict], dict]:
    mappings = list_merchant_price_mappings(db=db, shop_id=shop_id, platform='fliggy', only_enabled=False)
    decorated: list[dict] = []
    mapped = 0
    partial = 0
    seen: set[tuple[str, str, str, str, float]] = set()
    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        current_price = round(float(raw_item.get('current_price') or raw_item.get('price') or 0), 2)
        if current_price <= 0:
            continue
        item = {
            **raw_item,
            'room_name': str(raw_item.get('room_name') or raw_item.get('room_type') or '').strip(),
            'rate_name': str(raw_item.get('rate_name') or raw_item.get('display_name') or '').strip(),
            'display_name': str(raw_item.get('display_name') or raw_item.get('rate_name') or raw_item.get('room_name') or raw_item.get('room_type') or '').strip(),
            'price': current_price,
            'current_price': current_price,
        }
        key = (
            _clean_text(item.get('room_name')),
            _clean_text(item.get('rate_name') or item.get('display_name')),
            str(item.get('gid') or '').strip(),
            str(item.get('hid') or '').strip(),
            current_price,
        )
        if key in seen:
            continue
        seen.add(key)
        mapping = _find_mapping_for_item(item, mappings)
        mapping_status = 'unmapped'
        mapping_id = None
        gid = str(item.get('gid') or '').strip()
        hid = str(item.get('hid') or '').strip()
        is_mapped = bool(gid and hid)
        if mapping is not None:
            mapping_id = mapping.get('mapping_id')
            gid = str(mapping.get('gid') or gid or '')
            hid = str(mapping.get('hid') or hid or '')
            is_mapped = bool(mapping.get('is_complete') or (gid and hid))
            if is_mapped:
                mapping_status = 'mapped'
                mapped += 1
            else:
                mapping_status = 'partial'
                partial += 1
        elif is_mapped:
            mapping_status = 'mapped'
            mapped += 1
        decorated.append({
            **item,
            'mapping_status': mapping_status,
            'mapping_id': mapping_id,
            'gid': gid,
            'hid': hid,
            'is_mapped': is_mapped,
            'source': str(item.get('source') or 'extension_local_merchant_page'),
        })
    summary = {
        'total': len(decorated),
        'mapped': mapped,
        'partial': partial,
        'unmapped': max(0, len(decorated) - mapped - partial),
    }
    return decorated, summary


def _select_target_items(items: list[dict], selected_items: list[dict] | None = None) -> list[dict]:
    if not selected_items:
        return items
    wanted = {_normalize_item_key(item) for item in selected_items}
    matched = [item for item in items if _normalize_item_key(item) in wanted]
    return matched or items


def _normalize_rule(rule: dict) -> dict:
    normalized = dict(rule or {})
    normalized.setdefault('target_name', None)
    normalized.setdefault('strategy', 'balanced')
    normalized.setdefault('min_price', None)
    normalized.setdefault('max_price', None)
    normalized.setdefault('max_change_pct', 8)
    normalized.setdefault('high_risk_change_pct', 10)
    normalized.setdefault('require_manual_approval', False)
    return normalized


def _merchant_rule_context(db: Session, *, shop_id: int) -> tuple[dict, dict]:
    context = collect_auto_pricing_context(db=db, shop_id=shop_id, trigger_type='merchant_panel', dry_run=True)
    rule = _normalize_rule(context.get('rule') if isinstance(context.get('rule'), dict) else {})
    inventory_snapshot = context.get('inventory_snapshot') if isinstance(context.get('inventory_snapshot'), dict) else {}
    return rule, inventory_snapshot


def _override_rule_target(rule: dict, competitor_hotel_name: str | None) -> dict:
    normalized = dict(rule or {})
    target_name = _normalize_competitor_hotel_name(competitor_hotel_name)
    if target_name:
        normalized['target_name'] = target_name
    return normalized


def _build_confirm_item_from_preview(item: dict, *, comment: str) -> dict:
    return {
        'room_name': str(item.get('room_name') or '').strip(),
        'rate_name': str(item.get('rate_name') or '').strip(),
        'display_name': str(item.get('display_name') or item.get('rate_name') or item.get('room_name') or '').strip(),
        'current_price': round(float(item.get('current_price') or item.get('price') or 0), 2),
        'final_price': round(float(item.get('final_price') or item.get('suggested_price') or 0), 2),
        'suggested_price': round(float(item.get('suggested_price') or item.get('final_price') or 0), 2),
        'risk_level': str(item.get('risk_level') or 'L2').strip().upper() or 'L2',
        'gid': str(item.get('gid') or '').strip(),
        'hid': str(item.get('hid') or '').strip(),
        'start_date': item.get('start_date'),
        'end_date': item.get('end_date'),
        'comment': str(item.get('comment') or comment or '').strip() or None,
        'recommendation': item.get('recommendation') if isinstance(item.get('recommendation'), dict) else {},
    }


def _extract_recommendation_summary(preview_items: list[dict]) -> dict:
    for item in preview_items:
        recommendation_payload = item.get('recommendation')
        if not isinstance(recommendation_payload, dict):
            continue
        competitor_context = recommendation_payload.get('competitor_context') if isinstance(recommendation_payload.get('competitor_context'), dict) else {}
        inventory_snapshot = recommendation_payload.get('inventory_snapshot') if isinstance(recommendation_payload.get('inventory_snapshot'), dict) else {}
        merchant_history_context = recommendation_payload.get('merchant_history_context') if isinstance(recommendation_payload.get('merchant_history_context'), dict) else {}
        price_card = recommendation_payload.get('price_recommendation') if isinstance(recommendation_payload.get('price_recommendation'), dict) else {}
        return {
            'sample_item': str(item.get('display_name') or item.get('rate_name') or item.get('room_name') or '').strip() or None,
            'recommendation_source': recommendation_payload.get('recommendation_source'),
            'competitor_context': {
                'price_median': competitor_context.get('price_median'),
                'price_avg': competitor_context.get('price_avg'),
                'price_low_band': competitor_context.get('price_low_band'),
                'price_high_band': competitor_context.get('price_high_band'),
                'price_count': competitor_context.get('price_count'),
                'latest_collected_at': competitor_context.get('latest_collected_at'),
                'data_source': competitor_context.get('data_source'),
                'target_names': competitor_context.get('target_names'),
            },
            'inventory_snapshot': inventory_snapshot,
            'merchant_history_context': merchant_history_context,
            'price_recommendation': {
                'price_mid': price_card.get('price_mid'),
                'price_min': price_card.get('price_min'),
                'price_max': price_card.get('price_max'),
                'risk_level': price_card.get('risk_level'),
                'context_summary': price_card.get('context_summary'),
            },
        }
    return {
        'sample_item': None,
        'recommendation_source': None,
        'competitor_context': {},
        'inventory_snapshot': {},
        'merchant_history_context': {},
        'price_recommendation': {},
    }


def _merge_inventory_snapshot(base_snapshot: dict, override_snapshot: dict | None, items: list[dict]) -> dict:
    snapshot = dict(base_snapshot or {})
    if isinstance(override_snapshot, dict):
        for key in ('total_rooms', 'available_rooms', 'current_price'):
            value = override_snapshot.get(key)
            if value is not None:
                snapshot[key] = value
    prices = [float(item.get('current_price') or item.get('price') or 0) for item in items if float(item.get('current_price') or item.get('price') or 0) > 0]
    if prices and not snapshot.get('current_price'):
        snapshot['current_price'] = round(sum(prices) / len(prices), 2)
    snapshot.setdefault('total_rooms', 1)
    snapshot.setdefault('available_rooms', 0)
    return snapshot


def _manual_mapping_lookup(manual_room_mappings: list[dict] | None) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for item in manual_room_mappings if isinstance(manual_room_mappings, list) else []:
        if not isinstance(item, dict):
            continue
        keys = [
            _clean_text(item.get('display_name') or item.get('displayName')),
            _clean_text(item.get('room_type') or item.get('roomType')),
            _clean_text(item.get('rate_name') or item.get('rateName')),
        ]
        for key in keys:
            if key and key not in result:
                result[key] = item
    return result


def _build_room_advice_mapping_items(items: list[dict], manual_room_mappings: list[dict] | None) -> list[dict]:
    manual_lookup = _manual_mapping_lookup(manual_room_mappings)
    result: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        manual = (
            manual_lookup.get(_clean_text(item.get('display_name') or item.get('rate_name') or item.get('room_name')))
            or manual_lookup.get(_clean_text(item.get('room_name')))
            or manual_lookup.get(_clean_text(item.get('rate_name')))
            or {}
        )
        current_price = round(float(manual.get('current_price') or 0), 2)
        if current_price <= 0:
            continue
        display_name = str(item.get('display_name') or item.get('rate_name') or item.get('room_name') or '').strip()
        room_name = str(item.get('room_name') or display_name).strip()
        rate_name = str(item.get('rate_name') or display_name or room_name).strip()
        if not display_name:
            continue
        dedupe_key = '|'.join([_clean_text(display_name), _clean_text(room_name), _clean_text(rate_name), str(item.get('gid') or ''), str(item.get('hid') or '')])
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        result.append(
            {
                'display_name': display_name,
                'room_type': room_name,
                'rate_name': rate_name or '标准价',
                'current_price': current_price,
                'competitor_room_names': manual.get('competitor_room_names') or manual.get('competitorRoomNames') or [],
                'gid': str(manual.get('gid') or item.get('gid') or '').strip() or None,
                'hid': str(manual.get('hid') or item.get('hid') or '').strip() or None,
                'enabled': True,
            }
        )
    return result


def _room_advice_key(item: dict) -> tuple[str, str, str]:
    return (
        _clean_text(item.get('display_name')),
        _clean_text(item.get('room_name') or item.get('room_type')),
        _clean_text(item.get('rate_name')),
    )


def _merge_room_advice_into_preview_items(preview_items: list[dict], advice_result: dict) -> list[dict]:
    advice_items = advice_result.get('room_recommendations') if isinstance(advice_result.get('room_recommendations'), list) else []
    advice_by_key: dict[tuple[str, str, str], dict] = {}
    advice_by_display: dict[str, dict] = {}
    for item in advice_items:
        if not isinstance(item, dict):
            continue
        key = _room_advice_key(item)
        advice_by_key[key] = item
        if key[0]:
            advice_by_display[key[0]] = item

    merged: list[dict] = []
    for item in preview_items:
        key = _room_advice_key(item)
        advice = advice_by_key.get(key) or advice_by_display.get(key[0])
        if not advice:
            merged.append(item)
            continue
        current_price = round(float(advice.get('current_price') or item.get('current_price') or item.get('price') or 0), 2)
        suggested_price = round(float(advice.get('suggested_price') or item.get('suggested_price') or current_price), 2)
        change_amount = round(suggested_price - current_price, 2)
        change_pct = round(change_amount / current_price * 100, 2) if current_price > 0 else 0
        recommendation = {
            'recommendation_source': advice_result.get('recommendation_source'),
            'competitor_context': advice_result.get('competitor_context') or {},
            'market_trend_context': advice_result.get('market_trend_context') or {},
            'inventory_snapshot': advice_result.get('inventory_snapshot') or {},
            'merchant_history_context': advice_result.get('merchant_history_context') or {},
            'price_recommendation': advice_result.get('price_recommendation') or {},
            'room_advice': advice,
        }
        merged.append(
            {
                **item,
                'current_price': current_price,
                'price': current_price,
                'suggested_price': suggested_price,
                'final_price': suggested_price,
                'change_amount': change_amount,
                'change_pct': change_pct,
                'risk_level': str(advice.get('risk_level') or item.get('risk_level') or 'L2').strip().upper(),
                'require_manual_approval': True,
                'submit_ready': bool(item.get('is_mapped') or (item.get('gid') and item.get('hid'))),
                'recommendation': recommendation,
                'room_advice': advice,
                'competitor_min_price': advice.get('competitor_min_price'),
                'competitor_avg_price': advice.get('competitor_avg_price'),
                'competitor_max_price': advice.get('competitor_max_price'),
                'match_mode': advice.get('match_mode'),
                'matched_room_count': advice.get('matched_room_count'),
            }
        )
    return merged


def refresh_merchant_mapping_prices(
    db: Session,
    *,
    shop_id: int,
    price_url: str | None = None,
    selectors: dict | str | None = None,
    headless: bool = True,
    collect_mode: str = 'cdp_current_page',
    debug_url: str | None = None,
) -> dict:
    merchant_preview = fetch_fliggy_merchant_price_preview(
        db=db,
        shop_id=shop_id,
        price_url=price_url,
        selectors=selectors,
        headless=headless,
        auto_login=True,
        login_headless=False,
        collect_mode=collect_mode,
        debug_url=debug_url,
    )
    items = merchant_preview.get('items') if isinstance(merchant_preview.get('items'), list) else []
    mappings = list_merchant_price_mappings(db=db, shop_id=shop_id, platform='fliggy', only_enabled=False)

    synced_items: list[dict] = []
    updated_count = 0
    skipped_count = 0
    for item in items:
        observed_price = round(float(item.get('price') or item.get('current_price') or 0), 2)
        matched_mapping = _find_mapping_for_item(item, mappings)
        sync_status = 'skipped'
        saved_mapping = None
        if matched_mapping is not None and observed_price > 0:
            saved_mapping = upsert_merchant_price_mapping(
                db=db,
                mapping_data={
                    'tenant_id': int(matched_mapping.get('tenant_id') or 1),
                    'shop_id': shop_id,
                    'platform': str(matched_mapping.get('platform') or 'fliggy'),
                    'room_name': str(matched_mapping.get('room_name') or '').strip(),
                    'rate_name': str(matched_mapping.get('rate_name') or '').strip(),
                    'merchant_room_key': str(matched_mapping.get('merchant_room_key') or '').strip(),
                    'merchant_rate_key': str(matched_mapping.get('merchant_rate_key') or '').strip(),
                    'gid': str(matched_mapping.get('gid') or '').strip(),
                    'hid': str(matched_mapping.get('hid') or '').strip(),
                    'status': str(matched_mapping.get('status') or 'draft'),
                    'notes': str(matched_mapping.get('notes') or '').strip(),
                },
            )
            sync_status = 'updated'
            updated_count += 1
        else:
            skipped_count += 1
            sync_status = 'missing_mapping' if matched_mapping is None else 'missing_price'

        synced_items.append(
            {
                'display_name': str(item.get('display_name') or item.get('rate_name') or item.get('room_name') or '').strip(),
                'room_name': str(item.get('room_name') or '').strip(),
                'rate_name': str(item.get('rate_name') or item.get('display_name') or '').strip(),
                'observed_price': observed_price if observed_price > 0 else None,
                'mapping_status': str(item.get('mapping_status') or 'unmapped'),
                'sync_status': sync_status,
                'gid': str((saved_mapping or matched_mapping or {}).get('gid') or item.get('gid') or '').strip(),
                'hid': str((saved_mapping or matched_mapping or {}).get('hid') or item.get('hid') or '').strip(),
                'observed_price': observed_price if observed_price > 0 else None,
                'last_seen_at': (saved_mapping or {}).get('last_seen_at'),
            }
        )

    refreshed_mappings = list_merchant_price_mappings(db=db, shop_id=shop_id, platform='fliggy', only_enabled=False)
    audit = create_merchant_pricing_audit(
        db=db,
        shop_id=shop_id,
        stage='merchant_mapping_price_refresh',
        audit_mode='preview',
        status='success',
        item_count=len(synced_items),
        payload={
            'updated_count': updated_count,
            'skipped_count': skipped_count,
            'mapping_summary': merchant_preview.get('mapping_summary') or {},
            'price_url': merchant_preview.get('price_url'),
            'source': 'merchant_mapping_price_refresh',
        },
    )
    return {
        'shop_id': shop_id,
        'status': 'success',
        'audit_mode': 'preview',
        'audit': audit,
        'price_preview_audit': merchant_preview.get('audit'),
        'source': 'merchant_mapping_price_refresh',
        'price_url': merchant_preview.get('price_url'),
        'storage_state_used': merchant_preview.get('storage_state_used'),
        'current_price': merchant_preview.get('current_price'),
        'item_count': len(synced_items),
        'updated_count': updated_count,
        'skipped_count': skipped_count,
        'items': synced_items,
        'mappings': refreshed_mappings,
        'mapping_summary': merchant_preview.get('mapping_summary') or {},
        'collected_at': merchant_preview.get('collected_at'),
    }


def preview_merchant_pricing_recommendations(
    db: Session,
    *,
    shop_id: int,
    price_url: str | None = None,
    selectors: dict | str | None = None,
    headless: bool = True,
    selected_items: list[dict] | None = None,
    competitor_hotel_name: str | None = None,
    merchant_items: list[dict] | None = None,
    collect_mode: str = 'cdp_current_page',
    debug_url: str | None = None,
) -> dict:
    if merchant_items:
        items, mapping_summary = _decorate_local_merchant_items(db=db, shop_id=shop_id, items=merchant_items)
        merchant_preview = {
            'items': items,
            'mapping_summary': mapping_summary,
            'price_url': price_url,
            'collected_at': None,
            'source': 'extension_local_merchant_page',
        }
    else:
        merchant_preview = fetch_fliggy_merchant_price_preview(
            db=db,
            shop_id=shop_id,
            price_url=price_url,
            selectors=selectors,
            headless=headless,
            auto_login=True,
            login_headless=False,
        )
        items = merchant_preview.get('items') if isinstance(merchant_preview.get('items'), list) else []
    target_items = _select_target_items(items, selected_items)
    base_rule, inventory_snapshot = _merchant_rule_context(db=db, shop_id=shop_id)
    rule = _override_rule_target(base_rule, competitor_hotel_name)
    normalized_competitor_name = _normalize_competitor_hotel_name(competitor_hotel_name)

    preview_items: list[dict] = []
    for item in target_items:
        current_price = round(float(item.get('price') or item.get('current_price') or 0), 2)
        item_inventory = {
            **inventory_snapshot,
            'current_price': current_price,
        }
        merchant_history = get_merchant_price_history_summary(
            db=db,
            shop_id=shop_id,
            room_name=str(item.get('room_name') or '').strip(),
            rate_name=str(item.get('rate_name') or item.get('display_name') or '').strip(),
            gid=str(item.get('gid') or '').strip(),
            hid=str(item.get('hid') or '').strip(),
            days=int(rule.get('lookback_days') or 7),
        )
        recommendation_payload = generate_auto_pricing_recommendation(
            db=db,
            shop_id=shop_id,
            rule=rule,
            inventory_snapshot=item_inventory,
            merchant_history_context=merchant_history,
        )
        recommendation = recommendation_payload.get('recommendation') if isinstance(recommendation_payload.get('recommendation'), dict) else {}
        suggested_price = round(float(recommendation_payload.get('suggested_price') or current_price), 2)
        risk = evaluate_auto_pricing_risk(
            rule=rule,
            inventory_snapshot=item_inventory,
            suggested_price=suggested_price,
        )
        preview_items.append(
            {
                **item,
                'current_price': current_price,
                'suggested_price': suggested_price,
                'final_price': round(float(risk['final_price']), 2),
                'change_pct': round(float(risk['change_pct']), 2),
                'risk_level': str(risk['risk_level']),
                'require_manual_approval': bool(risk['require_manual_approval']),
                'submit_ready': bool(item.get('is_mapped')),
                'merchant_history': merchant_history,
                'recommendation': recommendation,
            }
        )

    audit = create_merchant_pricing_audit(
        db=db,
        shop_id=shop_id,
        stage='merchant_pricing_preview',
        audit_mode='dry_run',
        status='success',
        item_count=len(preview_items),
        payload={
            'selected_item_count': len(target_items),
            'mapping_summary': merchant_preview.get('mapping_summary') or {},
            'price_url': merchant_preview.get('price_url'),
            'source': 'merchant_pricing_preview',
            'merchant_source': merchant_preview.get('source'),
            'competitor_hotel_name': normalized_competitor_name,
        },
    )
    return {
        'shop_id': shop_id,
        'status': 'success',
        'audit_mode': 'dry_run',
        'audit': audit,
        'price_preview_audit': merchant_preview.get('audit'),
        'rule': rule,
        'item_count': len(preview_items),
        'items': preview_items,
        'mapping_summary': merchant_preview.get('mapping_summary') or {},
        'collected_at': merchant_preview.get('collected_at'),
        'source': 'merchant_pricing_preview',
        'auto_login_performed': bool(merchant_preview.get('auto_login_performed')),
        'credential_saved': bool(merchant_preview.get('credential_saved')),
        'price_url': merchant_preview.get('price_url'),
        'storage_state_used': merchant_preview.get('storage_state_used'),
        'competitor_hotel_name': normalized_competitor_name,
    }


def list_merchant_pricing_items(
    db: Session,
    *,
    shop_id: int,
    price_url: str | None = None,
    selectors: dict | str | None = None,
    headless: bool = True,
    selected_items: list[dict] | None = None,
    merchant_items: list[dict] | None = None,
    collect_mode: str = 'cdp_current_page',
    debug_url: str | None = None,
) -> dict:
    if merchant_items:
        items, mapping_summary = _decorate_local_merchant_items(db=db, shop_id=shop_id, items=merchant_items)
        merchant_preview = {
            'items': items,
            'mapping_summary': mapping_summary,
            'price_url': price_url,
            'collected_at': None,
            'source': 'extension_local_merchant_page',
        }
    else:
        merchant_preview = fetch_fliggy_merchant_price_preview(
            db=db,
            shop_id=shop_id,
            price_url=price_url,
            selectors=selectors,
            headless=headless,
            auto_login=True,
            login_headless=False,
            collect_mode=collect_mode,
            debug_url=debug_url,
        )
        items = merchant_preview.get('items') if isinstance(merchant_preview.get('items'), list) else []
    target_items = _select_target_items(items, selected_items)
    list_items = [
        {
            **item,
            'current_price': round(float(item.get('current_price') or item.get('price') or 0), 2),
            'submit_ready': bool(item.get('is_mapped')),
        }
        for item in target_items
    ]
    mapping_summary = merchant_preview.get('mapping_summary') or {}
    audit = create_merchant_pricing_audit(
        db=db,
        shop_id=shop_id,
        stage='merchant_pricing_item_list',
        audit_mode='preview',
        status='success',
        item_count=len(list_items),
        payload={
            'selected_item_count': len(target_items),
            'mapping_summary': mapping_summary,
            'price_url': merchant_preview.get('price_url'),
            'source': 'merchant_pricing_item_list',
        },
    )
    return {
        'shop_id': shop_id,
        'status': 'success',
        'audit_mode': 'preview',
        'audit': audit,
        'price_preview_audit': merchant_preview.get('audit'),
        'item_count': len(list_items),
        'items': list_items,
        'mapping_summary': mapping_summary,
        'collected_at': merchant_preview.get('collected_at'),
        'source': 'merchant_pricing_item_list',
        'auto_login_performed': bool(merchant_preview.get('auto_login_performed')),
        'credential_saved': bool(merchant_preview.get('credential_saved')),
        'price_url': merchant_preview.get('price_url'),
        'storage_state_used': merchant_preview.get('storage_state_used'),
        'collect_mode': merchant_preview.get('collect_mode'),
        'collect_mode_requested': merchant_preview.get('collect_mode_requested'),
        'cdp_fallback_reason': merchant_preview.get('cdp_fallback_reason'),
        'matched_page_url': merchant_preview.get('matched_page_url'),
        'debug_url': merchant_preview.get('debug_url'),
    }


def preview_competitor_driven_pricing_workflow(
    db: Session,
    *,
    shop_id: int,
    competitor_hotel_name: str | None = None,
    price_url: str | None = None,
    selectors: dict | str | None = None,
    headless: bool = True,
    merchant_items: list[dict] | None = None,
    competitor_hotels: list[dict] | None = None,
    manual_room_mappings: list[dict] | None = None,
    inventory_snapshot: dict | None = None,
    strategy: str = 'balanced',
) -> dict:
    normalized_name = _normalize_competitor_hotel_name(competitor_hotel_name)
    preview_result = preview_merchant_pricing_recommendations(
        db=db,
        shop_id=shop_id,
        price_url=price_url,
        selectors=selectors,
        headless=headless,
        competitor_hotel_name=normalized_name,
        merchant_items=merchant_items,
    )
    preview_items = preview_result.get('items') if isinstance(preview_result.get('items'), list) else []
    _, base_inventory = _merchant_rule_context(db=db, shop_id=shop_id)
    room_mapping_items = _build_room_advice_mapping_items(preview_items, manual_room_mappings)
    room_advice_result = preview_competitor_pricing_advice(
        db=db,
        shop_id=shop_id,
        inventory_snapshot=_merge_inventory_snapshot(base_inventory, inventory_snapshot, preview_items),
        competitor_hotels=competitor_hotels or [],
        manual_room_mappings=room_mapping_items,
        competitor_hotel_name=normalized_name,
        strategy=strategy,
    )
    preview_items = _merge_room_advice_into_preview_items(preview_items, room_advice_result)
    ready_submit_count = len([item for item in preview_items if bool(item.get('submit_ready'))])
    workflow_summary = {
        'competitor_hotel_name': normalized_name or '综合竞对酒店',
        'item_count': len(preview_items),
        'ready_submit_count': ready_submit_count,
        'room_advice_summary': room_advice_result.get('advice_summary') or {},
        'analyzed_hotels': room_advice_result.get('analyzed_hotels') or [],
        **_extract_recommendation_summary(preview_items),
    }
    return {
        **preview_result,
        'items': preview_items,
        'competitor_hotel_name': normalized_name,
        'ready_submit_count': ready_submit_count,
        'workflow_summary': workflow_summary,
        'room_pricing_advice': room_advice_result,
        'source': 'merchant_competitor_workflow_preview',
    }


def generate_merchant_pricing_suggestions(
    db: Session,
    *,
    shop_id: int,
    price_url: str | None = None,
    selectors: dict | str | None = None,
    headless: bool = True,
    selected_items: list[dict] | None = None,
    preview_only: bool = True,
    approver_user_id: int | None = None,
    comment: str = '',
) -> dict:
    preview_result = preview_merchant_pricing_recommendations(
        db=db,
        shop_id=shop_id,
        price_url=price_url,
        selectors=selectors,
        headless=headless,
        selected_items=selected_items,
    )
    preview_items = preview_result.get('items') if isinstance(preview_result.get('items'), list) else []
    ready_items = [item for item in preview_items if bool(item.get('submit_ready'))]
    skipped_items = [
        {
            'display_name': str(item.get('display_name') or item.get('rate_name') or item.get('room_name') or '').strip(),
            'reason': 'mapping_incomplete',
        }
        for item in preview_items
        if not bool(item.get('submit_ready'))
    ]

    result = {
        'shop_id': shop_id,
        'status': str(preview_result.get('status') or 'success'),
        'preview_only': bool(preview_only),
        'preview': preview_result,
        'preview_item_count': len(preview_items),
        'ready_submit_count': len(ready_items),
        'skipped_submit_count': len(skipped_items),
        'skipped_submit_items': skipped_items,
        'source': 'merchant_pricing_generate',
    }
    if preview_only:
        return result

    if approver_user_id is None or int(approver_user_id) < 1:
        raise ValueError('approver_user_id is required when preview_only=false')
    if not ready_items:
        raise ValueError('no mapped merchant pricing items are ready to submit')

    submit_result = confirm_merchant_pricing_recommendations(
        db=db,
        shop_id=shop_id,
        approver_user_id=int(approver_user_id),
        comment=comment,
        confirmed_items=[_build_confirm_item_from_preview(item, comment=comment) for item in ready_items],
    )
    result.update(
        {
            'status': str(submit_result.get('status') or result['status']),
            'submitted': submit_result,
            'submitted_count': int(submit_result.get('submitted_count') or 0),
        }
    )
    return result


def submit_merchant_pricing_recommendations_direct(
    db: Session,
    *,
    shop_id: int,
    price_url: str | None = None,
    selectors: dict | str | None = None,
    headless: bool = True,
    selected_items: list[dict] | None = None,
    confirmed_items: list[dict] | None = None,
    collect_mode: str = 'cdp_current_page',
    debug_url: str | None = None,
    comment: str = '',
) -> dict:
    preview_result: dict | None = None
    skipped_items: list[dict] = []
    if confirmed_items:
        ready_items = [dict(item) for item in confirmed_items if isinstance(item, dict)]
    else:
        preview_result = preview_merchant_pricing_recommendations(
            db=db,
            shop_id=shop_id,
            price_url=price_url,
            selectors=selectors,
            headless=headless,
            selected_items=selected_items,
            collect_mode=collect_mode,
            debug_url=debug_url,
        )
        preview_items = preview_result.get('items') if isinstance(preview_result.get('items'), list) else []
        ready_items = [item for item in preview_items if bool(item.get('submit_ready'))]
        skipped_items = [
            {
                'display_name': str(item.get('display_name') or item.get('rate_name') or item.get('room_name') or '').strip(),
                'reason': 'mapping_incomplete',
            }
            for item in preview_items
            if not bool(item.get('submit_ready'))
        ]
    if not ready_items:
        raise ValueError('no mapped merchant pricing items are ready to submit')

    submit_result = submit_fliggy_merchant_price_updates(
        db=db,
        shop_id=shop_id,
        items=ready_items,
        price_url=price_url,
        selectors=selectors,
        headless=headless,
        auto_login=True,
        login_headless=False,
        collect_mode=collect_mode,
        debug_url=debug_url,
    )
    submitted_items = submit_result.get('items') if isinstance(submit_result.get('items'), list) else []
    success_count = int(submit_result.get('success_count') or 0)
    failed_count = int(submit_result.get('failed_count') or 0)
    overall_status = str(submit_result.get('status') or ('success' if failed_count == 0 else ('partial_failed' if success_count else 'failed')))
    audit = create_merchant_pricing_audit(
        db=db,
        shop_id=shop_id,
        stage='merchant_pricing_direct_submit',
        audit_mode='formal_submit',
        status=overall_status,
        item_count=len(submitted_items),
        action_count=len(submitted_items),
        payload={
            'comment': str(comment or '').strip(),
            'success_count': success_count,
            'failed_count': failed_count,
            'unsubmitted_count': 0,
            'skipped_submit_count': len(skipped_items),
            'stopped_on_first_failure': False,
            'submit_channel': str(submit_result.get('submit_channel') or 'merchant_portal'),
            'price_url': submit_result.get('price_url'),
            'storage_state_used': submit_result.get('storage_state_used'),
            'auto_login_performed': bool(submit_result.get('auto_login_performed')),
            'items': [
                {
                    'display_name': str(item.get('display_name') or ''),
                    'gid': str(item.get('gid') or ''),
                    'hid': str(item.get('hid') or ''),
                    'status': str(item.get('status') or 'unknown'),
                    'final_price': item.get('final_price'),
                    'message': str(item.get('message') or ''),
                }
                for item in submitted_items
            ],
        },
    )
    return {
        'shop_id': shop_id,
        'status': overall_status,
        'audit_mode': 'formal_submit',
        'audit': audit,
        'preview': preview_result,
        'submitted_count': len(submitted_items),
        'success_count': success_count,
        'failed_count': failed_count,
        'unsubmitted_count': 0,
        'skipped_submit_count': len(skipped_items),
        'skipped_submit_items': skipped_items,
        'stopped_on_first_failure': False,
        'items': submitted_items,
        'price_url': submit_result.get('price_url'),
        'storage_state_used': submit_result.get('storage_state_used'),
        'auto_login_performed': bool(submit_result.get('auto_login_performed')),
        'submit_channel': str(submit_result.get('submit_channel') or 'merchant_portal'),
        'source': 'merchant_pricing_direct_submit',
    }


def submit_uniform_merchant_pricing(
    db: Session,
    *,
    shop_id: int,
    target_price: float,
    price_url: str | None = None,
    selectors: dict | str | None = None,
    headless: bool = True,
    selected_items: list[dict] | None = None,
    comment: str = '',
) -> dict:
    normalized_target_price = round(float(target_price), 2)
    if normalized_target_price <= 0:
        raise ValueError('target_price must be greater than 0')

    preview_result = fetch_fliggy_merchant_price_preview(
        db=db,
        shop_id=shop_id,
        price_url=price_url,
        selectors=selectors,
        headless=headless,
        auto_login=True,
        login_headless=False,
    )
    preview_items = preview_result.get('items') if isinstance(preview_result.get('items'), list) else []
    target_items = _select_target_items(preview_items, selected_items)
    ready_items = [item for item in target_items if bool(item.get('is_mapped'))]
    skipped_items = [
        {
            'display_name': str(item.get('display_name') or item.get('rate_name') or item.get('room_name') or '').strip(),
            'reason': 'mapping_incomplete',
        }
        for item in target_items
        if not bool(item.get('is_mapped'))
    ]
    if not ready_items:
        raise ValueError('no mapped merchant pricing items are ready to submit')

    normalized_comment = str(comment or '').strip() or 'browser_extension_uniform_submit'
    confirmed_items = []
    for item in ready_items:
        confirmed = _build_confirm_item_from_preview(item, comment=normalized_comment)
        confirmed['final_price'] = normalized_target_price
        confirmed['suggested_price'] = normalized_target_price
        confirmed_items.append(confirmed)

    submit_result = submit_merchant_pricing_recommendations_direct(
        db=db,
        shop_id=shop_id,
        price_url=price_url,
        selectors=selectors,
        headless=headless,
        confirmed_items=confirmed_items,
        comment=normalized_comment,
    )
    submit_result['preview'] = preview_result
    submit_result['uniform_target_price'] = normalized_target_price
    submit_result['ready_submit_count'] = len(ready_items)
    submit_result['skipped_submit_count'] = len(skipped_items)
    submit_result['skipped_submit_items'] = skipped_items
    submit_result['credential_saved'] = bool(preview_result.get('credential_saved'))
    submit_result['auto_login_performed'] = bool(
        submit_result.get('auto_login_performed') or preview_result.get('auto_login_performed')
    )
    submit_result['source'] = 'merchant_uniform_price_submit'
    return submit_result


def confirm_merchant_pricing_recommendations(
    db: Session,
    *,
    shop_id: int,
    approver_user_id: int,
    confirmed_items: list[dict],
    comment: str = '',
) -> dict:
    if not confirmed_items:
        raise ValueError('confirmed_items must not be empty')

    ready_items = [dict(item) for item in confirmed_items if isinstance(item, dict)]
    submit_result = submit_fliggy_merchant_price_updates(
        db=db,
        shop_id=shop_id,
        items=ready_items,
        auto_login=True,
        login_headless=False,
    )
    submitted_items = submit_result.get('items') if isinstance(submit_result.get('items'), list) else []
    success_count = int(submit_result.get('success_count') or 0)
    failed_count = int(submit_result.get('failed_count') or 0)
    overall_status = str(submit_result.get('status') or ('success' if failed_count == 0 else ('partial_failed' if success_count else 'failed')))
    audit = create_merchant_pricing_audit(
        db=db,
        shop_id=shop_id,
        stage='merchant_pricing_confirm',
        audit_mode='formal_submit',
        status=overall_status,
        item_count=len(submitted_items),
        action_count=len(submitted_items),
        payload={
            'approver_user_id': int(approver_user_id),
            'comment': str(comment or '').strip(),
            'success_count': success_count,
            'pending_count': 0,
            'failed_count': failed_count,
            'submit_channel': str(submit_result.get('submit_channel') or 'merchant_portal'),
            'price_url': submit_result.get('price_url'),
            'storage_state_used': submit_result.get('storage_state_used'),
            'auto_login_performed': bool(submit_result.get('auto_login_performed')),
            'items': [
                {
                    'display_name': str(item.get('display_name') or ''),
                    'gid': str(item.get('gid') or ''),
                    'hid': str(item.get('hid') or ''),
                    'status': str(item.get('status') or 'unknown'),
                    'final_price': item.get('final_price'),
                    'message': str(item.get('message') or ''),
                }
                for item in submitted_items
            ],
        },
    )
    return {
        'shop_id': shop_id,
        'status': overall_status,
        'audit_mode': 'formal_submit',
        'audit': audit,
        'submitted_count': len(submitted_items),
        'success_count': success_count,
        'pending_count': 0,
        'failed_count': failed_count,
        'items': submitted_items,
        'price_url': submit_result.get('price_url'),
        'storage_state_used': submit_result.get('storage_state_used'),
        'auto_login_performed': bool(submit_result.get('auto_login_performed')),
        'submit_channel': str(submit_result.get('submit_channel') or 'merchant_portal'),
        'source': 'merchant_pricing_confirm',
    }
