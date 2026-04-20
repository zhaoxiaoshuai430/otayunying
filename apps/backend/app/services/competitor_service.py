from __future__ import annotations

import json
import os
import re
import unicodedata
from collections import Counter
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.merchant_connection_service import get_merchant_credential, record_merchant_login_result, save_merchant_credential
from app.services.shop_service import get_shop_config

_BROWSERS_DIR = str(Path(__file__).resolve().parents[2] / ".browsers")
if Path(_BROWSERS_DIR).is_dir():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", _BROWSERS_DIR)

_FLIGGY_GUEST_PLATFORM = "fliggy_guest"
_FLIGGY_GUEST_DEFAULT_START_URL = "https://hotel.fliggy.com/"
_FLIGGY_GUEST_DEFAULT_LOGIN_URL = _FLIGGY_GUEST_DEFAULT_START_URL
_FLIGGY_COLLECT_MODE_PREFER_CDP = "prefer_cdp"
_FLIGGY_COLLECT_MODE_STORAGE_STATE = "storage_state"
_FLIGGY_COLLECT_MODE_CDP_CURRENT_PAGE = "cdp_current_page"
_FLIGGY_CDP_DEFAULT_DEBUG_URL = "http://127.0.0.1:9222"
_COMPETITOR_SNAPSHOT_SOURCE_MAX_LEN = 32
_GUEST_SESSION_LOGIN_REQUIRED_ERRORS = {
    "guest session not found, login first",
    "guest session expired, login required",
}
_FLIGGY_GUEST_LOGIN_HINTS = (
    "\u5bc6\u7801\u767b\u5f55",
    "\u8d26\u53f7\u767b\u5f55",
    "\u626b\u7801\u767b\u5f55",
    "\u77ed\u4fe1\u767b\u5f55",
    "\u767b\u5f55",
    "\u8bf7\u5148\u767b\u5f55",
    "\u624b\u673a\u53f7\u767b\u5f55",
)
_FLIGGY_GUEST_AUTH_COOKIE_NAMES = {
    "cookie17",
    "unb",
    "tracknick",
    "_w_tb_nick",
    "lid",
    "uc1",
    "uc2",
    "uc3",
    "uc4",
}
_STORAGE_NAME_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")
_FLIGGY_HOTEL_URL_KEYWORDS = (
    'hotel_detail',
    'hotel.fliggy.com',
    'hotel_list',
)
_FLIGGY_HOTEL_NAME_KEYWORDS = (
    "\u9152\u5e97",
    "\u5bbe\u9986",
    "\u6c11\u5bbf",
    "\u5ba2\u6808",
    "\u516c\u5bd3",
    "\u65c5\u820d",
    "\u9752\u65c5",
    "\u5ea6\u5047",
    "\u5c71\u5e84",
    "hotel",
    "resort",
    "inn",
    "hostel",
    "homestay",
    "apartment",
    "suite",
)
_FLIGGY_HOTEL_CONTEXT_KEYWORDS = (
    "\u8bc4\u5206",
    "\u70b9\u8bc4",
    "\u8bc4\u8bba",
    "\u5730\u56fe",
    "\u9884\u8ba2",
    "\u65e9\u9910",
    "\u53cc\u5e8a",
    "\u5927\u5e8a",
    "\u5165\u4f4f",
    "\u79bb\u5e97",
    "\u4f4f\u5ba2",
    "\u53ef\u53d6\u6d88",
    "\u542b\u65e9",
    "\u65e0\u65e9",
    "\u6bcf\u665a",
    "\u8d77\u8ba2",
    "\u67e5\u770b\u8be6\u60c5",
)
_FLIGGY_NON_HOTEL_KEYWORDS = (
    "\u673a\u7968",
    "\u822a\u73ed",
    "\u822a\u7ebf",
    "\u51fa\u53d1",
    "\u5230\u8fbe",
    "\u5f80\u8fd4",
    "\u5355\u7a0b",
    "\u4e2d\u8f6c",
    "\u503c\u673a",
    "\u673a\u573a",
    "\u63a5\u9001\u673a",
    "\u98de\u884c",
    "\u706b\u8f66\u7968",
    "\u6c7d\u8f66\u7968",
    "\u95e8\u7968",
)
_FLIGGY_HOTEL_MARKETING_SUFFIX_PATTERNS = (
    r"(?:[\s|｜/·•~_-]|[【\[\(（])*(?:会员价|限时抢购|今日特惠|今夜特惠|优惠价|专享价|抢购价|券后价|返现优惠|连住优惠|提前订优惠|早订优惠|新客专享|品牌特惠|门店特惠)[】\]\)）\s|｜/·•~_-]*$",
    r"(?:[\s|｜/·•~_-]|[【\[\(（])*(?:立减|立省)\s*\d+(?:\.\d+)?\s*(?:元|起)?[】\]\)）\s|｜/·•~_-]*$",
    r"(?:[\s|｜/·•~_-]|[【\[\(（])*(?:立减|立省)[】\]\)）\s|｜/·•~_-]*$",
)
_FLIGGY_CANDIDATE_CONTAINER_SELECTORS = (
    "[class*='hotel']",
    "[class*='item']",
    "[class*='card']",
    "li",
    "article",
    "section",
    "div",
    "a",
)
_TARGET_HOTEL_NAME_SPLIT_PATTERN = re.compile(r"[\r\n,，;；]+")

_COMPETITOR_SNAPSHOT_SOURCE_ALIASES = {
    "manual": "manual",
    "schedule": "schedule",
    "scheduled": "schedule",
    "scheduler": "schedule",
    "cron": "schedule",
    "fliggy": "fliggy_playwright",
    "playwright": "fliggy_playwright",
    "fliggy_playwright": "fliggy_playwright",
    "fliggy_daily": "fliggy_playwright_daily",
    "playwright_daily": "fliggy_playwright_daily",
    "fliggy_playwright_daily": "fliggy_playwright_daily",
    "cdp": "fliggy_playwright_cdp",
    "fliggy_cdp": "fliggy_playwright_cdp",
    "playwright_cdp": "fliggy_playwright_cdp",
    "fliggy_playwright_cdp": "fliggy_playwright_cdp",
}
def _is_fliggy_home_or_root_url(url: str) -> bool:
    normalized = str(url or "").strip().lower().rstrip("/")
    return normalized in {
        "https://hotel.fliggy.com",
        "http://hotel.fliggy.com",
        "https://www.fliggy.com",
        "http://www.fliggy.com",
        "https://fliggy.com",
        "http://fliggy.com",
    }


def _looks_like_fliggy_hotel_list_url(url: str) -> bool:
    normalized = str(url or "").strip().lower()
    if not normalized.startswith(("http://", "https://")):
        return False
    if _is_fliggy_home_or_root_url(normalized):
        return False
    return "hotel.fliggy.com" in normalized


def normalize_fliggy_guest_start_url(start_url: str) -> str:
    """Refresh Fliggy hotel list URLs to today's stay dates while preserving city filters."""
    value = str(start_url or "").strip()
    normalized = value.lower()
    if "hotel.fliggy.com" not in normalized or "hotel_list" not in normalized:
        return value

    parsed = urlparse(value)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    query["checkIn"] = today.isoformat()
    query["checkOut"] = tomorrow.isoformat()
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _query_param_value(url: str, key: str) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    return dict(parse_qsl(urlparse(value).query, keep_blank_values=True)).get(key, "").strip()


def _should_navigate_fliggy_cdp_page(*, current_url: str, start_url: str) -> bool:
    normalized_start_url = normalize_fliggy_guest_start_url(start_url)
    if not _looks_like_fliggy_hotel_list_url(normalized_start_url):
        return False

    # cdp_current_page must use the current visible logged-in list page.
    # Saved start_url is only a fallback for discovery and must not force navigation.
    return False

def _normalize_fliggy_collect_mode(raw_mode: str | None) -> str:
    normalized = str(raw_mode or "").strip().lower() or _FLIGGY_COLLECT_MODE_CDP_CURRENT_PAGE
    if normalized == _FLIGGY_COLLECT_MODE_PREFER_CDP:
        return _FLIGGY_COLLECT_MODE_CDP_CURRENT_PAGE
    if normalized == _FLIGGY_COLLECT_MODE_CDP_CURRENT_PAGE:
        return normalized
    if normalized == _FLIGGY_COLLECT_MODE_STORAGE_STATE:
        raise ValueError("guest Fliggy collection only supports cdp_current_page; use a logged-in browser page instead")
    raise ValueError(f"unsupported collect_mode: {raw_mode}")

_DEFAULT_FLIGGY_GUEST_SELECTOR_MAP = {
    "username": [
        "input[name='fm-login-id']",
        "input[name='loginId']",
        "input[name='username']",
        "input[type='text']",
        "input[placeholder*='\u8d26\u53f7']",
        "input[placeholder*='\u4f1a\u5458\u540d']",
        "input[placeholder*='\u624b\u673a\u53f7']",
    ],
    "password": [
        "input[name='fm-login-password']",
        "input[name='password']",
        "input[type='password']",
        "input[placeholder*='\u5bc6\u7801']",
    ],
    "submit": [
        "button[type='submit']",
        "button:has-text('\u767b\u5f55')",
        "button:has-text('\u7acb\u5373\u767b\u5f55')",
        "text=\u767b\u5f55",
    ],
    "entry": [
        "a:has-text('\u767b\u5f55')",
        "button:has-text('\u767b\u5f55')",
        "a[href*='login']",
        "a[href*='passport']",
        "text=\u767b\u5f55",
    ],
    "success": [
        "text=\u6211\u7684\u8ba2\u5355",
        "text=\u9000\u51fa\u767b\u5f55",
        "text=\u6211\u7684\u6743\u76ca",
        "text=\u6b22\u8fce\u56de\u6765",
        "text=\u9152\u5e97",
    ],
}



