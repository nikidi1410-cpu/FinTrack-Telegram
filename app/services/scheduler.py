"""Jadwal laporan otomatis: mingguan (Minggu 20:00) & bulanan (tgl 1, 09:00) WIB."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from app.clients.telegram_client import get_telegram
from app.core.config import get_settings
from app.services.analytics_service import monthly_insight, weekly_insight


def _now() -> datetime:
    return datetime.now(ZoneInfo(get_settings().timezone))


async def _broadcast(text: str) -> None:
    bot = get_telegram()
    for user_id in get_settings().whitelist:  # chat pribadi: chat_id == user_id
        try:
            await bot.send_message(user_id, text)
        except Exception:
            logger.exception("Gagal kirim laporan ke {}", user_id)


async def send_weekly() -> None:
    logger.info("Mengirim laporan mingguan")
    await _broadcast(await weekly_insight(_now().date()))


async def send_monthly() -> None:
    last_month = _now().date().replace(day=1) - timedelta(days=1)
    logger.info("Mengirim review bulanan {}-{}", last_month.month, last_month.year)
    await _broadcast(await monthly_insight(last_month.month, last_month.year))


def create_scheduler() -> AsyncIOScheduler:
    tz = ZoneInfo(get_settings().timezone)
    # misfire_grace_time: kalau laptop sempat sleep melewati jadwal, laporan tetap dikirim saat bangun
    # (maks. 3 jam). Jadwal yang lewat saat program mati tidak dikirim ulang.
    opts = {"misfire_grace_time": 3 * 3600, "coalesce": True}
    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(send_weekly, CronTrigger(day_of_week="sun", hour=20, timezone=tz), id="weekly", **opts)
    scheduler.add_job(send_monthly, CronTrigger(day=1, hour=9, timezone=tz), id="monthly", **opts)
    return scheduler
