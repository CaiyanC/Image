from pydantic import BaseModel, ConfigDict, Field, field_validator


class CompetitorAssetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand: str | None = Field(None, min_length=1, max_length=64)
    maintainer: str | None = Field(None, max_length=100)
    source_note: str | None = Field(None, max_length=2000)
    notes: str | None = Field(None, max_length=2000)

    @field_validator("brand")
    @classmethod
    def require_brand(cls, value):
        if value is None or not value.strip():
            raise ValueError("竞品品牌不能为空")
        return value.strip()
