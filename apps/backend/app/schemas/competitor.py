from pydantic import BaseModel, Field


class CompetitorTarget(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=8, max_length=2048)
    note: str | None = None


class CompetitorCollectRequest(BaseModel):
    shop_id: int = Field(default=1, ge=1)
    targets: list[CompetitorTarget] = Field(default_factory=list, min_length=1, max_length=20)
    use_openclaw: bool = True
    limit_per_page_chars: int = Field(default=6000, ge=500, le=20000)


class FliggyPlaywrightCollectRequest(BaseModel):
    shop_id: int = Field(default=1, ge=1)
    start_url: str = Field(min_length=8, max_length=2048)
    max_pages: int = Field(default=1, ge=1, le=20)
    max_hotels: int = Field(default=50, ge=1, le=500)
    target_hotel_names: list[str] = Field(default_factory=list, max_length=50)
    headless: bool = True
    save_result: bool = True
    collect_mode: str = Field(default='cdp_current_page', max_length=32)
    debug_url: str | None = Field(default=None, max_length=2048)
    target_page_url_keyword: str = Field(default='', max_length=255)
    login_url: str | None = Field(default=None, max_length=2048)
    storage_state_name: str = Field(default='', max_length=255)
    username: str = Field(default='', max_length=128)
    password: str = Field(default='', max_length=255)
    login_headless: bool = False
    auto_login: bool = False
    save_credential: bool = True
    selectors: dict | None = None
    page_snapshot: dict | None = None


class FliggyGuestLoginRequest(BaseModel):
    shop_id: int = Field(default=1, ge=1)
    login_url: str | None = Field(default=None, max_length=2048)
    start_url: str | None = Field(default=None, max_length=2048)
    storage_state_name: str = Field(default='', max_length=255)
    username: str = Field(default='', max_length=128)
    password: str = Field(default='', max_length=255)
    headless: bool = False
    selectors: dict | None = None


class MerchantCredentialUpsertRequest(BaseModel):
    shop_id: int = Field(default=1, ge=1)
    username: str = Field(default='', max_length=128)
    password: str = Field(default='', max_length=255)
    login_url: str | None = Field(default=None, max_length=2048)
    price_url: str | None = Field(default=None, max_length=2048)
    storage_state_name: str = Field(default='', max_length=255)
    selectors: dict | None = None


class FliggyMerchantLoginRequest(BaseModel):
    shop_id: int = Field(default=1, ge=1)
    username: str = Field(default='', max_length=128)
    password: str = Field(default='', max_length=255)
    login_url: str | None = Field(default=None, max_length=2048)
    storage_state_name: str = Field(default='', max_length=255)
    headless: bool = True
    selectors: dict | None = None


class FliggyMerchantPriceCollectRequest(BaseModel):
    shop_id: int = Field(default=1, ge=1)
    price_url: str | None = Field(default=None, max_length=2048)
    headless: bool = True
    save_result: bool = True
    collect_mode: str = Field(default='prefer_cdp', max_length=32)
    debug_url: str | None = Field(default=None, max_length=2048)
    selectors: dict | None = None


class FliggyMerchantPricePreviewRequest(BaseModel):
    shop_id: int = Field(default=1, ge=1)
    price_url: str | None = Field(default=None, max_length=2048)
    login_url: str | None = Field(default=None, max_length=2048)
    storage_state_name: str = Field(default='', max_length=255)
    username: str = Field(default='', max_length=128)
    password: str = Field(default='', max_length=255)
    headless: bool = True
    login_headless: bool = False
    auto_login: bool = False
    save_credential: bool = True
    collect_mode: str = Field(default='prefer_cdp', max_length=32)
    debug_url: str | None = Field(default=None, max_length=2048)
    selectors: dict | None = None


class HotelRoomCrawlTarget(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=8, max_length=2048)


class HotelRoomCrawlRequest(BaseModel):
    shop_id: int = Field(default=1, ge=1)
    hotels: list[HotelRoomCrawlTarget] = Field(min_length=1, max_length=20)
    headless: bool = True
    save_result: bool = True
    debug_url: str | None = Field(default=None, max_length=2048)



