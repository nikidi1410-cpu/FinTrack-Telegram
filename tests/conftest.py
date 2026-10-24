import os

# Tes tidak boleh menyalakan bot sungguhan (polling ke Telegram) atau scheduler.
os.environ["TELEGRAM_MODE"] = "off"
os.environ["SCHEDULER_ENABLED"] = "false"
