from __future__ import annotations

import json
import threading
import time
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.services.auto_pricing_service import (
    collect_auto_pricing_context,
    evaluate_auto_pricing_risk,
    generate_auto_pricing_recommendation,
)
from app.services.competitor_live_cache import store_live_competitor_result
from app.services.competitor_service import (
    collect_fliggy_hotel_prices_playwright,
    normalize_fliggy_guest_start_url,
    parse_target_hotel_names,
    save_competitor_collection,
)
from app.services.merchant_pricing_audit_service import (
    create_merchant_pricing_audit,
    get_latest_merchant_pricing_audit,
)

_FLIGGY_GUEST_PLATFORM = 'fliggy_guest'
_DEFAULT_DEBUG_URL = 'http://127.0.0.1:9222'
_DEFAULT_INTERVAL_MINUTES = 60
_DEFAULT_MAX_PAGES = 1
_DEFAULT_MAX_HOTELS = 50
_POLL_INTERVAL_SECONDS = 15
_RECOMMENDATION_STAGE = 'fliggy_schedule_recommendation'
_RECOMMENDATION_AUDIT_MODE = 'dry_run'

_STATUS_LOCK = threading.Lock()
_RUNNER_LOCK = threading.Lock()
_JOB_STATUS: dict[int, dict] = {}
_RUNNER = None


def _safe_int(raw_value: object, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError, AttributeError):
        value = default
    return max(minimum, min(maximum, value))


def _safe_float(raw_value: object, *, default: float = 0.0) -> float:
    try:
        return round(float(str(raw_value).strip()), 2)
    except (TypeError, ValueError, AttributeError):
        return round(float(default), 2)


def _safe_bool(raw_value: object) -> bool:
    if isinstance(raw_value, bool):
        return raw_value
    return str(raw_value or '').strip().lower() in {'1', 'true', 'yes', 'on', 'enabled'}


def _format_ts(raw_ts: float | int | None) -> str | None:
    if not raw_ts:
        return None
    return datetime.fromtimestamp(float(raw_ts)).strftime('%Y-%m-%d %H:%M:%S')


def _parse_selectors(raw_value: object) -> dict:
    if isinstance(raw_value, dict):
        return dict(raw_value)
    if isinstance(raw_value, str) and raw_value.strip():
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _normalize_fliggy_schedule_recommendation(audit: dict | None) -> dict | None:
    if not isinstance(audit, dict):
        return None

    payload = audit.get('payload') if isinstance(audit.get('payload'), dict) else {}
    recommendation = payload.get('recommendation') if isinstance(payload.get('recommendation'), dict) else {}
    recommendation_card = recommendation.get('price_recommendation') if isinstance(recommendation.get('price_recommendation'), dict) else {}
    inventory_snapshot = payload.get('inventory_snapshot') if isinstance(payload.get('inventory_snapshot'), dict) else {}
    rule = payload.get('rule') if isinstance(payload.get('rule'), dict) else {}
    competitor_context = recommendation.get('competitor_context') if isinstance(recommendation.get('competitor_context'), dict) else {}
    reasons = recommendation_card.get('reasons') if isinstance(recommendation_card.get('reasons'), list) else []

    return {
        'audit_id': int(audit.get('audit_id') or 0),
        'status': str(audit.get('status') or 'success'),
        'created_at': audit.get('created_at') or payload.get('generated_at') or recommendation_card.get('updated_at'),
        'trigger_type': str(payload.get('trigger_type') or 'fliggy_schedule'),
        'strategy': str(rule.get('strategy') or 'balanced'),
        'current_price': _safe_float(payload.get('current_price'), default=inventory_snapshot.get('current_price') or 0.0),
        'suggested_price': _safe_float(payload.get('suggested_price'), default=inventory_snapshot.get('current_price') or 0.0),
        'final_price': _safe_float(payload.get('final_price'), default=inventory_snapshot.get('current_price') or 0.0),
        'change_pct': _safe_float(payload.get('change_pct'), default=0.0),
        'risk_level': str(payload.get('risk_level') or 'L2'),
        'require_manual_approval': bool(payload.get('require_manual_approval')),
        'recommendation_source': str(recommendation.get('recommendation_source') or 'fallback'),
        'price_min': _safe_float(recommendation_card.get('price_min'), default=0.0),
        'price_mid': _safe_float(recommendation_card.get('price_mid'), default=0.0),
        'price_max': _safe_float(recommendation_card.get('price_max'), default=0.0),
        'context_summary': str(recommendation_card.get('context_summary') or '').strip(),
        'reasons': [str(item).strip() for item in reasons if str(item).strip()][:5],
        'inventory_snapshot': inventory_snapshot,
        'rule': rule,
        'competitor_context': competitor_context,
        'competitor_price_count': int(competitor_context.get('price_count') or 0),
        'competitor_price_avg': _safe_float(competitor_context.get('price_avg'), default=0.0),
        'latest_competitor_at': str(competitor_context.get('latest_collected_at') or '').strip() or None,
        'recommendation': recommendation,
    }


