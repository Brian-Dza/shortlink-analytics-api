"""Dashboard UI root endpoint serving the single-page frontend."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

STATIC_DIR = Path(__file__).resolve().parents[3] / "static"

router = APIRouter(include_in_schema=False)


@router.get("/")
async def serve_dashboard() -> FileResponse:
    """Serve the web dashboard entrypoint HTML."""
    return FileResponse(
        STATIC_DIR / "index.html",
        media_type="text/html; charset=utf-8",
    )
