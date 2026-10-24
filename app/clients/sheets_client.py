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


def get_spreadsheet() -> gspread.Spreadsheet:
    settings = get_settings()
    if not settings.google_sheets_spreadsheet_id:
        raise RuntimeError("GOOGLE_SHEETS_SPREADSHEET_ID belum diisi di .env")
    return get_gspread_client().open_by_key(settings.google_sheets_spreadsheet_id)
