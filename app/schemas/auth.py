"""Pydantic schemas for user registration, login, and JWT tokens."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    """Input payload for creating a new user account."""

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Normalize email casing and surrounding whitespace."""
        return value.strip().lower()


class LoginRequest(BaseModel):
    """Input payload for authenticating with email and password."""

    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Normalize email casing and surrounding whitespace."""
        return value.strip().lower()


class UserResponse(BaseModel):
    """Public representation of a registered user."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    created_at: datetime


class TokenResponse(BaseModel):
    """JWT access token response returned on successful login."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int