def _strip_tags(html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return _strip_tags(match.group(1))


def _extract_meta_description(html: str) -> str:
    match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return ""
    return _strip_tags(match.group(1))


def _extract_price_signals(text: str) -> list[str]:
    patterns = [
        r"(?:¥|￥)\s?\d+(?:\.\d{1,2})?",
        r"\d+(?:\.\d{1,2})?\s?(?:元|RMB|CNY)",
        r"\$\s?\d+(?:\.\d{1,2})?",
    ]
    candidates: list[str] = []
    for pattern in patterns:
        candidates.extend(re.findall(pattern, text, flags=re.IGNORECASE))
    unique = []
    seen = set()
    for item in candidates:
        norm = item.strip()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        unique.append(norm)
    return unique[:15]


def _fetch_html(url: str, timeout_sec: int, user_agent: str) -> str:
    req = Request(url, method="GET")
    req.add_header("User-Agent", user_agent)
    req.add_header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8")
    with urlopen(req, timeout=timeout_sec) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _extract_json_candidate(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or start >= end:
        return text
    return text[start : end + 1]


def _extract_response_text(payload: dict) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = payload.get("output")
    if isinstance(output, list):
        chunks: list[str] = []
        for node in output:
            if not isinstance(node, dict):
                continue
            node_type = str(node.get("type") or "")
            if node_type == "output_text":
                direct_text = node.get("text")
                if isinstance(direct_text, str) and direct_text.strip():
                    chunks.append(direct_text.strip())
                continue
            content = node.get("content")
            if isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    part_type = str(item.get("type") or "")
                    txt = item.get("text")
                    if part_type in {"output_text", "text", "input_text"} and isinstance(txt, str) and txt.strip():
                        chunks.append(txt.strip())
        if chunks:
            return "\n".join(chunks)
    return ""


def _extract_chat_completions_text(payload: dict) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return ""
    if not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""

    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            txt = item.get("text")
            if isinstance(txt, str) and txt.strip():
                chunks.append(txt.strip())
        return "\n".join(chunks)
    return ""


def _normalize_openclaw_analysis(result: dict) -> dict:
    def _as_text_list(value: object) -> list[str]:
        if isinstance(value, list):
            out: list[str] = []
            for item in value:
                txt = str(item or "").strip()
                if txt:
                    out.append(txt)
            return out[:30]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    return {
        "summary": str(result.get("summary") or "").strip() or "openclaw_result",
        "pricing_signals": _as_text_list(result.get("pricing_signals")),
        "promotion_signals": _as_text_list(result.get("promotion_signals")),
        "inventory_signals": _as_text_list(result.get("inventory_signals")),
        "risk_notes": _as_text_list(result.get("risk_notes")),
    }


def _build_openclaw_prompt(*, target_name: str, target_url: str, signals: dict) -> str:
    return (
        "You are a market analyst. Return JSON only (no markdown/code fences) with keys: "
        "summary, pricing_signals, promotion_signals, inventory_signals, risk_notes.\n"
        f"Target: {target_name}\n"
        f"URL: {target_url}\n"
        f"Signals: {json.dumps(signals, ensure_ascii=False)}"
    )


def _build_openclaw_headers(*, token: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    normalized_token = str(token or "").strip()
    if normalized_token:
        headers["Authorization"] = f"Bearer {normalized_token}"
    return headers


def _call_openclaw_responses_text(*, base_url: str, model: str, token: str, prompt: str, timeout_sec: int) -> str:
    payload = {
        "model": model,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }
        ],
    }
    req = Request(
        f"{base_url}/v1/responses",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )
    for key, value in _build_openclaw_headers(token=token).items():
        req.add_header(key, value)
    with urlopen(req, timeout=timeout_sec) as resp:
        raw = resp.read().decode("utf-8")
    parsed = json.loads(raw)
    if isinstance(parsed.get("error"), dict):
        err = parsed["error"]
        raise RuntimeError(str(err.get("message") or "openclaw responses error"))
    response_text = _extract_response_text(parsed)
    if not response_text:
        raise RuntimeError("openclaw responses empty response")
    return response_text


def _call_openclaw_chat_completions_text(*, base_url: str, model: str, token: str, prompt: str, timeout_sec: int) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = Request(
        f"{base_url}/v1/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )
    for key, value in _build_openclaw_headers(token=token).items():
        req.add_header(key, value)
    with urlopen(req, timeout=timeout_sec) as resp:
        raw = resp.read().decode("utf-8")
    parsed = json.loads(raw)
    if isinstance(parsed.get("error"), dict):
        err = parsed["error"]
        raise RuntimeError(str(err.get("message") or "openclaw chat completions error"))
    response_text = _extract_chat_completions_text(parsed)
    if not response_text:
        raise RuntimeError("openclaw chat completions empty response")
    return response_text


def _parse_openclaw_analysis_text(text: str) -> dict:
    result = json.loads(_extract_json_candidate(text))
    if not isinstance(result, dict):
        raise RuntimeError("openclaw invalid json structure")
    return _normalize_openclaw_analysis(result)


def _heuristic_analysis(signals: dict) -> dict:
    prices = signals.get("price_signals", [])
    promo_words = ["优惠", "折扣", "满减", "coupon", "sale", "促销", "限时"]
    text = (signals.get("title", "") + " " + signals.get("meta_description", "") + " " + signals.get("snippet", "")).lower()
    promo_hits = [w for w in promo_words if w.lower() in text]
    return {
        "summary": "heuristic_result",
        "pricing_signals": prices,
        "promotion_signals": promo_hits,
        "inventory_signals": [],
        "risk_notes": [],
    }


def _call_openclaw_analysis(*, target_name: str, target_url: str, signals: dict) -> dict:
    settings = get_settings()
    token = str(settings.openclaw_api_key or "").strip()
    model = str(settings.openclaw_model or "").strip() or "openclaw:main"
    base_url = str(settings.openclaw_base_url).rstrip("/")
    if not base_url:
        raise RuntimeError("missing OPENCLAW_BASE_URL")
    timeout_sec = max(5, int(settings.competitor_crawl_timeout_sec))
    prompt = _build_openclaw_prompt(target_name=target_name, target_url=target_url, signals=signals)

    errors: list[str] = []
    callers = [
        ("responses", _call_openclaw_responses_text),
        ("chat_completions", _call_openclaw_chat_completions_text),
    ]
    for mode, caller in callers:
        try:
            text_result = caller(
                base_url=base_url,
                model=model,
                token=token,
                prompt=prompt,
                timeout_sec=timeout_sec,
            )
            return _parse_openclaw_analysis_text(text_result)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            errors.append(f"{mode}: {exc}")

    raise RuntimeError("; ".join(errors) or "openclaw call failed")


def collect_competitor_intel(
    *,
    shop_id: int,
    targets: list[dict],
    use_openclaw: bool,
    limit_per_page_chars: int,
) -> dict:
    settings = get_settings()
    timeout_sec = max(3, int(settings.competitor_crawl_timeout_sec))
    user_agent = settings.competitor_crawl_user_agent
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    items: list[dict] = []
    for raw_target in targets:
        name = str(raw_target.get("name") or "").strip()
        url = str(raw_target.get("url") or "").strip()
        note = raw_target.get("note")

        if not name or not url:
            items.append(
                {
                    "name": name or "unknown",
                    "url": url,
                    "note": note,
                    "fetch_status": "invalid_target",
                    "error": "name and url are required",
                }
            )
            continue

        if not (url.startswith("http://") or url.startswith("https://")):
            items.append(
                {
                    "name": name,
                    "url": url,
                    "note": note,
                    "fetch_status": "invalid_url",
                    "error": "url must start with http:// or https://",
                }
            )
            continue

        try:
            html = _fetch_html(url=url, timeout_sec=timeout_sec, user_agent=user_agent)
            text = _strip_tags(html)
            clipped = text[:limit_per_page_chars]
            signals = {
                "title": _extract_title(html),
                "meta_description": _extract_meta_description(html),
                "price_signals": _extract_price_signals(clipped),
                "snippet": clipped[:800],
            }

            analysis_source = "heuristic"
            analysis = _heuristic_analysis(signals)
            openclaw_error = ""
            if use_openclaw:
                try:
                    analysis = _call_openclaw_analysis(target_name=name, target_url=url, signals=signals)
                    analysis_source = "openclaw"
                except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
                    openclaw_error = str(exc)

            item = {
                "name": name,
                "url": url,
                "note": note,
                "fetch_status": "success",
                "analysis_source": analysis_source,
                "signals": signals,
                "analysis": analysis,
            }
            if openclaw_error:
                item["openclaw_error"] = openclaw_error
            items.append(item)
        except (HTTPError, URLError, TimeoutError) as exc:
            items.append(
                {
                    "name": name,
                    "url": url,
                    "note": note,
                    "fetch_status": "fetch_failed",
                    "error": str(exc),
                }
            )

    return {
        "shop_id": shop_id,
        "collected_at": now,
        "count": len(items),
        "items": items,
    }


def _extract_fliggy_price_from_text(text: str) -> float | None:
    match = re.search(r"(?:¥|￥)\s*(\d+(?:\.\d{1,2})?)", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _clean_fliggy_candidate_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_target_hotel_names(raw_value: object | None) -> list[str]:
    if isinstance(raw_value, list):
        values = raw_value
    elif isinstance(raw_value, tuple):
        values = list(raw_value)
    else:
        text = str(raw_value or "").strip()
        values = _TARGET_HOTEL_NAME_SPLIT_PATTERN.split(text) if text else []

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text_value = _normalize_fliggy_hotel_name(str(value or "").strip())
        if not text_value:
            continue
        key = "".join(text_value.lower().split())
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text_value[:128])
    return normalized[:50]


def _strip_fliggy_invisible_chars(value: str) -> str:
    """Remove invisible and private-use characters from Fliggy text."""
    sanitized: list[str] = []
    for char in str(value or ""):
        if unicodedata.category(char) in {"Cc", "Cf", "Co", "Cs"}:
            continue
        sanitized.append(char)
    return "".join(sanitized)


def _normalize_fliggy_hotel_name(value: str) -> str:
    """Normalize a Fliggy hotel name while preserving the core property name."""
    raw_text = _clean_fliggy_candidate_text(_strip_fliggy_invisible_chars(value))
    if not raw_text:
        return ""

    normalized = re.sub(r"[★☆◆◇●•※¤]+", " ", raw_text)
    normalized = _clean_fliggy_candidate_text(normalized)
    previous = None
    while normalized and normalized != previous:
        previous = normalized
        for pattern in _FLIGGY_HOTEL_MARKETING_SUFFIX_PATTERNS:
            normalized = re.sub(pattern, "", normalized, flags=re.IGNORECASE)
        normalized = _clean_fliggy_candidate_text(normalized.rstrip("-|｜/·•~_"))
    return normalized or raw_text


def _split_fliggy_candidate_lines(value: str) -> list[str]:
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def _score_fliggy_hotel_candidate(*, name: str, raw_text: str, href: str) -> int:
    lines = _split_fliggy_candidate_lines(raw_text)
    score = 0
    if _extract_fliggy_price_from_text(raw_text) is not None:
        score += 2
    if _contains_any_keyword(href, _FLIGGY_HOTEL_URL_KEYWORDS):
        score += 2
    if _contains_any_keyword(name, _FLIGGY_HOTEL_NAME_KEYWORDS):
        score += 2
    elif _contains_any_keyword(raw_text, _FLIGGY_HOTEL_NAME_KEYWORDS):
        score += 1
    if _contains_any_keyword(raw_text, _FLIGGY_HOTEL_CONTEXT_KEYWORDS):
        score += 1
    if 2 <= len(lines) <= 8:
        score += 1
    if name and name in raw_text:
        score += 1
    return score


def _contains_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    normalized = str(text or "").lower()
    return any(keyword.lower() in normalized for keyword in keywords)


def _looks_like_fliggy_hotel_card(*, name: str, raw_text: str, href: str) -> tuple[bool, str]:
    combined = _clean_fliggy_candidate_text(f"{name}\n{raw_text}")
    normalized_combined = combined.lower()
    normalized_href = str(href or "").strip().lower()

    for keyword in _FLIGGY_NON_HOTEL_KEYWORDS:
        if keyword.lower() in normalized_combined or keyword.lower() in normalized_href:
            return False, f"non_hotel_keyword:{keyword}"

    has_hotel_name_signal = _contains_any_keyword(name, _FLIGGY_HOTEL_NAME_KEYWORDS)
    has_hotel_text_signal = _contains_any_keyword(raw_text, _FLIGGY_HOTEL_NAME_KEYWORDS)
    score = _score_fliggy_hotel_candidate(name=name, raw_text=raw_text, href=normalized_href)
    if score >= 4 and (has_hotel_name_signal or has_hotel_text_signal):
        return True, 'hotel_signal'
    if score >= 5 and _contains_any_keyword(normalized_href, _FLIGGY_HOTEL_URL_KEYWORDS) and _contains_any_keyword(raw_text, _FLIGGY_HOTEL_CONTEXT_KEYWORDS):
        return True, 'hotel_signal'
    return False, 'weak_hotel_signal'


def _normalize_competitor_snapshot_source(raw_source: str | None) -> str:
    """Normalize historical competitor snapshot source labels to canonical values."""
    original = str(raw_source or "").strip()
    token = original.lower().replace("-", "_").replace(" ", "_")
    token = re.sub(r"_+", "_", token).strip("_")
    if not token:
        return "manual"
    if token in _COMPETITOR_SNAPSHOT_SOURCE_ALIASES:
        return _COMPETITOR_SNAPSHOT_SOURCE_ALIASES[token]
    if token.startswith("fliggy") or "playwright" in token:
        if "daily" in token or "schedule" in token:
            return "fliggy_playwright_daily"
        if "cdp" in token or "debug" in token:
            return "fliggy_playwright_cdp"
        return "fliggy_playwright"
    if token in {"scheduled_job", "scheduled_task"}:
        return "schedule"
    return (original or "manual")[:_COMPETITOR_SNAPSHOT_SOURCE_MAX_LEN]


def _parse_competitor_snapshot_signals(raw_value: object) -> dict:
    """Parse snapshot signals payload from DB rows or in-memory dicts."""
    if isinstance(raw_value, dict):
        return raw_value
    if isinstance(raw_value, str) and raw_value.strip():
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def build_competitor_snapshot_cleanup_plan(snapshot: dict) -> dict:
    """Build cleanup actions for one historical competitor snapshot row."""
    raw_name = _clean_fliggy_candidate_text(snapshot.get("target_name") or "")
    raw_source = str(snapshot.get("source") or "").strip()
    url = _clean_fliggy_candidate_text(snapshot.get("target_url") or "")
    url_lower = url.lower()
    normalized_source = _normalize_competitor_snapshot_source(raw_source)
    signals = _parse_competitor_snapshot_signals(snapshot.get("signals_json"))
    title = _clean_fliggy_candidate_text(signals.get("title") or "")
    snippet = _clean_fliggy_candidate_text(signals.get("snippet") or "")
    raw_price_signals = signals.get("price_signals") if isinstance(signals.get("price_signals"), list) else []
    price_signals = [_clean_fliggy_candidate_text(value) for value in raw_price_signals if _clean_fliggy_candidate_text(value)]

    candidate_name = raw_name
    if not candidate_name or candidate_name.lower() == "unknown":
        candidate_name = title
    elif _extract_fliggy_price_from_text(candidate_name) is not None and title:
        candidate_name = title

    normalized_name = _normalize_fliggy_hotel_name(candidate_name) if candidate_name else ""
    target_name = (normalized_name or candidate_name or raw_name)[:128]

    updates: dict[str, str] = {}
    reasons: list[str] = []
    if target_name and target_name != raw_name:
        updates["target_name"] = target_name
        reasons.append("normalized_target_name")
    if normalized_source != raw_source:
        updates["source"] = normalized_source
        reasons.append("normalized_source")

    combined_text = _clean_fliggy_candidate_text("\n".join(part for part in [target_name, title, snippet, " ".join(price_signals)] if part))
    is_fliggy_snapshot = (
        "fliggy" in normalized_source
        or "hotel.fliggy.com" in url_lower
        or _is_fliggy_home_or_root_url(url_lower)
        or "login" in url_lower
        or "passport" in url_lower
    )

    invalid_reason = ""
    if is_fliggy_snapshot:
        if url_lower and (_is_fliggy_home_or_root_url(url_lower) or "login" in url_lower or "passport" in url_lower):
            invalid_reason = "invalid_fliggy_entry_url"
        elif raw_name and _extract_fliggy_price_from_text(raw_name) is not None and not _contains_any_keyword(target_name or combined_text, _FLIGGY_HOTEL_NAME_KEYWORDS):
            invalid_reason = "price_as_target_name"
        elif not (target_name or title) and not price_signals:
            invalid_reason = "missing_target_name"
        else:
            keep, reason = _looks_like_fliggy_hotel_card(
                name=target_name or raw_name or title,
                raw_text=combined_text or (target_name or raw_name or title),
                href=url,
            )
            if not keep and reason.startswith("non_hotel_keyword:"):
                invalid_reason = reason

    if invalid_reason:
        reasons.append(invalid_reason)

    return {
        "id": int(snapshot.get("id") or 0),
        "target_name": target_name,
        "source": normalized_source,
        "updates": updates,
        "should_update": bool(updates),
        "should_delete": bool(invalid_reason),
        "invalid_reason": invalid_reason or None,
        "reasons": reasons,
    }

def _extract_fliggy_rows_from_page(page) -> dict:
    """Extract hotel name/price/url rows from a Fliggy result page."""
    rows: list[dict] = []

    if hasattr(page, 'query_selector_all'):
        nodes = []
        seen_handles: set[int] = set()
        for selector in _FLIGGY_CANDIDATE_CONTAINER_SELECTORS:
            try:
                selector_nodes = page.query_selector_all(selector)
            except Exception:
                selector_nodes = []
            for el in selector_nodes[:160]:
                handle_id = id(el)
                if handle_id in seen_handles:
                    continue
                seen_handles.add(handle_id)
                nodes.append(el)
            if len(nodes) >= 400:
                break
        for el in nodes:
            try:
                text_value = str(el.inner_text(timeout=1000) or '').strip()
            except Exception:
                continue
            if not text_value or len(text_value) < 8 or len(text_value) > 350:
                continue
            if '?' not in text_value and '?' not in text_value:
                continue

            lines = _split_fliggy_candidate_lines(text_value)
            name = ''
            try:
                name_node = el.query_selector('h1,h2,h3,h4,[class*="title"],[class*="name"],[class*="hotel"]')
            except Exception:
                name_node = None
            if name_node is not None:
                try:
                    name = str(name_node.inner_text(timeout=500) or '').strip()
                except Exception:
                    name = ''
            if not name:
                name = lines[0] if lines else ''

            href = ''
            try:
                href = str(el.get_attribute('href') or '').strip()
            except Exception:
                href = ''
            if not href:
                try:
                    link = el.query_selector('a')
                except Exception:
                    link = None
                if link is not None:
                    try:
                        href = str(link.get_attribute('href') or '').strip()
                    except Exception:
                        href = ''
            rows.append({'name': name, 'text': text_value, 'href': href, 'line_count': len(lines)})
    else:
        rows = page.evaluate(
            """
            () => {
              const selectors = [
                "[class*='hotel']",
                "[class*='item']",
                "[class*='card']",
                "li",
                "article",
                "section",
                "div",
                "a",
              ];
              const nodes = [];
              const seen = new Set();
              for (const selector of selectors) {
                const matches = Array.from(document.querySelectorAll(selector)).slice(0, 160);
                for (const el of matches) {
                  if (!el || seen.has(el)) continue;
                  seen.add(el);
                  nodes.push(el);
                }
                if (nodes.length >= 400) break;
              }
              const out = [];
              for (const el of nodes) {
                if (!el || !el.innerText) continue;
                const text = String(el.innerText || '').trim();
                if (!text || text.length < 8 || text.length > 350) continue;
                if (!(text.includes('?') || text.includes('?'))) continue;

                let name = '';
                const nameNode = el.querySelector('h1,h2,h3,h4,[class*="title"],[class*="name"],[class*="hotel"]');
                if (nameNode && nameNode.innerText) name = String(nameNode.innerText).trim();
                const lines = text.split('\\n').map(s => s.trim()).filter(Boolean);
                if (!name) {
                  name = lines.length ? lines[0] : '';
                }

                const href = el.getAttribute('href') || ((el.querySelector('a') || {}).href) || '';
                out.push({ name, text, href, line_count: lines.length });
              }
              return out;
            }
            """
        )


    if not rows and hasattr(page, 'locator'):
        try:
            body_text = str(page.locator('body').inner_text(timeout=2000) or '')
        except Exception:
            body_text = ''
        if body_text:
            lines = [_clean_fliggy_candidate_text(line) for line in body_text.splitlines() if _clean_fliggy_candidate_text(line)]
            body_href = str(getattr(page, 'url', '') or '').strip()
            body_seen: set[str] = set()
            for idx, line in enumerate(lines):
                price = _extract_fliggy_price_from_text(line)
                if price is None:
                    continue
                name = ''
                for offset in range(1, 8):
                    if idx + offset >= len(lines):
                        break
                    candidate_name = lines[idx + offset]
                    if _contains_any_keyword(candidate_name, _FLIGGY_HOTEL_NAME_KEYWORDS):
                        name = candidate_name
                        break
                if not name:
                    continue
                key = f'{name}|{price:.2f}'
                if key in body_seen:
                    continue
                body_seen.add(key)
                raw_text = ' '.join(lines[idx:min(len(lines), idx + 6)])
                rows.append({'name': name, 'text': raw_text, 'href': body_href})


    normalized: list[dict] = []
    filtered_examples: list[dict] = []
    filter_summary: Counter[str] = Counter()
    seen: set[str] = set()
    raw_row_count = 0

    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_text = _clean_fliggy_candidate_text(row.get('text') or '')
        if not raw_text:
            continue
        raw_row_count += 1
        price = _extract_fliggy_price_from_text(raw_text)
        if price is None:
            continue
        raw_name = _clean_fliggy_candidate_text(row.get('name') or '')
        if not raw_name:
            raw_lines = _split_fliggy_candidate_lines(row.get('text') or '')
            raw_name = raw_lines[0] if raw_lines else ''
        name = _normalize_fliggy_hotel_name(raw_name) or raw_name
        href = _clean_fliggy_candidate_text(row.get('href') or '')
        keep, reason = _looks_like_fliggy_hotel_card(name=name, raw_text=raw_text, href=href)
        if not keep:
            filter_summary[reason] += 1
            if len(filtered_examples) < 8:
                filtered_examples.append(
                    {
                        'name': name or 'unknown',
                        'price': price,
                        'url': href,
                        'reason': reason,
                        'raw_text': raw_text[:240],
                    }
                )
            continue
        key = f"{name}|{price:.2f}|{href}"
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                'hotel_name': name or 'unknown',
                'price': price,
                'url': href,
                'raw_text': raw_text[:500],
            }
        )

    return {
        'rows': normalized,
        'raw_row_count': raw_row_count,
        'filtered_row_count': sum(filter_summary.values()),
        'filter_summary': dict(filter_summary),
        'filtered_examples': filtered_examples,
    }


