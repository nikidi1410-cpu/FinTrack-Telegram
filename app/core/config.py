from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


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
    sheet_transaksi: str = "Transaksi"
    sheet_budget: str = "Budget_Kategori"
    sheet_summary: str = "Summary"
    catat_bunga: bool = False

    # Scheduler
    scheduler_enabled: bool = True

    @property
    def whitelist(self) -> set[int]:
        """ID pengguna Telegram yang diizinkan memakai bot."""
        return {int(n) for n in self.telegram_allowed_user_ids.split(",") if n.strip()}

    @property
    def service_account_path(self) -> Path:
        path = self.google_service_account_file
        return path if path.is_absolute() else BASE_DIR / path


@lru_cache
def get_settings() -> Settings:
    return Settings()
