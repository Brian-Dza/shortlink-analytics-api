"""Public short link resolution, HTTP 307 redirect, and async click recording."""

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from fastapi.responses import RedirectResponse

from app.api.deps import get_app_settings, get_link_service
from app.core.config import Settings
from app.services.analytics_service import extract_click_metadata, record_click_background
from app.services.link_service import LinkService

router = APIRouter(tags=["Redirect"])


@router.get(
    "/{short_code}",
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    summary="Resolve short link and redirect with HTTP 307",
)
async def redirect_short_link(
    short_code: str,
    request: Request,
    background_tasks: BackgroundTasks,
    link_service: LinkService = Depends(get_link_service),
    settings: Settings = Depends(get_app_settings),
) -> RedirectResponse:
    """Resolve short_code via Cache-Aside and schedule non-blocking click telemetry."""
    resolved = await link_service.resolve_short_code(short_code)
    metadata = extract_click_metadata(
        request,
        ip_hash_salt=settings.ip_hash_salt.get_secret_value(),
    )
    background_tasks.add_task(
        record_click_background,
        session_factory=request.app.state.session_factory,
        link_id=resolved.link_id,
        metadata=metadata,
    )
    return RedirectResponse(
        url=resolved.original_url,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Cache-Control": "no-store"},
    )
