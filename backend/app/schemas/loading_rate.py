from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


class LoadingRateItem(BaseModel):
    """A product line used when cargo volume is derived from master data."""

    sku: str = Field(min_length=1, max_length=100)
    carton_count: int = Field(gt=0)


class LoadingRateCalculationRequest(BaseModel):
    container_usable_volume_m3: Decimal = Field(gt=0)
    actual_cargo_volume_m3: Decimal | None = Field(default=None, ge=0)
    items: list[LoadingRateItem] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def require_one_volume_source(self):
        if self.actual_cargo_volume_m3 is None and not self.items:
            raise ValueError("请填写实际货物体积，或提供按 SKU 计算的装柜明细")
        if self.actual_cargo_volume_m3 is not None and self.items:
            raise ValueError("实际货物体积和 SKU 装柜明细只能填写一种")
        return self
