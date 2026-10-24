from datetime import datetime
from zoneinfo import ZoneInfo

from google.genai import errors, types
from loguru import logger
from pydantic import ValidationError

from app.clients.gemini_client import get_gemini_client
from app.core.config import get_settings
from app.schemas.transaction import KATEGORI_PENGELUARAN, ExtractionResult

SYSTEM_PROMPT = """\
Anda adalah asisten cerdas akuntansi dan ekstraksi transaksi keuangan Indonesia.
Tugas Anda adalah membaca gambar (struk belanja fisik, screenshot transfer bank, screenshot QRIS, \
screenshot riwayat/mutasi transaksi, bukti bayar) atau teks deskripsi pengeluaran, kemudian \
mengekstraknya ke format JSON terstruktur.

Hari ini: {today} (zona waktu Asia/Jakarta).

Aturan Penting:
1. Selalu utamakan nilai Grand Total (nominal akhir yang dibayarkan) setelah dikurangi diskon dan \
ditambah pajak/service charge. Jangan ambil Subtotal.
2. Format tanggal harus YYYY-MM-DD. Jika tahun tidak tertera, gunakan tahun {year}. Jika tanggal \
tidak disebut sama sekali (umumnya pada input teks), gunakan hari ini. "Kemarin" = sehari sebelum hari ini.
3. Nominal harus berupa INTEGER positif tanpa tanda titik, koma, atau simbol mata uang \
(contoh: 50000, bukan Rp50.000). Format Indonesia memakai titik sebagai pemisah ribuan: \
"83.250" = 83250.
4. Normalisasikan singkatan bahasa Indonesia: "50k", "50rb" -> 50000; "1jt" -> 1000000; \
"1.5jt" / "1,5jt" -> 1500000.
5. Pengeluaran diklasifikasikan ke salah satu kategori resmi: {kategori}. \
Jika tipe_transaksi "Pemasukan" (gaji, transfer masuk, bunga, cashback, refund), kategori wajib "Pemasukan".
6. Screenshot riwayat/mutasi bisa berisi BANYAK transaksi: ekstrak SETIAP baris sebagai satu item \
di "transaksi", termasuk yang nominalnya sama. Tanda "+" / warna hijau = Pemasukan, "-" = Pengeluaran. \
Jangan mengarang baris yang terpotong atau tidak terbaca jelas.
7. Screenshot transfer bank: nama penerima menjadi merchant. Deteksi metode pembayaran bila terlihat: \
BCA, Mandiri, BRI, BSI, SeaBank, Jago, GoPay, OVO, ShopeePay, DANA, QRIS. Teks tanpa metode -> "Tunai".
8. Jangan simpan nomor rekening lengkap; cukup nama bank atau 4 digit terakhir.
9. Jika gambar/teks bukan transaksi keuangan atau tidak terbaca sama sekali, set \
"is_valid_transaction": false, "transaksi": [], dan berikan alasan singkat yang ramah di "pesan_error" \
(contoh: "Fotonya buram, coba kirim ulang dengan cahaya lebih terang ya.").
10. confidence_score: 0.9+ jika semua data jelas; turunkan jika nominal/tanggal ditebak.
"""


def _build_config() -> types.GenerateContentConfig:
    now = datetime.now(ZoneInfo(get_settings().timezone))
    prompt = SYSTEM_PROMPT.format(
        today=now.strftime("%Y-%m-%d (%A)"),
        year=now.year,
        kategori=", ".join(f"'{k}'" for k in KATEGORI_PENGELUARAN),
    )
    return types.GenerateContentConfig(
        system_instruction=prompt,
        response_mime_type="application/json",
        response_schema=ExtractionResult,
        temperature=0,
    )


async def _extract(contents: list) -> ExtractionResult:
    try:
        response = await get_gemini_client().aio.models.generate_content(
            model=get_settings().gemini_model,
            contents=contents,
            config=_build_config(),
        )
    except errors.APIError as exc:
        logger.error("Gemini error {}: {}", exc.code, exc.message)
        return ExtractionResult(
            is_valid_transaction=False,
            pesan_error="Maaf, AI-nya lagi sibuk. Coba kirim ulang sebentar lagi ya. 🙏",
        )
    try:
        result = ExtractionResult.model_validate_json(response.text)
    except ValidationError as exc:
        logger.warning("Output Gemini tidak valid: {} | raw={}", exc, response.text)
        return ExtractionResult(
            is_valid_transaction=False,
            pesan_error="Maaf, aku belum bisa membaca transaksinya. Coba kirim ulang ya.",
        )
    if result.is_valid_transaction and not result.transaksi:
        result.is_valid_transaction = False
        result.pesan_error = result.pesan_error or "Tidak ada transaksi yang terbaca."
    return result


async def extract_transaction_from_image(
    image_bytes: bytes, mime_type: str = "image/jpeg", caption: str | None = None
) -> ExtractionResult:
    """Ekstrak satu atau lebih transaksi dari foto struk / screenshot bukti bayar."""
    contents: list = [types.Part.from_bytes(data=image_bytes, mime_type=mime_type)]
    if caption:
        contents.append(f"Catatan dari pengguna: {caption}")
    return await _extract(contents)


async def extract_transaction_from_text(text: str) -> ExtractionResult:
    """Ekstrak transaksi dari pesan teks santai, mis. "bensin 50k" atau "beli ketoprak 18rb tunai"."""
    return await _extract([text])
