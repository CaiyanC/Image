from datetime import datetime

from pydantic import BaseModel, Field


class ToolCreateRequest(BaseModel):
    tool_key: str = Field(min_length=1, max_length=64)
    name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    category: str | None = Field(default=None, max_length=64)
    icon_key: str | None = Field(default=None, max_length=64)
    is_enabled: bool = True
    sort_order: int = Field(default=0, ge=0, le=10000)


class ToolUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    category: str | None = Field(default=None, max_length=64)
    icon_key: str | None = Field(default=None, max_length=64)
    is_enabled: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10000)


class ToolResponse(BaseModel):
    tool_key: str
    name: str
    description: str | None
    category: str
    icon_key: str
    route_path: str
    permission_key: str
    is_enabled: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ToolRunResponse(BaseModel):
    id: str
    tool_key: str
    status: str
    parameters: dict
    input_files: list
    output_files: list
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}