def build_fliggy_schedule_settings(raw_selectors: object) -> dict:
    selectors = _parse_selectors(raw_selectors)
    return {
        'schedule_enabled': _safe_bool(selectors.get('schedule_enabled')),
        'schedule_interval_minutes': _safe_int(
            selectors.get('schedule_interval_minutes'),
            default=_DEFAULT_INTERVAL_MINUTES,
            minimum=_DEFAULT_INTERVAL_MINUTES,
            maximum=24 * 60,
        ),
        'debug_url': str(selectors.get('debug_url') or _DEFAULT_DEBUG_URL).strip() or _DEFAULT_DEBUG_URL,
        'target_page_url_keyword': str(selectors.get('target_page_url_keyword') or '').strip(),
        'max_pages': _safe_int(selectors.get('max_pages'), default=_DEFAULT_MAX_PAGES, minimum=1, maximum=20),
        'max_hotels': _safe_int(selectors.get('max_hotels'), default=_DEFAULT_MAX_HOTELS, minimum=1, maximum=200),
        'target_hotel_names': parse_target_hotel_names(selectors.get('target_hotel_names')),
    }


def merge_fliggy_schedule_settings(
    raw_selectors: object,
    *,
    schedule_enabled: bool,
    schedule_interval_minutes: int = _DEFAULT_INTERVAL_MINUTES,
    debug_url: str = _DEFAULT_DEBUG_URL,
    target_page_url_keyword: str = '',
    max_pages: int = _DEFAULT_MAX_PAGES,
    max_hotels: int = _DEFAULT_MAX_HOTELS,
    target_hotel_names: list[str] | None = None,
) -> dict:
    merged = _parse_selectors(raw_selectors)
    merged['schedule_enabled'] = bool(schedule_enabled)
    merged['schedule_interval_minutes'] = _safe_int(
        schedule_interval_minutes,
        default=_DEFAULT_INTERVAL_MINUTES,
        minimum=_DEFAULT_INTERVAL_MINUTES,
        maximum=24 * 60,
    )
    merged['debug_url'] = str(debug_url or _DEFAULT_DEBUG_URL).strip() or _DEFAULT_DEBUG_URL
    merged['target_page_url_keyword'] = str(target_page_url_keyword or '').strip()
    merged['max_pages'] = _safe_int(max_pages, default=_DEFAULT_MAX_PAGES, minimum=1, maximum=20)
    merged['max_hotels'] = _safe_int(max_hotels, default=_DEFAULT_MAX_HOTELS, minimum=1, maximum=200)
    merged['target_hotel_names'] = parse_target_hotel_names(target_hotel_names)
    return merged


