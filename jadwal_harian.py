from __future__ import annotations

"""
Scrape SEMUA situs tanpa Telegram -- versi terjadwal dari /updateall dan
/carikerja. Dijalankan otomatis oleh GitHub Actions
(.github/workflows/scrape-harian.yml), atau manual:

    python jadwal_harian.py              # semua situs (= /updateall)
    python jadwal_harian.py --carikerja  # Indeed & LinkedIn, 68 kata kunci
    python jadwal_harian.py --reset      # KOSONGKAN tabel dulu (cara lama)

ALUR (tanpa reset): tabel TIDAK dikosongkan, jadi Jobly tidak pernah kosong.
  1. Hasil tiap situs di-upsert: lowongan yang masih ada ter-refresh
     `updated_at`-nya, lowongan baru ditambahkan.
  2. Begitu satu situs selesai, lowongan situs itu yang TIDAK muncul lagi
     (updated_at lebih tua dari waktu mulai situs itu) dihapus.
  3. Pengaman: kalau situs gagal, hasilnya 0, atau yang akan dihapus lebih
     banyak daripada yang baru didapat (tanda situs memblokir/error), data
     lama situs itu DIPERTAHANKAN.
  4. Di akhir --carikerja, lowongan yang sudah BASI_HARI hari tidak pernah
     muncul lagi (situs yang terus gagal/tutup, hasil /update manual) dihapus.

Indeed & LinkedIn: hasil per kata kunci saling tumpang tindih, jadi
penghapusan dilakukan sekali di akhir --carikerja, bukan per kata kunci.

Mencegah dua proses jalan bersamaan dengan file kunci (.jadwal.lock).
"""

import fcntl
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s",
                    level=logging.INFO)
# httpx mencatat setiap URL request di level INFO; di GitHub Actions log
# repo publik bisa dibaca siapa saja, jadi cukup tampilkan peringatan.
for _nama in ("httpx", "httpcore", "hpack", "urllib3"):
    logging.getLogger(_nama).setLevel(logging.WARNING)
log = logging.getLogger("jadwal_harian")

# Lowongan yang tidak muncul lagi selama ini dihapus apa pun alasannya.
BASI_HARI = 3


def _sekarang() -> datetime:
    # Mundur 5 menit sebagai jarak aman kalau jam runner dan jam database
    # sedikit berbeda. Lowongan yang baru di-upsert pasti lebih baru dari ini,
    # yang dari scrape kemarin (~24 jam lalu) pasti lebih tua.
    return datetime.now(timezone.utc) - timedelta(minutes=5)


def _tandai(records: list[dict]) -> list[dict]:
    """Isi updated_at secara eksplisit, supaya penanda "masih ada" tidak
    bergantung pada trigger set_updated_at di database."""
    kini = datetime.now(timezone.utc).isoformat()
    for r in records:
        r["updated_at"] = kini
    return records


def _hitung_basi(sites: list[str] | None, batas: datetime) -> int:
    import db
    q = db.get_client().table("jobs").select("id", count="exact").lt("updated_at", batas.isoformat())
    if sites:
        q = q.in_("site", sites)
    return q.limit(1).execute().count or 0


def _hapus_basi(sites: list[str] | None, batas: datetime) -> int:
    """Hapus per 500 baris supaya tidak kena statement timeout Supabase."""
    import db
    client = db.get_client()
    total = 0
    while True:
        q = client.table("jobs").select("id").lt("updated_at", batas.isoformat())
        if sites:
            q = q.in_("site", sites)
        ids = [r["id"] for r in (q.limit(500).execute().data or [])]
        if not ids:
            return total
        client.table("jobs").delete().in_("id", ids).execute()
        total += len(ids)


def _bersihkan(sites: list[str], batas: datetime, baru: int) -> str:
    """Hapus lowongan lama situs ini yang tidak muncul lagi. Return catatan."""
    try:
        basi = _hitung_basi(sites, batas)
        if not basi:
            return ""
        if basi > baru:
            return f" (⚠️ {basi} lama dipertahankan: hasil hari ini lebih sedikit)"
        return f" (−{_hapus_basi(sites, batas)} tutup)"
    except Exception as e:  # noqa: BLE001
        log.exception("Gagal hapus lowongan lama %s", sites)
        return f" (⚠️ gagal hapus lama: {str(e)[:40]})"


def _kirim(teks: str) -> None:
    import config

    import requests

    log.info(teks)
    tujuan = sorted(config.ALLOWED_CHAT_IDS)
    if not tujuan:
        log.warning("ALLOWED_CHAT_IDS kosong: ringkasan tidak dikirim ke Telegram.")
        return
    # Kirim ke SEMUA chat di ALLOWED_CHAT_IDS. Chat yang ditolak Telegram
    # (ID salah / belum pernah /start bot) dilewati; alasannya dicatat tanpa
    # memuat URL (URL berisi token bot).
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    terkirim = 0
    for i, chat in enumerate(tujuan, start=1):
        try:
            r = requests.post(url, json={"chat_id": chat, "text": teks[:4000]}, timeout=15)
            data = r.json()
        except Exception as e:  # noqa: BLE001
            log.warning("Chat #%d: gagal kirim (%s)", i, type(e).__name__)
            continue
        if data.get("ok"):
            terkirim += 1
        else:
            log.warning("Chat #%d ditolak Telegram: %s", i, data.get("description"))
    log.info("Ringkasan terkirim ke %d dari %d chat", terkirim, len(tujuan))


