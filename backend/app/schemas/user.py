from datetime import datetime
from typing import Optional, List, Annotated
from pydantic import BaseModel, BeforeValidator, Field
from .common import UuidStr


def empty_to_none(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    normalized = v.strip()
    return normalized or None


OptionalEmail = Annotated[Optional[str], BeforeValidator(empty_to_none)]


class UserGroupInfo(BaseModel):
    group_id: UuidStr
    group_name: str
    group_role: str

    model_config = {"from_attributes": True}


class UserBase(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    email: OptionalEmail = Field(default=None, max_length=255)


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=100)


class UserUpdate(BaseModel):
    username: Optional[str] = Field(default=None, min_length=1, max_length=100)
    email: OptionalEmail = Field(default=None, max_length=255)
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=100)
    user_type: Optional[str] = Field(default=None, min_length=1, max_length=50)
    is_active: Optional[bool] = None


class UserProfileUpdate(BaseModel):
    username: Optional[str] = Field(default=None, min_length=1, max_length=100)
    email: OptionalEmail = Field(default=None, max_length=255)
    display_name: Optional[str] = Field(default=None, max_length=100)


class PasswordChange(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class AdminPasswordReset(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)


class UserResponse(UserBase):
    id: UuidStr
    user_type: str
    display_name: Optional[str] = None
    is_active: bool
    groups: List[UserGroupInfo] = []
    permissions: List[str] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=128)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
