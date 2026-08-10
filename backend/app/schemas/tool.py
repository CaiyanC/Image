from datetime import datetime
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, Field, model_validator


class ToolCreateRequest(BaseModel):
    tool_key: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    category: str | None = Field(default=None, max_length=64)
    icon_key: str | None = Field(default=None, max_length=64)
    entry_type: Literal["internal", "external"] = "internal"
    external_url: AnyHttpUrl | None = None
    open_mode: Literal["same_tab", "new_tab"] = "new_tab"
    is_enabled: bool = True
    sort_order: int = Field(default=0, ge=0, le=10000)

    @model_validator(mode="after")
    def validate_entry(self):
        if self.entry_type == "external" and self.external_url is None:
            raise ValueError("external_url is required for external tools")
        if self.entry_type == "internal" and self.external_url is not None:
            raise ValueError("external_url is only supported for external tools")
        return self


class ToolUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    category: str | None = Field(default=None, max_length=64)
    icon_key: str | None = Field(default=None, max_length=64)
    external_url: AnyHttpUrl | None = None
    open_mode: Literal["same_tab", "new_tab"] | None = None
    is_enabled: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10000)


class ToolResponse(BaseModel):
    tool_key: str
    name: str
    description: str | None
    category: str
    icon_key: str
    route_path: str
    entry_type: Literal["internal", "external"]
    external_url: str | None
    open_mode: Literal["same_tab", "new_tab"]
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


class ToolRunConfirmRequest(BaseModel):
    parameters: dict = Field(default_factory=dict)
