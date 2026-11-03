from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


def _parse_user_spreadsheets(value: str) -> dict[int, str]:
    """'111:sheetA,222:sheetB' -> {111: 'sheetA', 222: 'sheetB'}."""
    result: dict[int, str] = {}
    for item in value.split(","):
        if not item.strip():
            continue
        user_id, _, spreadsheet_id = (part.strip() for part in item.partition(":"))
        if not user_id.isdigit() or not spreadsheet_id:
            raise ValueError(f"USER_SPREADSHEETS harus berformat ID_TELEGRAM:ID_SPREADSHEET, bukan '{item.strip()}'")
        result[int(user_id)] = spreadsheet_id
    return result


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Aplikasi
    app_name: str = "FinTrack-WA"
    app_env: str = "development"
    log_level: str = "INFO"
    timezone: str = "Asia/Jakarta"

    # Keamanan
    telegram_allowed_user_ids: str = ""
    webhook_secret: str = ""

    # Telegram bot
    telegram_bot_token: str = ""
    # polling (lokal, tanpa URL publik) | webhook (server) | off
    telegram_mode: str = "polling"
    # Wajib untuk mode webhook, mis. https://fintrack.example.com
    public_base_url: str = ""

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"

    # Google Sheets
    google_service_account_file: Path = Path("credentials/service_account.json")
    google_sheets_spreadsheet_id: str = ""
    # Pengguna dengan spreadsheet sendiri: ID_TELEGRAM:ID_SPREADSHEET, pisahkan dengan koma
    user_spreadsheets: str = ""
    sheet_transaksi: str = "Transaksi"
    sheet_budget: str = "Budget_Kategori"
    sheet_summary: str = "Summary"
    catat_bunga: bool = False

    # Scheduler
    scheduler_enabled: bool = True

    @field_validator("user_spreadsheets")
    @classmethod
    def _validate_user_spreadsheets(cls, value: str) -> str:
        _parse_user_spreadsheets(value)  # format salah -> program berhenti dengan pesan yang jelas
        return value

    @property
    def whitelist(self) -> set[int]:
        """ID pengguna Telegram yang diizinkan memakai bot."""
        allowed = {int(n) for n in self.telegram_allowed_user_ids.split(",") if n.strip()}
        return allowed | set(_parse_user_spreadsheets(self.user_spreadsheets))

    def spreadsheet_id_for(self, user_id: int | str) -> str:
        """Spreadsheet milik pengguna; tanpa spreadsheet sendiri -> spreadsheet utama."""
        own = _parse_user_spreadsheets(self.user_spreadsheets).get(int(user_id))
        return own or self.google_sheets_spreadsheet_id

    @property
    def service_account_path(self) -> Path:
        path = self.google_service_account_file
        return path if path.is_absolute() else BASE_DIR / path


@lru_cache
def get_settings() -> Settings:
    return Settings()
