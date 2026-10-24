# FinTrack-WA

Expense tracker berbasis Telegram (awalnya WhatsApp di PRD): foto struk / teks → Gemini → Google Sheets. Spesifikasi lengkap ada di `PRD-whatsapp-expense-tracker.md`.

## Setup lokal (Windows / PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy .env.example .env      # lalu isi nilainya
uvicorn app.main:app --reload
```

Cek: http://localhost:8000/health (menunjukkan konfigurasi mana yang sudah terisi) dan http://localhost:8000/docs.

Tes: `pytest -q`

## Kredensial

1. **Gemini** — buat API key di https://aistudio.google.com/apikey → `GEMINI_API_KEY`.
2. **Google Sheets** — di Google Cloud Console: aktifkan *Google Sheets API* dan *Google Drive API*, buat Service Account, unduh key JSON ke `credentials/service_account.json`. Bagikan spreadsheet ke email service account (akses Editor), lalu isi `GOOGLE_SHEETS_SPREADSHEET_ID`. Buat tab & header otomatis: `python -m scripts.setup_sheets` (aman diulang).
3. **Telegram bot** — buat bot via @BotFather → `TELEGRAM_BOT_TOKEN`; ID akun Telegram-mu (cek via @userinfobot) → `TELEGRAM_ALLOWED_USER_IDS`.

## Autostart di Windows (bot menyala sendiri saat login)

```powershell
powershell -ExecutionPolicy Bypass -File scriptsutostart.ps1 install    # pasang + jalan saat login
powershell -ExecutionPolicy Bypass -File scriptsutostart.ps1 status     # cek bot berjalan / tidak
powershell -ExecutionPolicy Bypass -File scriptsutostart.ps1 uninstall  # lepas & hentikan bot
```

Berjalan tanpa jendela via `pythonw -m scripts.run_server`; log di `logs/server.out` dan `logs/fintrack.log`.
Jangan menjalankan `uvicorn` manual bersamaan — dua bot polling akan bentrok (Telegram 409 Conflict).

## Docker

```bash
docker build -t fintrack-wa .
docker run --env-file .env -v ./credentials:/app/credentials:ro -p 8000:8000 fintrack-wa
```

## Struktur

```
app/
  main.py            # FastAPI app + lifespan
  core/config.py     # Settings dari .env (pydantic-settings)
  core/logging.py    # Loguru (console + logs/fintrack.log)
  clients/           # Client Gemini & gspread (singleton)
  routers/           # Endpoint HTTP (health; webhook di Phase 4)
  services/          # Business logic (Phase 2–5)
  schemas/           # Pydantic models (Phase 2)
credentials/         # service_account.json (tidak di-commit)
tests/
```
