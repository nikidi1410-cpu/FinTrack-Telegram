"""Pengguna dengan spreadsheet sendiri tidak boleh saling melihat atau mengubah data."""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.transaction import ExtractionResult, Transaction
from app.services import bot_handler, scheduler
from app.services import sheets_service as svc
from scripts.setup_sheets import parse_spreadsheet_id

ANAK, IBU = 111, 222
SHEET_UTAMA, SHEET_IBU = "sheet-utama", "sheet-ibu"
HEADERS = list(svc.TRANSAKSI_HEADERS)


class FakeWorksheet:
    def __init__(self, values):
        self.values = values

    def get_values(self, **kwargs):
        return [list(r) for r in self.values]

    def append_rows(self, rows, **kwargs):
        for r in rows:
            self.values.append([v[1:] if isinstance(v, str) and v.startswith("'") else v for v in r])

    def batch_update(self, data, **kwargs):
        status = HEADERS.index("Status")
        for d in data:
            self.values[int(d["range"].lstrip(svc.col("Status"))) - 1][status] = d["values"][0][0]


class FakeSpreadsheet:
    def __init__(self):
        settings = svc.get_settings()
        self.tabs = {
            settings.sheet_transaksi: FakeWorksheet([list(HEADERS)]),
            settings.sheet_budget: FakeWorksheet([["Kategori", "Budget_Bulanan"], ["Transportasi", 800_000]]),
        }

    def worksheet(self, title):
        return self.tabs[title]

    @property
    def transaksi(self):
        return self.tabs[svc.get_settings().sheet_transaksi].values[1:]


@pytest.fixture
def sheets(monkeypatch):
    settings = svc.get_settings()
    monkeypatch.setattr(settings, "telegram_allowed_user_ids", str(ANAK))
    monkeypatch.setattr(settings, "google_sheets_spreadsheet_id", SHEET_UTAMA)
    monkeypatch.setattr(settings, "user_spreadsheets", f"{IBU}:{SHEET_IBU}")
    fakes = {SHEET_UTAMA: FakeSpreadsheet(), SHEET_IBU: FakeSpreadsheet()}
    monkeypatch.setattr(svc, "get_spreadsheet", lambda spreadsheet_id: fakes[spreadsheet_id])
    return fakes


class FakeBot:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))

    async def send_typing(self, chat_id):
        pass


def trx(nominal: int, merchant: str) -> Transaction:
    today = datetime.now(ZoneInfo(svc.get_settings().timezone)).date().isoformat()
    return Transaction(
        tanggal=today, waktu=None, nominal=nominal, kategori="Transportasi", merchant=merchant,
        deskripsi="Bensin", metode_pembayaran="Tunai", tipe_transaksi="Pengeluaran", confidence_score=0.95,
    )


def send(bot: FakeBot, user: int, text: str) -> str:
    update = {"update_id": 1, "message": {"from": {"id": user}, "chat": {"id": user}, "text": text}}
    asyncio.run(bot_handler.handle_update(bot, update))
    return bot.sent[-1][1]


def record(monkeypatch, nominal: int, merchant: str):
    async def fake_extract(text):
        return ExtractionResult(is_valid_transaction=True, transaksi=[trx(nominal, merchant)])

    monkeypatch.setattr(bot_handler, "extract_transaction_from_text", fake_extract)


def test_whitelist_includes_users_with_own_spreadsheet():
    s = Settings(_env_file=None, telegram_allowed_user_ids="111", user_spreadsheets="222:abc, 333:def")
    assert s.whitelist == {111, 222, 333}


def test_each_user_resolves_to_own_spreadsheet():
    s = Settings(_env_file=None, google_sheets_spreadsheet_id="utama", telegram_allowed_user_ids="111",
                 user_spreadsheets="222:abc")
    assert s.spreadsheet_id_for(111) == "utama"
    assert s.spreadsheet_id_for(222) == "abc"
    assert s.spreadsheet_id_for("222") == "abc"  # kolom Pengirim berupa teks


