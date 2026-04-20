from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_env_file() -> str:
    backend_root = Path(__file__).resolve().parents[2]
    search_roots = (backend_root, *backend_root.parents)
    fallback = backend_root / ".env"

    for root in search_roots:
        candidate = root / "private-secrets" / "backend" / ".env"
        if candidate.is_file():
            return str(candidate)

    for root in search_roots:
        candidate = root / "backend" / ".env"
        if candidate.is_file():
            return str(candidate)

    if fallback.is_file():
        return str(fallback)
    return str(search_roots[-1] / "private-secrets" / "backend" / ".env")


class Settings(BaseSettings):
    app_name: str = "fliggy-ai-mvp"
    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    flask_secret_key: str = ""
    auth_allow_header_fallback: bool = True
    db_host: str
    db_port: int = 3306
    db_name: str
    db_user: str
    db_password: str
    db_charset: str = "utf8mb4"

    llm_provider: str = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    tongyi_api_key: str = ""
    tongyi_model: str = "qwen-plus"
    tongyi_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    openclaw_base_url: str = "http://127.0.0.1:18789"
    openclaw_api_key: str = ""
    openclaw_model: str = "openclaw:main"
    llm_timeout_sec: int = 5
    competitor_crawl_user_agent: str = "fliggy-ai-mvp-bot/1.0 (+internal-testing)"
    competitor_crawl_timeout_sec: int = 20
    competitor_daily_enabled: bool = False
    competitor_daily_shop_id: int = 1
    competitor_daily_hour: int = 9
    competitor_daily_minute: int = 0
    competitor_daily_use_openclaw: bool = True
    competitor_daily_limit_per_page_chars: int = 6000
    competitor_daily_targets_json: str = "[]"
    fliggy_playwright_timeout_sec: int = 30
    fliggy_playwright_wait_after_load_ms: int = 1800
    fliggy_playwright_daily_enabled: bool = False
    fliggy_playwright_daily_shop_id: int = 1
    fliggy_playwright_daily_start_url: str = ""
    fliggy_playwright_daily_hour: int = 8
    fliggy_playwright_daily_minute: int = 0
    fliggy_playwright_daily_max_pages: int = 1
    fliggy_playwright_daily_max_hotels: int = 50
    fliggy_playwright_daily_headless: bool = True

    fliggy_gateway: str = "https://eco.taobao.com/router/rest"
    fliggy_app_key: str = ""
    fliggy_app_secret: str = ""
    fliggy_session: str = ""
    fliggy_sign_method: str = "md5"
    fliggy_version: str = "2.0"
    fliggy_format: str = "json"
    fliggy_timeout_sec: int = 15
    fliggy_sync_method_orders: str = "taobao.xhotel.order.distribution.tmc.list"
    fliggy_sync_method_hotel_baseinfo: str = "taobao.xhotel.baseinfo.get"
    fliggy_hotel_id: str = ""
    fliggy_room_status_hotel_id: str = ""
    fliggy_price_push_enabled: bool = False
    fliggy_price_push_method: str = "taobao.xhotel.rate.update"
    fliggy_price_push_payload_json: str = ""

    room_status_auto_enabled: bool = False
    room_status_shop_id: int = 1
    room_status_total_rooms: int = 20
    room_status_available_rooms: int = 5
    room_status_current_price: float = 299.0

    daily_revenue_auto_enabled: bool = False
    daily_revenue_shop_id: int = 1
    daily_revenue_sync_hour: int = 0
    daily_revenue_sync_minute: int = 5

    auto_pricing_schedule_enabled: bool = False
    auto_pricing_schedule_hour: int = 8
    auto_pricing_schedule_minute: int = 15

    action_retry_max_times: int = 2
    action_approval_retry_max_times: int = 1
    approval_timeout_hours: int = 24
    alert_failed_actions_threshold: int = 5
    alert_failed_sync_jobs_threshold: int = 3

    celery_broker_url: str = "redis://127.0.0.1:6379/0"
    celery_result_backend: str = "redis://127.0.0.1:6379/1"

    model_config = SettingsConfigDict(
        env_file=_resolve_env_file(),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @property
    def database_url(self) -> str:
        password = quote_plus(self.db_password)
        return (
            f"mysql+pymysql://{self.db_user}:{password}@{self.db_host}:{self.db_port}/"
            f"{self.db_name}?charset={self.db_charset}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
