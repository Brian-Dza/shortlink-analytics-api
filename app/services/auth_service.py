"""Authentication business logic service."""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import ConflictException, UnauthorizedException
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse


class AuthService:
    """Handles user registration, credential verification, and user resolution."""

    def __init__(
        self,
        session: AsyncSession,
        user_repo: UserRepository,
        settings: Settings,
    ) -> None:
        self._session = session
        self._user_repo = user_repo
        self._settings = settings

    async def register(self, payload: RegisterRequest) -> User:
        """Register a new user account with an Argon2id password hash."""
        existing = await self._user_repo.get_by_email(payload.email)
        if existing is not None:
            raise ConflictException(
                "An account with this email already exists.",
                code="EMAIL_ALREADY_REGISTERED",
            )

        hashed_password = hash_password(payload.password)
        try:
            user = await self._user_repo.create(
                email=payload.email,
                hashed_password=hashed_password,
            )
        except IntegrityError as exc:
            raise ConflictException(
                "An account with this email already exists.",
                code="EMAIL_ALREADY_REGISTERED",
            ) from exc

        await self._session.commit()
        return user

    async def login(self, payload: LoginRequest) -> TokenResponse:
        """Authenticate credentials and issue a signed JWT access token."""
        user = await self._user_repo.get_by_email(payload.email)
        if user is None or not verify_password(payload.password, user.hashed_password):
            raise UnauthorizedException(
                "Invalid email or password.",
                code="INVALID_CREDENTIALS",
            )

        token, expires_in = create_access_token(
            subject=str(user.id),
            settings=self._settings,
        )
        return TokenResponse(access_token=token, expires_in=expires_in)

    async def get_user_by_id(self, user_id: uuid.UUID) -> User:
        """Resolve an authenticated user by UUID or fail with 401."""
        user = await self._user_repo.get_by_id(user_id)
        if user is None:
            raise UnauthorizedException(
                "Authenticated user no longer exists.",
                code="USER_NOT_FOUND",
            )
        return user