def _build_collection_result_from_fliggy_rows(*, shop_id: int, start_url: str, rows: list[dict], stats: dict | None = None) -> dict:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    items: list[dict] = []
    for row in rows:
        price = float(row.get("price") or 0)
        raw_hotel_name = str(row.get("hotel_name") or "")
        hotel_name = _normalize_fliggy_hotel_name(raw_hotel_name) or raw_hotel_name or "unknown"
        url = str(row.get("url") or start_url)
        raw_text = str(row.get("raw_text") or "")
        items.append(
            {
                "name": hotel_name,
                "url": url,
                "note": "fliggy_playwright",
                "fetch_status": "success",
                "analysis_source": "playwright",
                "signals": {
                    "title": hotel_name,
                    "meta_description": "",
                    "price_signals": [f"\u00A5{price:g}"],
                    "snippet": raw_text[:800],
                },
                "analysis": {
                    "summary": "playwright_price_capture",
                    "pricing_signals": [f"\u00A5{price:g}"],
                    "promotion_signals": [],
                    "inventory_signals": [],
                    "risk_notes": [],
                },
            }
        )

    stats = stats if isinstance(stats, dict) else {}
    raw_row_count = int(stats.get('raw_row_count') or len(items))
    filtered_row_count = int(stats.get('filtered_row_count') or 0)
    filter_summary = stats.get('filter_summary') if isinstance(stats.get('filter_summary'), dict) else {}
    filtered_examples = stats.get('filtered_examples') if isinstance(stats.get('filtered_examples'), list) else []

    return {
        "shop_id": shop_id,
        "collected_at": now,
        "count": len(items),
        "raw_row_count": raw_row_count,
        "kept_row_count": len(items),
        "filtered_row_count": filtered_row_count,
        "filter_summary": filter_summary,
        "filtered_examples": filtered_examples[:8],
        "items": items,
    }


def _normalize_target_hotel_match_text(value: str) -> str:
    normalized = _normalize_fliggy_hotel_name(str(value or "").strip())
    compact = "".join(normalized.lower().split())
    return re.sub(r"[（()）【】\[\]·•｜|/_\-.,，。:：]", "", compact)


def _strip_target_hotel_city_prefix(value: str) -> str:
    normalized = _normalize_fliggy_hotel_name(str(value or "").strip())
    matched = re.match(r"^[一-鿿]{2,4}(.*)$", normalized)
    if not matched:
        return normalized
    candidate = matched.group(1).strip()
    if candidate and any(keyword in candidate for keyword in ("酒店", "宾馆", "民宿", "客栈", "公寓", "旅舍")):
        return candidate
    return normalized


def _build_target_hotel_match_keys(value: str) -> set[str]:
    normalized = _normalize_fliggy_hotel_name(str(value or "").strip())
    if not normalized:
        return set()

    candidates = {normalized}
    without_paren = re.sub(r"[（(][^（）()]{1,40}[)）]\s*$", "", normalized).strip()
    if without_paren:
        candidates.add(without_paren)

    expanded_candidates = set(candidates)
    for candidate in list(candidates):
        without_city = _strip_target_hotel_city_prefix(candidate)
        if without_city:
            expanded_candidates.add(without_city)

    keys: set[str] = set()
    for candidate in expanded_candidates:
        key = _normalize_target_hotel_match_text(candidate)
        if key:
            keys.add(key)
    return keys


def _target_hotel_name_matches(*, target_name: str, item_name: str) -> bool:
    target_keys = _build_target_hotel_match_keys(target_name)
    item_keys = _build_target_hotel_match_keys(item_name)
    if not target_keys or not item_keys:
        return False

    for target_key in target_keys:
        for item_key in item_keys:
            shorter = min(len(target_key), len(item_key))
            if shorter < 2:
                continue
            if target_key == item_key:
                return True
            if target_key in item_key:
                return True
            if shorter >= 6 and item_key in target_key:
                return True
    return False



