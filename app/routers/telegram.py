import secrets

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from app.clients.telegram_client import get_telegram
from app.core.config import get_settings
from app.services.bot_handler import handle_update

router = APIRouter(tags=["telegram"])


@router.post("/webhook/telegram")
async def telegram_webhook(
    request: Request,
    background: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    """Dipanggil Telegram tiap ada pesan masuk (mode webhook)."""
    settings = get_settings()
    if settings.telegram_mode.lower() != "webhook":
        raise HTTPException(status_code=404)
    # Tanpa secret, siapa pun bisa mengirim update palsu atas nama user di whitelist.
    expected = settings.webhook_secret
    if not expected or not secrets.compare_digest(x_telegram_bot_api_secret_token or "", expected):
        raise HTTPException(status_code=403, detail="secret token salah")
    update = await request.json()
    # Balas 200 secepatnya; Telegram mengirim ulang update bila respons lambat.
    background.add_task(handle_update, get_telegram(), update)
    return {"ok": True}
