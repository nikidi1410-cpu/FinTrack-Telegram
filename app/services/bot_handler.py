"""Otak bot: terima satu update Telegram, tentukan maksudnya, lalu balas."""

import asyncio
import re
from html import escape
from datetime import datetime
from zoneinfo import ZoneInfo

from loguru import logger

from app.clients.telegram_client import TelegramClient
from app.core.config import get_settings
from app.schemas.transaction import ExtractionResult
from app.services import replies, sheets_service
from app.services.ai_extractor import extract_transaction_from_image, extract_transaction_from_text
from app.services.analytics_service import weekly_insight

# Satu pesan diproses sampai selesai sebelum pesan berikutnya, supaya cek duplikat
# dan "batal" selalu melihat data terbaru.
_lock = asyncio.Lock()

BATAL = {"batal", "batalkan", "undo", "cancel", "hapus", "hapus transaksi terakhir", "batalkan transaksi terakhir"}
RINGKASAN = ("habis berapa", "ringkasan", "rekap", "total pengeluaran", "pengeluaran bulan ini", "keluar berapa")
BUDGET = ("budget", "anggaran")
INSIGHT = ("insight", "analisis", "evaluasi", "saran hemat", "tips hemat")
# Kata kunci -> kategori, untuk "sisa budget makan?"
KATEGORI_ALIAS = {
    "makan": "Makanan & Minuman", "minum": "Makanan & Minuman", "jajan": "Makanan & Minuman",
    "transport": "Transportasi", "bensin": "Transportasi", "ojol": "Transportasi",
    "belanja": "Belanja Harian",
    "tagihan": "Tagihan & Utilitas", "listrik": "Tagihan & Utilitas", "pulsa": "Tagihan & Utilitas",
    "hiburan": "Hiburan & Lifestyle", "lifestyle": "Hiburan & Lifestyle", "nongkrong": "Hiburan & Lifestyle",
    "kesehatan": "Kesehatan & Kebersihan", "obat": "Kesehatan & Kebersihan", "skincare": "Kesehatan & Kebersihan",
    "pendidikan": "Pendidikan & Kerja", "kerja": "Pendidikan & Kerja", "kursus": "Pendidikan & Kerja",
    "lain": "Lain-lain",
}


def detect_intent(text: str) -> tuple[str, str | None]:
    """-> (intent, kategori). intent: start | batal | insight | ringkasan | budget | transaksi."""
    t = re.sub(r"[^\w\s/]", " ", text.lower()).strip()
    t = re.sub(r"\s+", " ", t)
    command = t.split("@")[0].split(" ")[0] if t.startswith("/") else ""

    if command in ("/start", "/help", "/bantuan") or t in ("help", "bantuan", "menu"):
        return "start", None
    if command == "/batal" or t in BATAL:
        return "batal", None
    if command == "/insight" or (any(k in t for k in INSIGHT) and not re.search(r"\d", t)):
        return "insight", None
    if command == "/budget" or (any(k in t for k in BUDGET) and not re.search(r"\d", t)):
        kategori = next((v for k, v in KATEGORI_ALIAS.items() if any(w.startswith(k) for w in t.split())), None)
        return "budget", kategori
    if command == "/ringkasan" or (any(k in t for k in RINGKASAN) and not re.search(r"\d+\s*(k|rb|ribu|jt)\b", t)):
        return "ringkasan", None
    return "transaksi", None


def _image_file(message: dict) -> tuple[str, str] | None:
    """(file_id, mime_type) dari foto atau gambar yang dikirim sebagai file."""
    if message.get("photo"):
        return message["photo"][-1]["file_id"], "image/jpeg"  # elemen terakhir = resolusi terbesar
    doc = message.get("document") or {}
    if str(doc.get("mime_type", "")).startswith("image/"):
        return doc["file_id"], doc["mime_type"]
    return None


async def _save(user_id: int, result: ExtractionResult) -> str:
    if not result.is_valid_transaction:
        return f"🤔 {escape(result.pesan_error or '')}"
    saved = await asyncio.to_thread(sheets_service.append_transactions, result.transaksi, user_id)
    logger.info("User {}: {} disimpan, {} duplikat, {} dilewati",
                user_id, len(saved.saved), len(saved.duplicates), len(saved.skipped))
    return replies.append_result(saved)


async def _reply_for(bot: TelegramClient, message: dict, user_id: int) -> str:
    chat_id = message["chat"]["id"]
    image = _image_file(message)
    text = message.get("text") or ""

    if image:
        await bot.send_typing(chat_id)
        file_id, mime = image
        data = await bot.download_file(file_id)
        result = await extract_transaction_from_image(data, mime, caption=message.get("caption"))
        return await _save(user_id, result)

    if not text:
        return replies.UNSUPPORTED

    intent, kategori = detect_intent(text)
    if intent == "start":
        return replies.WELCOME
    if intent == "batal":
        rows = await asyncio.to_thread(sheets_service.void_last_transaction, user_id)
        return replies.voided(rows)
    if intent == "ringkasan":
        s = await asyncio.to_thread(sheets_service.get_monthly_summary)
        b = await asyncio.to_thread(sheets_service.get_budget_status)
        today = datetime.now(ZoneInfo(get_settings().timezone)).date()
        return replies.summary(s, b, today)
    if intent == "insight":
        await bot.send_typing(chat_id)
        return await weekly_insight(datetime.now(ZoneInfo(get_settings().timezone)).date())
    if intent == "budget":
        b = await asyncio.to_thread(sheets_service.get_budget_status)
        return replies.budget(b, kategori)

    await bot.send_typing(chat_id)
    result = await extract_transaction_from_text(text)
    return await _save(user_id, result)


async def handle_update(bot: TelegramClient, update: dict) -> None:
    message = update.get("message")
    if not message or "from" not in message:
        return
    user_id = message["from"]["id"]
    chat_id = message["chat"]["id"]
    if user_id not in get_settings().whitelist:
        logger.warning("Pesan dari user {} (@{}) diabaikan: tidak ada di whitelist",
                       user_id, message["from"].get("username"))
        return

    async with _lock:
        try:
            reply = await _reply_for(bot, message, user_id)
        except Exception:
            logger.exception("Gagal memproses update {}", update.get("update_id"))
            reply = replies.ERROR
        await bot.send_message(chat_id, reply)
