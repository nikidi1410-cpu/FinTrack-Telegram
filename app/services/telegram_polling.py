"""Long polling: bot menarik pesan baru dari Telegram (untuk jalan di laptop tanpa URL publik)."""

import asyncio

import httpx
from loguru import logger

from app.clients.telegram_client import TelegramClient, TelegramError
from app.services.bot_handler import handle_update


async def run_polling(bot: TelegramClient) -> None:
    # Polling dan webhook tidak bisa aktif bersamaan. Pesan yang tertunda tetap diproses.
    await bot.call("deleteWebhook", drop_pending_updates=False)
    me = await bot.call("getMe")
    logger.info("Bot @{} aktif (mode polling)", me["username"])

    offset = None
    while True:
        try:
            updates = await bot.get_updates(offset)
        except (httpx.HTTPError, TelegramError) as exc:
            logger.warning("getUpdates gagal ({}), coba lagi 5 dtk", exc)
            await asyncio.sleep(5)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            try:
                await handle_update(bot, update)
            except Exception:  # satu pesan gagal (mis. kirim balasan error) tidak boleh mematikan bot
                logger.exception("Update {} gagal ditangani", update["update_id"])
