from __future__ import annotations

from datetime import datetime

from app.core.config import get_settings
from app.services.fliggy_merchant_service import (
    _SESSION_LOGIN_REQUIRED_ERRORS,
    _clean_text,
    _click_first,
    _evaluate_authenticated_page,
    _first_text,
    _normalize_selector_map,
    _resolve_connection_context,
    _resolve_default_urls,
    _safe_storage_name,
    _state_dir,
    _wait_for_any_selector,
    login_fliggy_merchant_session,
)

SUBMIT_SELECTOR_MAP = {
    'edit_trigger': [
        "button:has-text('修改价格')",
        "button:has-text('修改房价')",
        "button:has-text('价格管理')",
        "button:has-text('房价管理')",
        "button:has-text('修改')",
        "button:has-text('改价')",
        "button:has-text('编辑')",
        "button:has-text('调整')",
        "button:has-text('调价')",
        "[role='button']:has-text('修改价格')",
        "[role='button']:has-text('修改房价')",
        "[role='button']:has-text('修改')",
        "[role='button']:has-text('改价')",
        "[role='button']:has-text('调价')",
        "[title*='修改']",
        "[title*='价格']",
        "[aria-label*='修改']",
        "[aria-label*='价格']",
        ".ant-btn:has-text('修改')",
        ".ant-btn:has-text('价格')",
        ".el-button:has-text('修改')",
        ".el-button:has-text('价格')",
        ".aui-button:has-text('修改')",
        ".aui-button:has-text('价格')",
    ],
    'price_input': [
        "input[type='number']",
        "input[inputmode='decimal']",
        "input[name*='price']",
        "input[id*='price']",
        "input[class*='price']",
        "input[placeholder*='价']",
        "input[placeholder*='房价']",
        "input[placeholder*='价格']",
        "input[aria-label*='价']",
        "input[aria-label*='价格']",
        ".ant-input-number-input",
        ".el-input__inner",
        ".aui-input__inner",
        "input[type='text']",
    ],
    'row_save': [
        "button:has-text('确认修改')",
        "button:has-text('确认提交')",
        "button:has-text('保存')",
        "button:has-text('确定')",
        "button:has-text('确认')",
        "button:has-text('提交')",
        "button:has-text('应用')",
        "button:has-text('完成')",
        ".ant-btn-primary:has-text('保存')",
        ".ant-btn-primary:has-text('确认')",
        ".el-button--primary:has-text('保存')",
        ".el-button--primary:has-text('确认')",
        ".aui-button--primary:has-text('保存')",
        ".aui-button--primary:has-text('确认')",
    ],
    'page_save': [
        "button:has-text('保存设置')",
        "button:has-text('保存全部')",
        "button:has-text('批量保存')",
        "button:has-text('确认修改')",
        "button:has-text('提交修改')",
        "button:has-text('确认提交')",
        "button:has-text('立即生效')",
        "button:has-text('提交')",
        "button:has-text('确定')",
        ".ant-btn-primary:has-text('保存')",
        ".ant-btn-primary:has-text('确定')",
        ".ant-btn-primary:has-text('提交')",
        ".el-button--primary:has-text('保存')",
        ".el-button--primary:has-text('确定')",
        ".el-button--primary:has-text('提交')",
        ".aui-button--primary:has-text('保存')",
        ".aui-button--primary:has-text('确定')",
        ".aui-button--primary:has-text('提交')",
    ],
    'confirm_submit': [
        ".ant-modal-confirm button.ant-btn-primary",
        ".ant-modal button.ant-btn-primary:has-text('确定')",
        ".ant-modal button.ant-btn-primary:has-text('确认')",
        ".el-message-box button.el-button--primary",
        ".aui-dialog button.aui-button--primary:has-text('确定')",
        ".aui-dialog button.aui-button--primary:has-text('确认')",
        ".aui-grid-modal__wrapper.active button.aui-button--primary:has-text('确定')",
        ".aui-grid-modal__wrapper.active button.aui-button--primary:has-text('确认')",
        "button:has-text('确认提交')",
        "button:has-text('确认修改')",
    ],
    'submit_success': [
        "text=保存成功",
        "text=提交成功",
        "text=修改成功",
        "text=设置成功",
        "text=更新成功",
        "text=生效成功",
        "text=操作成功",
        ".ant-message-notice:has-text('成功')",
        ".el-message--success",
        ".aui-message--success",
    ],
    'submit_error': [
        "text=保存失败",
        "text=提交失败",
        "text=修改失败",
        "text=设置失败",
        "text=更新失败",
        "text=生效失败",
        "text=操作失败",
        ".ant-message-notice:has-text('失败')",
        ".el-message--error",
        ".aui-message--error",
    ],
    'loading_mask': [
        ".ant-spin-spinning",
        ".el-loading-mask",
        ".aui-loading-mask",
        "[aria-busy='true']",
        ".loading",
    ],
}

