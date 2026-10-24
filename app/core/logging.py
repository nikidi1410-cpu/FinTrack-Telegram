import sys

from loguru import logger

from app.core.config import BASE_DIR, get_settings


def setup_logging() -> None:
    settings = get_settings()
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level.upper(),
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )
    logger.add(
        BASE_DIR / "logs" / "fintrack.log",
        level="INFO",
        rotation="10 MB",
        retention="14 days",
        encoding="utf-8",
    )
