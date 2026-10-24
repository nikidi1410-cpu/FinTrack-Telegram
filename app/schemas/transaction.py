from typing import Literal

from pydantic import BaseModel, Field, field_validator

KATEGORI_PENGELUARAN = [
    "Makanan & Minuman",
    "Transportasi",
    "Belanja Harian",
    "Tagihan & Utilitas",
    "Hiburan & Lifestyle",
    "Kesehatan & Kebersihan",
    "Pendidikan & Kerja",
    "Lain-lain",
]

Kategori = Literal[
    "Makanan & Minuman",
    "Transportasi",
    "Belanja Harian",
    "Tagihan & Utilitas",
    "Hiburan & Lifestyle",
    "Kesehatan & Kebersihan",
    "Pendidikan & Kerja",
    "Lain-lain",
    "Pemasukan",
]
TipeTransaksi = Literal["Pengeluaran", "Pemasukan"]


class Transaction(BaseModel):
    tanggal: str = Field(description="Tanggal transaksi, format YYYY-MM-DD")
    waktu: str | None = Field(default=None, description="Jam transaksi HH:MM, null jika tidak ada")
    nominal: int = Field(description="Nominal akhir dalam Rupiah, integer positif")
    kategori: Kategori
    merchant: str = Field(description="Nama toko / penerima / pengirim transfer")
    deskripsi: str = Field(description="Rincian singkat item atau keperluan")
    metode_pembayaran: str = Field(description="QRIS, Tunai, BCA, GoPay, ShopeePay, dll.")
    tipe_transaksi: TipeTransaksi
    confidence_score: float = Field(description="Keyakinan ekstraksi, 0.0 sampai 1.0")

    @field_validator("nominal")
    @classmethod
    def nominal_positif(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("nominal harus positif")
        return v


class ExtractionResult(BaseModel):
    is_valid_transaction: bool
    transaksi: list[Transaction] = Field(
        default_factory=list,
        description="Semua transaksi yang terbaca; satu gambar riwayat bisa berisi banyak transaksi",
    )
    pesan_error: str | None = Field(
        default=None, description="Alasan singkat jika bukan bukti transaksi / tidak terbaca"
    )