HWHT_SUBMIT_SELECTOR_MAP = {
    'edit_trigger': [
        "button.aui-button:has-text('修改')",
        "button.aui-button:has-text('改价')",
        "button.aui-button:has-text('编辑')",
        ".aui-table button:has-text('修改')",
    ],
    'price_input': [
        ".aui-input__inner",
        "input.aui-input__inner",
        "input[placeholder*='价格']",
        "input[type='number']",
    ],
    'row_save': [
        "button.aui-button--primary:has-text('保存')",
        "button.aui-button--primary:has-text('确定')",
        "button.aui-button--primary:has-text('提交')",
    ],
    'page_save': [
        "button.aui-button--primary:has-text('保存全部')",
        "button.aui-button--primary:has-text('批量保存')",
        "button.aui-button--primary:has-text('提交')",
    ],
    'confirm_submit': [
        ".aui-grid-modal__wrapper.active button.aui-button--primary:has-text('确定')",
        ".aui-grid-modal__wrapper.active button.aui-button--primary:has-text('确认')",
        ".aui-dialog button.aui-button--primary:has-text('确定')",
        ".aui-dialog button.aui-button--primary:has-text('确认')",
    ],
    'submit_success': [
        "text=保存成功",
        "text=操作成功",
    ],
    'submit_error': [
        "text=保存失败",
        "text=操作失败",
    ],
}


def _merge_submit_selectors(raw_selectors: dict | str | None, *, login_url: str, price_url: str) -> dict[str, list[str]]:
    selector_map = _normalize_selector_map(raw_selectors, login_url=login_url, price_url=price_url)
    url_text = f'{login_url} {price_url}'.lower()
    submit_seed = SUBMIT_SELECTOR_MAP
    if 'ebooking.hwht.com' in url_text:
        submit_seed = {
            key: [*HWHT_SUBMIT_SELECTOR_MAP.get(key, []), *values]
            for key, values in SUBMIT_SELECTOR_MAP.items()
        }
    for key, values in submit_seed.items():
        existing = selector_map.get(key)
        merged = [str(item).strip() for item in (existing or []) if str(item).strip()]
        selector_map[key] = [*merged, *[item for item in values if item not in merged]]
    return selector_map


def _score_price_update_row(item: dict, row_text: str) -> tuple[int, str]:
    normalized_text = _clean_text(row_text)
    if not normalized_text:
        return 0, ''

    gid = str(item.get('gid') or '').strip()
    hid = str(item.get('hid') or '').strip()
    room_name = _clean_text(item.get('room_name'))
    rate_name = _clean_text(item.get('rate_name') or item.get('display_name'))
    display_name = _clean_text(item.get('display_name'))

    score = 0
    matched_by = ''
    if gid and gid in normalized_text:
        score += 10
        matched_by = 'gid'
    elif gid and rate_name and rate_name not in normalized_text:
        return 0, ''
    if hid and hid in normalized_text:
        score += 6
        matched_by = matched_by or 'hid'
    if rate_name and rate_name in normalized_text:
        score += 5
        matched_by = matched_by or 'rate_name'
    if display_name and display_name in normalized_text:
        score += 3
        matched_by = matched_by or 'display_name'
    if room_name and room_name in normalized_text:
        score += 2
        matched_by = matched_by or 'room_name'

    if gid and gid not in normalized_text and hid and hid not in normalized_text and rate_name and rate_name not in normalized_text:
        return 0, ''
    return score, matched_by


