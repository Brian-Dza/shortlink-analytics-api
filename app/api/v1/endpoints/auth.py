"""Authentication endpoints for user registration and JWT login."""

from fastapi import APIRouter, Depends, status

from app.api.deps import get_auth_service
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
async def register_user(
    payload: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> UserResponse:
    """Create a user account with an Argon2id hashed password."""
    user = await auth_service.register(payload)
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate and obtain a JWT access token",
)
async def login_user(
    payload: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Verify user credentials and return a signed Bearer access token."""
    return await auth_service.login(payload)
