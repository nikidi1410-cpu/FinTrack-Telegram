import httpx

from app.core.config import get_settings

API = "https://api.telegram.org"


class TelegramError(RuntimeError):
    pass


class TelegramClient:
    """Pembungkus tipis Telegram Bot API (https://core.telegram.org/bots/api)."""

    def __init__(self, token: str):
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN belum diisi di .env")
        self._token = token
        # Long polling menahan request hingga 30 dtk, jadi timeout baca harus lebih panjang.
        self._http = httpx.AsyncClient(base_url=f"{API}/bot{token}", timeout=httpx.Timeout(10, read=40))

    async def call(self, method: str, **params) -> dict | list | bool:
        resp = await self._http.post(f"/{method}", json={k: v for k, v in params.items() if v is not None})
        data = resp.json()
        if not data.get("ok"):
            raise TelegramError(f"{method}: {data.get('description', resp.status_code)}")
        return data["result"]

    async def send_message(self, chat_id: int, text: str) -> None:
        await self.call(
            "sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
            link_preview_options={"is_disabled": True},
        )

    async def send_typing(self, chat_id: int) -> None:
        await self.call("sendChatAction", chat_id=chat_id, action="typing")

    async def download_file(self, file_id: str) -> bytes:
        info = await self.call("getFile", file_id=file_id)
        resp = await self._http.get(f"{API}/file/bot{self._token}/{info['file_path']}")
        resp.raise_for_status()
        return resp.content

    async def get_updates(self, offset: int | None, timeout: int = 30) -> list[dict]:
        return await self.call("getUpdates", offset=offset, timeout=timeout, allowed_updates=["message"])

    async def aclose(self) -> None:
        await self._http.aclose()


_client: TelegramClient | None = None


def get_telegram() -> TelegramClient:
    global _client
    if _client is None:
        _client = TelegramClient(get_settings().telegram_bot_token.strip())
    return _client


async def close_telegram() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
