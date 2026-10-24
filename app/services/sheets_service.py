"""Repository Google Sheets: simpan, batalkan, dan ringkas transaksi.

Semua fungsi di sini sinkron (gspread). Dari handler async, panggil lewat
`asyncio.to_thread(...)` agar event loop tidak terblokir.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

import gspread
from gspread.utils import DateTimeOption, ValueRenderOption, rowcol_to_a1

from app.clients.sheets_client import get_spreadsheet
from app.core.config import get_settings
from app.schemas.transaction import KATEGORI_PENGELUARAN, Transaction

TRANSAKSI_HEADERS = [
    "ID_Transaksi", "Timestamp", "Tanggal", "Waktu", "Tipe", "Kategori", "Nominal",
    "Merchant", "Keterangan", "Metode", "Status", "Pengirim",
]


def col(header: str) -> str:
    """Huruf kolom untuk header tab Transaksi, mis. col("Nominal") -> "G"."""
    return rowcol_to_a1(1, TRANSAKSI_HEADERS.index(header) + 1).rstrip("1")


@dataclass
class TransactionRow:
    row: int  # nomor baris di sheet (header = baris 1)
    id: str
    timestamp: str
    tanggal: str
    waktu: str
    tipe: str
    kategori: str
    nominal: int
    merchant: str
    keterangan: str
    metode: str
    status: str
    pengirim: str

    @property
    def active(self) -> bool:
        return self.status == "Active"


@dataclass
class AppendResult:
    saved: list[tuple[str, Transaction]] = field(default_factory=list)  # (ID_Transaksi, data)
    duplicates: list[Transaction] = field(default_factory=list)
    skipped: list[Transaction] = field(default_factory=list)  # mis. bunga tabungan


@dataclass
class MonthlySummary:
    month: int
    year: int
    total_pengeluaran: int
    total_pemasukan: int
    jumlah_transaksi: int
    per_kategori: dict[str, int]  # pengeluaran per kategori, urut terbesar


@dataclass
class BudgetItem:
    kategori: str
    budget: int
    terpakai: int

    @property
    def sisa(self) -> int:
        return self.budget - self.terpakai

    @property
    def persen(self) -> int:
        return round(self.terpakai / self.budget * 100) if self.budget else 0


@dataclass
class BudgetStatus:
    month: int
    year: int
    items: list[BudgetItem]

    @property
    def total_budget(self) -> int:
        return sum(i.budget for i in self.items)

    @property
    def total_terpakai(self) -> int:
        return sum(i.terpakai for i in self.items)

    @property
    def persen(self) -> int:
        return round(self.total_terpakai / self.total_budget * 100) if self.total_budget else 0


# ---------- helper ----------

def _now() -> datetime:
    return datetime.now(ZoneInfo(get_settings().timezone))


def _worksheet(title: str) -> gspread.Worksheet:
    return get_spreadsheet().worksheet(title)


def _norm_time(value: str | None) -> str:
    """'4:10' / '04:10:00' -> '04:10'; kosong -> ''."""
    if not value:
        return ""
    parts = str(value).strip().split(":")
    try:
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    except (IndexError, ValueError):
        return str(value).strip()


def _as_text(value: str) -> str:
    """Cegah teks dari AI/pengguna terbaca sebagai rumus (mis. '=...', '+62...')."""
    return f"'{value}" if value and value[0] in "=+-@" else value


def _to_int(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _read_rows(ws: gspread.Worksheet) -> list[TransactionRow]:
    values = ws.get_values(
        value_render_option=ValueRenderOption.unformatted,
        date_time_render_option=DateTimeOption.formatted_string,
    )
    rows = []
    for i, v in enumerate(values[1:], start=2):
        v = list(v) + [""] * (len(TRANSAKSI_HEADERS) - len(v))
        if not v[0]:
            continue
        rows.append(TransactionRow(
            row=i, id=str(v[0]), timestamp=str(v[1]), tanggal=str(v[2]), waktu=_norm_time(str(v[3])),
            tipe=str(v[4]), kategori=str(v[5]), nominal=_to_int(v[6]), merchant=str(v[7]),
            keterangan=str(v[8]), metode=str(v[9]), status=str(v[10]),
            pengirim=str(_to_int(v[11]) or v[11]),
        ))
    return rows


def _is_bunga(t: Transaction) -> bool:
    text = f"{t.merchant} {t.deskripsi}".lower()
    # Hanya pemasukan bunga & pajaknya; "Toko Bunga" (pengeluaran beli bunga) tetap dicatat.
    return (t.tipe_transaksi == "Pemasukan" and "bunga" in text) or "pajak bunga" in text


def _dedup_key(tanggal: str, waktu: str, nominal: int, tipe: str) -> tuple:
    return tanggal, waktu, nominal, tipe


# ---------- API ----------

def append_transactions(transactions: list[Transaction], user_id: int | str) -> AppendResult:
    """Simpan transaksi ke tab Transaksi.

    Dilewati: bunga tabungan (jika CATAT_BUNGA=false) dan duplikat, yaitu transaksi
    yang tanggal + jam + nominal + tipe-nya sama persis dengan transaksi aktif milik
    pengirim yang sama. Transaksi tanpa jam (umumnya input teks) tidak dicek duplikat,
    karena "bensin 50k" dua kali sehari bisa saja memang dua transaksi.
    """
    settings = get_settings()
    user = str(user_id)
    ws = _worksheet(settings.sheet_transaksi)
    existing = _read_rows(ws)
    seen = {
        _dedup_key(r.tanggal, r.waktu, r.nominal, r.tipe)
        for r in existing if r.active and r.pengirim == user and r.waktu
    }

    now = _now()
    prefix = f"TRX-{now:%Y%m%d}-"
    seq = sum(r.id.startswith(prefix) for r in existing)
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    result = AppendResult()
    rows = []
    for t in transactions:
        if not settings.catat_bunga and _is_bunga(t):
            result.skipped.append(t)
            continue
        waktu = _norm_time(t.waktu)
        if waktu and _dedup_key(t.tanggal, waktu, t.nominal, t.tipe_transaksi) in seen:
            result.duplicates.append(t)
            continue
        seq += 1
        trx_id = f"{prefix}{seq:04d}"
        rows.append([
            trx_id, timestamp, t.tanggal, waktu, t.tipe_transaksi, t.kategori, t.nominal,
            _as_text(t.merchant), _as_text(t.deskripsi), _as_text(t.metode_pembayaran),
            "Active", f"'{user}",
        ])
        result.saved.append((trx_id, t))

    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED", table_range="A1")
    return result


def void_last_transaction(user_id: int | str) -> list[TransactionRow]:
    """Tandai Void kiriman terakhir pengguna (semua baris dari satu pesan/screenshot).

    Mengembalikan baris yang dibatalkan; list kosong jika tidak ada yang bisa dibatalkan.
    """
    ws = _worksheet(get_settings().sheet_transaksi)
    mine = [r for r in _read_rows(ws) if r.active and r.pengirim == str(user_id)]
    if not mine:
        return []
    last_ts = mine[-1].timestamp
    targets = [r for r in mine if r.timestamp == last_ts]
    ws.batch_update(
        [{"range": f"{col('Status')}{r.row}", "values": [["Void"]]} for r in targets],
        value_input_option="RAW",
    )
    for r in targets:
        r.status = "Void"
    return targets


def list_transactions(start: date, end: date) -> list[TransactionRow]:
    """Transaksi aktif dengan Tanggal di antara start dan end (inklusif)."""
    rows = []
    for r in _read_rows(_worksheet(get_settings().sheet_transaksi)):
        try:
            if r.active and start <= date.fromisoformat(r.tanggal) <= end:
                rows.append(r)
        except ValueError:
            continue
    return rows


def _month_rows(month: int, year: int) -> list[TransactionRow]:
    prefix = f"{year:04d}-{month:02d}"
    rows = _read_rows(_worksheet(get_settings().sheet_transaksi))
    return [r for r in rows if r.active and r.tanggal.startswith(prefix)]


def get_monthly_summary(month: int | None = None, year: int | None = None) -> MonthlySummary:
    now = _now()
    month, year = month or now.month, year or now.year
    rows = _month_rows(month, year)

    per_kategori: dict[str, int] = {}
    for r in rows:
        if r.tipe == "Pengeluaran":
            per_kategori[r.kategori] = per_kategori.get(r.kategori, 0) + r.nominal
    return MonthlySummary(
        month=month,
        year=year,
        total_pengeluaran=sum(per_kategori.values()),
        total_pemasukan=sum(r.nominal for r in rows if r.tipe == "Pemasukan"),
        jumlah_transaksi=len(rows),
        per_kategori=dict(sorted(per_kategori.items(), key=lambda kv: kv[1], reverse=True)),
    )


def get_budget_status(month: int | None = None, year: int | None = None) -> BudgetStatus:
    summary = get_monthly_summary(month, year)
    values = _worksheet(get_settings().sheet_budget).get_values(
        value_render_option=ValueRenderOption.unformatted
    )
    budgets = {str(v[0]).strip(): _to_int(v[1]) for v in values[1:] if v and str(v[0]).strip()}

    kategori = [k for k in KATEGORI_PENGELUARAN if k in budgets]
    kategori += [k for k in budgets if k not in kategori]
    kategori += [k for k in summary.per_kategori if k not in kategori]
    items = [BudgetItem(k, budgets.get(k, 0), summary.per_kategori.get(k, 0)) for k in kategori]
    return BudgetStatus(month=summary.month, year=summary.year, items=items)