def _match_target_hotel_name_for_item(item: dict, *, target_name: str) -> bool:
    if not isinstance(item, dict):
        return False
    signals = item.get("signals") if isinstance(item.get("signals"), dict) else {}
    candidates = [
        str(item.get("name") or "").strip(),
        str(signals.get("title") or "").strip(),
        str(signals.get("snippet") or "").strip(),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        for part in _split_fliggy_candidate_lines(candidate) or [candidate]:
            if _target_hotel_name_matches(target_name=target_name, item_name=part):
                return True
    return False


def _row_matches_target_hotel_names(*, name: str, raw_text: str, href: str, target_hotel_names: list[str]) -> bool:
    if not target_hotel_names:
        return False
    probe_item = {
        "name": str(name or "").strip(),
        "url": str(href or "").strip(),
        "signals": {
            "title": str(name or "").strip(),
            "snippet": str(raw_text or "").strip(),
        },
    }
    return any(_match_target_hotel_name_for_item(probe_item, target_name=target_name) for target_name in target_hotel_names)


def _normalize_city_hint(value: str) -> str:
    text = _clean_fliggy_candidate_text(str(value or ""))
    text = re.sub(r"(省|市|自治区|特别行政区|地区|盟)$", "", text)
    return text[:4]


def _extract_target_city_hint(target_name: str) -> str:
    normalized = _normalize_fliggy_hotel_name(str(target_name or "").strip())
    if not normalized:
        return ""
    matched = re.match(r"^([\u4e00-\u9fff]{2,4})", normalized)
    if not matched:
        return ""
    return _normalize_city_hint(matched.group(1))


def _build_page_target_city_warning(*, page_snapshot: dict, target_hotel_names: list[str]) -> str:
    if not isinstance(page_snapshot, dict):
        return ""
    page_context = page_snapshot.get("page_context") if isinstance(page_snapshot.get("page_context"), dict) else {}
    page_city = _normalize_city_hint(str(page_context.get("cityName") or page_context.get("city_name") or ""))
    if not page_city:
        return ""

    mismatched_targets: list[str] = []
    for target_name in parse_target_hotel_names(target_hotel_names):
        city_hint = _extract_target_city_hint(target_name)
        if city_hint and city_hint != page_city and page_city not in target_name:
            mismatched_targets.append(target_name)

    if not mismatched_targets:
        return ""
    sample = mismatched_targets[0]
    return f"当前页城市为{page_city}，但指定酒店疑似属于其他城市：{sample}。请先切到对应城市/酒店列表页再采集。"

def _filter_collection_result_by_target_hotels(result: dict, *, target_hotel_names: list[str] | None) -> dict:
    normalized_targets = parse_target_hotel_names(target_hotel_names)
    if not normalized_targets:
        updated = dict(result)
        updated["target_hotel_names"] = []
        updated["matched_target_hotel_names"] = []
        updated["missing_target_hotel_names"] = []
        updated["target_filtered_out_count"] = 0
        return updated

    target_pairs = [(name, _normalize_target_hotel_match_text(name)) for name in normalized_targets]
    original_items = result.get("items") if isinstance(result.get("items"), list) else []
    filtered_items: list[dict] = []
    matched_targets: set[str] = set()
    target_filtered_examples = list(result.get("filtered_examples") or [])[:8]

    for item in original_items:
        if not isinstance(item, dict):
            continue
        item_name = str(item.get("name") or "").strip()
        matched = [
            target_name
            for target_name, _normalized_target in target_pairs
            if _match_target_hotel_name_for_item(item, target_name=target_name)
        ]
        if matched:
            filtered_items.append(item)
            matched_targets.update(matched)
            continue
        if len(target_filtered_examples) < 8:
            signals = item.get("signals") if isinstance(item.get("signals"), dict) else {}
            price_signals = signals.get("price_signals") if isinstance(signals.get("price_signals"), list) else []
            target_filtered_examples.append(
                {
                    "name": item_name or "unknown",
                    "price": price_signals[0] if price_signals else "",
                    "url": str(item.get("url") or "").strip(),
                    "reason": "target_hotel_name_mismatch",
                    "raw_text": str(signals.get("snippet") or "")[:240],
                }
            )

    filtered_out_count = max(0, len(original_items) - len(filtered_items))
    filter_summary = Counter()
    existing_summary = result.get("filter_summary") if isinstance(result.get("filter_summary"), dict) else {}
    filter_summary.update({str(key): int(value) for key, value in existing_summary.items()})
    if filtered_out_count:
        filter_summary["target_hotel_name_mismatch"] += filtered_out_count

    updated = dict(result)
    updated["items"] = filtered_items
    updated["count"] = len(filtered_items)
    updated["kept_row_count"] = len(filtered_items)
    updated["filtered_row_count"] = int(result.get("filtered_row_count") or 0) + filtered_out_count
    updated["filter_summary"] = dict(filter_summary)
    updated["filtered_examples"] = target_filtered_examples[:8]
    updated["target_hotel_names"] = normalized_targets
    updated["matched_target_hotel_names"] = [name for name in normalized_targets if name in matched_targets]
    updated["missing_target_hotel_names"] = [name for name in normalized_targets if name not in matched_targets]
    updated["target_filtered_out_count"] = filtered_out_count
    return updated


def _annotate_collection_result_target_matches(result: dict, *, target_hotel_names: list[str] | None) -> dict:
    normalized_targets = parse_target_hotel_names(target_hotel_names)
    updated = dict(result)
    if not normalized_targets:
        updated["target_hotel_names"] = []
        updated["matched_target_hotel_names"] = []
        updated["missing_target_hotel_names"] = []
        updated["target_match_items"] = []
        return updated

    original_items = result.get("items") if isinstance(result.get("items"), list) else []
    matched_targets: set[str] = set()
    target_match_items: list[dict] = []

    for target_name in normalized_targets:
        matched_item = None
        for item in original_items:
            if not isinstance(item, dict):
                continue
            if _match_target_hotel_name_for_item(item, target_name=target_name):
                matched_item = item
                matched_targets.add(target_name)
                break
        if matched_item is None:
            continue

        signals = matched_item.get("signals") if isinstance(matched_item.get("signals"), dict) else {}
        price_signals = signals.get("price_signals") if isinstance(signals.get("price_signals"), list) else []
        target_match_items.append(
            {
                "target_name": target_name,
                "matched_name": str(matched_item.get("name") or "").strip(),
                "price": price_signals[0] if price_signals else "",
                "url": str(matched_item.get("url") or "").strip(),
            }
        )

    updated["target_hotel_names"] = normalized_targets
    updated["matched_target_hotel_names"] = [name for name in normalized_targets if name in matched_targets]
    updated["missing_target_hotel_names"] = [name for name in normalized_targets if name not in matched_targets]
    updated["target_match_items"] = target_match_items
    return updated


def _fliggy_guest_state_dir() -> Path:
    path = Path(__file__).resolve().parents[2] / ".playwright" / "fliggy_guest_states"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_storage_state_name(raw_name: str | None, *, shop_id: int) -> str:
    value = str(raw_name or "").strip() or f"guest-shop-{shop_id}.json"
    value = _STORAGE_NAME_PATTERN.sub("-", value)
    if not value.endswith(".json"):
        value += ".json"
    return value


def _normalize_guest_selector_map(raw_value: dict | str | None) -> dict[str, list[str]]:
    merged = {key: list(values) for key, values in _DEFAULT_FLIGGY_GUEST_SELECTOR_MAP.items()}
    if raw_value in (None, "", {}):
        return merged
    payload = raw_value if not isinstance(raw_value, str) else json.loads(raw_value)
    if not isinstance(payload, dict):
        return merged
    for key, value in payload.items():
        if isinstance(value, str):
            candidates = [value.strip()] if value.strip() else []
        elif isinstance(value, list):
            candidates = [str(item).strip() for item in value if str(item).strip()]
        else:
            continue
        if candidates:
            merged[str(key)] = candidates
    return merged


def _guest_body_text(page) -> str:
    try:
        return str(page.locator("body").inner_text(timeout=1500) or "").strip()
    except Exception:
        return ""


def _has_any_selector(page, selectors: list[str]) -> bool:
    for selector in selectors:
        try:
            if page.locator(selector).first.count() > 0:
                return True
        except Exception:
            continue
    return False


def _wait_for_any_selector(page, selectors: list[str], *, timeout_ms: int) -> bool:
    for selector in selectors:
        try:
            page.locator(selector).first.wait_for(state="visible", timeout=timeout_ms)
            return True
        except Exception:
            continue
    return False


def _fill_first(page, selectors: list[str], value: str) -> bool:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0:
                locator.fill(value, timeout=2000)
                return True
        except Exception:
            continue
    return False


def _click_first(page, selectors: list[str]) -> bool:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0:
                locator.click(timeout=2000)
                return True
        except Exception:
            continue
    return False


def _first_non_javascript_href(page, selectors: list[str]) -> str:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() == 0:
                continue
            href = str(locator.get_attribute("href") or "").strip()
            if href and not href.lower().startswith("javascript"):
                return href
        except Exception:
            continue
    return ""


def _open_fliggy_guest_login_entry(page, selectors: dict[str, list[str]], *, login_url: str, wait_ms: int) -> bool:
    if not _is_fliggy_home_or_root_url(login_url):
        return False
    if _has_any_selector(page, selectors.get("password", [])):
        return False

    current_url = str(getattr(page, "url", "") or "")
    opened = _click_first(page, selectors.get("entry", []))
    if opened:
        try:
            page.wait_for_timeout(wait_ms)
            page.wait_for_load_state("domcontentloaded", timeout=max(3000, wait_ms * 4))
        except Exception:
            pass
        next_url = str(getattr(page, "url", "") or "")
        if next_url != current_url or _has_any_selector(page, selectors.get("password", [])):
            return True
        if _looks_like_fliggy_guest_login_page(page, selectors, login_url=login_url):
            return True

    direct_login_url = _first_non_javascript_href(page, selectors.get("entry", []))
    if not direct_login_url:
        return opened
    try:
        page.goto(direct_login_url, timeout=max(3000, wait_ms * 4), wait_until="domcontentloaded")
        page.wait_for_timeout(wait_ms)
        return True
    except Exception:
        return opened


def _looks_like_fliggy_guest_login_page(page, selectors: dict[str, list[str]], *, login_url: str = "") -> bool:
    current_url = str(getattr(page, "url", "") or "").lower()
    normalized_login_url = str(login_url or "").strip().lower().rstrip("/")
    body_text = _guest_body_text(page)
    if normalized_login_url and not _is_fliggy_home_or_root_url(normalized_login_url) and current_url.startswith(normalized_login_url):
        return True
    if "login" in current_url or "passport" in current_url:
        return True
    if _has_any_selector(page, selectors.get("password", [])) and _has_any_selector(page, selectors.get("submit", [])):
        return True
    return any(hint in body_text for hint in _FLIGGY_GUEST_LOGIN_HINTS)


def _get_cookie_names(target) -> set[str]:
    try:
        if target is None or not hasattr(target, "cookies"):
            return set()
        cookies = target.cookies()
    except Exception:
        return set()

    names: set[str] = set()
    for item in cookies:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().lower()
        if name:
            names.add(name)
    return names


def _get_page_cookie_names(page) -> set[str]:
    try:
        context = getattr(page, "context", None)
        if callable(context):
            context = context()
    except Exception:
        context = None
    return _get_cookie_names(context)


def _has_fliggy_auth_cookie(target) -> bool:
    return bool(_get_cookie_names(target) & _FLIGGY_GUEST_AUTH_COOKIE_NAMES)


def _is_fliggy_guest_authenticated(page, selectors: dict[str, list[str]], *, login_url: str = "") -> bool:
    if _looks_like_fliggy_guest_login_page(page, selectors, login_url=login_url):
        return False

    if _get_page_cookie_names(page) & _FLIGGY_GUEST_AUTH_COOKIE_NAMES:
        return True

    if _has_any_selector(page, selectors.get("success", [])) and not _has_any_selector(page, selectors.get("entry", [])):
        return True

    body_text = _guest_body_text(page)
    return "\u9000\u51fa\u767b\u5f55" in body_text or "\u6b22\u8fce\u56de\u6765" in body_text


def _resolve_fliggy_guest_context(db: Session, *, shop_id: int) -> dict:
    shop_config = get_shop_config(db=db, shop_id=shop_id)
    tenant_id = int(getattr(shop_config, "tenant_id", 1) or 1)
    credential = get_merchant_credential(
        db=db,
        shop_id=shop_id,
        tenant_id=tenant_id,
        platform=_FLIGGY_GUEST_PLATFORM,
    )
    login_url = str(credential.get("login_url") or _FLIGGY_GUEST_DEFAULT_LOGIN_URL).strip() or _FLIGGY_GUEST_DEFAULT_LOGIN_URL
    start_url = normalize_fliggy_guest_start_url(
        str(credential.get("price_url") or _FLIGGY_GUEST_DEFAULT_START_URL).strip() or _FLIGGY_GUEST_DEFAULT_START_URL
    )
    return {
        "credential": credential,
        "login_url": login_url,
        "start_url": start_url,
        "storage_state_name": str(credential.get("storage_state_name") or "").strip(),
        "selectors": credential.get("selectors") if credential.get("has_selectors") else None,
    }


def _try_record_guest_login_result(db: Session | None, *, shop_id: int, status: str, message: str) -> None:
    if db is None:
        return None
    try:
        record_merchant_login_result(
            db=db,
            shop_id=shop_id,
            platform=_FLIGGY_GUEST_PLATFORM,
            status=status,
            message=message,
        )
    except Exception:
        return None


def login_fliggy_guest_session(
    db: Session,
    *,
    shop_id: int,
    login_url: str | None = None,
    start_url: str | None = None,
    username: str = "",
    password: str = "",
    storage_state_name: str | None = None,
    selectors: dict | str | None = None,
    headless: bool = False,
) -> dict:
    context_data = _resolve_fliggy_guest_context(db=db, shop_id=shop_id)
    saved_credential = get_merchant_credential(db=db, shop_id=shop_id, platform=_FLIGGY_GUEST_PLATFORM, include_secret=True)
    resolved_login_url = str(login_url or context_data["login_url"] or _FLIGGY_GUEST_DEFAULT_LOGIN_URL).strip() or _FLIGGY_GUEST_DEFAULT_LOGIN_URL
    resolved_start_url = str(start_url or context_data["start_url"] or _FLIGGY_GUEST_DEFAULT_START_URL).strip() or _FLIGGY_GUEST_DEFAULT_START_URL
    resolved_username = str(username or saved_credential.get("username") or "").strip()
    resolved_password = str(password or saved_credential.get("password") or "")
    resolved_selectors = selectors if selectors not in (None, "") else context_data["selectors"]
    selector_map = _normalize_guest_selector_map(resolved_selectors)
    state_name = _safe_storage_state_name(storage_state_name or context_data["storage_state_name"], shop_id=shop_id)
    state_path = _fliggy_guest_state_dir() / state_name

    if resolved_username:
        save_merchant_credential(
            db=db,
            credential_data={
                "tenant_id": int(context_data["credential"].get("tenant_id") or 1),
                "shop_id": shop_id,
                "platform": _FLIGGY_GUEST_PLATFORM,
                "username": resolved_username,
                "password": resolved_password,
                "login_url": resolved_login_url,
                "price_url": resolved_start_url,
                "storage_state_name": state_name,
                "selectors": resolved_selectors,
            },
        )

    settings = get_settings()
    timeout_ms = max(5000, int(settings.fliggy_playwright_timeout_sec) * 1000)
    wait_ms = max(500, int(settings.fliggy_playwright_wait_after_load_ms))

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - env-dependent
        raise RuntimeError("playwright not installed. run: py -3 -m pip install playwright") from exc

    verified_by = ""
    with sync_playwright() as p:  # pragma: no cover - heavy integration
        try:
            browser = p.chromium.launch(headless=headless)
        except Exception as exc:
            raise RuntimeError("failed to launch chromium. run: py -3 -m playwright install chromium") from exc

        context = browser.new_context(user_agent=settings.competitor_crawl_user_agent)
        page = context.new_page()
        try:
            page.goto(resolved_login_url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(wait_ms)
            _open_fliggy_guest_login_entry(page, selector_map, login_url=resolved_login_url, wait_ms=wait_ms)
            if resolved_username and resolved_password:
                _wait_for_any_selector(page, selector_map.get("username", []), timeout_ms=min(timeout_ms, 8000))
                _wait_for_any_selector(page, selector_map.get("password", []), timeout_ms=min(timeout_ms, 8000))
                _fill_first(page, selector_map.get("username", []), resolved_username)
                _fill_first(page, selector_map.get("password", []), resolved_password)
                _click_first(page, selector_map.get("submit", []))
                try:
                    page.wait_for_timeout(wait_ms)
                    page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 8000))
                except PlaywrightTimeoutError:
                    pass

            deadline_ms = timeout_ms if headless else max(timeout_ms, 120000)
            start_at = datetime.now().timestamp()
            while True:
                if _has_fliggy_auth_cookie(context):
                    verified_by = "guest-auth-cookie"
                    break
                if _is_fliggy_guest_authenticated(page, selector_map, login_url=resolved_login_url):
                    verified_by = "guest-current-page"
                    break
                elapsed_ms = int((datetime.now().timestamp() - start_at) * 1000)
                if elapsed_ms >= deadline_ms:
                    _try_record_guest_login_result(db, shop_id=shop_id, status="failed", message="guest login not verified")
                    raise RuntimeError("guest login not verified")
                page.wait_for_timeout(min(wait_ms, 1500) if not headless else wait_ms)

            context.storage_state(path=str(state_path))
            _try_record_guest_login_result(db, shop_id=shop_id, status="success", message=verified_by)
        finally:
            browser.close()

    return {
        "shop_id": shop_id,
        "status": "success",
        "login_url": resolved_login_url,
        "start_url": resolved_start_url,
        "storage_state_path": str(state_path),
        "storage_state_name": state_name,
        "session_saved": True,
        "headless": headless,
        "verified_by": verified_by,
    }


