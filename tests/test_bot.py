import asyncio
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.transaction import ExtractionResult, Transaction
from app.services import bot_handler, replies
from app.services.bot_handler import detect_intent
from app.services.sheets_service import AppendResult, BudgetItem, BudgetStatus, MonthlySummary

USER = 7044311934


@pytest.mark.parametrize(
    "text, expected",
    [
        ("/start", ("start", None)),
        ("/ringkasan@Fintrack_Niki_bot", ("ringkasan", None)),
        ("Batal", ("batal", None)),
        ("hapus transaksi terakhir", ("batal", None)),
        ("Bulan ini habis berapa?", ("ringkasan", None)),
        ("sisa budget?", ("budget", None)),
        ("Sisa budget makan?", ("budget", "Makanan & Minuman")),
        ("budget transportasi", ("budget", "Transportasi")),
        ("bensin 50k", ("transaksi", None)),
        ("batal beli sepatu, jadinya beli sandal 80rb", ("transaksi", None)),
        ("rekap belanja 50rb", ("transaksi", None)),
    ],
)
def test_detect_intent(text, expected):
    assert detect_intent(text) == expected


def trx(**kw) -> Transaction:
    base = dict(
        tanggal="2026-10-16", waktu="04:10", nominal=83250, kategori="Belanja Harian",
        merchant="ShopeePay", deskripsi="Pembayaran", metode_pembayaran="ShopeePay",
        tipe_transaksi="Pengeluaran", confidence_score=0.95,
    )
    return Transaction(**{**base, **kw})


def test_reply_single_escapes_html():
    text = replies.append_result(AppendResult(saved=[("TRX-1", trx(merchant="<Toko & Co>"))]))
    assert "Pengeluaran Berhasil Dicatat" in text
    assert "Rp 83.250" in text and "16 Okt 2026 04:10" in text
    assert "&lt;Toko &amp; Co&gt;" in text


def test_reply_multi_with_notes_and_warning():
    saved = [("1", trx()), ("2", trx(nominal=250000, tipe_transaksi="Pemasukan", kategori="Pemasukan",
                                     merchant="Maryeni", confidence_score=0.6))]
    text = replies.append_result(AppendResult(saved=saved, duplicates=[trx()], skipped=[trx(), trx()]))
    assert "2 Transaksi Berhasil Dicatat" in text
    assert "Total pengeluaran: <b>Rp 83.250</b>" in text and "Total pemasukan: <b>Rp 250.000</b>" in text
    assert "⚠️" in text and "1 transaksi dilewati" in text and "2 transaksi bunga" in text


def test_reply_nothing_new():
    text = replies.append_result(AppendResult(duplicates=[trx()]))
    assert "Tidak ada transaksi baru" in text


def test_summary_status_lines():
    s = MonthlySummary(10, 2026, 900_000, 0, 3, {"Makanan & Minuman": 900_000})
    b = BudgetStatus(10, 2026, [BudgetItem("Makanan & Minuman", 1_000_000, 900_000)])
    assert "lebih cepat dari jadwal" in replies.summary(s, b, date(2026, 10, 5))
    assert "batas aman" in replies.summary(s, b, date(2026, 10, 30))
    over = BudgetStatus(10, 2026, [BudgetItem("Makanan & Minuman", 500_000, 900_000)])
    assert "terlampaui" in replies.summary(s, over, date(2026, 10, 30))


class FakeBot:
    def __init__(self):
        self.sent: list[str] = []

    async def send_message(self, chat_id, text):
        self.sent.append(text)

    async def send_typing(self, chat_id):
        pass

    async def download_file(self, file_id):
        return b"img"


def msg(user=USER, **kw) -> dict:
    return {"update_id": 1, "message": {"from": {"id": user}, "chat": {"id": user}, **kw}}


@pytest.fixture
def whitelist(monkeypatch):
    monkeypatch.setattr(bot_handler.get_settings(), "telegram_allowed_user_ids", str(USER))


def test_unknown_user_is_ignored(whitelist):
    bot = FakeBot()
    asyncio.run(bot_handler.handle_update(bot, msg(user=1, text="bensin 50k")))
    assert bot.sent == []


def test_text_transaction_flow(whitelist, monkeypatch):
    calls = {}

    async def fake_extract(text):
        return ExtractionResult(is_valid_transaction=True, transaksi=[trx(nominal=50000, merchant="SPBU")])

    def fake_append(items, user_id):
        calls["user"] = user_id
        return AppendResult(saved=[("TRX-1", t) for t in items])

    monkeypatch.setattr(bot_handler, "extract_transaction_from_text", fake_extract)
    monkeypatch.setattr(bot_handler.sheets_service, "append_transactions", fake_append)
    bot = FakeBot()
    asyncio.run(bot_handler.handle_update(bot, msg(text="bensin 50k")))
    assert calls["user"] == USER
    assert "Rp 50.000" in bot.sent[0]


def test_photo_uses_largest_size_and_caption(whitelist, monkeypatch):
    seen = {}

    async def fake_extract(data, mime, caption=None):
        seen.update(data=data, caption=caption)
        return ExtractionResult(is_valid_transaction=False, pesan_error="Fotonya buram")

    monkeypatch.setattr(bot_handler, "extract_transaction_from_image", fake_extract)
    bot = FakeBot()
    photo = [{"file_id": "small"}, {"file_id": "big"}]
    asyncio.run(bot_handler.handle_update(bot, msg(photo=photo, caption="belanja bulanan")))
    assert seen == {"data": b"img", "caption": "belanja bulanan"}
    assert "Fotonya buram" in bot.sent[0]


def test_error_still_replies(whitelist, monkeypatch):
    def boom(user_id):
        raise RuntimeError("sheets down")

    monkeypatch.setattr(bot_handler.sheets_service, "void_last_transaction", boom)
    bot = FakeBot()
    asyncio.run(bot_handler.handle_update(bot, msg(text="batal")))
    assert bot.sent == [replies.ERROR]


def test_webhook_disabled_outside_webhook_mode():
    with TestClient(app) as client:
        assert client.post("/webhook/telegram", json={}).status_code == 404
