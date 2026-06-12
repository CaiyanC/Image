from datetime import datetime
from typing import Optional, List, Annotated
from pydantic import BaseModel, BeforeValidator
from .common import UuidStr


def empty_to_none(v: Optional[str]) -> Optional[str]:
    if v is None or v == "":
        return None
    return v


OptionalEmail = Annotated[Optional[str], BeforeValidator(empty_to_none)]


class UserGroupInfo(BaseModel):
    group_id: UuidStr
    group_name: str
    group_role: str

    model_config = {"from_attributes": True}


class UserBase(BaseModel):
    username: str
    email: OptionalEmail = None


class UserCreate(UserBase):
    password: str
    display_name: Optional[str] = None


class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: OptionalEmail = None
    password: Optional[str] = None
    display_name: Optional[str] = None
    user_type: Optional[str] = None
    is_active: Optional[bool] = None


class UserProfileUpdate(BaseModel):
    username: Optional[str] = None
    email: OptionalEmail = None
    display_name: Optional[str] = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class AdminPasswordReset(BaseModel):
    new_password: str


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
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