def _collect_fliggy_rows_with_pagination(page, *, max_pages: int, max_hotels: int, wait_ms: int) -> tuple[list[dict], int, str, dict]:
    collected: list[dict] = []
    seen: set[str] = set()
    page_count = 0
    last_error = ""
    raw_row_count = 0
    filtered_row_count = 0
    filter_summary: Counter[str] = Counter()
    filtered_examples: list[dict] = []

    for _ in range(max_pages):
        page_count += 1
        extraction = _extract_fliggy_rows_from_page(page)
        rows = extraction.get('rows', []) if isinstance(extraction, dict) else []
        raw_row_count += int(extraction.get('raw_row_count') or 0) if isinstance(extraction, dict) else 0
        filtered_row_count += int(extraction.get('filtered_row_count') or 0) if isinstance(extraction, dict) else 0
        if isinstance(extraction, dict) and isinstance(extraction.get('filter_summary'), dict):
            filter_summary.update({str(key): int(value) for key, value in extraction['filter_summary'].items()})
        if isinstance(extraction, dict) and isinstance(extraction.get('filtered_examples'), list):
            for example in extraction['filtered_examples']:
                if len(filtered_examples) >= 8:
                    break
                if isinstance(example, dict):
                    filtered_examples.append(example)
        for row in rows:
            key = f"{row.get('hotel_name')}|{row.get('price')}|{row.get('url')}"
            if key in seen:
                continue
            seen.add(key)
            collected.append(row)
            if len(collected) >= max_hotels:
                break
        if len(collected) >= max_hotels:
            break

        next_button = page.locator(
            "a:has-text('\u4e0b\u4e00\u9875'),button:has-text('\u4e0b\u4e00\u9875'),[class*='next'],[aria-label*='\u4e0b\u4e00']"
        ).first
        if next_button.count() == 0:
            break
        try:
            if hasattr(next_button, 'is_visible') and not next_button.is_visible():
                break
        except Exception:
            break
        try:
            next_button.click(timeout=5000)
            page.wait_for_timeout(wait_ms)
        except Exception as exc:
            if exc.__class__.__name__ == 'TimeoutError':
                break
            last_error = str(exc)
            break

    return collected, page_count, last_error, {
        'raw_row_count': raw_row_count,
        'filtered_row_count': filtered_row_count,
        'filter_summary': dict(filter_summary),
        'filtered_examples': filtered_examples[:8],
    }


def _iter_browser_pages(browser) -> list:
    contexts = getattr(browser, "contexts", [])
    if callable(contexts):
        contexts = contexts()
    pages: list = []
    for context in contexts or []:
        context_pages = getattr(context, "pages", [])
        if callable(context_pages):
            context_pages = context_pages()
        for page in context_pages or []:
            pages.append(page)
    return pages


def _is_active_browser_page(page) -> bool:
    try:
        return str(page.evaluate("() => document.visibilityState") or "").lower() == "visible"
    except Exception:
        return False


def _pick_fliggy_cdp_target_page(browser, *, target_page_url_keyword: str = ""):
    normalized_keyword = str(target_page_url_keyword or "").strip().lower()
    all_matches = []
    keyword_matches = []
    for page in _iter_browser_pages(browser):
        current_url = str(getattr(page, "url", "") or "").strip()
        if not _looks_like_fliggy_hotel_list_url(current_url):
            continue
        all_matches.append(page)
        if normalized_keyword and normalized_keyword not in current_url.lower():
            continue
        keyword_matches.append(page)

    matches = keyword_matches or all_matches
    if not matches:
        raise RuntimeError("no fliggy hotel list page found in chrome debug session")

    for page in matches:
        if _is_active_browser_page(page):
            return page
    return matches[0]

def _collect_fliggy_hotel_prices_via_cdp(
    *,
    shop_id: int,
    start_url: str,
    max_pages: int,
    max_hotels: int,
    debug_url: str,
    target_page_url_keyword: str = "",
    login_url: str | None = None,
    selectors: dict | str | None = None,
) -> dict:
    selector_map = _normalize_guest_selector_map(selectors)
    settings = get_settings()
    timeout_ms = max(5000, int(settings.fliggy_playwright_timeout_sec) * 1000)
    wait_ms = max(500, int(settings.fliggy_playwright_wait_after_load_ms))
    resolved_debug_url = str(debug_url or "").strip() or _FLIGGY_CDP_DEFAULT_DEBUG_URL
    resolved_start_url = normalize_fliggy_guest_start_url(start_url)

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - env-dependent
        raise RuntimeError("playwright not installed. run: py -3 -m pip install playwright") from exc

    matched_page_url = ""
    with sync_playwright() as p:  # pragma: no cover - heavy integration
        try:
            browser = p.chromium.connect_over_cdp(resolved_debug_url)
        except Exception as exc:
            raise RuntimeError(f"failed to connect chromium debug url: {resolved_debug_url}") from exc

        page = _pick_fliggy_cdp_target_page(browser, target_page_url_keyword=target_page_url_keyword)
        matched_page_url = str(getattr(page, "url", "") or "").strip()
        if _should_navigate_fliggy_cdp_page(current_url=matched_page_url, start_url=resolved_start_url):
            page.goto(resolved_start_url, timeout=timeout_ms, wait_until="domcontentloaded")
            matched_page_url = str(getattr(page, "url", "") or "").strip()
        try:
            page.wait_for_timeout(wait_ms)
            page.wait_for_load_state("domcontentloaded", timeout=min(timeout_ms, 8000))
        except Exception:
            pass
        if _looks_like_fliggy_guest_login_page(page, selector_map, login_url=str(login_url or "")):
            raise RuntimeError("connected page is login page, please open a logged-in fliggy hotel list page")
        collected, page_count, last_error, stats = _collect_fliggy_rows_with_pagination(
            page,
            max_pages=max_pages,
            max_hotels=max_hotels,
            wait_ms=wait_ms,
        )

    result = _build_collection_result_from_fliggy_rows(
        shop_id=shop_id,
        start_url=matched_page_url or resolved_start_url,
        rows=collected,
        stats=stats,
    )
    result["meta"] = {
        "source": "fliggy_playwright_cdp",
        "page_count": page_count,
        "captured_hotels": len(collected),
    }
    result["matched_page_url"] = matched_page_url
    result["debug_url"] = resolved_debug_url
    if target_page_url_keyword:
        result["target_page_url_keyword"] = target_page_url_keyword
    if last_error:
        result["meta"]["last_error"] = last_error
    return result


def _collect_fliggy_hotel_prices_playwright_once(
    *,
    shop_id: int,
    start_url: str,
    max_pages: int,
    max_hotels: int,
    headless: bool,
    storage_state_path: Path | None = None,
    login_url: str | None = None,
    selectors: dict | str | None = None,
) -> dict:
    if not start_url.startswith(("http://", "https://")):
        raise ValueError("start_url must start with http:// or https://")
    if _is_fliggy_home_or_root_url(start_url):
        raise ValueError("start_url must be a Fliggy hotel search/list page with visible prices, not the homepage https://hotel.fliggy.com/")

    selector_map = _normalize_guest_selector_map(selectors)
    settings = get_settings()
    timeout_ms = max(5000, int(settings.fliggy_playwright_timeout_sec) * 1000)
    wait_ms = max(500, int(settings.fliggy_playwright_wait_after_load_ms))

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - env-dependent
        raise RuntimeError("playwright not installed. run: py -3 -m pip install playwright") from exc

    with sync_playwright() as p:  # pragma: no cover - heavy integration
        try:
            browser = p.chromium.launch(headless=headless)
        except Exception as exc:
            raise RuntimeError("failed to launch chromium. run: py -3 -m playwright install chromium") from exc

        context_kwargs = {"user_agent": settings.competitor_crawl_user_agent}
        if storage_state_path is not None and storage_state_path.exists():
            context_kwargs["storage_state"] = str(storage_state_path)
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        try:
            page.goto(start_url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(wait_ms)
            if _looks_like_fliggy_guest_login_page(page, selector_map, login_url=str(login_url or "")):
                if storage_state_path is not None and storage_state_path.exists():
                    raise RuntimeError("guest session expired, login required")
                raise RuntimeError("guest session not found, login first")
            collected, page_count, last_error, stats = _collect_fliggy_rows_with_pagination(
                page,
                max_pages=max_pages,
                max_hotels=max_hotels,
                wait_ms=wait_ms,
            )
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(f"playwright timeout: {exc}") from exc
        finally:
            context.close()
            browser.close()

    result = _build_collection_result_from_fliggy_rows(shop_id=shop_id, start_url=start_url, rows=collected, stats=stats)
    result["meta"] = {
        "source": "fliggy_playwright",
        "page_count": page_count,
        "captured_hotels": len(collected),
    }
    if storage_state_path is not None and storage_state_path.exists():
        result["storage_state_used"] = storage_state_path.name
    if last_error:
        result["meta"]["last_error"] = last_error
    return result


def collect_fliggy_hotel_prices_playwright(
    *,
    shop_id: int,
    start_url: str,
    max_pages: int,
    max_hotels: int,
    headless: bool,
    db: Session | None = None,
    collect_mode: str = _FLIGGY_COLLECT_MODE_CDP_CURRENT_PAGE,
    debug_url: str | None = None,
    target_page_url_keyword: str = "",
    target_hotel_names: list[str] | None = None,
    runtime_settings: dict | None = None,
    login_url: str | None = None,
    storage_state_name: str | None = None,
    username: str = "",
    password: str = "",
    login_headless: bool = False,
    auto_login: bool = False,
    save_credential: bool = True,
    selectors: dict | str | None = None,
) -> dict:
    """Collect Fliggy hotel price rows by attaching to the user's logged-in browser page."""
    resolved_collect_mode = _normalize_fliggy_collect_mode(collect_mode)
    resolved_start_url = normalize_fliggy_guest_start_url(str(start_url or "").strip())
    resolved_login_url = str(login_url or "").strip()
    resolved_debug_url = str(debug_url or "").strip() or _FLIGGY_CDP_DEFAULT_DEBUG_URL
    resolved_target_page_url_keyword = str(target_page_url_keyword or "").strip()
    resolved_target_hotel_names = parse_target_hotel_names(target_hotel_names)
    resolved_runtime_settings = runtime_settings if isinstance(runtime_settings, dict) else {}
    resolved_selectors = selectors
    credential_saved = False

    if db is not None:
        context_data = _resolve_fliggy_guest_context(db=db, shop_id=shop_id)
        resolved_start_url = normalize_fliggy_guest_start_url(
            resolved_start_url or str(context_data["start_url"] or "").strip() or _FLIGGY_GUEST_DEFAULT_START_URL
        )
        resolved_login_url = resolved_login_url or str(context_data["login_url"] or "").strip() or resolved_start_url
        resolved_selectors = resolved_selectors if resolved_selectors not in (None, "") else context_data["selectors"]
        stored_target_hotel_names = []
        if isinstance(context_data.get("selectors"), dict):
            stored_target_hotel_names = parse_target_hotel_names(context_data["selectors"].get("target_hotel_names"))
        if not resolved_target_hotel_names:
            resolved_target_hotel_names = stored_target_hotel_names
        if isinstance(resolved_selectors, str):
            try:
                resolved_selectors = json.loads(resolved_selectors)
            except json.JSONDecodeError:
                resolved_selectors = {}
        elif not isinstance(resolved_selectors, dict):
            resolved_selectors = {}
        if resolved_target_hotel_names:
            resolved_selectors["target_hotel_names"] = resolved_target_hotel_names
        else:
            resolved_selectors.pop("target_hotel_names", None)
        for key, value in resolved_runtime_settings.items():
            if value in (None, '', [], {}):
                resolved_selectors.pop(str(key), None)
                continue
            resolved_selectors[str(key)] = value
        if save_credential:
            save_merchant_credential(
                db=db,
                credential_data={
                    "tenant_id": int(context_data["credential"].get("tenant_id") or 1),
                    "shop_id": shop_id,
                    "platform": _FLIGGY_GUEST_PLATFORM,
                    "username": "",
                    "password": "",
                    "login_url": resolved_login_url,
                    "price_url": resolved_start_url,
                    "storage_state_name": "",
                    "selectors": resolved_selectors,
                },
            )
            credential_saved = True
    else:
        resolved_start_url = normalize_fliggy_guest_start_url(resolved_start_url or _FLIGGY_GUEST_DEFAULT_START_URL)

    result = _collect_fliggy_hotel_prices_via_cdp(
        shop_id=shop_id,
        start_url=resolved_start_url,
        max_pages=max_pages,
        max_hotels=max_hotels,
        debug_url=resolved_debug_url,
        target_page_url_keyword=resolved_target_page_url_keyword,
        login_url=resolved_login_url,
        selectors=resolved_selectors,
    )
    result = _filter_collection_result_by_target_hotels(result, target_hotel_names=resolved_target_hotel_names)
    result["collect_mode"] = resolved_collect_mode
    result["target_hotel_names"] = resolved_target_hotel_names
    result["auto_login_performed"] = False
    result["credential_saved"] = credential_saved
    result["public_access_fallback"] = False
    return result


def collect_fliggy_hotel_prices_from_extension_page(
    *,
    shop_id: int,
    start_url: str,
    max_hotels: int,
    target_hotel_names: list[str] | None = None,
    page_snapshot: dict | None = None,
) -> dict:
    resolved_start_url = normalize_fliggy_guest_start_url(str(start_url or "").strip())
    snapshot = page_snapshot if isinstance(page_snapshot, dict) else {}
    candidate_rows = snapshot.get("candidate_rows") if isinstance(snapshot.get("candidate_rows"), list) else []

    normalized_targets = parse_target_hotel_names(target_hotel_names)
    warning_message = _build_page_target_city_warning(page_snapshot=snapshot, target_hotel_names=normalized_targets)

    normalized: list[dict] = []
    filtered_examples: list[dict] = []
    filter_summary: Counter[str] = Counter()
    seen: set[str] = set()
    raw_row_count = 0

    for row in candidate_rows:
        if not isinstance(row, dict):
            continue
        raw_text = _clean_fliggy_candidate_text(row.get("text") or "")
        if not raw_text:
            continue
        raw_row_count += 1
        explicit_price = row.get("price")
        try:
            price = round(float(explicit_price), 2) if explicit_price not in (None, "") else None
        except (TypeError, ValueError):
            price = None
        if price is None or price <= 0:
            price = _extract_fliggy_price_from_text(raw_text)
        if price is None:
            continue
        raw_name = _clean_fliggy_candidate_text(row.get("name") or "")
        if not raw_name:
            raw_lines = _split_fliggy_candidate_lines(row.get("text") or "")
            raw_name = raw_lines[0] if raw_lines else ""
        name = _normalize_fliggy_hotel_name(raw_name) or raw_name
        href = _clean_fliggy_candidate_text(row.get("href") or "")
        keep, reason = _looks_like_fliggy_hotel_card(name=name, raw_text=raw_text, href=href)
        if not keep and _row_matches_target_hotel_names(
            name=name,
            raw_text=raw_text,
            href=href,
            target_hotel_names=normalized_targets,
        ):
            keep = True
            reason = "target_hotel_hint"
        if not keep:
            filter_summary[reason] += 1
            if len(filtered_examples) < 8:
                filtered_examples.append(
                    {
                        "name": name or "unknown",
                        "price": price,
                        "url": href,
                        "reason": reason,
                        "raw_text": raw_text[:240],
                    }
                )
            continue
        key = f"{name}|{price:.2f}|{href}"
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "hotel_name": name or "unknown",
                "price": price,
                "url": href,
                "raw_text": raw_text[:500],
            }
        )

    result = _build_collection_result_from_fliggy_rows(
        shop_id=shop_id,
        start_url=resolved_start_url,
        rows=normalized,
        stats={
            "raw_row_count": raw_row_count,
            "filtered_row_count": sum(filter_summary.values()),
            "filter_summary": dict(filter_summary),
            "filtered_examples": filtered_examples,
        },
    )
    result = _annotate_collection_result_target_matches(result, target_hotel_names=normalized_targets)
    result["collect_mode"] = "extension_page"
    result["target_hotel_names"] = normalized_targets
    if warning_message:
        result["warning_message"] = warning_message
    result["matched_page_url"] = resolved_start_url
    result["meta"] = {
        "source": "fliggy_extension",
        "page_count": 1,
        "captured_hotels": len(result.get("items") or []),
        "candidate_row_count": raw_row_count,
    }
    for item in result.get("items") or []:
        if not isinstance(item, dict):
            continue
        item["note"] = "fliggy_extension"
        item["analysis_source"] = "extension_page"
        analysis = item.get("analysis") if isinstance(item.get("analysis"), dict) else {}
        item["analysis"] = {
            **analysis,
            "summary": "extension_page_capture",
        }
    return result

