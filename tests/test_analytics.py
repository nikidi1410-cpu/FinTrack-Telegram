from datetime import date

from app.services import analytics_service as an
from app.services.bot_handler import detect_intent
from app.services.sheets_service import BudgetItem, BudgetStatus, TransactionRow


def row(tanggal, nominal, merchant="Kopi Kenangan", kategori="Makanan & Minuman", tipe="Pengeluaran"):
    return TransactionRow(
        row=0, id="x", timestamp="", tanggal=tanggal, waktu="", tipe=tipe, kategori=kategori,
        nominal=nominal, merchant=merchant, keterangan="", metode="", status="Active", pengirim="1",
    )


def test_small_habits_groups_repeated_small_spending():
    rows = [row("2026-10-01", 30000), row("2026-10-02", 30000), row("2026-10-03", 28000, merchant="kopi kenangan"),
            row("2026-10-04", 500000, merchant="Kopi Kenangan"),  # bukan transaksi kecil
            row("2026-10-05", 20000, merchant="Indomaret")]
    assert an.small_habits(rows) == [
        {"merchant": "Kopi Kenangan", "kategori": "Makanan & Minuman", "kali": 3, "total": 88000}
    ]


def test_weekly_facts_compares_with_previous_week(monkeypatch):
    rows = [row("2026-10-21", 100000), row("2026-10-15", 50000, kategori="Transportasi"),
            row("2026-10-14", 200000), row("2026-10-08", 50000),
            row("2026-10-20", 250000, tipe="Pemasukan", kategori="Pemasukan")]
    monkeypatch.setattr(an.sheets_service, "list_transactions",
                        lambda start, end: [r for r in rows if start.isoformat() <= r.tanggal <= end.isoformat()])
    monkeypatch.setattr(an.sheets_service, "get_budget_status", lambda m, y: BudgetStatus(m, y, [
        BudgetItem("Makanan & Minuman", 400_000, 350_000), BudgetItem("Transportasi", 800_000, 50_000)]))

    f = an.weekly_facts(date(2026, 10, 21))
    assert f["periode"] == "2026-10-15 s/d 2026-10-21"
    assert f["total_pengeluaran"] == 150000 and f["total_pengeluaran_minggu_lalu"] == 250000
    assert f["perubahan_persen"] == -40
    # 88% terpakai padahal bulan baru 68% -> rawan
    assert [k["kategori"] for k in f["budget_bulan_ini"]["kategori_rawan"]] == ["Makanan & Minuman"]


def test_sanitize_keeps_only_bold_italic():
    out = an._sanitize("```html\n<b>Laporan</b> <script>x</script> 5 < 10 & <i>ok</i>\n```")
    assert out == "<b>Laporan</b> &lt;script&gt;x&lt;/script&gt; 5 &lt; 10 &amp; <i>ok</i>"


def test_sanitize_drops_unbalanced_tags():
    assert an._sanitize("<b>judul tanpa penutup") == "judul tanpa penutup"


def test_insight_intent():
    assert detect_intent("/insight") == ("insight", None)
    assert detect_intent("minta analisis pengeluaranku dong") == ("insight", None)
