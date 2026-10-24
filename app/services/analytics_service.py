"""Insight engine (PRD §4.5): hitung fakta dari Sheets, lalu Gemini menulis narasinya.

Angka selalu dihitung di Python; Gemini hanya merangkai kata dari angka tersebut
supaya tidak ada angka karangan.
"""

import asyncio
import calendar
import json
import re
from datetime import date, timedelta
from html import escape

from google.genai import errors, types
from loguru import logger

from app.clients.gemini_client import get_gemini_client
from app.core.config import get_settings
from app.services import sheets_service
from app.services.replies import BULAN, rupiah
from app.services.sheets_service import TransactionRow

SMALL_HABIT_MAX = 50_000  # transaksi "kecil" untuk deteksi kebiasaan
SMALL_HABIT_MIN_COUNT = 3
TELEGRAM_LIMIT = 4000


def _pengeluaran(rows: list[TransactionRow]) -> list[TransactionRow]:
    return [r for r in rows if r.tipe == "Pengeluaran"]


def _per_kategori(rows: list[TransactionRow]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in _pengeluaran(rows):
        out[r.kategori] = out.get(r.kategori, 0) + r.nominal
    return dict(sorted(out.items(), key=lambda kv: kv[1], reverse=True))


def _change(now: int, before: int) -> int | None:
    return round((now - before) / before * 100) if before else None


def small_habits(rows: list[TransactionRow]) -> list[dict]:
    """Transaksi kecil berulang di merchant yang sama, mis. kopi 20x."""
    groups: dict[str, list[TransactionRow]] = {}
    for r in _pengeluaran(rows):
        if r.nominal <= SMALL_HABIT_MAX:
            groups.setdefault(r.merchant.strip().lower(), []).append(r)
    habits = [
        {"merchant": g[0].merchant, "kategori": g[0].kategori, "kali": len(g), "total": sum(r.nominal for r in g)}
        for g in groups.values() if len(g) >= SMALL_HABIT_MIN_COUNT
    ]
    return sorted(habits, key=lambda h: h["total"], reverse=True)[:5]


def _top(rows: list[TransactionRow], n: int = 3) -> list[dict]:
    top = sorted(_pengeluaran(rows), key=lambda r: r.nominal, reverse=True)[:n]
    return [{"tanggal": r.tanggal, "merchant": r.merchant, "kategori": r.kategori, "nominal": r.nominal} for r in top]


def _budget_facts(month: int, year: int, today: date | None) -> dict:
    b = sheets_service.get_budget_status(month, year)
    days = calendar.monthrange(year, month)[1]
    progres = round(today.day / days * 100) if today else 100
    peringatan = [
        {"kategori": i.kategori, "terpakai": i.terpakai, "budget": i.budget, "persen": i.persen}
        for i in b.items
        if i.budget and (i.persen >= 100 or (i.persen >= 80 and i.persen > progres + 10))
    ]
    return {
        "bulan_sudah_berjalan_persen": progres,  # bukan budget!
        "total_budget": b.total_budget,
        "total_terpakai": b.total_terpakai,
        "budget_terpakai_persen": b.persen,
        "kategori_rawan": peringatan,
    }


def weekly_facts(today: date) -> dict:
    """7 hari terakhir (termasuk hari ini) vs 7 hari sebelumnya."""
    start = today - timedelta(days=6)
    prev_start, prev_end = start - timedelta(days=7), start - timedelta(days=1)
    rows = sheets_service.list_transactions(prev_start, today)
    now = [r for r in rows if r.tanggal >= start.isoformat()]
    prev = [r for r in rows if r.tanggal < start.isoformat()]
    month_rows = sheets_service.list_transactions(today.replace(day=1), today)

    total_now = sum(r.nominal for r in _pengeluaran(now))
    total_prev = sum(r.nominal for r in _pengeluaran(prev))
    return {
        "jenis": "mingguan",
        "periode": f"{start.isoformat()} s/d {today.isoformat()}",
        "periode_pembanding": f"{prev_start.isoformat()} s/d {prev_end.isoformat()}",
        "jumlah_transaksi": len(_pengeluaran(now)),
        "total_pengeluaran": total_now,
        "total_pengeluaran_minggu_lalu": total_prev,
        "perubahan_persen": _change(total_now, total_prev),
        "per_kategori": _per_kategori(now),
        "per_kategori_minggu_lalu": _per_kategori(prev),
        "transaksi_terbesar": _top(now),
        "kebiasaan_kecil_bulan_ini": small_habits(month_rows),
        "budget_bulan_ini": _budget_facts(today.month, today.year, today),
    }


def monthly_facts(month: int, year: int) -> dict:
    """Review satu bulan penuh vs bulan sebelumnya."""
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    prev_end = start - timedelta(days=1)
    prev_start = prev_end.replace(day=1)
    rows = sheets_service.list_transactions(prev_start, end)
    now = [r for r in rows if r.tanggal >= start.isoformat()]
    prev = [r for r in rows if r.tanggal < start.isoformat()]

    total_now = sum(r.nominal for r in _pengeluaran(now))
    total_prev = sum(r.nominal for r in _pengeluaran(prev))
    pemasukan = sum(r.nominal for r in now if r.tipe == "Pemasukan")
    return {
        "jenis": "bulanan",
        "periode": f"{BULAN[month - 1]} {year}",
        "jumlah_transaksi": len(_pengeluaran(now)),
        "total_pengeluaran": total_now,
        "total_pengeluaran_bulan_lalu": total_prev,
        "perubahan_persen": _change(total_now, total_prev),
        "total_pemasukan": pemasukan,
        "selisih_pemasukan_pengeluaran": pemasukan - total_now,
        "per_kategori": _per_kategori(now),
        "per_kategori_bulan_lalu": _per_kategori(prev),
        "transaksi_terbesar": _top(now),
        "kebiasaan_kecil": small_habits(now),
        "budget": _budget_facts(month, year, None),
    }


NARRATOR_PROMPT = """\
Kamu adalah asisten keuangan pribadi yang ramah dan jujur. Tulis pesan Telegram berbahasa \
Indonesia santai (pakai "kamu") berdasarkan DATA JSON yang diberikan.

Aturan:
- HANYA gunakan angka yang ada di data. Jangan menghitung ulang atau mengarang angka.
- Format uang: Rp 1.234.567 (titik sebagai pemisah ribuan).
- Format: boleh tag HTML <b> dan <i> saja. Jangan pakai Markdown (*, _, #) atau tag lain.
- Maksimal sekitar 15 baris. Emoji secukupnya.
- Struktur: judul tebal sesuai jenis laporan (mingguan/bulanan) + periode, ringkasan total & \
perubahan vs periode sebelumnya, 1–3 temuan paling penting (kategori naik tajam, kategori budget \
rawan, kebiasaan kecil yang menumpuk), lalu 2–3 tips hemat yang konkret dan realistis.
- budget_terpakai_persen = porsi budget yang sudah dipakai; bulan_sudah_berjalan_persen = porsi hari \
dalam bulan yang sudah lewat. Keduanya BERBEDA, jangan tertukar.
- perubahan_persen null berarti belum ada data pembanding; jangan sebut persentase.
- Jika jumlah_transaksi kecil (< 5), sampaikan bahwa datanya masih sedikit sehingga analisis \
belum akurat, dan semangati untuk rajin mencatat. Jangan berlebihan menyimpulkan.
"""


def _sanitize(text: str) -> str:
    """Escape semua HTML lalu kembalikan hanya <b>/<i>, agar Telegram tidak menolak pesan."""
    text = re.sub(r"```\w*", "", text).strip()
    safe = escape(text, quote=False)
    safe = re.sub(r"&lt;(/?)(b|i)&gt;", r"<\1\2>", safe)
    # Tag yang tidak tertutup bikin Telegram menolak pesan; buang semua tag jika tidak seimbang.
    for tag in ("b", "i"):
        if safe.count(f"<{tag}>") != safe.count(f"</{tag}>"):
            safe = re.sub(r"</?(b|i)>", "", safe)
            break
    return safe[:TELEGRAM_LIMIT]


def _fallback(facts: dict) -> str:
    """Laporan tanpa AI, dipakai bila Gemini gagal."""
    judul = "Laporan Mingguan" if facts["jenis"] == "mingguan" else "Review Bulanan"
    lines = [f"📈 <b>{judul}</b> ({escape(facts['periode'])})\n",
             f"💸 Total pengeluaran: <b>{rupiah(facts['total_pengeluaran'])}</b>"]
    if facts["perubahan_persen"] is not None:
        arah = "naik" if facts["perubahan_persen"] > 0 else "turun"
        lines.append(f"{'📈' if arah == 'naik' else '📉'} {arah} {abs(facts['perubahan_persen'])}% dari periode sebelumnya")
    for k, v in list(facts["per_kategori"].items())[:3]:
        lines.append(f"• {escape(k)}: {rupiah(v)}")
    return "\n".join(lines)


async def narrate(facts: dict) -> str:
    try:
        response = await get_gemini_client().aio.models.generate_content(
            model=get_settings().gemini_model,
            contents=json.dumps(facts, ensure_ascii=False),
            config=types.GenerateContentConfig(system_instruction=NARRATOR_PROMPT, temperature=0.7),
        )
        if response.text:
            return _sanitize(response.text)
    except errors.APIError as exc:
        logger.error("Gemini gagal menulis insight: {} {}", exc.code, exc.message)
    return _fallback(facts)


async def weekly_insight(today: date) -> str:
    facts = await asyncio.to_thread(weekly_facts, today)
    return await narrate(facts)


async def monthly_insight(month: int, year: int) -> str:
    facts = await asyncio.to_thread(monthly_facts, month, year)
    return await narrate(facts)
