from pydantic import BaseModel, Field


class PluginLoginRequest(BaseModel):
    tenant_id: int = Field(default=1, ge=1)
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=255)


class PluginSwitchShopRequest(BaseModel):
    shop_id: int = Field(ge=1)


class PluginCompetitorHotelItem(BaseModel):
    hotel_name: str = Field(min_length=1, max_length=128)
    hotel_url: str = Field(min_length=8, max_length=2048)
    enabled: bool = True
    sort_order: int = Field(default=10, ge=0, le=100000)


class PluginCompetitorHotelsSaveRequest(BaseModel):
    items: list[PluginCompetitorHotelItem] = Field(default_factory=list, max_length=50)