def carikerja() -> int:
    """Versi terjadwal dari /carikerja -> Semua kelompok."""
    import config
    import db
    from kata_kunci import HASIL_PER_KATA, SITUS, _daftar_kata
    from scraper import df_to_records, run_search

    mulai = time.time()
    batas = _sekarang()
    kata = _daftar_kata("semua")
    catatan: list[str] = []
    total = 0
    per_situs: dict[str, int] = {}
    for i, term in enumerate(kata, start=1):
        log.info("(%d/%d) %s ...", i, len(kata), term)
        try:
            df = run_search(search_term=term, location=config.DEFAULT_LOCATION,
                            sites=SITUS, country_indeed=config.DEFAULT_COUNTRY_INDEED,
                            results_wanted=HASIL_PER_KATA)
            records = df_to_records(df, search_term=term,
                                    search_location=config.DEFAULT_LOCATION,
                                    requested_by_chat_id="jadwal")
            if not records:
                catatan.append(f"⚪ {term}: 0")
                continue
            unik = _tandai(db.deduplicate(records)[0])
            simpan = db.upsert_jobs(unik)
            total += simpan
            for r in unik:
                per_situs[r.get("site")] = per_situs.get(r.get("site"), 0) + 1
            catatan.append(f"✅ {term}: {simpan}")
        except Exception as e:  # noqa: BLE001
            log.exception("Gagal untuk '%s'", term)
            catatan.append(f"❌ {term}: {str(e)[:50]}")

    # Bersihkan Indeed/LinkedIn yang tidak muncul lagi di 68 kata kunci.
    bersih = []
    for situs in SITUS:
        baru = per_situs.get(situs, 0)
        if baru:
            bersih.append(f"{situs}: {baru}" + _bersihkan([situs], batas, baru))
        else:
            bersih.append(f"{situs}: 0, data lama dipertahankan")
    # Lowongan semua situs yang BASI_HARI hari tidak muncul lagi.
    try:
        lama = _hapus_basi(None, datetime.now(timezone.utc) - timedelta(days=BASI_HARI))
        if lama:
            bersih.append(f"−{lama} lowongan yang {BASI_HARI} hari tidak muncul lagi")
    except Exception:  # noqa: BLE001
        log.exception("Gagal hapus lowongan basi")
    catatan.insert(0, "\n".join(bersih) + "\n")

    menit = (time.time() - mulai) / 60
    _kirim(f"🔎 Cari kerja terjadwal ({', '.join(SITUS)}) selesai ({menit:.0f} menit): "
           f"{total} loker tersimpan/terupdate\n\n" + "\n".join(catatan))
    return 0


def main() -> int:
    kunci = open(Path(__file__).with_name(".jadwal.lock"), "w")
    try:
        fcntl.flock(kunci, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.warning("Scrape terjadwal lain masih berjalan, yang ini dilewati.")
        return 0

    if "--carikerja" in sys.argv:
        return carikerja()

    import config
    import db
    import sites

    mulai = time.time()
    specs, _ = sites.resolve(["all"])
    if not config.WEB3CAREER_API_TOKEN:
        # Tanpa token, situs ini pasti gagal; lewati supaya laporan bersih.
        specs = [s for s in specs if s.name != "web3career"]
    catatan: list[str] = []
    total = 0

    direset = "--reset" in sys.argv
    if direset:
        log.info("Mengosongkan tabel jobs (reset_jobs) ...")
        try:
            db.get_client().rpc("reset_jobs").execute()
            catatan.append("🗑 Tabel jobs dikosongkan sebelum scrape")
        except Exception as e:  # noqa: BLE001
            # Lanjut scrape saja: data lama tetap di-update lewat upsert.
            log.exception("Reset gagal, lanjut scrape tanpa reset")
            catatan.append(f"⚠️ Reset gagal ({str(e)[:60]}), data lama tidak dihapus")

    for i, spec in enumerate(specs, start=1):
        log.info("(%d/%d) %s ...", i, len(specs), spec.label)
        batas = _sekarang()
        try:
            records = sites.run(spec, query="semua", limit=config.SCRAPE_ALL_RESULTS,
                                chat_id="jadwal", search_location=config.DEFAULT_LOCATION)
        except Exception as e:  # noqa: BLE001
            log.exception("Gagal scrape %s", spec.name)
            catatan.append(f"❌ {spec.label}: {str(e)[:60]}")
            continue
        if not records:
            catatan.append(f"⚪ {spec.label}: 0")
            continue
        unik = _tandai(db.deduplicate(records)[0])
        try:
            simpan = db.upsert_jobs(unik)
        except Exception as e:  # noqa: BLE001
            log.exception("Gagal simpan %s", spec.name)
            catatan.append(f"⚠️ {spec.label}: {len(unik)} didapat, gagal simpan")
            continue
        total += simpan
        tambahan = ""
        if not direset:
            nama_situs = sorted({str(r.get("site")) for r in unik if r.get("site")})
            tambahan = _bersihkan(nama_situs, batas, simpan)
        catatan.append(f"✅ {spec.label}: {simpan}{tambahan}")
        log.info("   %s: %d tersimpan", spec.label, simpan)

    menit = (time.time() - mulai) / 60
    _kirim(f"🗓 Scrape semua situs selesai ({menit:.0f} menit): "
           f"{total} loker tersimpan/terupdate\n\n" + "\n".join(catatan))
    return 0


if __name__ == "__main__":
    sys.exit(main())