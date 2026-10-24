import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services import ai_extractor

TRX = {
    "tanggal": "2026-10-21",
    "waktu": None,
    "nominal": 50000,
    "kategori": "Transportasi",
    "merchant": "SPBU",
    "deskripsi": "bensin",
    "metode_pembayaran": "Tunai",
    "tipe_transaksi": "Pengeluaran",
    "confidence_score": 0.95,
}


def fake_gemini(monkeypatch, raw: str) -> None:
    async def generate_content(**kwargs):
        return SimpleNamespace(text=raw)

    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    monkeypatch.setattr(ai_extractor, "get_gemini_client", lambda: client)


def run(coro):
    return asyncio.run(coro)


def test_text_valid(monkeypatch):
    fake_gemini(monkeypatch, json.dumps({"is_valid_transaction": True, "transaksi": [TRX]}))
    result = run(ai_extractor.extract_transaction_from_text("bensin 50k"))
    assert result.is_valid_transaction
    assert result.transaksi[0].nominal == 50000


def test_image_multiple_transactions(monkeypatch):
    income = {**TRX, "nominal": 250000, "kategori": "Pemasukan", "tipe_transaksi": "Pemasukan"}
    fake_gemini(monkeypatch, json.dumps({"is_valid_transaction": True, "transaksi": [TRX, income]}))
    result = run(ai_extractor.extract_transaction_from_image(b"fake-bytes"))
    assert [t.tipe_transaksi for t in result.transaksi] == ["Pengeluaran", "Pemasukan"]


def test_valid_but_empty_becomes_invalid(monkeypatch):
    fake_gemini(monkeypatch, json.dumps({"is_valid_transaction": True, "transaksi": []}))
    result = run(ai_extractor.extract_transaction_from_text("??"))
    assert not result.is_valid_transaction
    assert result.pesan_error


@pytest.mark.parametrize(
    "raw",
    [
        "bukan json",
        json.dumps({"is_valid_transaction": True, "transaksi": [{**TRX, "nominal": -5}]}),
        json.dumps({"is_valid_transaction": True, "transaksi": [{**TRX, "kategori": "Ngawur"}]}),
    ],
)
def test_bad_output_falls_back_to_error(monkeypatch, raw):
    fake_gemini(monkeypatch, raw)
    result = run(ai_extractor.extract_transaction_from_text("bensin 50k"))
    assert not result.is_valid_transaction
    assert result.transaksi == []
    assert result.pesan_error
