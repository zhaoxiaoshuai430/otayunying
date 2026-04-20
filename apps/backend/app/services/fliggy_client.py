import hashlib
import json
import re
from datetime import date, datetime
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.core.config import get_settings

if TYPE_CHECKING:
    from app.services.shop_service import ShopConfig


class FliggyClientError(RuntimeError):
    """Raised when a Fliggy TOP API call fails."""


_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def _serialize_value(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _render_template_value(template: object, context: dict[str, object]) -> object:
    if isinstance(template, dict):
        return {str(key): _render_template_value(value, context) for key, value in template.items()}
    if isinstance(template, list):
        return [_render_template_value(item, context) for item in template]
    if not isinstance(template, str):
        return template

    full = _PLACEHOLDER_PATTERN.fullmatch(template)
    if full:
        return context.get(full.group(1), "")

    def _replace(match: re.Match[str]) -> str:
        value = context.get(match.group(1), "")
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    return _PLACEHOLDER_PATTERN.sub(_replace, template)


class FliggyClient:
    """Minimal TOP API client for Fliggy integrations."""

    def __init__(self, shop_config: "ShopConfig | None" = None) -> None:
        self.settings = get_settings()
        self.shop_config = shop_config

    def _credential(self, key: str) -> str:
        if self.shop_config is not None:
            value = getattr(self.shop_config, key, '')
            if value:
                return str(value)
        return str(getattr(self.settings, key, '') or '')

    def _build_base_params(self, method: str, use_session: bool) -> dict[str, str]:
        params = {
            "method": method,
            "app_key": self._credential('fliggy_app_key'),
            "format": self.settings.fliggy_format,
            "v": self.settings.fliggy_version,
            "sign_method": self.settings.fliggy_sign_method,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        session = self._credential('fliggy_session')
        if use_session and session:
            params['session'] = session
        return params

    @staticmethod
    def _sign(secret: str, params: dict[str, str]) -> str:
        raw = secret + ''.join(f"{k}{params[k]}" for k in sorted(params)) + secret
        return hashlib.md5(raw.encode('utf-8')).hexdigest().upper()

    def call(self, method: str, biz_params: dict | None = None, use_session: bool = True) -> dict:
        app_key = self._credential('fliggy_app_key')
        app_secret = self._credential('fliggy_app_secret')
        if not app_key or not app_secret:
            raise FliggyClientError('missing FLIGGY_APP_KEY or FLIGGY_APP_SECRET')

        payload = self._build_base_params(method=method, use_session=use_session)
        for key, value in (biz_params or {}).items():
            payload[key] = _serialize_value(value)
        payload['sign'] = self._sign(secret=app_secret, params=payload)

        data = urlencode(payload).encode('utf-8')
        req = Request(self.settings.fliggy_gateway, data=data, method='POST')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded;charset=utf-8')

        try:
            with urlopen(req, timeout=self.settings.fliggy_timeout_sec) as resp:
                raw = resp.read().decode('utf-8')
        except HTTPError as exc:
            raise FliggyClientError(f'http error: {exc.code}') from exc
        except URLError as exc:
            raise FliggyClientError(f'network error: {exc.reason}') from exc
        except TimeoutError as exc:
            raise FliggyClientError('request timeout') from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FliggyClientError('invalid response from fliggy api') from exc

        if 'error_response' in parsed:
            error = parsed['error_response'] or {}
            code = error.get('sub_code') or error.get('code') or 'UNKNOWN'
            msg = error.get('sub_msg') or error.get('msg') or 'unknown fliggy error'
            raise FliggyClientError(f'{code}: {msg}')

        return parsed

    def build_price_push_request(self, payload: dict) -> tuple[str, dict]:
        """Build one real Fliggy price-push request from a shop-level template.

        Args:
            payload: Runtime action payload containing new price and shop context.

        Returns:
            Tuple of TOP method and rendered biz params.

        Raises:
            FliggyClientError: If the shop-level push config is missing or invalid.
        """
        method = self._credential('fliggy_price_push_method')
        template_json = self._credential('fliggy_price_push_payload_json')
        if not method:
            raise FliggyClientError('missing fliggy price push method')
        if not template_json:
            raise FliggyClientError('missing fliggy price push payload template')

        try:
            template = json.loads(template_json)
        except json.JSONDecodeError as exc:
            raise FliggyClientError('invalid fliggy price push payload template json') from exc
        if not isinstance(template, dict):
            raise FliggyClientError('fliggy price push payload template must be a json object')

        today = date.today().isoformat()
        current_price = payload.get('current_price', payload.get('previous_price'))
        context: dict[str, object] = {
            'shop_id': payload.get('shop_id'),
            'new_price': payload.get('new_price'),
            'previous_price': payload.get('previous_price'),
            'current_price': current_price,
            'suggested_price_mid': payload.get('suggested_price_mid'),
            'price_min': payload.get('price_min'),
            'price_max': payload.get('price_max'),
            'change_pct': payload.get('change_pct'),
            'total_rooms': payload.get('total_rooms'),
            'available_rooms': payload.get('available_rooms'),
            'start_date': payload.get('start_date') or today,
            'end_date': payload.get('end_date') or payload.get('start_date') or today,
            'execution_date': today,
            'gid': payload.get('gid'),
            'hid': payload.get('hid'),
            'merchant_room_name': payload.get('merchant_room_name'),
            'merchant_rate_name': payload.get('merchant_rate_name'),
            'merchant_display_name': payload.get('merchant_display_name'),
            'fliggy_hotel_id': self._credential('fliggy_hotel_id'),
            'fliggy_room_status_hotel_id': self._credential('fliggy_room_status_hotel_id'),
        }
        rendered = _render_template_value(template, context)
        if not isinstance(rendered, dict):
            raise FliggyClientError('rendered fliggy price push payload must be a json object')
        return method, rendered

    def push_price(self, payload: dict) -> dict:
        """Call one configured Fliggy pricing API with rendered runtime values.

        Args:
            payload: Runtime action payload containing target price fields.

        Returns:
            Parsed Fliggy API response.
        """
        method, biz_params = self.build_price_push_request(payload)
        return self.call(method=method, biz_params=biz_params, use_session=True)