def _find_matching_row(page, selectors: dict[str, list[str]], item: dict):
    best_row = None
    best_score = 0
    best_reason = ''
    best_text = ''
    for row_selector in selectors['room_rows']:
        try:
            locators = page.locator(row_selector)
            count = min(locators.count(), 100)
        except Exception:
            count = 0
        if count == 0:
            continue
        for index in range(count):
            row = locators.nth(index)
            try:
                row_text = row.inner_text(timeout=1500)
            except Exception:
                row_text = ''
            score, reason = _score_price_update_row(item, row_text)
            if score > best_score:
                best_row = row
                best_score = score
                best_reason = reason
                best_text = _clean_text(row_text)
    return best_row, best_score, best_reason, best_text


def _first_locator(locator_owner, selectors: list[str]):
    for selector in selectors:
        try:
            locator = locator_owner.locator(selector).first
            if locator.count() > 0:
                return locator, selector
        except Exception:
            continue
    return None, ''


def _fill_price_input(locator, final_price: float) -> str:
    price_text = f'{float(final_price):.2f}'
    try:
        locator.click(timeout=2000)
    except Exception:
        pass
    try:
        locator.fill('', timeout=2000)
    except Exception:
        pass
    try:
        locator.fill(price_text, timeout=3000)
        return price_text
    except Exception:
        try:
            locator.press('Control+A', timeout=1000)
            locator.press('Backspace', timeout=1000)
            locator.type(price_text, delay=30, timeout=4000)
            return price_text
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f'failed to fill price input: {exc}') from exc


def _wait_loading_clear(page, selectors: dict[str, list[str]], *, timeout_ms: int) -> None:
    for selector in selectors['loading_mask']:
        try:
            page.locator(selector).first.wait_for(state='hidden', timeout=timeout_ms)
            return
        except Exception:
            continue


def _price_variants(final_price: float) -> set[str]:
    rounded = round(float(final_price), 2)
    integer_text = str(int(rounded))
    one_decimal = f'{rounded:.1f}'
    two_decimal = f'{rounded:.2f}'
    return {integer_text, one_decimal, two_decimal}


def _detect_submit_outcome(page, row, selectors: dict[str, list[str]], *, final_price: float, timeout_ms: int) -> tuple[str, str]:
    _wait_loading_clear(page, selectors, timeout_ms=min(timeout_ms, 3000))
    if _wait_for_any_selector(page, selectors['submit_error'], timeout_ms=1200, poll_ms=200):
        message = _first_text(page, selectors['submit_error']) or '页面提示提交失败'
        return 'failed', message
    if _wait_for_any_selector(page, selectors['submit_success'], timeout_ms=1800, poll_ms=200):
        return 'success', _first_text(page, selectors['submit_success']) or '页面提示提交成功'

    try:
        latest_text = _clean_text(row.inner_text(timeout=1500))
    except Exception:
        latest_text = ''
    if latest_text and any(price_token in latest_text for price_token in _price_variants(final_price)):
        return 'success', '行价格已更新'
    return 'success', '已提交，未捕获明确成功提示'


def _click_optional_submit_confirmation(page, selectors: dict[str, list[str]], *, wait_ms: int) -> bool:
    clicked = _click_first(page, selectors.get('confirm_submit', []))
    if clicked:
        try:
            page.wait_for_timeout(wait_ms)
        except Exception:
            pass
    return clicked


