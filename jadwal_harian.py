from __future__ import annotations

"""
Scrape SEMUA situs registry tanpa Telegram -- versi terjadwal dari /updateall.

Dijalankan otomatis oleh GitHub Actions (.github/workflows/scrape-harian.yml)
atau systemd timer (jobspy-scrape.timer), atau manual:

    python jadwal_harian.py              # semua situs (= /updateall)
    python jadwal_harian.py --reset      # KOSONGKAN tabel dulu, lalu semua situs
    python jadwal_harian.py --carikerja  # Indeed & LinkedIn, 68 kata kunci
                                         # (= /carikerja -> Semua kelompok)

--reset memanggil fungsi Postgres reset_jobs() (TRUNCATE ... RESTART
IDENTITY), sama seperti /reset di Telegram. Fungsinya harus sudah dibuat
lewat reset_jobs.sql.

Sama seperti /updateall: hasil tiap situs langsung di-upsert ke Supabase
begitu situs itu selesai, jadi kalau proses berhenti di tengah, situs yang
sudah selesai tetap tersimpan. Ringkasan dikirim ke chat Telegram pertama di
ALLOWED_CHAT_IDS (kalau diisi).

Di Oracle Always Free, jadwal harian ini juga membantu server tidak dianggap
"menganggur" (Oracle bisa mengambil kembali VM yang CPU, jaringan, dan
memorinya di bawah 20% selama 7 hari).

Mencegah dua proses jalan bersamaan dengan file kunci (.jadwal.lock).
"""

import fcntl
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s",
                    level=logging.INFO)
# httpx mencatat setiap URL request di level INFO; di GitHub Actions log
# repo publik bisa dibaca siapa saja, jadi cukup tampilkan peringatan.
for _nama in ("httpx", "httpcore", "hpack", "urllib3"):
    logging.getLogger(_nama).setLevel(logging.WARNING)
log = logging.getLogger("jadwal_harian")


def _kirim(teks: str) -> None:
    import config

    log.info(teks)
    tujuan = sorted(config.ALLOWED_CHAT_IDS)[:1]
    if not tujuan:
        log.warning("ALLOWED_CHAT_IDS kosong: ringkasan tidak dikirim ke Telegram.")
        return
    try:
        from telegram_api import send_message
        send_message(tujuan[0], teks[:4000], parse_mode=None)
    except Exception:  # noqa: BLE001
        log.exception("Gagal mengirim ringkasan ke Telegram")


def carikerja() -> int:
    """Versi terjadwal dari /carikerja -> Semua kelompok."""
    import config
    import db
    from kata_kunci import HASIL_PER_KATA, SITUS, _daftar_kata
    from scraper import df_to_records, run_search

    mulai = time.time()
    kata = _daftar_kata("semua")
    catatan: list[str] = []
    total = 0
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
            unik, _ = db.deduplicate(records)
            simpan = db.upsert_jobs(unik)
            total += simpan
            catatan.append(f"✅ {term}: {simpan}")
        except Exception as e:  # noqa: BLE001
            log.exception("Gagal untuk '%s'", term)
            catatan.append(f"❌ {term}: {str(e)[:50]}")

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
    catatan: list[str] = []
    total = 0

    if "--reset" in sys.argv:
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
        unik, _ = db.deduplicate(records)
        try:
            simpan = db.upsert_jobs(unik)
        except Exception as e:  # noqa: BLE001
            log.exception("Gagal simpan %s", spec.name)
            catatan.append(f"⚠️ {spec.label}: {len(unik)} didapat, gagal simpan")
            continue
        total += simpan
        catatan.append(f"✅ {spec.label}: {simpan}")
        log.info("   %s: %d tersimpan", spec.label, simpan)

    menit = (time.time() - mulai) / 60
    _kirim(f"🗓 Scrape semua situs selesai ({menit:.0f} menit): "
           f"{total} loker tersimpan/terupdate\n\n" + "\n".join(catatan))
    return 0


if __name__ == "__main__":
    sys.exit(main())
