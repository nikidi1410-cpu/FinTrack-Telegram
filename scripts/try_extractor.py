"""Coba AI extractor secara manual terhadap Gemini sungguhan.

    python -m scripts.try_extractor "bensin 50k"
    python -m scripts.try_extractor path/ke/struk.jpg
"""

import asyncio
import mimetypes
import sys
import time
from pathlib import Path

from app.services.ai_extractor import extract_transaction_from_image, extract_transaction_from_text


async def main(arg: str) -> None:
    path = Path(arg)
    start = time.perf_counter()
    if path.is_file():
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        result = await extract_transaction_from_image(path.read_bytes(), mime)
    else:
        result = await extract_transaction_from_text(arg)
    print(result.model_dump_json(indent=2))
    print(f"\n({time.perf_counter() - start:.1f} detik)")


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:])))