def _update_job_status(shop_id: int, **changes) -> dict:
    with _STATUS_LOCK:
        current = dict(_JOB_STATUS.get(int(shop_id)) or {})
        current.update(changes)
        _JOB_STATUS[int(shop_id)] = current
        return dict(current)


def generate_fliggy_schedule_recommendation(
    db: Session,
    *,
    shop_id: int,
    trigger_type: str = 'fliggy_schedule',
) -> dict:
    context = collect_auto_pricing_context(db=db, shop_id=shop_id, trigger_type=trigger_type, dry_run=True)
    if str(context.get('status') or '').lower() != 'ok':
        raise RuntimeError(str(context.get('reason') or 'auto pricing context unavailable'))

    rule = context.get('rule') if isinstance(context.get('rule'), dict) else {}
    inventory_snapshot = context.get('inventory_snapshot') if isinstance(context.get('inventory_snapshot'), dict) else {}
    if not inventory_snapshot:
        raise RuntimeError('inventory snapshot unavailable for schedule recommendation')

    recommendation_payload = generate_auto_pricing_recommendation(
        db=db,
        shop_id=shop_id,
        rule=rule,
        inventory_snapshot=inventory_snapshot,
    )
    recommendation = recommendation_payload.get('recommendation') if isinstance(recommendation_payload.get('recommendation'), dict) else {}
    suggested_price = _safe_float(
        recommendation_payload.get('suggested_price'),
        default=inventory_snapshot.get('current_price') or 0.0,
    )
    risk = evaluate_auto_pricing_risk(
        rule=rule,
        inventory_snapshot=inventory_snapshot,
        suggested_price=suggested_price,
    )
    generated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    payload = {
        'trigger_type': str(trigger_type or 'fliggy_schedule'),
        'generated_at': generated_at,
        'current_price': _safe_float(risk.get('current_price'), default=inventory_snapshot.get('current_price') or 0.0),
        'suggested_price': suggested_price,
        'final_price': _safe_float(risk.get('final_price'), default=suggested_price),
        'change_pct': _safe_float(risk.get('change_pct'), default=0.0),
        'risk_level': str(risk.get('risk_level') or 'L2'),
        'require_manual_approval': bool(risk.get('require_manual_approval')),
        'rule': rule,
        'inventory_snapshot': inventory_snapshot,
        'recommendation': recommendation,
        'source': _RECOMMENDATION_STAGE,
    }
    audit = create_merchant_pricing_audit(
        db=db,
        shop_id=shop_id,
        stage=_RECOMMENDATION_STAGE,
        audit_mode=_RECOMMENDATION_AUDIT_MODE,
        status='success',
        item_count=1,
        payload=payload,
    )
    return _normalize_fliggy_schedule_recommendation({**audit, 'created_at': generated_at, 'payload': payload}) or {
        'created_at': generated_at,
        'suggested_price': suggested_price,
    }


def get_latest_fliggy_schedule_recommendation(db: Session, *, shop_id: int) -> dict | None:
    latest_audit = get_latest_merchant_pricing_audit(
        db=db,
        shop_id=shop_id,
        stage=_RECOMMENDATION_STAGE,
        audit_mode=_RECOMMENDATION_AUDIT_MODE,
    )
    return _normalize_fliggy_schedule_recommendation(latest_audit)


