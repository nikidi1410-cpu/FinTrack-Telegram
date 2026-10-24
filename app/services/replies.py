"""Template balasan bot (format HTML Telegram), diadaptasi dari PRD §4.4."""

import calendar
from datetime import date
from html import escape

from app.schemas.transaction import Transaction
from app.services.sheets_service import AppendResult, BudgetItem, BudgetStatus, MonthlySummary, TransactionRow

BULAN = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
         "Agustus", "September", "Oktober", "November", "Desember"]
LOW_CONFIDENCE = 0.8

WELCOME = (
    "👋 <b>Halo! Aku FinTrack, pencatat keuanganmu.</b>\n\n"
    "Cara pakai:\n"
    "📸 Kirim <b>foto struk</b> / <b>screenshot</b> transfer, QRIS, atau riwayat transaksi\n"
    "✍️ Atau ketik santai: <i>bensin 50k</i>, <i>makan bakso 25rb tunai</i>\n\n"
    "Perintah lain:\n"
    "📊 <i>bulan ini habis berapa?</i> atau /ringkasan\n"
    "🎯 <i>sisa budget</i> / <i>sisa budget makan</i> atau /budget\n"
    "💡 <i>minta insight</i> atau /insight — analisis &amp; tips 7 hari terakhir\n"
    "↩️ <i>batal</i> atau /batal — membatalkan kiriman terakhir"
)
ERROR = "😵 Maaf, ada gangguan saat memproses pesanmu. Coba lagi sebentar ya."
UNSUPPORTED = "Aku cuma bisa membaca <b>teks</b> dan <b>gambar</b> (foto struk / screenshot) ya. 🙏"


def rupiah(n: int) -> str:
    return f"Rp {n:,}".replace(",", ".")


def tgl(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.day} {BULAN[d.month - 1][:3]} {d.year}"


def _warn(t: Transaction) -> str:
    return " ⚠️" if t.confidence_score < LOW_CONFIDENCE else ""


def _single(t: Transaction) -> str:
    judul = "Pengeluaran" if t.tipe_transaksi == "Pengeluaran" else "Pemasukan"
    waktu = f" {t.waktu}" if t.waktu else ""
    return (
        f"✅ <b>{judul} Berhasil Dicatat!</b>{_warn(t)}\n\n"
        f"📅 Tanggal: {tgl(t.tanggal)}{waktu}\n"
        f"💰 Nominal: {rupiah(t.nominal)}\n"
        f"🏷️ Kategori: {escape(t.kategori)}\n"
        f"🏪 Merchant: {escape(t.merchant)}\n"
        f"💳 Metode: {escape(t.metode_pembayaran)}\n"
        f"📝 Keterangan: {escape(t.deskripsi)}"
    )


def _multi(saved: list[Transaction]) -> str:
    lines = [f"✅ <b>{len(saved)} Transaksi Berhasil Dicatat!</b>\n"]
    for i, t in enumerate(saved, 1):
        tanda = "🔻" if t.tipe_transaksi == "Pengeluaran" else "🟢"
        waktu = f" {t.waktu}" if t.waktu else ""
        lines.append(
            f"{i}. {tanda} {rupiah(t.nominal)} · {escape(t.merchant)}{_warn(t)}\n"
            f"     {tgl(t.tanggal)}{waktu} · {escape(t.kategori)}"
        )
    keluar = sum(t.nominal for t in saved if t.tipe_transaksi == "Pengeluaran")
    masuk = sum(t.nominal for t in saved if t.tipe_transaksi == "Pemasukan")
    lines.append("")
    if keluar:
        lines.append(f"💸 Total pengeluaran: <b>{rupiah(keluar)}</b>")
    if masuk:
        lines.append(f"💰 Total pemasukan: <b>{rupiah(masuk)}</b>")
    return "\n".join(lines)


