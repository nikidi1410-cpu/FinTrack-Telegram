"""Siapkan struktur spreadsheet FinTrack-WA (tab Transaksi, Budget_Kategori, Summary).

Aman dijalankan berulang: tab yang sudah ada tidak dihapus, dan budget yang
sudah diubah pengguna tidak ditimpa.

Jalankan dari root proyek:  python -m scripts.setup_sheets
"""

import gspread

from app.clients.sheets_client import get_spreadsheet
from app.core.config import get_settings
from app.services.sheets_service import TRANSAKSI_HEADERS, col

# Nilai awal; silakan ubah langsung di Google Sheets.
DEFAULT_BUDGET = [
    ("Makanan & Minuman", 2_500_000),
    ("Transportasi", 800_000),
    ("Belanja Harian", 1_000_000),
    ("Tagihan & Utilitas", 750_000),
    ("Hiburan & Lifestyle", 1_000_000),
    ("Kesehatan & Kebersihan", 300_000),
    ("Pendidikan & Kerja", 300_000),
    ("Lain-lain", 500_000),
]

RUPIAH = {"numberFormat": {"type": "CURRENCY", "pattern": '"Rp "#,##0'}}
BOLD = {"textFormat": {"bold": True}}


def get_or_create(ss: gspread.Spreadsheet, title: str, rows: int, cols: int) -> gspread.Worksheet:
    try:
        return ss.worksheet(title)
    except gspread.WorksheetNotFound:
        # Pakai "Sheet1" bawaan spreadsheet baru daripada membiarkannya kosong.
        if title == get_settings().sheet_transaksi:
            for ws in ss.worksheets():
                if ws.title in ("Sheet1", "Sheet 1") and not any(ws.get_all_values()):
                    ws.update_title(title)
                    return ws
        return ss.add_worksheet(title, rows=rows, cols=cols)


def setup_transaksi(ss: gspread.Spreadsheet) -> None:
    ws = get_or_create(ss, get_settings().sheet_transaksi, rows=1000, cols=len(TRANSAKSI_HEADERS))
    values = ws.get_all_values()
    if values and values[0][: len(TRANSAKSI_HEADERS)] != TRANSAKSI_HEADERS and len(values) > 1:
        raise SystemExit("Header tab Transaksi berbeda dan sudah ada data; ubah manual agar data tidak bergeser.")
    if ws.col_count < len(TRANSAKSI_HEADERS):
        ws.add_cols(len(TRANSAKSI_HEADERS) - ws.col_count)

    last = col(TRANSAKSI_HEADERS[-1])
    ws.update([TRANSAKSI_HEADERS], "A1")
    ws.format(f"A1:{last}1", BOLD)
    ws.format(f"A2:{last}", {"numberFormat": {"type": "TEXT"}})  # reset format lama
    ws.format(f"{col('Timestamp')}2:{col('Timestamp')}", {"numberFormat": {"type": "DATE_TIME", "pattern": "yyyy-mm-dd hh:mm:ss"}})
    ws.format(f"{col('Tanggal')}2:{col('Tanggal')}", {"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}})
    ws.format(f"{col('Waktu')}2:{col('Waktu')}", {"numberFormat": {"type": "TIME", "pattern": "hh:mm"}})
    ws.format(f"{col('Nominal')}2:{col('Nominal')}", RUPIAH)
    ws.freeze(rows=1)


def setup_budget(ss: gspread.Spreadsheet) -> None:
    ws = get_or_create(ss, get_settings().sheet_budget, rows=50, cols=2)
    ws.update([["Kategori", "Budget_Bulanan"]], "A1")
    if not ws.col_values(1)[1:]:
        ws.update([list(row) for row in DEFAULT_BUDGET], "A2")
    ws.format("A1:B1", BOLD)
    ws.format("B2:B", RUPIAH)
    ws.freeze(rows=1)


def setup_summary(ss: gspread.Spreadsheet) -> None:
    s = get_settings()
    trx, budget = f"'{s.sheet_transaksi}'", f"'{s.sheet_budget}'"
    ws = get_or_create(ss, s.sheet_summary, rows=30, cols=5)
    ws.clear()

    first, last = 5, 4 + len(DEFAULT_BUDGET)
    rows = [
        ["Awal bulan", "=EOMONTH(TODAY(),-1)+1"],
        ["Akhir bulan", "=EOMONTH(TODAY(),0)"],
        [],
        ["Kategori", "Budget", "Terpakai", "Sisa", "% Terpakai"],
    ]
    nominal, kat, tipe, status, tgl = (
        f"{trx}!{c}:{c}" for c in map(col, ["Nominal", "Kategori", "Tipe", "Status", "Tanggal"])
    )
    for r, (kategori, _) in enumerate(DEFAULT_BUDGET, start=first):
        rows.append([
            kategori,
            f"=IFERROR(VLOOKUP(A{r},{budget}!A:B,2,FALSE),0)",
            f'=SUMIFS({nominal},{kat},A{r},{tipe},"Pengeluaran",{status},"Active",'
            f'{tgl},">="&$B$1,{tgl},"<="&$B$2)',
            f"=B{r}-C{r}",
            f"=IF(B{r}=0,0,C{r}/B{r})",
        ])
    total = last + 1
    rows.append([
        "TOTAL",
        f"=SUM(B{first}:B{last})",
        f"=SUM(C{first}:C{last})",
        f"=B{total}-C{total}",
        f"=IF(B{total}=0,0,C{total}/B{total})",
    ])
    # Locale berdesimal koma (mis. in_ID) memakai ";" sebagai pemisah argumen rumus.
    locale = ss.fetch_sheet_metadata()["properties"].get("locale", "en_US")
    if not locale.startswith(("en", "ja", "ko", "zh", "th", "he")):
        rows = [[cell.replace(",", ";") if cell.startswith("=") else cell for cell in row] for row in rows]
    ws.update(rows, "A1", value_input_option="USER_ENTERED")

    ws.format("B1:B2", {"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}})
    ws.format("A1:A2", BOLD)
    ws.format("A4:E4", BOLD)
    ws.format(f"A{total}:E{total}", BOLD)
    ws.format(f"B{first}:D{total}", RUPIAH)
    ws.format(f"E{first}:E{total}", {"numberFormat": {"type": "PERCENT", "pattern": "0%"}})


def main() -> None:
    ss = get_spreadsheet()
    setup_transaksi(ss)
    setup_budget(ss)
    setup_summary(ss)
    print(f"Selesai. Tab di '{ss.title}': {[ws.title for ws in ss.worksheets()]}")


if __name__ == "__main__":
    main()
