from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class Token(BaseModel):
    access_token: str
    # False positive: "bearer" is the OAuth2 token TYPE, per RFC 6750, not a
    # credential. The value is public and appears verbatim in every response.
    token_type: str = "bearer"  # noqa: S105


class UserOut(BaseModel):
    id: int
    email: EmailStr
    is_admin: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    is_admin: bool = False
