from datetime import datetime

import pytest

from app.schemas.transaction import Transaction
from app.services import sheets_service as svc


class FakeWorksheet:
    """Meniru tab Transaksi: menyimpan baris seperti yang dibaca kembali dari Sheets."""

    def __init__(self):
        self.values = [list(svc.TRANSAKSI_HEADERS)]

    def get_values(self, **kwargs):
        return [list(r) for r in self.values]

    def append_rows(self, rows, **kwargs):
        for r in rows:
            self.values.append([v[1:] if isinstance(v, str) and v.startswith("'") else v for v in r])

    def batch_update(self, data, **kwargs):
        status_idx = svc.TRANSAKSI_HEADERS.index("Status")
        for d in data:
            row = int(d["range"].lstrip(svc.col("Status")))
            self.values[row - 1][status_idx] = d["values"][0][0]


@pytest.fixture
def ws(monkeypatch):
    sheet = FakeWorksheet()
    monkeypatch.setattr(svc, "_worksheet", lambda title: sheet)
    return sheet


def trx(**kw) -> Transaction:
    base = dict(
        tanggal="2026-10-16", waktu="04:10", nominal=83250, kategori="Belanja Harian",
        merchant="ShopeePay", deskripsi="Pembayaran", metode_pembayaran="ShopeePay",
        tipe_transaksi="Pengeluaran", confidence_score=0.95,
    )
    return Transaction(**{**base, **kw})


BUNGA = dict(nominal=2, kategori="Pemasukan", merchant="Bunga Tabungan", deskripsi="Bunga", tipe_transaksi="Pemasukan")


def test_skip_bunga_but_keep_toko_bunga(ws):
    result = svc.append_transactions([trx(**BUNGA), trx(merchant="Toko Bunga Melati")], 1)
    assert [t.merchant for _, t in result.saved] == ["Toko Bunga Melati"]
    assert len(result.skipped) == 1


def test_catat_bunga_setting(ws, monkeypatch):
    monkeypatch.setattr(svc.get_settings(), "catat_bunga", True)
    assert len(svc.append_transactions([trx(**BUNGA)], 1).saved) == 1


def test_duplicate_screenshot_is_not_saved_twice(ws):
    batch = [trx(), trx(waktu="02:21")]
    assert len(svc.append_transactions(batch, 1).saved) == 2
    again = svc.append_transactions(batch, 1)
    assert again.saved == [] and len(again.duplicates) == 2
    # Pengguna lain dengan transaksi yang sama tetap dicatat.
    assert len(svc.append_transactions(batch, 2).saved) == 2


def test_text_without_time_is_never_duplicate(ws):
    bensin = trx(waktu=None, nominal=50000, merchant="SPBU")
    svc.append_transactions([bensin], 1)
    assert len(svc.append_transactions([bensin], 1).saved) == 1


def test_ids_are_sequential(ws):
    ids = [i for i, _ in svc.append_transactions([trx(), trx(waktu="05:00")], 1).saved]
    ids += [i for i, _ in svc.append_transactions([trx(waktu="06:00")], 1).saved]
    assert [i[-4:] for i in ids] == ["0001", "0002", "0003"]


def test_formula_like_text_is_escaped(ws):
    svc.append_transactions([trx(merchant="=HYPERLINK(\"x\")")], 1)
    assert ws.values[1][svc.TRANSAKSI_HEADERS.index("Merchant")] == '=HYPERLINK("x")'  # tersimpan sebagai teks


def test_void_last_batch_only_for_that_user(ws, monkeypatch):
    times = iter(datetime(2026, 10, 21, hour) for hour in (10, 11, 12))
    monkeypatch.setattr(svc, "_now", lambda: next(times))  # tiap kiriman punya Timestamp berbeda
    svc.append_transactions([trx(), trx(waktu="02:21")], 1)  # kiriman 1: screenshot
    svc.append_transactions([trx(waktu=None, nominal=25000)], 1)  # kiriman 2: teks
    svc.append_transactions([trx(waktu="09:00")], 2)  # pengguna lain

    assert [r.nominal for r in svc.void_last_transaction(1)] == [25000]
    assert len(svc.void_last_transaction(1)) == 2
    assert svc.void_last_transaction(1) == []
    assert [r.active for r in svc._read_rows(ws) if r.pengirim == "2"] == [True]