class FliggyHotelScheduleRunner:
    def __init__(self, session_factory, *, logger=None) -> None:
        self._session_factory = session_factory
        self._logger = logger
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._loop, name='fliggy-hourly-collector', daemon=True)

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as exc:  # pragma: no cover
                if self._logger is not None:
                    self._logger.exception('Fliggy hourly collector tick failed', exc_info=exc)
            self._stop_event.wait(_POLL_INTERVAL_SECONDS)

    def _load_jobs(self, db: Session) -> list[dict]:
        try:
            rows = db.execute(
                text(
                    """
                    SELECT shop_id, price_url, selector_json
                    FROM merchant_credentials
                    WHERE platform = :platform
                    """
                ),
                {'platform': _FLIGGY_GUEST_PLATFORM},
            ).mappings().all()
        except SQLAlchemyError as exc:
            raise RuntimeError(str(exc)) from exc

        jobs: list[dict] = []
        for row in rows:
            selectors = _parse_selectors(row.get('selector_json'))
            settings = build_fliggy_schedule_settings(selectors)
            jobs.append(
                {
                    'shop_id': int(row.get('shop_id') or 0),
                    'start_url': normalize_fliggy_guest_start_url(str(row.get('price_url') or '').strip()),
                    **settings,
                }
            )
        return jobs

    def _should_run(self, job: dict, *, now_ts: float) -> bool:
        if not job.get('schedule_enabled'):
            return False
        status = dict(_JOB_STATUS.get(int(job['shop_id'])) or {})
        if status.get('is_running'):
            return False
        last_started_ts = float(status.get('last_started_ts') or 0)
        if last_started_ts <= 0:
            return True
        return (now_ts - last_started_ts) >= int(job.get('schedule_interval_minutes') or _DEFAULT_INTERVAL_MINUTES) * 60

    def _run_job(self, job: dict) -> None:
        shop_id = int(job['shop_id'])
        started_at_ts = time.time()
        _update_job_status(
            shop_id,
            is_running=True,
            last_started_ts=started_at_ts,
            last_started_at=_format_ts(started_at_ts),
            last_status='running',
            last_error='',
            schedule_enabled=bool(job.get('schedule_enabled')),
            schedule_interval_minutes=int(job.get('schedule_interval_minutes') or _DEFAULT_INTERVAL_MINUTES),
        )

        db = self._session_factory()
        try:
            result = collect_fliggy_hotel_prices_playwright(
                db=db,
                shop_id=shop_id,
                start_url=str(job.get('start_url') or ''),
                max_pages=int(job.get('max_pages') or _DEFAULT_MAX_PAGES),
                max_hotels=int(job.get('max_hotels') or _DEFAULT_MAX_HOTELS),
                headless=True,
                collect_mode='cdp_current_page',
                debug_url=str(job.get('debug_url') or _DEFAULT_DEBUG_URL),
                target_page_url_keyword=str(job.get('target_page_url_keyword') or ''),
                target_hotel_names=list(job.get('target_hotel_names') or []),
                save_credential=False,
            )
            live_result = {
                **result,
                'target_page_url_keyword': str(job.get('target_page_url_keyword') or ''),
                'debug_url': str(job.get('debug_url') or _DEFAULT_DEBUG_URL),
                'collect_mode': 'cdp_current_page',
            }
            store_live_competitor_result(shop_id=shop_id, result=live_result, source='fliggy_live_schedule')
            saved = save_competitor_collection(db=db, shop_id=shop_id, result=result, source='schedule')

            recommendation = None
            recommendation_error = ''
            try:
                recommendation = generate_fliggy_schedule_recommendation(
                    db=db,
                    shop_id=shop_id,
                    trigger_type='fliggy_schedule',
                )
            except Exception as exc:
                recommendation_error = str(exc)
                if self._logger is not None:
                    self._logger.exception('Fliggy hourly recommendation failed for shop %s', shop_id, exc_info=exc)

            finished_at_ts = time.time()
            _update_job_status(
                shop_id,
                is_running=False,
                last_finished_ts=finished_at_ts,
                last_finished_at=_format_ts(finished_at_ts),
                last_success_ts=finished_at_ts,
                last_success_at=_format_ts(finished_at_ts),
                last_status='success',
                last_error='',
                last_count=int(result.get('count') or 0),
                last_saved_count=int(saved.get('saved_count') or 0),
                last_recommendation_status='success' if recommendation else ('failed' if recommendation_error else 'idle'),
                last_recommendation_at=recommendation.get('created_at') if isinstance(recommendation, dict) else None,
                last_recommendation_error=recommendation_error,
                last_recommendation_suggested_price=(recommendation or {}).get('suggested_price') if isinstance(recommendation, dict) else None,
                last_recommendation_source=(recommendation or {}).get('recommendation_source') if isinstance(recommendation, dict) else None,
            )
        except Exception as exc:
            finished_at_ts = time.time()
            _update_job_status(
                shop_id,
                is_running=False,
                last_finished_ts=finished_at_ts,
                last_finished_at=_format_ts(finished_at_ts),
                last_status='failed',
                last_error=str(exc),
            )
            if self._logger is not None:
                self._logger.exception('Fliggy hourly collector failed for shop %s', shop_id, exc_info=exc)
        finally:
            db.close()

    def tick(self) -> None:
        db = self._session_factory()
        try:
            jobs = self._load_jobs(db)
        finally:
            db.close()

        now_ts = time.time()
        for job in jobs:
            shop_id = int(job.get('shop_id') or 0)
            if shop_id < 1:
                continue
            _update_job_status(
                shop_id,
                schedule_enabled=bool(job.get('schedule_enabled')),
                schedule_interval_minutes=int(job.get('schedule_interval_minutes') or _DEFAULT_INTERVAL_MINUTES),
            )
            if not self._should_run(job, now_ts=now_ts):
                continue
            self._run_job(job)