def append_result(result: AppendResult) -> str:
    saved = [t for _, t in result.saved]
    notes = []
    if result.duplicates:
        notes.append(f"🔁 {len(result.duplicates)} transaksi dilewati karena sudah pernah dicatat.")
    if result.skipped:
        notes.append(f"⏭️ {len(result.skipped)} transaksi bunga tabungan tidak dicatat.")

    if not saved:
        return "ℹ️ Tidak ada transaksi baru yang dicatat.\n\n" + "\n".join(notes)

    parts = [_single(saved[0]) if len(saved) == 1 else _multi(saved)]
    if any(t.confidence_score < LOW_CONFIDENCE for t in saved):
        parts.append("⚠️ <i>Data bertanda ⚠️ kurang jelas terbaca, mohon dicek. Kalau salah, ketik \"batal\" lalu kirim ulang.</i>")
    if notes:
        parts.append("\n".join(notes))
    parts.append('<i>Ketik "batal" jika salah mencatat.</i>')
    return "\n\n".join(parts)


def voided(rows: list[TransactionRow]) -> str:
    if not rows:
        return "ℹ️ Tidak ada transaksi yang bisa dibatalkan."
    if len(rows) == 1:
        r = rows[0]
        return f"↩️ <b>Transaksi dibatalkan:</b>\n{rupiah(r.nominal)} · {escape(r.merchant)} ({tgl(r.tanggal)})"
    total = sum(r.nominal for r in rows)
    return f"↩️ <b>{len(rows)} transaksi dari kiriman terakhir dibatalkan</b> (total {rupiah(total)})."


def _status_line(persen: int, today: date) -> str:
    """Bandingkan budget terpakai dengan seberapa jauh bulan sudah berjalan."""
    progres_bulan = today.day / calendar.monthrange(today.year, today.month)[1] * 100
    if persen >= 100:
        return "🚨 <i>Status: Budget bulan ini sudah terlampaui!</i>"
    if persen > progres_bulan + 10:
        return f"⚠️ <i>Status: Pengeluaranmu lebih cepat dari jadwal ({persen}% terpakai, bulan baru berjalan {progres_bulan:.0f}%).</i>"
    return "💡 <i>Status: Pengeluaranmu masih dalam batas aman.</i>"


def summary(s: MonthlySummary, b: BudgetStatus, today: date) -> str:
    lines = [
        f"📊 <b>Ringkasan Pengeluaran {BULAN[s.month - 1]} {s.year}</b>\n",
        f"💸 Total Terpakai: <b>{rupiah(s.total_pengeluaran)}</b>",
        f"🎯 Total Budget: {rupiah(b.total_budget)} ({b.persen}% terpakai)",
    ]
    if s.total_pemasukan:
        lines.append(f"💰 Pemasukan: {rupiah(s.total_pemasukan)}")
    top = list(s.per_kategori.items())[:3]
    if top:
        lines.append("\nTop 3 Kategori Terbesar:")
        lines += [f"{i}. {escape(k)}: {rupiah(v)}" for i, (k, v) in enumerate(top, 1)]
    else:
        lines.append("\nBelum ada pengeluaran bulan ini. 🎉")
    lines.append("\n" + _status_line(b.persen, today))
    return "\n".join(lines)


def _bar(persen: int) -> str:
    filled = min(10, round(persen / 10))
    return "▓" * filled + "░" * (10 - filled)


def _budget_item(i: BudgetItem) -> str:
    icon = "🚨" if i.persen >= 100 else "⚠️" if i.persen >= 80 else "✅"
    return (
        f"{icon} <b>{escape(i.kategori)}</b>\n"
        f"{_bar(i.persen)} {i.persen}%\n"
        f"{rupiah(i.terpakai)} / {rupiah(i.budget)} · sisa {rupiah(i.sisa)}"
    )


def budget(b: BudgetStatus, kategori: str | None = None) -> str:
    items = [i for i in b.items if i.kategori == kategori] if kategori else b.items
    header = f"🎯 <b>Budget {BULAN[b.month - 1]} {b.year}</b>"
    if not items:
        return f"{header}\n\nKategori itu belum punya budget di tab Budget_Kategori."
    body = "\n\n".join(_budget_item(i) for i in items)
    footer = "" if kategori else (
        f"\n\n<b>Total:</b> {rupiah(b.total_terpakai)} / {rupiah(b.total_budget)} ({b.persen}%)"
    )
    return f"{header}\n\n{body}{footer}"