def build_competitor_snapshot_rows(*, shop_id: int, result: dict, source: str) -> list[dict]:
    """Build normalized rows for DB persistence from collection result."""
    rows: list[dict] = []
    collected_at = str(result.get("collected_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    items = result.get("items", [])
    if not isinstance(items, list):
        return rows

    for item in items:
        if not isinstance(item, dict):
            continue
        analysis = item.get("analysis") if isinstance(item.get("analysis"), dict) else {}
        signals = item.get("signals") if isinstance(item.get("signals"), dict) else {}
        price_signals = signals.get("price_signals") if isinstance(signals.get("price_signals"), list) else []
        promotion_signals = analysis.get("promotion_signals") if isinstance(analysis.get("promotion_signals"), list) else []
        risk_notes = analysis.get("risk_notes") if isinstance(analysis.get("risk_notes"), list) else []

        rows.append(
            {
                "shop_id": int(shop_id),
                "target_name": str(item.get("name") or "unknown")[:128],
                "target_url": str(item.get("url") or "")[:1024],
                "fetch_status": str(item.get("fetch_status") or "unknown")[:32],
                "analysis_source": str(item.get("analysis_source") or "heuristic")[:32],
                "price_signal_count": len(price_signals),
                "promotion_signal_count": len(promotion_signals),
                "risk_note_count": len(risk_notes),
                "signals_json": json.dumps(signals, ensure_ascii=False),
                "analysis_json": json.dumps(analysis, ensure_ascii=False),
                "openclaw_error": str(item.get("openclaw_error") or "")[:500],
                "collected_at": collected_at,
                "source": str(source or "manual")[:_COMPETITOR_SNAPSHOT_SOURCE_MAX_LEN],
            }
        )
    return rows


def _ensure_competitor_snapshot_column_compat(db: Session) -> None:
    """Upgrade existing competitor_snapshots columns when older schemas are too narrow."""
    try:
        columns = db.execute(text("SHOW COLUMNS FROM competitor_snapshots")).mappings().all()
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc

    source_type = ""
    for column in columns:
        field_name = str(column.get("Field") or "").strip().lower()
        if field_name == "source":
            source_type = str(column.get("Type") or "").strip().lower()
            break

    match = re.match(r"varchar\((\d+)\)", source_type)
    if match and int(match.group(1)) >= _COMPETITOR_SNAPSHOT_SOURCE_MAX_LEN:
        return

    try:
        db.execute(
            text(
                f"""
                ALTER TABLE competitor_snapshots
                MODIFY COLUMN source VARCHAR({_COMPETITOR_SNAPSHOT_SOURCE_MAX_LEN}) NOT NULL DEFAULT 'manual'
                """
            )
        )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError(str(exc)) from exc


def ensure_competitor_tables(db: Session) -> None:
    """Ensure competitor snapshot table exists."""
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS competitor_snapshots (
              id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
              shop_id BIGINT UNSIGNED NOT NULL,
              target_name VARCHAR(128) NOT NULL,
              target_url VARCHAR(1024) NOT NULL,
              fetch_status VARCHAR(32) NOT NULL DEFAULT 'unknown',
              analysis_source VARCHAR(32) NOT NULL DEFAULT 'heuristic',
              price_signal_count INT UNSIGNED NOT NULL DEFAULT 0,
              promotion_signal_count INT UNSIGNED NOT NULL DEFAULT 0,
              risk_note_count INT UNSIGNED NOT NULL DEFAULT 0,
              signals_json JSON NULL,
              analysis_json JSON NULL,
              openclaw_error VARCHAR(500) NULL,
              source VARCHAR(32) NOT NULL DEFAULT 'manual',
              collected_at DATETIME NOT NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (id),
              KEY idx_comp_snap_shop_time (shop_id, collected_at),
              KEY idx_comp_snap_shop_target_time (shop_id, target_name, collected_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    )
    _ensure_competitor_snapshot_column_compat(db)


def save_competitor_collection(db: Session, *, shop_id: int, result: dict, source: str = "manual") -> dict:
    """Persist competitor collection result into DB."""
    rows = build_competitor_snapshot_rows(shop_id=shop_id, result=result, source=source)
    if not rows:
        return {"saved_count": 0}

    try:
        ensure_competitor_tables(db)
        for row in rows:
            db.execute(
                text(
                    """
                    INSERT INTO competitor_snapshots
                    (shop_id, target_name, target_url, fetch_status, analysis_source,
                     price_signal_count, promotion_signal_count, risk_note_count,
                     signals_json, analysis_json, openclaw_error, source, collected_at)
                    VALUES
                    (:shop_id, :target_name, :target_url, :fetch_status, :analysis_source,
                     :price_signal_count, :promotion_signal_count, :risk_note_count,
                     :signals_json, :analysis_json, :openclaw_error, :source, :collected_at)
                    """
                ),
                row,
            )
        db.commit()
        return {"saved_count": len(rows)}
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError(str(exc)) from exc


def get_latest_competitor_prices(db: Session, *, shop_id: int, limit: int = 100) -> dict:
    """Get the latest competitor prices, deduplicated by hotel name (most recent first)."""
    ensure_competitor_tables(db)
    try:
        rows = db.execute(
            text(
                """
                SELECT target_name, target_url, signals_json, collected_at, source
                FROM competitor_snapshots
                WHERE shop_id = :shop_id AND fetch_status = 'success'
                ORDER BY collected_at DESC
                LIMIT :limit
                """
            ),
            {"shop_id": shop_id, "limit": limit},
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc

    seen: set[str] = set()
    hotels: list[dict] = []
    latest_time = ""

    for row in rows:
        name = str(row["target_name"])
        if name in seen:
            continue
        seen.add(name)

        signals: dict = {}
        raw = row["signals_json"]
        if isinstance(raw, str) and raw.strip():
            try:
                signals = json.loads(raw)
            except json.JSONDecodeError:
                pass
        elif isinstance(raw, dict):
            signals = raw

        price_signals = signals.get("price_signals", [])
        price: float | None = None
        for ps in price_signals:
            price = _extract_fliggy_price_from_text(str(ps))
            if price is not None:
                break

        collected_at = str(row["collected_at"])
        if not latest_time:
            latest_time = collected_at

        hotels.append({
            "hotel_name": name,
            "url": str(row["target_url"]),
            "price": price,
            "price_signals": price_signals[:5],
            "collected_at": collected_at,
            "source": str(row["source"]),
        })

    return {
        "shop_id": shop_id,
        "count": len(hotels),
        "latest_collected_at": latest_time,
        "hotels": hotels,
    }


def get_competitor_trends(
    db: Session,
    *,
    shop_id: int,
    days: int = 7,
    target_name: str | None = None,
    limit: int = 200,
) -> dict:
    """Query competitor historical trends and latest snapshots."""
    if days < 1 or days > 90:
        raise ValueError("days must be between 1 and 90")
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")

    target = (target_name or "").strip()
    try:
        ensure_competitor_tables(db)
        if target:
            trend_rows = db.execute(
                text(
                    """
                    SELECT
                      DATE(collected_at) AS day,
                      target_name,
                      COUNT(*) AS sample_count,
                      SUM(CASE WHEN fetch_status = 'success' THEN 1 ELSE 0 END) AS success_count,
                      AVG(price_signal_count) AS avg_price_signal_count,
                      AVG(promotion_signal_count) AS avg_promotion_signal_count,
                      SUM(CASE WHEN analysis_source = 'openclaw' THEN 1 ELSE 0 END) AS openclaw_count
                    FROM competitor_snapshots
                    WHERE shop_id = :shop_id
                      AND target_name = :target_name
                      AND collected_at >= DATE_SUB(NOW(), INTERVAL :days DAY)
                    GROUP BY DATE(collected_at), target_name
                    ORDER BY day DESC
                    LIMIT :limit
                    """
                ),
                {"shop_id": shop_id, "target_name": target, "days": days, "limit": limit},
            ).mappings().all()

            latest_rows = db.execute(
                text(
                    """
                    SELECT
                      id, target_name, target_url, fetch_status, analysis_source,
                      price_signal_count, promotion_signal_count, risk_note_count,
                      source, collected_at
                    FROM competitor_snapshots
                    WHERE shop_id = :shop_id
                      AND target_name = :target_name
                    ORDER BY collected_at DESC
                    LIMIT :limit
                    """
                ),
                {"shop_id": shop_id, "target_name": target, "limit": min(limit, 100)},
            ).mappings().all()
        else:
            trend_rows = db.execute(
                text(
                    """
                    SELECT
                      DATE(collected_at) AS day,
                      target_name,
                      COUNT(*) AS sample_count,
                      SUM(CASE WHEN fetch_status = 'success' THEN 1 ELSE 0 END) AS success_count,
                      AVG(price_signal_count) AS avg_price_signal_count,
                      AVG(promotion_signal_count) AS avg_promotion_signal_count,
                      SUM(CASE WHEN analysis_source = 'openclaw' THEN 1 ELSE 0 END) AS openclaw_count
                    FROM competitor_snapshots
                    WHERE shop_id = :shop_id
                      AND collected_at >= DATE_SUB(NOW(), INTERVAL :days DAY)
                    GROUP BY DATE(collected_at), target_name
                    ORDER BY day DESC
                    LIMIT :limit
                    """
                ),
                {"shop_id": shop_id, "days": days, "limit": limit},
            ).mappings().all()

            latest_rows = db.execute(
                text(
                    """
                    SELECT
                      id, target_name, target_url, fetch_status, analysis_source,
                      price_signal_count, promotion_signal_count, risk_note_count,
                      source, collected_at
                    FROM competitor_snapshots
                    WHERE shop_id = :shop_id
                    ORDER BY collected_at DESC
                    LIMIT :limit
                    """
                ),
                {"shop_id": shop_id, "limit": min(limit, 100)},
            ).mappings().all()

        trend = []
        for row in trend_rows:
            trend.append(
                {
                    "day": str(row["day"]),
                    "target_name": row["target_name"],
                    "sample_count": int(row["sample_count"] or 0),
                    "success_count": int(row["success_count"] or 0),
                    "avg_price_signal_count": float(row["avg_price_signal_count"] or 0),
                    "avg_promotion_signal_count": float(row["avg_promotion_signal_count"] or 0),
                    "openclaw_count": int(row["openclaw_count"] or 0),
                }
            )

        latest = []
        for row in latest_rows:
            latest.append(
                {
                    "id": int(row["id"]),
                    "target_name": row["target_name"],
                    "target_url": row["target_url"],
                    "fetch_status": row["fetch_status"],
                    "analysis_source": row["analysis_source"],
                    "price_signal_count": int(row["price_signal_count"] or 0),
                    "promotion_signal_count": int(row["promotion_signal_count"] or 0),
                    "risk_note_count": int(row["risk_note_count"] or 0),
                    "source": row["source"],
                    "collected_at": str(row["collected_at"]),
                }
            )

        return {
            "shop_id": shop_id,
            "days": days,
            "target_name": target or None,
            "trend": trend,
            "latest": latest,
        }
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Room-type level crawling (hotel detail page)
# ---------------------------------------------------------------------------

_FLIGGY_ROOM_JS = """
() => {
  const rooms = [];
  const roomSelectors =
    'h1,h2,h3,h4,h5,[class*="type"],[class*="Type"],'
    + '[class*="name"],[class*="Name"],[class*="title"],[class*="Title"],'
    + '[class*="room-type"],[class*="roomType"],[class*="room_type"]';
  const rateSelectors =
    '[class*="rate"],[class*="Rate"],[class*="plan"],[class*="Plan"],'
    + '[class*="policy"],[class*="Policy"],[class*="sale"],[class*="Sale"],'
    + '[class*="product"],[class*="Product"],[class*="bed"],[class*="Bed"]';

  const normalize = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const splitLines = (value) => {
    const seen = new Set();
    return String(value || '')
      .split('\\n')
      .map((line) => normalize(line))
      .filter((line) => {
        if (!line || seen.has(line)) {
          return false;
        }
        seen.add(line);
        return true;
      });
  };
  const isPriceLine = (value) => /[¥￥]\s*(\d+(?:\.\d{1,2})?)/.test(value);
  const isActionLine = (value) => /^(预订|预定|在线付|在线预付|立即预订|去预订|查看详情|房型详情|更多|套餐详情|选择|地图|评论|评分)$/.test(value);
  const isMetaOnlyLine = (value) => /^(含早|无早|不含早|双早|单早|可取消|不可取消|不可退|免费取消|到店付|在线付|担保|预付|现付)$/.test(value);
  const isValidLabel = (value) => value.length >= 2 && value.length <= 40 && !isPriceLine(value) && !/^\d+$/.test(value) && !isActionLine(value);
  const looksLikeRateName = (value) => /(标准价|会员价|连住|套餐|优惠|特惠|大促|限时|取消|含早|无早|双早|单早|预付|现付|到店付|担保|礼包|礼遇|房费)$/.test(value);

  const pickText = (root, selector) => normalize(root.querySelector(selector)?.innerText || '');

  const extractRoomType = (row, lines) => {
    const named = pickText(row, roomSelectors).split('\\n')[0].trim();
    if (isValidLabel(named)) {
      return named;
    }
    for (const line of lines) {
      if (isValidLabel(line) && !looksLikeRateName(line) && !isMetaOnlyLine(line)) {
        return line;
      }
    }
    return lines.find((line) => isValidLabel(line)) || '';
  };

  const extractRateName = (row, lines, roomType) => {
    const named = pickText(row, rateSelectors).split('\\n')[0].trim();
    if (isValidLabel(named) && named !== roomType) {
      return named;
    }
    const candidates = lines.filter((line) => isValidLabel(line) && line !== roomType);
    const semantic = candidates.find((line) => looksLikeRateName(line));
    if (semantic) {
      return semantic;
    }
    const fallback = candidates.find((line) => !isMetaOnlyLine(line));
    return fallback || candidates[0] || '';
  };

  const pushRoom = (rowText, roomType, rateName, price, breakfast, cancelable) => {
    if (!roomType || !price) {
      return;
    }
    rooms.push({
      room_type: roomType,
      rate_name: rateName || roomType,
      price,
      breakfast,
      cancelable,
      raw: rowText.substring(0, 300),
    });
  };

  const rows = document.querySelectorAll(
    'tr, [class*="room-item"], [class*="RoomItem"], [class*="room_item"],'
    + '[class*="roomCard"], [class*="room-card"], [class*="J_RoomItem"]'
  );
  for (const row of rows) {
    const text = normalize(row.innerText || '');
    if (!text || text.length < 5) continue;
    const priceMatch = text.match(/[¥￥]\s*(\d+(?:\.\d{1,2})?)/);
    if (!priceMatch) continue;
    const price = parseFloat(priceMatch[1]);
    if (price < 10 || price > 99999) continue;

    const lines = splitLines(row.innerText || text);
    const roomType = extractRoomType(row, lines);
    const rateName = extractRateName(row, lines, roomType);
    if (!roomType) continue;

    let breakfast = '未知';
    if (/含早|含双早|含单早|有早餐/.test(text)) breakfast = '含早';
    else if (/无早|不含早/.test(text)) breakfast = '无早';

    let cancelable = '未知';
    if (/免费取消|可取消|可免费/.test(text)) cancelable = '可取消';
    else if (/不可取消|不可退/.test(text)) cancelable = '不可取消';

    pushRoom(text, roomType, rateName, price, breakfast, cancelable);
  }

  if (rooms.length === 0) {
    const allEls = document.querySelectorAll('div, section, li, article, td');
    const seen = new Set();
    for (const el of allEls) {
      const rawText = el.innerText || '';
      const text = normalize(rawText);
      if (!text || text.length < 8 || text.length > 500) continue;
      const priceMatch = text.match(/[¥￥]\s*(\d+(?:\.\d{1,2})?)/);
      if (!priceMatch) continue;
      const price = parseFloat(priceMatch[1]);
      if (price < 10 || price > 99999) continue;

      const lines = splitLines(rawText || text);
      const roomType = extractRoomType(el, lines);
      const rateName = extractRateName(el, lines, roomType);
      if (!roomType) continue;
      const key = `${roomType}|${rateName || roomType}|${price}`;
      if (seen.has(key)) continue;
      seen.add(key);

      let breakfast = '未知';
      if (/含早|含双早|含单早|有早餐/.test(text)) breakfast = '含早';
      else if (/无早|不含早/.test(text)) breakfast = '无早';

      let cancelable = '未知';
      if (/免费取消|可取消|可免费/.test(text)) cancelable = '可取消';
      else if (/不可取消|不可退/.test(text)) cancelable = '不可取消';

      pushRoom(text, roomType, rateName, price, breakfast, cancelable);
    }
  }

  const uniq = [];
  const keys = new Set();
  for (const room of rooms) {
    const key = `${room.room_type}|${room.rate_name || room.room_type}|${room.price}`;
    if (keys.has(key)) continue;
    keys.add(key);
    uniq.push(room);
  }
  return uniq;
}
"""



def _looks_like_fliggy_detail_url(url: str) -> bool:
    normalized = str(url or '').strip().lower()
    hotel_domains = ('hotel.fliggy.com', 'hotel.alitrip.com', 'hotel.taobao.com')
    return any(domain in normalized for domain in hotel_domains) and 'hotel_detail' in normalized


def _pick_fliggy_authenticated_page(browser, *, hotel_url: str = ''):
    normalized_target = str(hotel_url or '').strip().lower()
    fliggy_pages = []
    exact_matches = []
    detail_pages = []
    for page in _iter_browser_pages(browser):
        current_url = str(getattr(page, 'url', '') or '').strip()
        lowered = current_url.lower()
        if 'fliggy.com' not in lowered:
            continue
        fliggy_pages.append(page)
        if normalized_target and lowered == normalized_target:
            exact_matches.append(page)
        if _looks_like_fliggy_detail_url(current_url):
            detail_pages.append(page)

    matches = exact_matches or detail_pages or fliggy_pages
    if not matches:
        raise RuntimeError('no logged-in fliggy page found in chrome debug session')

    for page in matches:
        if _is_active_browser_page(page):
            return page
    return matches[0]


def _normalize_crawled_room_items(raw_rooms) -> list[dict]:
    rooms: list[dict] = []
    if not isinstance(raw_rooms, list):
        return rooms
    for item in raw_rooms:
        if not isinstance(item, dict):
            continue
        rooms.append({
            'room_type': str(item.get('room_type', '')).strip()[:64],
            'rate_name': str(item.get('rate_name', '')).strip()[:128],
            'price': float(item.get('price', 0)),
            'breakfast': str(item.get('breakfast', '未知'))[:16],
            'cancelable': str(item.get('cancelable', '未知'))[:16],
            'raw_text': str(item.get('raw', ''))[:300],
        })
    return rooms


def _looks_like_fliggy_detail_content(page) -> bool:
    current_url = str(getattr(page, 'url', '') or '').strip().lower()
    try:
        title = str(page.title() or '')
    except Exception:
        title = ''
    body_text = _guest_body_text(page)
    if not (_looks_like_fliggy_detail_url(current_url) or '\u98de\u732a\u9152\u5e97' in title or '\u9152\u5e97\u9884\u8ba2' in title):
        return False
    detail_markers = ('\u62a5\u4ef7\u5217\u8868', '\u5e8a\u578b\uff1a', '\u9762\u79ef\uff1a', '\u7a97\u578b\uff1a', '\u697c\u5c42\uff1a', '\u4f4f\u5ba2\u8bc4\u4ef7', '\u9152\u5e97\u9884\u8ba2')
    return sum(1 for marker in detail_markers if marker in body_text or marker in title) >= 2


def crawl_hotel_room_prices(
    *,
    hotel_name: str,
    hotel_url: str,
    headless: bool = True,
    debug_url: str | None = None,
) -> dict:
    """Visit a single hotel detail page and extract room types with prices."""
    if not hotel_url.startswith("http://") and not hotel_url.startswith("https://"):
        raise ValueError("hotel_url must start with http:// or https://")

    settings = get_settings()
    timeout_ms = max(10000, int(settings.fliggy_playwright_timeout_sec) * 1000)
    wait_ms = max(2000, int(settings.fliggy_playwright_wait_after_load_ms))
    resolved_debug_url = str(debug_url or '').strip() or _FLIGGY_CDP_DEFAULT_DEBUG_URL
    selector_map = _normalize_guest_selector_map(None)

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError("playwright not installed") from exc

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rooms: list[dict] = []

    with sync_playwright() as p:
        local_browser = None
        local_context = None
        page = None
        temp_page = None
        try:
            if _looks_like_fliggy_detail_url(hotel_url):
                try:
                    cdp_browser = p.chromium.connect_over_cdp(resolved_debug_url)
                    seed_page = _pick_fliggy_authenticated_page(cdp_browser, hotel_url=hotel_url)
                    current_url = str(getattr(seed_page, 'url', '') or '').strip().lower()
                    target_url = hotel_url.strip().lower()
                    if current_url == target_url:
                        page = seed_page
                    else:
                        temp_page = seed_page.context.new_page()
                        page = temp_page
                except Exception:
                    page = None
                    temp_page = None

            if page is None:
                try:
                    local_browser = p.chromium.launch(headless=headless)
                except Exception as exc:
                    raise RuntimeError("failed to launch chromium") from exc
                local_context = local_browser.new_context(user_agent=settings.competitor_crawl_user_agent)
                page = local_context.new_page()

            current_url = str(getattr(page, 'url', '') or '').strip().lower()
            target_url = hotel_url.strip().lower()
            if current_url != target_url:
                page.goto(hotel_url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(wait_ms)

            if not _looks_like_fliggy_detail_url(hotel_url) and _looks_like_fliggy_guest_login_page(page, selector_map, login_url=''):
                raise RuntimeError('detail page requires a logged-in fliggy browser session')

            for _ in range(3):
                page.evaluate("window.scrollBy(0, 600)")
                page.wait_for_timeout(800)

            rooms = _normalize_crawled_room_items(page.evaluate(_FLIGGY_ROOM_JS))
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(f"timeout loading {hotel_url}: {exc}") from exc
        finally:
            if temp_page is not None:
                try:
                    temp_page.close()
                except Exception:
                    pass
            if local_context is not None:
                try:
                    local_context.close()
                except Exception:
                    pass
            if local_browser is not None:
                try:
                    local_browser.close()
                except Exception:
                    pass

    return {
        'hotel_name': hotel_name,
        'hotel_url': hotel_url,
        'collected_at': now,
        'room_count': len(rooms),
        'rooms': rooms,
    }



def crawl_multiple_hotels_room_prices(
    *,
    hotels: list[dict],
    headless: bool = True,
    debug_url: str | None = None,
) -> list[dict]:
    """Crawl room prices for multiple hotels sequentially."""
    results: list[dict] = []
    for h in hotels:
        name = str(h.get("name", "")).strip()
        url = str(h.get("url", "")).strip()
        if not name or not url:
            results.append({"hotel_name": name or "unknown", "hotel_url": url, "error": "\u7f3a\u5c11\u540d\u79f0\u6216URL", "rooms": []})
            continue
        try:
            result = crawl_hotel_room_prices(hotel_name=name, hotel_url=url, headless=headless, debug_url=debug_url)
            results.append(result)
        except (RuntimeError, ValueError) as exc:
            results.append({"hotel_name": name, "hotel_url": url, "error": str(exc), "rooms": []})
    return results



# ---------------------------------------------------------------------------
# Room prices persistence
# ---------------------------------------------------------------------------

def ensure_room_prices_table(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS hotel_room_prices (
              id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
              shop_id BIGINT UNSIGNED NOT NULL,
              hotel_name VARCHAR(128) NOT NULL,
              hotel_url VARCHAR(1024) NOT NULL DEFAULT '',
              room_type VARCHAR(64) NOT NULL,
              price DECIMAL(10, 2) NOT NULL,
              breakfast VARCHAR(16) NOT NULL DEFAULT '未知',
              cancelable VARCHAR(16) NOT NULL DEFAULT '未知',
              raw_text VARCHAR(300) NULL,
              collected_at DATETIME NOT NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (id),
              KEY idx_room_shop_time (shop_id, collected_at),
              KEY idx_room_hotel_time (shop_id, hotel_name, collected_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    )


def save_room_prices(db: Session, *, shop_id: int, crawl_results: list[dict]) -> int:
    """Persist room-type pricing from crawl results."""
    ensure_room_prices_table(db)
    total_saved = 0
    try:
        for hotel in crawl_results:
            hotel_name = str(hotel.get("hotel_name", ""))
            hotel_url = str(hotel.get("hotel_url", ""))
            collected_at = str(hotel.get("collected_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            rooms = hotel.get("rooms", [])
            if not isinstance(rooms, list):
                continue
            for room in rooms:
                if not isinstance(room, dict):
                    continue
                db.execute(
                    text(
                        """
                        INSERT INTO hotel_room_prices
                        (shop_id, hotel_name, hotel_url, room_type, price, breakfast, cancelable, raw_text, collected_at)
                        VALUES
                        (:shop_id, :hotel_name, :hotel_url, :room_type, :price, :breakfast, :cancelable, :raw_text, :collected_at)
                        """
                    ),
                    {
                        "shop_id": shop_id,
                        "hotel_name": hotel_name[:128],
                        "hotel_url": hotel_url[:1024],
                        "room_type": str(room.get("room_type", ""))[:64],
                        "price": float(room.get("price", 0)),
                        "breakfast": str(room.get("breakfast", "未知"))[:16],
                        "cancelable": str(room.get("cancelable", "未知"))[:16],
                        "raw_text": str(room.get("raw_text", ""))[:300],
                        "collected_at": collected_at,
                    },
                )
                total_saved += 1
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError(str(exc)) from exc
    return total_saved


def get_latest_room_prices(db: Session, *, shop_id: int, limit: int = 200) -> dict:
    """Get the most recent room-type prices, grouped by hotel."""
    ensure_room_prices_table(db)
    try:
        rows = db.execute(
            text(
                """
                SELECT hotel_name, hotel_url, room_type, price, breakfast, cancelable, collected_at
                FROM hotel_room_prices
                WHERE shop_id = :shop_id
                  AND collected_at = (
                    SELECT MAX(collected_at) FROM hotel_room_prices WHERE shop_id = :shop_id
                  )
                ORDER BY hotel_name, price
                LIMIT :limit
                """
            ),
            {"shop_id": shop_id, "limit": limit},
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc

    hotels_map: dict[str, dict] = {}
    latest_time = ""
    for row in rows:
        hname = str(row["hotel_name"])
        if not latest_time:
            latest_time = str(row["collected_at"])
        if hname not in hotels_map:
            hotels_map[hname] = {
                "hotel_name": hname,
                "hotel_url": str(row["hotel_url"]),
                "rooms": [],
            }
        hotels_map[hname]["rooms"].append({
            "room_type": str(row["room_type"]),
            "price": float(row["price"]),
            "breakfast": str(row["breakfast"]),
            "cancelable": str(row["cancelable"]),
        })

    hotels_list = list(hotels_map.values())
    for h in hotels_list:
        prices = [r["price"] for r in h["rooms"] if r["price"] > 0]
        h["min_price"] = min(prices) if prices else 0
        h["max_price"] = max(prices) if prices else 0
        h["room_count"] = len(h["rooms"])

    return {
        "shop_id": shop_id,
        "collected_at": latest_time,
        "hotel_count": len(hotels_list),
        "total_rooms": sum(h["room_count"] for h in hotels_list),
        "hotels": hotels_list,
    }


# ---------------------------------------------------------------------------
# Historical room price analysis
# ---------------------------------------------------------------------------

def get_room_price_history(
    db: Session,
    *,
    shop_id: int,
    days: int = 30,
    hotel_name: str | None = None,
    limit: int = 5000,
) -> dict:
    """Query historical room prices within a date range, with per-hotel/room-type aggregation."""
    ensure_room_prices_table(db)

    params: dict = {"shop_id": shop_id, "days": days, "limit": limit}
    name_filter = ""
    if hotel_name and hotel_name.strip():
        name_filter = "AND hotel_name = :hotel_name"
        params["hotel_name"] = hotel_name.strip()

    try:
        rows = db.execute(
            text(
                f"""
                SELECT hotel_name, room_type, price, breakfast, cancelable,
                       collected_at, DATE(collected_at) AS day
                FROM hotel_room_prices
                WHERE shop_id = :shop_id
                  AND collected_at >= DATE_SUB(NOW(), INTERVAL :days DAY)
                  {name_filter}
                ORDER BY collected_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()

        agg_rows = db.execute(
            text(
                f"""
                SELECT hotel_name, room_type,
                       COUNT(*) AS sample_count,
                       ROUND(AVG(price), 2) AS avg_price,
                       MIN(price) AS min_price,
                       MAX(price) AS max_price,
                       ROUND(STDDEV_POP(price), 2) AS price_stddev,
                       MIN(DATE(collected_at)) AS first_seen,
                       MAX(DATE(collected_at)) AS last_seen
                FROM hotel_room_prices
                WHERE shop_id = :shop_id
                  AND collected_at >= DATE_SUB(NOW(), INTERVAL :days DAY)
                  {name_filter}
                GROUP BY hotel_name, room_type
                ORDER BY hotel_name, avg_price
                """
            ),
            {k: v for k, v in params.items() if k != "limit"},
        ).mappings().all()

        daily_rows = db.execute(
            text(
                f"""
                SELECT hotel_name, DATE(collected_at) AS day,
                       ROUND(AVG(price), 2) AS avg_price,
                       MIN(price) AS min_price,
                       MAX(price) AS max_price,
                       COUNT(*) AS cnt
                FROM hotel_room_prices
                WHERE shop_id = :shop_id
                  AND collected_at >= DATE_SUB(NOW(), INTERVAL :days DAY)
                  {name_filter}
                GROUP BY hotel_name, DATE(collected_at)
                ORDER BY day
                """
            ),
            {k: v for k, v in params.items() if k != "limit"},
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise RuntimeError(str(exc)) from exc

    records = []
    for r in rows:
        records.append({
            "hotel_name": str(r["hotel_name"]),
            "room_type": str(r["room_type"]),
            "price": float(r["price"]),
            "breakfast": str(r["breakfast"]),
            "day": str(r["day"]),
            "collected_at": str(r["collected_at"]),
        })

    aggregation = []
    for r in agg_rows:
        aggregation.append({
            "hotel_name": str(r["hotel_name"]),
            "room_type": str(r["room_type"]),
            "sample_count": int(r["sample_count"]),
            "avg_price": float(r["avg_price"] or 0),
            "min_price": float(r["min_price"] or 0),
            "max_price": float(r["max_price"] or 0),
            "price_stddev": float(r["price_stddev"] or 0),
            "first_seen": str(r["first_seen"]),
            "last_seen": str(r["last_seen"]),
        })

    daily_trend = []
    for r in daily_rows:
        daily_trend.append({
            "hotel_name": str(r["hotel_name"]),
            "day": str(r["day"]),
            "avg_price": float(r["avg_price"] or 0),
            "min_price": float(r["min_price"] or 0),
            "max_price": float(r["max_price"] or 0),
            "count": int(r["cnt"]),
        })

    return {
        "shop_id": shop_id,
        "days": days,
        "record_count": len(records),
        "records": records,
        "aggregation": aggregation,
        "daily_trend": daily_trend,
    }


def _build_price_analysis_prompt(
    *,
    history: dict,
    my_hotel_name: str,
    my_price: float,
    my_total_rooms: int,
    my_available_rooms: int,
) -> str:
    """Build a prompt for the LLM to analyze historical competitor pricing data."""
    agg = history.get("aggregation", [])
    trend = history.get("daily_trend", [])
    days = history.get("days", 30)

    agg_text = ""
    for a in agg[:50]:
        agg_text += (
            f"  {a['hotel_name']} - {a['room_type']}: "
            f"均价¥{a['avg_price']:.0f}, 最低¥{a['min_price']:.0f}, "
            f"最高¥{a['max_price']:.0f}, 波动{a['price_stddev']:.0f}, "
            f"采样{a['sample_count']}次\n"
        )

    trend_text = ""
    hotels_in_trend = set()
    for t in trend:
        hotels_in_trend.add(t["hotel_name"])
    for h in list(hotels_in_trend)[:10]:
        h_days = [t for t in trend if t["hotel_name"] == h]
        if len(h_days) >= 2:
            first_p = h_days[0]["avg_price"]
            last_p = h_days[-1]["avg_price"]
            change = last_p - first_p
            trend_text += f"  {h}: {h_days[0]['day']}均价¥{first_p:.0f} → {h_days[-1]['day']}均价¥{last_p:.0f} (变化{change:+.0f})\n"

    return (
        "你是一位资深酒店收益管理专家。请根据以下竞对酒店的历史价格数据进行深度分析，并给出具体可执行的定价和运营建议。\n\n"
        f"【我的酒店信息】\n"
        f"  名称: {my_hotel_name}\n"
        f"  当前挂牌价: ¥{my_price:.0f}\n"
        f"  总房间: {my_total_rooms}, 可用: {my_available_rooms}, "
        f"入住率: {((my_total_rooms - my_available_rooms) / max(my_total_rooms, 1)) * 100:.0f}%\n\n"
        f"【数据范围】最近 {days} 天\n\n"
        f"【竞对房型价格汇总】\n{agg_text}\n"
        f"【价格趋势变化】\n{trend_text}\n"
        "请返回 JSON，格式：\n"
        '{"analysis": {"market_summary": "市场整体情况总结(100字以内)", '
        '"price_position": "我的酒店在竞对中的价格定位分析(100字以内)", '
        '"trend_insight": "价格趋势洞察(100字以内)", '
        '"risk_warning": "风险预警(50字以内)"}, '
        '"suggestions": [{"title": "建议标题", "detail": "具体操作建议(50字以内)", "priority": "high|medium|low"}], '
        '"recommended_price_range": {"min": number, "mid": number, "max": number}}'
    )


def analyze_room_price_history(
    db: Session,
    *,
    shop_id: int,
    days: int = 30,
    hotel_name: str | None = None,
    my_hotel_name: str = "我的酒店",
    my_price: float = 299.0,
    my_total_rooms: int = 20,
    my_available_rooms: int = 5,
) -> dict:
    """Query historical data and call LLM for analysis and suggestions."""
    history = get_room_price_history(db=db, shop_id=shop_id, days=days, hotel_name=hotel_name)
    if not history.get("aggregation"):
        return {
            "shop_id": shop_id,
            "days": days,
            "error": "该时间范围内无历史数据，请先抓取竞对房型价格。",
            "history": history,
            "analysis": None,
        }

    prompt = _build_price_analysis_prompt(
        history=history,
        my_hotel_name=my_hotel_name,
        my_price=my_price,
        my_total_rooms=my_total_rooms,
        my_available_rooms=my_available_rooms,
    )

    settings = get_settings()
    provider = str(getattr(settings, "llm_provider", "openai") or "openai").strip().lower()
    if provider == "tongyi":
        api_key = str(getattr(settings, "tongyi_api_key", "") or getattr(settings, "openai_api_key", "")).strip()
        model = str(getattr(settings, "tongyi_model", "") or "qwen-plus").strip()
        base_url = str(getattr(settings, "tongyi_base_url", "") or DEFAULT_TONGYI_BASE_URL).strip().rstrip("/")
    else:
        api_key = str(getattr(settings, "openai_api_key", "")).strip()
        model = str(getattr(settings, "openai_model", "") or "gpt-4o-mini").strip()
        base_url = str(getattr(settings, "openai_base_url", "") or DEFAULT_OPENAI_BASE_URL).strip().rstrip("/")

    analysis_result: dict | None = None
    llm_source = "none"

    if api_key:
        endpoint = base_url.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"

        payload = {
            "model": model,
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "你是酒店收益管理专家，仅返回 JSON。"},
                {"role": "user", "content": prompt},
            ],
        }
        req = Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
        )
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Content-Type", "application/json")
        try:
            with urlopen(req, timeout=30) as response:
                raw = response.read().decode("utf-8")
            parsed = json.loads(raw)
            content = parsed["choices"][0]["message"]["content"]
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1:
                analysis_result = json.loads(content[start:end + 1])
                llm_source = provider
        except Exception:
            pass

    if analysis_result is None:
        agg = history.get("aggregation", [])
        all_avg = [a["avg_price"] for a in agg if a["avg_price"] > 0]
        market_avg = sum(all_avg) / len(all_avg) if all_avg else my_price
        market_min = min(a["min_price"] for a in agg) if agg else my_price
        market_max = max(a["max_price"] for a in agg) if agg else my_price
        diff = my_price - market_avg

        if diff > 50:
            position = "您的价格明显高于竞对均价，可能影响订单转化率"
        elif diff < -50:
            position = "您的价格明显低于竞对均价，存在提价空间"
        else:
            position = "您的价格处于市场中游位置，竞争力适中"

        analysis_result = {
            "analysis": {
                "market_summary": f"竞对均价约¥{market_avg:.0f}，价格区间¥{market_min:.0f}-¥{market_max:.0f}",
                "price_position": position,
                "trend_insight": "基于规则分析，建议持续跟踪价格变化趋势",
                "risk_warning": "数据量有限时分析可能不够精准",
            },
            "suggestions": [
                {"title": "持续采集数据", "detail": "建议每日定时抓取竞对价格，积累更多数据样本", "priority": "high"},
                {"title": "关注价格波动", "detail": f"当竞对均价偏离¥{market_avg:.0f}超过10%时及时调价", "priority": "medium"},
            ],
            "recommended_price_range": {
                "min": round(market_avg * 0.85, 0),
                "mid": round(market_avg, 0),
                "max": round(market_avg * 1.15, 0),
            },
        }
        llm_source = "rule_based"

    return {
        "shop_id": shop_id,
        "days": days,
        "llm_source": llm_source,
        "history": history,
        "analysis": analysis_result,
    }