def ensure_fliggy_schedule_started(*, session_factory, logger=None):
    global _RUNNER
    with _RUNNER_LOCK:
        if _RUNNER is not None and _RUNNER.is_alive():
            return _RUNNER
        _RUNNER = FliggyHotelScheduleRunner(session_factory=session_factory, logger=logger)
        _RUNNER.start()
        return _RUNNER


def get_fliggy_schedule_status(*, shop_id: int, credential: dict | None = None, db: Session | None = None) -> dict:
    selectors = credential.get('selectors') if isinstance(credential, dict) and isinstance(credential.get('selectors'), dict) else {}
    settings = build_fliggy_schedule_settings(selectors)
    with _STATUS_LOCK:
        runtime = dict(_JOB_STATUS.get(int(shop_id)) or {})

    runner_started = _RUNNER is not None and _RUNNER.is_alive()
    next_run_at = None
    if settings['schedule_enabled']:
        if runtime.get('is_running'):
            next_run_at = '执行中'
        else:
            last_started_ts = float(runtime.get('last_started_ts') or 0)
            if last_started_ts > 0:
                next_run_at = _format_ts(last_started_ts + settings['schedule_interval_minutes'] * 60)
            else:
                next_run_at = '等待首次执行'

    latest_recommendation = None
    if db is not None:
        try:
            latest_recommendation = get_latest_fliggy_schedule_recommendation(db=db, shop_id=shop_id)
        except Exception:
            latest_recommendation = None

    return {
        'runner_started': runner_started,
        'schedule_enabled': bool(settings['schedule_enabled']),
        'schedule_interval_minutes': int(settings['schedule_interval_minutes']),
        'is_running': bool(runtime.get('is_running')),
        'last_status': str(runtime.get('last_status') or ('idle' if runner_started else 'not_started')),
        'last_started_at': runtime.get('last_started_at'),
        'last_finished_at': runtime.get('last_finished_at'),
        'last_success_at': runtime.get('last_success_at'),
        'last_error': str(runtime.get('last_error') or ''),
        'last_count': int(runtime.get('last_count') or 0),
        'last_saved_count': int(runtime.get('last_saved_count') or 0),
        'next_run_at': next_run_at,
        'last_recommendation_status': str(runtime.get('last_recommendation_status') or ('success' if latest_recommendation else 'idle')),
        'last_recommendation_at': runtime.get('last_recommendation_at') or ((latest_recommendation or {}).get('created_at') if latest_recommendation else None),
        'last_recommendation_error': str(runtime.get('last_recommendation_error') or ''),
        'latest_recommendation': latest_recommendation,
    }

