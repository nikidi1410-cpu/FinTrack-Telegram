from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "config": {
            "gemini_api_key": bool(settings.gemini_api_key),
            "service_account_file": settings.service_account_path.is_file(),
            "spreadsheet_id": bool(settings.google_sheets_spreadsheet_id),
            "telegram_bot_token": bool(settings.telegram_bot_token),
            "whitelist_count": len(settings.whitelist),
        },
    }
