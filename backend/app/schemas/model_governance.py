from datetime import datetime

from pydantic import BaseModel, Field, computed_field


class CredentialResponse(BaseModel):
    id: str | None = None
    provider_name: str | None = None
    api_base_url: str | None = None
    scope_type: str | None = None
    scope_id: str | None = None
    is_enabled: bool | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    key_hint: str = Field(exclude=True)

    model_config = {"from_attributes": True}

    @computed_field
    @property
    def api_key_masked(self) -> str:
        return f"****{self.key_hint}" if len(self.key_hint) == 4 else "****"


class CredentialCreateRequest(BaseModel):
    provider_name: str = Field(min_length=1, max_length=100)
    api_base_url: str = Field(min_length=1, max_length=500)
    api_key: str = Field(min_length=1)
    scope_type: str = Field(pattern="^(company|group|user)$")
    scope_id: str | None = Field(default=None, max_length=36)
    is_enabled: bool = True


class CredentialUpdateRequest(BaseModel):
    provider_name: str | None = Field(default=None, min_length=1, max_length=100)
    api_base_url: str | None = Field(default=None, min_length=1, max_length=500)
    api_key: str | None = Field(default=None, min_length=1)
    scope_type: str | None = Field(default=None, pattern="^(company|group|user)$")
    scope_id: str | None = Field(default=None, max_length=36)
    is_enabled: bool | None = None


class ModelCreateRequest(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=120)
    provider_name: str = Field(min_length=1, max_length=100)
    capability: str = Field(min_length=1, max_length=32)
    request_model_name: str = Field(min_length=1, max_length=255)
    api_format: str = Field(default="openai", pattern="^(openai|gemini)$")
    api_endpoint: str | None = Field(default=None, max_length=500)
    is_enabled: bool = True


class ModelUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    provider_name: str | None = Field(default=None, min_length=1, max_length=100)
    capability: str | None = Field(default=None, min_length=1, max_length=32)
    request_model_name: str | None = Field(default=None, min_length=1, max_length=255)
    api_format: str | None = Field(default=None, pattern="^(openai|gemini)$")
    api_endpoint: str | None = Field(default=None, max_length=500)
    is_enabled: bool | None = None


class ModelResponse(BaseModel):
    id: str
    display_name: str
    provider_name: str
    capability: str
    request_model_name: str
    api_format: str
    api_endpoint: str | None
    is_enabled: bool

    model_config = {"from_attributes": True}


class SelectableModelResponse(BaseModel):
    id: str
    name: str
    capability: str


class FeatureModelSetRequest(BaseModel):
    is_default: bool = False
    sort_order: int = Field(default=0, ge=0, le=10000)
    is_enabled: bool = True


class FeatureModelResponse(BaseModel):
    id: str
    feature_key: str
    model_id: str
    is_default: bool
    sort_order: int
    is_enabled: bool

    model_config = {"from_attributes": True}


class AccessRuleSetRequest(BaseModel):
    model_id: str = Field(min_length=1, max_length=64)
    subject_type: str = Field(pattern="^(group|user)$")
    subject_id: str = Field(min_length=1, max_length=36)
    effect: str = Field(pattern="^(allow|deny)$")


class AccessRuleResponse(AccessRuleSetRequest):
    id: str
    feature_key: str

    model_config = {"from_attributes": True}


class UsageLogResponse(BaseModel):
    id: str
    user_id: str | None
    feature_key: str
    model_id: str | None
    credential_scope_type: str | None
    result: str
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class UsageLogListResponse(BaseModel):
    items: list[UsageLogResponse]
    total: int


class AuthorizationOverviewModelResponse(BaseModel):
    model_id: str
    display_name: str
    permission_source: str
    key_available: bool
    credential_scope_type: str | None


class AuthorizationOverviewFeatureResponse(BaseModel):
    feature_key: str
    models: list[AuthorizationOverviewModelResponse]


class AuthorizationOverviewRowResponse(BaseModel):
    subject_type: str
    subject_id: str
    subject_name: str
    has_personal_override: bool
    features: list[AuthorizationOverviewFeatureResponse]


class AuthorizationOverviewCatalogModelResponse(BaseModel):
    model_id: str
    display_name: str
    provider_name: str


class AuthorizationOverviewFeatureCatalogResponse(BaseModel):
    feature_key: str
    models: list[AuthorizationOverviewCatalogModelResponse]


class AuthorizationOverviewGroupResponse(BaseModel):
    subject_id: str
    subject_name: str
    features: list[AuthorizationOverviewFeatureResponse]
    members: list[AuthorizationOverviewRowResponse]


class AuthorizationOverviewResponse(BaseModel):
    features: list[AuthorizationOverviewFeatureCatalogResponse]
    groups: list[AuthorizationOverviewGroupResponse]


class AuthorizationOverviewSelectionRequest(BaseModel):
    model_ids: list[str]
