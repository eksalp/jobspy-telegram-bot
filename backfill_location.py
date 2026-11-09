#!/usr/bin/env python3
"""
Isi kolom country & region untuk SEMUA baris yang sudah ada di tabel jobs.

    python backfill_location.py            # jalankan sungguhan
    python backfill_location.py --dry-run  # cuma laporan, tidak mengubah DB

Jalankan SEKALI setelah migration_add_region.sql dieksekusi di Supabase.
Setelah ini, baris BARU otomatis dapat country+region dari sites/base.py —
script ini cuma untuk mengisi baris LAMA yang sudah terlanjur ada.

CARA KERJA: mengelompokkan berdasarkan location (bukan per-baris) supaya
hemat — kalau ada 2.650 baris dengan location "Kota Adm. Jakarta Selatan",
normalize_location() cuma dipanggil sekali untuk string itu, hasilnya
dipakai untuk meng-update semua 2.650 baris sekaligus lewat satu query.

Butuh SUPABASE_URL dan SUPABASE_SERVICE_ROLE_KEY di .env (sama seperti
yang dipakai bot.py).
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from location_normalizer import normalize_location  # noqa: E402


def _get_client():
    from dotenv import load_dotenv
    load_dotenv()

    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        sys.exit(
            "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY tidak ketemu di .env. "
            "Jalankan skrip ini dari folder project (yang ada .env-nya)."
        )
    return create_client(url, key)


def _semua_lokasi_unik(client) -> dict[str, int]:
    """Ambil tiap nilai location unik + jumlah barisnya, dengan paginasi.

    Supabase membatasi hasil per request (default 1000), jadi untuk tabel
    besar ini perlu diambil bertahap lewat range().
    """
    hasil: dict[str, int] = {}
    offset = 0
    ukuran_halaman = 1000

    while True:
        resp = (
            client.table("jobs")
            .select("location")
            .range(offset, offset + ukuran_halaman - 1)
            .execute()
        )
        baris = resp.data or []
        if not baris:
            break

        for row in baris:
            loc = row.get("location")
            hasil[loc] = hasil.get(loc, 0) + 1

        offset += len(baris)
        if len(baris) < ukuran_halaman:
            break

    return hasil


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Cuma tampilkan laporan, jangan ubah database.")
    args = parser.parse_args()

    client = _get_client()

    print("Mengambil semua nilai location unik dari tabel jobs...")
    lokasi_unik = _semua_lokasi_unik(client)
    total_baris = sum(lokasi_unik.values())
    print(f"Ditemukan {len(lokasi_unik)} nilai location unik "
          f"({total_baris:,} baris total)\n")

    # Kelompokkan berdasarkan hasil normalisasi (country, region), supaya
    # satu UPDATE bisa menangani banyak nilai location sekaligus kalau
    # kebetulan menghasilkan (country, region) yang sama.
    per_hasil: dict[tuple, list[str]] = {}
    tidak_dikenali: list[tuple[str, int]] = []

    for loc, jumlah in lokasi_unik.items():
        country, region = normalize_location(loc)
        if country is None and loc is not None:
            tidak_dikenali.append((loc, jumlah))
        per_hasil.setdefault((country, region), []).append(loc)

    # Laporan sebelum eksekusi
    print("=" * 70)
    print("RINGKASAN PEMETAAN")
    print("=" * 70)
    for (country, region), daftar_loc in sorted(
            per_hasil.items(), key=lambda kv: -sum(lokasi_unik[l] for l in kv[1])):
        jumlah = sum(lokasi_unik[l] for l in daftar_loc)
        label = f"{country or '(tidak diketahui)'}"
        if region:
            label += f" / {region}"
        print(f"  {jumlah:>7,} baris  ->  {label}  ({len(daftar_loc)} variasi teks)")

    if tidak_dikenali:
        tidak_dikenali.sort(key=lambda x: -x[1])
        total_tidak_dikenali = sum(j for _, j in tidak_dikenali)
        print()
        print(f"⚠️  {total_tidak_dikenali:,} baris ({len(tidak_dikenali)} variasi teks) "
              "TIDAK DIKENALI — country/region akan diisi NULL:")
        for loc, jumlah in tidak_dikenali[:30]:
            print(f"     {jumlah:>6,}x  {loc!r}")
        if len(tidak_dikenali) > 30:
            print(f"     ... dan {len(tidak_dikenali) - 30} variasi lain")
        print()
        print("Kalau ada yang seharusnya dikenali, tambahkan ke kamus di")
        print("location_normalizer.py (_KOTA_KE_PROVINSI atau _KOTA_ASING),")
        print("lalu jalankan ulang skrip ini — aman diulang berkali-kali.")

    if args.dry_run:
        print("\n--dry-run aktif: database TIDAK diubah.")
        return

    # Eksekusi: update per nilai location (bukan per hasil gabungan), supaya
    # progresnya jelas dan gampang di-retry kalau ada yang gagal di tengah.
    print("\nMenulis ke database...")
    berhasil = gagal = 0

    for loc, jumlah in sorted(lokasi_unik.items(), key=lambda kv: -kv[1]):
        country, region = normalize_location(loc)
        try:
            query = client.table("jobs").update(
                {"country": country, "region": region})
            if loc is None:
                query = query.is_("location", "null")
            else:
                query = query.eq("location", loc)
            query.execute()
            berhasil += 1
        except Exception as e:  # noqa: BLE001
            gagal += 1
            print(f"  GAGAL untuk location={loc!r}: {e}")

    print(f"\nSelesai: {berhasil} nilai location berhasil diupdate, "
          f"{gagal} gagal.")
    print(f"Total baris terpengaruh: ~{total_baris:,}")


if __name__ == "__main__":
    main()
