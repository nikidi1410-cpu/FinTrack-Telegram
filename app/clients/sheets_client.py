from functools import lru_cache

import gspread
from gspread.http_client import BackOffHTTPClient

from app.core.config import get_settings


@lru_cache
def get_gspread_client() -> gspread.Client:
    """Client gspread terautentikasi via Google Service Account (singleton)."""
    path = get_settings().service_account_path
    if not path.is_file():
        raise RuntimeError(f"File service account tidak ditemukan: {path}")
    # BackOffHTTPClient otomatis mengulang request saat kena rate-limit (HTTP 429) / error 5xx.
    return gspread.service_account(filename=path, http_client=BackOffHTTPClient)


def get_spreadsheet(spreadsheet_id: str | None = None) -> gspread.Spreadsheet:
    """Buka spreadsheet berdasarkan ID; tanpa ID -> spreadsheet utama dari .env."""
    spreadsheet_id = spreadsheet_id or get_settings().google_sheets_spreadsheet_id
    if not spreadsheet_id:
        raise RuntimeError("GOOGLE_SHEETS_SPREADSHEET_ID belum diisi di .env")
    return get_gspread_client().open_by_key(spreadsheet_id)
