from datetime import date

from pydantic import BaseModel, Field


class InventorySnapshot(BaseModel):
    total_rooms: int = Field(default=1, ge=1)
    available_rooms: int = Field(default=0, ge=0)
    occupancy_rate: float | None = Field(default=None, ge=0, le=1)
    current_price: float | None = Field(default=None, gt=0)


class PricingRecommendationRequest(BaseModel):
    shop_id: int = Field(default=1, ge=1)
    inventory_snapshot: InventorySnapshot
    target_name: str | None = Field(default=None, min_length=1, max_length=128)
    days: int = Field(default=7, ge=1, le=90)
    strategy: str = Field(default='balanced', pattern='^(conservative|balanced|aggressive)$')
    limit: int = Field(default=50, ge=1, le=200)
    event_date: date | None = None
    target_occupancy_min: float = Field(default=0.15, gt=0, lt=1)
    target_occupancy_max: float = Field(default=0.20, gt=0, lt=1)
    expected_cancel_rate: float | None = Field(default=None, ge=0, le=0.6)
    demand_heat: float | None = Field(default=None, ge=0, le=1)
    competitor_price_cap_ratio: float = Field(default=1.15, ge=1.0, le=1.3)


class MerchantPriceItemSelector(BaseModel):
    room_name: str = Field(default='', max_length=255)
    rate_name: str = Field(default='', max_length=255)
    display_name: str = Field(default='', max_length=255)
    gid: str = Field(default='', max_length=128)
    hid: str = Field(default='', max_length=128)


class MerchantPriceMappingUpsertRequest(BaseModel):
    shop_id: int = Field(default=1, ge=1)
    platform: str = Field(default='fliggy', min_length=1, max_length=32)
    room_name: str = Field(min_length=1, max_length=255)
    rate_name: str = Field(default='', max_length=255)
    merchant_room_key: str = Field(default='', max_length=128)
    merchant_rate_key: str = Field(default='', max_length=128)
    gid: str = Field(default='', max_length=128)
    hid: str = Field(default='', max_length=128)
    status: str = Field(default='draft', pattern='^(draft|active|enabled|disabled|inactive)$')
    notes: str = Field(default='', max_length=255)


class MerchantPricingPreviewRequest(BaseModel):
    shop_id: int = Field(default=1, ge=1)
    price_url: str | None = Field(default=None, max_length=2048)
    headless: bool = True
    selectors: dict | None = None
    selected_items: list[MerchantPriceItemSelector] = Field(default_factory=list, max_length=50)
    merchant_items: list[dict] = Field(default_factory=list, max_length=100)
    collect_mode: str = Field(default='cdp_current_page', max_length=32)
    debug_url: str | None = Field(default=None, max_length=2048)


class MerchantPricingGenerateRequest(BaseModel):
    shop_id: int = Field(default=1, ge=1)
    price_url: str | None = Field(default=None, max_length=2048)
    headless: bool = True
    selectors: dict | None = None
    selected_items: list[MerchantPriceItemSelector] = Field(default_factory=list, max_length=50)
    preview_only: bool = True
    approver_user_id: int | None = Field(default=None, ge=1)
    comment: str = Field(default='', max_length=255)


class MerchantPricingDirectSubmitRequest(BaseModel):
    shop_id: int = Field(default=1, ge=1)
    price_url: str | None = Field(default=None, max_length=2048)
    headless: bool = True
    selectors: dict | None = None
    selected_items: list[MerchantPriceItemSelector] = Field(default_factory=list, max_length=50)
    merchant_items: list[dict] = Field(default_factory=list, max_length=100)
    collect_mode: str = Field(default='cdp_current_page', max_length=32)
    debug_url: str | None = Field(default=None, max_length=2048)
    comment: str = Field(default='', max_length=255)


