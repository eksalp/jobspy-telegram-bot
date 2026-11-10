from __future__ import annotations

"""
"Scrape dulu, baru hapus yang tutup" -- dipakai bersama oleh scrape terjadwal
(jadwal_harian.py) dan perintah bot (/<situs>, /updateall).

Cara pakai per situs:
    batas = sekarang()                    # SEBELUM scrape dimulai
    records = ... scrape ...
    unik = tandai(db.deduplicate(records)[0])
    simpan = db.upsert_jobs(unik)
    catatan = bersihkan([nama_site], batas, simpan)

Lowongan situs itu yang updated_at-nya lebih tua dari `batas` berarti tidak
muncul lagi di scrape ini -> dihapus. Pengaman: kalau yang akan dihapus lebih
banyak daripada hasil baru (situs error/memblokir), data lama dipertahankan.
"""

import logging
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

# Lowongan yang tidak muncul lagi selama ini dihapus apa pun alasannya.
BASI_HARI = 3

# Situs yang menolak IP server GitHub tapi terbuka dari Mac (IP rumah).
# Dilewati scrape terjadwal di GitHub; dijalankan MANUAL dari bot di Mac
# (/pertamina_ptc, /jakartakerja). TIDAK ikut pembersihan BASI_HARI, karena
# belum tentu dijalankan tiap hari. Lowongan yang tutup tetap dihapus setiap
# kali perintahnya dijalankan dan berhasil.
HANYA_DARI_MAC = ["pertamina_ptc", "jakartakerja"]


def sekarang() -> datetime:
    # Mundur 5 menit sebagai jarak aman kalau jam runner dan jam database
    # sedikit berbeda. Lowongan yang baru di-upsert pasti lebih baru dari ini,
    # yang dari scrape kemarin (~24 jam lalu) pasti lebih tua.
    return datetime.now(timezone.utc) - timedelta(minutes=5)


def tandai(records: list[dict]) -> list[dict]:
    """Isi updated_at secara eksplisit, supaya penanda "masih ada" tidak
    bergantung pada trigger set_updated_at di database."""
    kini = datetime.now(timezone.utc).isoformat()
    for r in records:
        r["updated_at"] = kini
    return records


def hitung_basi(sites: list[str] | None, batas: datetime) -> int:
    import db
    q = db.get_client().table("jobs").select("id", count="exact").lt("updated_at", batas.isoformat())
    if sites:
        q = q.in_("site", sites)
    return q.limit(1).execute().count or 0


def hapus_basi(sites: list[str] | None, batas: datetime,
                kecuali: list[str] | None = None) -> int:
    """Hapus per 500 baris supaya tidak kena statement timeout Supabase."""
    import db
    client = db.get_client()
    total = 0
    while True:
        q = client.table("jobs").select("id").lt("updated_at", batas.isoformat())
        if sites:
            q = q.in_("site", sites)
        if kecuali:
            q = q.filter("site", "not.in", "(" + ",".join(kecuali) + ")")
        ids = [r["id"] for r in (q.limit(500).execute().data or [])]
        if not ids:
            return total
        client.table("jobs").delete().in_("id", ids).execute()
        total += len(ids)


def bersihkan(sites: list[str], batas: datetime, baru: int) -> str:
    """Hapus lowongan lama situs ini yang tidak muncul lagi. Return catatan."""
    try:
        basi = hitung_basi(sites, batas)
        if not basi:
            return ""
        if basi > baru:
            return f" (⚠️ {basi} lama dipertahankan: hasil hari ini lebih sedikit)"
        return f" (−{hapus_basi(sites, batas)} tutup)"
    except Exception as e:  # noqa: BLE001
        log.exception("Gagal hapus lowongan lama %s", sites)
        return f" (⚠️ gagal hapus lama: {str(e)[:40]})"
