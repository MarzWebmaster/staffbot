from pydantic import BaseModel, Field
from typing import Optional


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    sub: str
    role: str
    exp: float


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6)
