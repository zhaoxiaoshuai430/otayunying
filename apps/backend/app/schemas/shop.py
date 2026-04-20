from pydantic import BaseModel, Field


class ShopUpsertRequest(BaseModel):
    shop_id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=128)
    status: str = Field(default='enabled')
    fliggy_hotel_id: str = Field(default='', max_length=64)
    fliggy_room_status_hotel_id: str = Field(default='', max_length=64)
    fliggy_app_key: str = Field(default='', max_length=128)
    fliggy_app_secret: str = Field(default='', max_length=255)
    fliggy_session: str = Field(default='', max_length=255)
    room_status_auto_enabled: bool = False
    room_status_total_rooms: int = Field(default=20, ge=1)
    room_status_available_rooms: int = Field(default=5, ge=0)
    room_status_current_price: float = Field(default=299.0, ge=0)
    daily_revenue_auto_enabled: bool = False
    fliggy_price_push_enabled: bool = False
    fliggy_price_push_method: str = Field(default='', max_length=128)
    fliggy_price_push_payload_json: str = Field(default='', max_length=20000)
    fliggy_merchant_login_url: str = Field(default='', max_length=2048)
    fliggy_merchant_price_url: str = Field(default='', max_length=2048)
    fliggy_merchant_storage_state: str = Field(default='', max_length=255)
    fliggy_merchant_price_selectors_json: str = Field(default='', max_length=20000)