@pytest.mark.parametrize("value", ["222", "abc:sheet", "222:", ":sheet"])
def test_invalid_user_spreadsheets_is_rejected(value):
    with pytest.raises(ValidationError, match="USER_SPREADSHEETS"):
        Settings(_env_file=None, user_spreadsheets=value)


def test_transaction_goes_to_senders_spreadsheet(sheets, monkeypatch):
    record(monkeypatch, 50_000, "SPBU Ibu")
    send(FakeBot(), IBU, "bensin 50k")
    assert [r[HEADERS.index("Merchant")] for r in sheets[SHEET_IBU].transaksi] == ["SPBU Ibu"]
    assert sheets[SHEET_UTAMA].transaksi == []


def test_summary_and_budget_only_show_own_data(sheets, monkeypatch):
    bot = FakeBot()
    record(monkeypatch, 111_000, "SPBU Anak")
    send(bot, ANAK, "bensin")
    record(monkeypatch, 222_000, "SPBU Ibu")
    send(bot, IBU, "bensin")

    for intent in ("/ringkasan", "/budget"):
        punya_anak, punya_ibu = send(bot, ANAK, intent), send(bot, IBU, intent)
        assert "111.000" in punya_anak and "222.000" not in punya_anak
        assert "222.000" in punya_ibu and "111.000" not in punya_ibu


def test_void_only_touches_own_spreadsheet(sheets, monkeypatch):
    bot = FakeBot()
    record(monkeypatch, 111_000, "SPBU Anak")
    send(bot, ANAK, "bensin")
    record(monkeypatch, 222_000, "SPBU Ibu")
    send(bot, IBU, "bensin")

    send(bot, IBU, "batal")
    status = HEADERS.index("Status")
    assert sheets[SHEET_IBU].transaksi[0][status] == "Void"
    assert sheets[SHEET_UTAMA].transaksi[0][status] == "Active"


def test_weekly_facts_use_own_spreadsheet(sheets):
    today = datetime.now(ZoneInfo(svc.get_settings().timezone)).date()
    svc.append_transactions([trx(111_000, "SPBU Anak")], ANAK)
    svc.append_transactions([trx(222_000, "SPBU Ibu")], IBU)

    from app.services.analytics_service import weekly_facts
    assert weekly_facts(ANAK, today)["total_pengeluaran"] == 111_000
    assert weekly_facts(IBU, today)["total_pengeluaran"] == 222_000


def test_scheduled_report_is_built_per_user(sheets, monkeypatch):
    bot = FakeBot()
    monkeypatch.setattr(scheduler, "get_telegram", lambda: bot)

    async def fake_weekly(user_id, today):
        return f"laporan milik {user_id}"

    monkeypatch.setattr(scheduler, "weekly_insight", fake_weekly)
    asyncio.run(scheduler.send_weekly())
    assert sorted(bot.sent) == [(ANAK, f"laporan milik {ANAK}"), (IBU, f"laporan milik {IBU}")]


def test_report_failure_for_one_user_does_not_stop_others(sheets, monkeypatch):
    bot = FakeBot()
    monkeypatch.setattr(scheduler, "get_telegram", lambda: bot)

    async def fake_monthly(user_id, month, year):
        if user_id == ANAK:
            raise RuntimeError("spreadsheet tidak bisa dibuka")
        return "laporan ibu"

    monkeypatch.setattr(scheduler, "monthly_insight", fake_monthly)
    asyncio.run(scheduler.send_monthly())
    assert bot.sent == [(IBU, "laporan ibu")]


def test_setup_script_accepts_id_or_url():
    assert parse_spreadsheet_id("abc_DEF-123") == "abc_DEF-123"
    assert parse_spreadsheet_id("https://docs.google.com/spreadsheets/d/abc_DEF-123/edit#gid=0") == "abc_DEF-123"
