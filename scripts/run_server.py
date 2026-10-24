"""Jalankan server FinTrack, juga tanpa jendela (pythonw.exe) untuk autostart Windows.

    .venv\\Scripts\\pythonw.exe -m scripts.run_server

pythonw tidak punya konsol (sys.stdout/stderr = None), jadi output dialihkan ke
logs/server.out (ditimpa setiap kali start). Log lengkap tetap di logs/fintrack.log.
"""

import sys

import uvicorn

from app.core.config import BASE_DIR

if __name__ == "__main__":
    if sys.stdout is None or sys.stderr is None:
        log_dir = BASE_DIR / "logs"
        log_dir.mkdir(exist_ok=True)
        out = open(log_dir / "server.out", "w", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = out
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
