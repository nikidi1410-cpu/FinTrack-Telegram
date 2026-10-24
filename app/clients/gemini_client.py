from functools import lru_cache

from google import genai

from app.core.config import get_settings


@lru_cache
def get_gemini_client() -> genai.Client:
    """Client Gemini (singleton). Dipakai oleh AI extractor & insight engine."""
    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY belum diisi di .env")
    return genai.Client(api_key=settings.gemini_api_key)