def _normalize_effective_date(raw_value: object | None) -> str:
    value = str(raw_value or '').strip()
    if not value:
        return ''
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return ''


def _resolve_effective_date_range(item: dict) -> tuple[str, str]:
    default_date = datetime.now().date().isoformat()
    start_date = _normalize_effective_date(item.get('start_date')) or default_date
    end_date = _normalize_effective_date(item.get('end_date')) or start_date
    return start_date, end_date


def _row_uses_hwht_editor(row) -> bool:
    try:
        row_class = str(row.get_attribute('class') or '').strip()
    except Exception:
        row_class = ''
    if 'rate-plan-item' in row_class:
        return True
    try:
        return row.locator('.list-item').count() > 0
    except Exception:
        return False


def _active_modal_locator(page):
    return page.locator('.aui-grid-modal__wrapper.active, .aui-grid-modal__wrapper.is__visible.active')


def _is_price_editor_modal(modal) -> bool:
    try:
        modal_text = _clean_text(modal.inner_text(timeout=1000))
    except Exception:
        modal_text = ''
    if not modal_text:
        return False
    return '有效期' in modal_text and ('价格（cny）' in modal_text.lower() or '价格(cny)' in modal_text.lower())


def _dismiss_blocking_portal_modals(page, *, timeout_ms: int) -> list[str]:
    dismissed: list[str] = []
    max_rounds = max(1, min(8, timeout_ms // 400 or 1))
    for _ in range(max_rounds):
        modals = _active_modal_locator(page)
        try:
            count = modals.count()
        except Exception:
            count = 0
        if count == 0:
            break
        modal = modals.last
        if _is_price_editor_modal(modal):
            break
        closed = False
        for selector in [
            "button:has-text('知道了')",
            '.confirm-btn',
            '.aui-grid-modal__close-btn',
            "button:has-text('取消')",
        ]:
            try:
                trigger = modal.locator(selector).first
                if trigger.count() == 0:
                    continue
                label = _clean_text(trigger.inner_text(timeout=500)) or selector
                trigger.click(timeout=2000, force=True)
                page.wait_for_timeout(400)
                dismissed.append(label)
                closed = True
                break
            except Exception:
                continue
        if not closed:
            break
    return dismissed


def _wait_for_price_editor_modal(page, *, timeout_ms: int):
    attempts = max(1, min(30, timeout_ms // 200 or 1))
    for _ in range(attempts):
        modals = _active_modal_locator(page)
        try:
            count = modals.count()
        except Exception:
            count = 0
        for index in range(max(0, count - 1), -1, -1):
            modal = modals.nth(index)
            if _is_price_editor_modal(modal):
                return modal
        try:
            page.wait_for_timeout(200)
        except Exception:
            break
    return None


def _open_hwht_price_editor(page, row, *, timeout_ms: int) -> tuple[object | None, str, list[str]]:
    dismissed = _dismiss_blocking_portal_modals(page, timeout_ms=timeout_ms)
    try:
        cell = row.locator('.list-item.active').first
        if cell.count() == 0:
            cell = row.locator('.list-item').first
    except Exception:
        cell = None
    if cell is None:
        return None, '已找到房型，但未找到可点击日期格', dismissed
    try:
        cell.click(timeout=min(timeout_ms, 5000), force=True)
    except Exception:
        dismissed.extend(_dismiss_blocking_portal_modals(page, timeout_ms=timeout_ms))
        try:
            cell.click(timeout=min(timeout_ms, 5000), force=True)
        except Exception as exc:
            return None, f'已找到房型，但点击日期格失败: {exc}', dismissed
    try:
        page.wait_for_timeout(600)
    except Exception:
        pass
    modal = _wait_for_price_editor_modal(page, timeout_ms=min(timeout_ms, 4000))
    if modal is None:
        return None, '已点击日期格，但未打开改价弹窗', dismissed
    return modal, '', dismissed


def _fill_text_input(locator, value: str) -> str:
    try:
        locator.click(timeout=2000)
    except Exception:
        pass
    try:
        locator.fill('', timeout=2000)
    except Exception:
        pass
    try:
        locator.fill(value, timeout=3000)
        return value
    except Exception:
        locator.press('Control+A', timeout=1000)
        locator.press('Backspace', timeout=1000)
        locator.type(value, delay=20, timeout=4000)
        return value


def _find_hwht_price_input(modal):
    for selector in ["input[type='number']", ".aui-input__inner[type='number']", 'input.aui-input__inner']:
        try:
            locators = modal.locator(selector)
            count = locators.count()
        except Exception:
            count = 0
        for index in range(count):
            locator = locators.nth(index)
            try:
                input_type = str(locator.get_attribute('type') or '').strip().lower()
            except Exception:
                input_type = ''
            if input_type == 'checkbox':
                continue
            return locator, selector
    return None, ''


def _apply_hwht_price_editor(modal, item: dict, *, final_price: float) -> tuple[str, str, str, str]:
    start_date, end_date = _resolve_effective_date_range(item)
    try:
        date_inputs = modal.locator('.aui-range-input')
        if date_inputs.count() < 2:
            raise RuntimeError('未找到有效期输入框')
        filled_start = _fill_text_input(date_inputs.nth(0), start_date)
        filled_end = _fill_text_input(date_inputs.nth(1), end_date)
        try:
            date_inputs.nth(1).press('Tab', timeout=1000)
        except Exception:
            pass
    except Exception as exc:
        raise RuntimeError(f'设置生效日期失败: {exc}') from exc

    price_input, input_selector = _find_hwht_price_input(modal)
    if price_input is None:
        raise RuntimeError('已打开改价弹窗，但未找到价格输入框')
    filled_price = _fill_price_input(price_input, final_price)
    return input_selector, filled_price, filled_start, filled_end


def _detect_hwht_submit_outcome(page, modal, row, selectors: dict[str, list[str]], *, final_price: float, timeout_ms: int) -> tuple[str, str]:
    _wait_loading_clear(page, selectors, timeout_ms=min(timeout_ms, 3000))
    if _wait_for_any_selector(page, selectors['submit_error'], timeout_ms=1200, poll_ms=200):
        return 'failed', _first_text(page, selectors['submit_error']) or '页面提示提交失败'

    modal_closed = False
    try:
        modal.wait_for(state='hidden', timeout=min(timeout_ms, 4000))
        modal_closed = True
    except Exception:
        modal_closed = False

    if _wait_for_any_selector(page, selectors['submit_success'], timeout_ms=1800, poll_ms=200):
        try:
            latest_text = _clean_text(row.inner_text(timeout=1500))
        except Exception:
            latest_text = ''
        if '调价中' in latest_text:
            return 'success', '已推送到 OTA，平台调价中'
        if latest_text and any(price_token in latest_text for price_token in _price_variants(final_price)):
            return 'success', '已提交并刷新房价'
        return 'success', _first_text(page, selectors['submit_success']) or '页面提示提交成功'
    if _wait_for_any_selector(page, selectors['submit_error'], timeout_ms=800, poll_ms=200):
        return 'failed', _first_text(page, selectors['submit_error']) or '页面提示提交失败'
    if modal_closed:
        try:
            latest_text = _clean_text(row.inner_text(timeout=1500))
        except Exception:
            latest_text = ''
        if '调价中' in latest_text:
            return 'success', '已推送到 OTA，平台调价中'
        if latest_text and any(price_token in latest_text for price_token in _price_variants(final_price)):
            return 'success', '已提交并刷新房价'
        return 'success', '已提交，等待页面刷新'

    try:
        modal_text = _clean_text(modal.inner_text(timeout=1000))
    except Exception:
        modal_text = ''
    if modal_text:
        return 'failed', modal_text[:120]
    return 'failed', '提交后未捕获明确结果'

def _submit_single_price_update(page, selectors: dict[str, list[str]], item: dict, *, timeout_ms: int, wait_ms: int) -> dict:
    row, score, matched_by, row_text = _find_matching_row(page, selectors, item)
    display_name = str(item.get('display_name') or item.get('rate_name') or item.get('room_name') or '').strip()
    if row is None or score <= 0:
        return {
            'display_name': display_name,
            'gid': str(item.get('gid') or '').strip(),
            'hid': str(item.get('hid') or '').strip(),
            'current_price': round(float(item.get('current_price') or item.get('price') or 0), 2),
            'final_price': round(float(item.get('final_price') or 0), 2),
            'status': 'failed',
            'matched_by': None,
            'message': '未在商家价格页找到匹配房型',
            'submit_channel': 'merchant_portal',
            'submitted_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

    final_price = round(float(item.get('final_price') or 0), 2)
    if final_price <= 0:
        return {
            'display_name': display_name,
            'gid': str(item.get('gid') or '').strip(),
            'hid': str(item.get('hid') or '').strip(),
            'current_price': round(float(item.get('current_price') or item.get('price') or 0), 2),
            'final_price': final_price,
            'status': 'failed',
            'matched_by': matched_by or 'row_text',
            'message': '最终价无效，必须大于 0',
            'row_text': row_text,
            'submit_channel': 'merchant_portal',
            'submitted_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

    if _row_uses_hwht_editor(row):
        modal, modal_error, dismissed = _open_hwht_price_editor(page, row, timeout_ms=timeout_ms)
        if modal is None:
            return {
                'display_name': display_name,
                'gid': str(item.get('gid') or '').strip(),
                'hid': str(item.get('hid') or '').strip(),
                'current_price': round(float(item.get('current_price') or item.get('price') or 0), 2),
                'final_price': final_price,
                'status': 'failed',
                'matched_by': matched_by or 'row_text',
                'message': modal_error,
                'row_text': row_text,
                'dismissed_modals': dismissed,
                'submit_channel': 'merchant_portal',
                'submitted_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            }
        try:
            input_selector, filled_text, filled_start, filled_end = _apply_hwht_price_editor(modal, item, final_price=final_price)
        except RuntimeError as exc:
            return {
                'display_name': display_name,
                'gid': str(item.get('gid') or '').strip(),
                'hid': str(item.get('hid') or '').strip(),
                'current_price': round(float(item.get('current_price') or item.get('price') or 0), 2),
                'final_price': final_price,
                'status': 'failed',
                'matched_by': matched_by or 'row_text',
                'message': str(exc),
                'row_text': row_text,
                'dismissed_modals': dismissed,
                'submit_channel': 'merchant_portal',
                'submitted_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            }
        submit_clicked = _click_first(modal, ["button:has-text('\u63d0\u4ea4')", ".aui-button--primary:has-text('\u63d0\u4ea4')"])
        if not submit_clicked:
            return {
                'display_name': display_name,
                'gid': str(item.get('gid') or '').strip(),
                'hid': str(item.get('hid') or '').strip(),
                'current_price': round(float(item.get('current_price') or item.get('price') or 0), 2),
                'final_price': final_price,
                'status': 'failed',
                'matched_by': matched_by or 'row_text',
                'message': '已打开改价弹窗，但未找到提交按钮',
                'row_text': row_text,
                'dismissed_modals': dismissed,
                'submit_channel': 'merchant_portal',
                'submitted_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            }
        try:
            page.wait_for_timeout(wait_ms)
        except Exception:
            pass
        _click_optional_submit_confirmation(page, selectors, wait_ms=wait_ms)
        status, message = _detect_hwht_submit_outcome(page, modal, row, selectors, final_price=final_price, timeout_ms=timeout_ms)
        return {
            'display_name': display_name,
            'gid': str(item.get('gid') or '').strip(),
            'hid': str(item.get('hid') or '').strip(),
            'current_price': round(float(item.get('current_price') or item.get('price') or 0), 2),
            'final_price': final_price,
            'status': status,
            'matched_by': matched_by or 'row_text',
            'message': message,
            'row_text': row_text,
            'input_selector': input_selector,
            'filled_value': filled_text,
            'start_date': filled_start,
            'end_date': filled_end,
            'dismissed_modals': dismissed,
            'submit_channel': 'merchant_portal',
            'submitted_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

    input_locator, input_selector = _first_locator(row, selectors['price_input'])
    if input_locator is None:
        _click_first(row, selectors['edit_trigger'])
        try:
            page.wait_for_timeout(300)
        except Exception:
            pass
        input_locator, input_selector = _first_locator(row, selectors['price_input'])
    if input_locator is None:
        input_locator, input_selector = _first_locator(page, selectors['price_input'])
    if input_locator is None:
        return {
            'display_name': display_name,
            'gid': str(item.get('gid') or '').strip(),
            'hid': str(item.get('hid') or '').strip(),
            'current_price': round(float(item.get('current_price') or item.get('price') or 0), 2),
            'final_price': final_price,
            'status': 'failed',
            'matched_by': matched_by or 'row_text',
            'message': '已找到房型，但未找到可编辑价格输入框',
            'row_text': row_text,
            'submit_channel': 'merchant_portal',
            'submitted_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

    filled_text = _fill_price_input(input_locator, final_price)
    clicked = _click_first(row, selectors['row_save'])
    if not clicked:
        clicked = _click_first(page, selectors['page_save'])
    if not clicked:
        try:
            input_locator.press('Enter', timeout=1500)
        except Exception:
            pass
    try:
        page.wait_for_timeout(wait_ms)
    except Exception:
        pass
    _click_optional_submit_confirmation(page, selectors, wait_ms=wait_ms)

    status, message = _detect_submit_outcome(page, row, selectors, final_price=final_price, timeout_ms=timeout_ms)
    return {
        'display_name': display_name,
        'gid': str(item.get('gid') or '').strip(),
        'hid': str(item.get('hid') or '').strip(),
        'current_price': round(float(item.get('current_price') or item.get('price') or 0), 2),
        'final_price': final_price,
        'status': status,
        'matched_by': matched_by or 'row_text',
        'message': message,
        'row_text': row_text,
        'input_selector': input_selector,
        'filled_value': filled_text,
        'submit_channel': 'merchant_portal',
        'submitted_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }

def _submit_fliggy_merchant_price_updates_once(
    db,
    *,
    shop_id: int,
    items: list[dict],
    price_url: str | None = None,
    selectors: dict | str | None = None,
    headless: bool = True,
) -> dict:
    context_data = _resolve_connection_context(db=db, shop_id=shop_id)
    resolved_urls = _resolve_default_urls(
        login_url=context_data['login_url'],
        price_url=price_url or context_data['price_url'],
    )
    resolved_price_url = resolved_urls['price_url']
    if not resolved_price_url.startswith(('http://', 'https://')):
        raise ValueError('price_url is required and must start with http:// or https://')

    state_name = _safe_storage_name(context_data['storage_state_name'], shop_id=shop_id)
    state_path = _state_dir() / state_name
    if not state_path.exists():
        raise RuntimeError('merchant session not found, login first')

    selector_map = _merge_submit_selectors(
        selectors or context_data['selectors'],
        login_url=str(context_data['login_url']),
        price_url=resolved_price_url,
    )
    settings = get_settings()
    timeout_ms = max(5000, int(settings.fliggy_playwright_timeout_sec) * 1000)
    wait_ms = max(500, int(settings.fliggy_playwright_wait_after_load_ms))

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover
        raise RuntimeError('playwright not installed. run: py -3 -m pip install playwright') from exc

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=headless)
        except Exception as exc:  # pragma: no cover
            raise RuntimeError('failed to launch chromium. run: py -3 -m playwright install chromium') from exc
        context = browser.new_context(storage_state=str(state_path), user_agent=settings.competitor_crawl_user_agent)
        page = context.new_page()
        try:
            page.goto(resolved_price_url, wait_until='domcontentloaded', timeout=timeout_ms)
            try:
                page.wait_for_timeout(wait_ms)
                page.wait_for_load_state('networkidle', timeout=min(timeout_ms, 5000))
            except PlaywrightTimeoutError:
                pass
            authenticated, reason = _evaluate_authenticated_page(
                page,
                selectors=selector_map,
                login_url=resolved_urls['login_url'],
                price_url=resolved_price_url,
                success_reason='price-submit-success-selector',
                price_reason='price-submit-rows',
                url_reason='price-submit-url',
            )
            if not authenticated:
                if reason == 'redirected-to-login':
                    raise RuntimeError('merchant session expired, login required')
                raise RuntimeError(f'merchant price submit page not ready: {reason}')

            submitted_items = [
                _submit_single_price_update(page, selector_map, item, timeout_ms=timeout_ms, wait_ms=wait_ms)
                for item in items
            ]
        finally:
            browser.close()

    success_count = sum(1 for item in submitted_items if str(item.get('status') or '') == 'success')
    failed_count = max(0, len(submitted_items) - success_count)
    status = 'success' if failed_count == 0 else ('partial_failed' if success_count else 'failed')
    return {
        'shop_id': shop_id,
        'status': status,
        'submitted_count': len(submitted_items),
        'success_count': success_count,
        'failed_count': failed_count,
        'items': submitted_items,
        'price_url': resolved_price_url,
        'storage_state_used': state_name,
        'submit_channel': 'merchant_portal',
        'submitted_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


def submit_fliggy_merchant_price_updates(
    db,
    *,
    shop_id: int,
    items: list[dict],
    price_url: str | None = None,
    selectors: dict | str | None = None,
    headless: bool = True,
    auto_login: bool = True,
    login_headless: bool = False,
    collect_mode: str | None = None,
    debug_url: str | None = None,
) -> dict:
    if not items:
        raise ValueError('items must not be empty')

    context_data = _resolve_connection_context(db=db, shop_id=shop_id)
    resolved_urls = _resolve_default_urls(
        login_url=context_data['login_url'],
        price_url=price_url or context_data['price_url'],
    )
    resolved_storage_state_name = _safe_storage_name(context_data['storage_state_name'], shop_id=shop_id)
    resolved_selectors = selectors if selectors not in (None, '') else context_data['selectors']
    auto_login_performed = False

    try:
        result = _submit_fliggy_merchant_price_updates_once(
            db=db,
            shop_id=shop_id,
            items=items,
            price_url=resolved_urls['price_url'],
            selectors=resolved_selectors,
            headless=headless,
        )
    except RuntimeError as exc:
        if not auto_login or str(exc) not in _SESSION_LOGIN_REQUIRED_ERRORS:
            raise
        login_result = login_fliggy_merchant_session(
            db=db,
            shop_id=shop_id,
            username='',
            password='',
            login_url=resolved_urls['login_url'],
            storage_state_name=resolved_storage_state_name,
            selectors=resolved_selectors,
            headless=login_headless,
        )
        auto_login_performed = bool(login_result.get('session_saved'))
        result = _submit_fliggy_merchant_price_updates_once(
            db=db,
            shop_id=shop_id,
            items=items,
            price_url=resolved_urls['price_url'],
            selectors=resolved_selectors,
            headless=headless,
        )

    return {
        **result,
        'auto_login_performed': auto_login_performed,
    }

