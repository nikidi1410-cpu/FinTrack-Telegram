import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from app.clients.telegram_client import close_telegram, get_telegram
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.routers import health, telegram
from app.services.scheduler import create_scheduler
from app.services.telegram_polling import run_polling

BOT_COMMANDS = [
    {"command": "ringkasan", "description": "Ringkasan pengeluaran bulan ini"},
    {"command": "budget", "description": "Sisa budget per kategori"},
    {"command": "insight", "description": "Analisis & tips 7 hari terakhir"},
    {"command": "batal", "description": "Batalkan kiriman terakhir"},
    {"command": "start", "description": "Cara pakai"},
]


async def start_bot(mode: str) -> asyncio.Task | None:
    settings = get_settings()
    if mode == "off" or not settings.telegram_bot_token:
        logger.info("Bot Telegram tidak dijalankan (mode={})", mode)
        return None
    bot = get_telegram()
    await bot.call("setMyCommands", commands=BOT_COMMANDS)
    if mode == "webhook":
        if not settings.public_base_url or not settings.webhook_secret:
            raise RuntimeError("TELEGRAM_MODE=webhook butuh PUBLIC_BASE_URL dan WEBHOOK_SECRET di .env")
        url = settings.public_base_url.rstrip("/") + "/webhook/telegram"
        await bot.call("setWebhook", url=url, secret_token=settings.webhook_secret,
                       allowed_updates=["message"])
        logger.info("Webhook Telegram diset ke {}", url)
        return None
    return asyncio.create_task(run_polling(bot), name="telegram-polling")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    logger.info("{} dimulai (env={})", settings.app_name, settings.app_env)
    polling = await start_bot(settings.telegram_mode.lower())
    scheduler = None
    if settings.scheduler_enabled and settings.telegram_bot_token:
        scheduler = create_scheduler()
        scheduler.start()
        logger.info("Scheduler aktif: laporan mingguan Minggu 20:00, bulanan tgl 1 09:00")
    yield
    if scheduler:
        scheduler.shutdown(wait=False)
    if polling:
        polling.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await polling
    await close_telegram()
    logger.info("{} dihentikan", settings.app_name)


app = FastAPI(title="FinTrack-WA", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(telegram.router)