class CompetitorDrivenPricingPreviewRequest(BaseModel):
    shop_id: int = Field(default=1, ge=1)
    competitor_hotel_name: str | None = Field(default=None, min_length=1, max_length=128)
    price_url: str | None = Field(default=None, max_length=2048)
    headless: bool = True
    selectors: dict | None = None
    merchant_items: list[dict] = Field(default_factory=list, max_length=100)
    competitor_hotels: list[dict] = Field(default_factory=list, max_length=20)
    manual_room_mappings: list[dict] = Field(default_factory=list, max_length=50)
    inventory_snapshot: dict = Field(default_factory=dict)
    strategy: str = Field(default='balanced', pattern='^(conservative|balanced|aggressive)$')


class CompetitorPricingAdviceRoom(BaseModel):
    room_type: str = Field(default='', max_length=255)
    rate_name: str = Field(default='', max_length=255)
    price: float = Field(gt=0)
    breakfast: str | None = Field(default=None, max_length=64)
    cancelable: str | None = Field(default=None, max_length=64)


class CompetitorPricingAdviceHotel(BaseModel):
    hotel_name: str = Field(min_length=1, max_length=255)
    hotel_url: str | None = Field(default=None, max_length=2048)
    rooms: list[CompetitorPricingAdviceRoom] = Field(default_factory=list, min_length=1, max_length=100)


class ManualRoomMapping(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    room_type: str = Field(default='', max_length=255)
    rate_name: str = Field(default='???', max_length=255)
    current_price: float = Field(gt=0)
    gid: str | None = Field(default=None, max_length=128)
    hid: str | None = Field(default=None, max_length=128)
    competitor_room_names: list[str] = Field(default_factory=list, max_length=20)
    enabled: bool = True


class ManualRoomMappingsReplaceRequest(BaseModel):
    shop_id: int | None = Field(default=None, ge=1)
    items: list[ManualRoomMapping] = Field(default_factory=list, max_length=50)


class CompetitorPricingAdviceRequest(BaseModel):
    shop_id: int = Field(default=1, ge=1)
    inventory_snapshot: InventorySnapshot
    competitor_hotels: list[CompetitorPricingAdviceHotel] = Field(default_factory=list, max_length=20)
    manual_room_mappings: list[ManualRoomMapping] = Field(default_factory=list, max_length=50)
    competitor_hotel_name: str | None = Field(default=None, min_length=1, max_length=255)
    strategy: str = Field(default='balanced', pattern='^(conservative|balanced|aggressive)$')
    event_date: date | None = None
    target_occupancy_min: float = Field(default=0.15, gt=0, lt=1)
    target_occupancy_max: float = Field(default=0.20, gt=0, lt=1)
    expected_cancel_rate: float | None = Field(default=None, ge=0, le=0.6)
    demand_heat: float | None = Field(default=None, ge=0, le=1)
    competitor_price_cap_ratio: float = Field(default=1.15, ge=1.0, le=1.3)


class MerchantUniformPriceSubmitRequest(BaseModel):
    shop_id: int = Field(default=1, ge=1)
    target_price: float = Field(gt=0)
    price_url: str | None = Field(default=None, max_length=2048)
    headless: bool = True
    selectors: dict | None = None
    selected_items: list[MerchantPriceItemSelector] = Field(default_factory=list, max_length=50)
    comment: str = Field(default='', max_length=255)


class MerchantPricingConfirmItem(BaseModel):
    room_name: str = Field(default='', max_length=255)
    rate_name: str = Field(default='', max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    current_price: float = Field(gt=0)
    final_price: float = Field(gt=0)
    suggested_price: float | None = Field(default=None, gt=0)
    risk_level: str = Field(default='L2', pattern='^L[0-3]$')
    gid: str = Field(min_length=1, max_length=128)
    hid: str = Field(min_length=1, max_length=128)
    start_date: date | None = None
    end_date: date | None = None
    comment: str | None = Field(default=None, max_length=255)


class MerchantPricingConfirmRequest(BaseModel):
    shop_id: int = Field(default=1, ge=1)
    approver_user_id: int = Field(ge=1)
    comment: str = Field(default='', max_length=255)
    confirmed_items: list[MerchantPricingConfirmItem] = Field(min_length=1, max_length=50)
