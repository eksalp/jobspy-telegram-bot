from __future__ import annotations

"""
Scraper untuk toploker.com.

CATATAN PENTING soal endpoint: dua path listing di situs ini berperilaku
BEDA TOTAL.

  /loker/daftar/{N}       -> DIBLOKIR diam-diam. Berapa pun N, server selalu
                             menyajikan konten identik dengan halaman 1
                             (dipastikan dengan mengecek link kartu pertama
                             di banyak nilai N: semuanya sama). Alat fetch
                             eksternal pun ditolak "bot detection" di path
                             ini. Kemungkinan besar proteksi Cloudflare yang
                             menyajikan fallback ke traffic non-browser,
                             tanpa memberi tahu (beda dari Cloudflare
                             Challenge yang terang-terangan menampilkan
                             "Just a moment...").

  /rekomendasi/daftar/{N} -> JALAN NORMAL. N di sini adalah OFFSET (bukan
                             nomor halaman), kelipatan 8 (ukuran halaman
                             situs ini). Dipastikan dengan pencarian biner:
                             isi berbeda-beda dan TIDAK BERPUTAR sampai
                             offset ~11.000, lalu kosong -- total katalog
                             sekitar 11.000+ lowongan.

Makanya LIST_URL modul ini memakai /rekomendasi/daftar, BUKAN /loker/daftar
yang tampak seperti listing utama di navigasi situsnya.

CATATAN PENTING LAIN -- masih berlaku di endpoint mana pun:

JUDUL LOWONGAN YANG TAMPIL DI KARTU SELALU TERPOTONG. Contoh nyata:
kartu menampilkan "dosen program studi s1 pendidikan" tapi lowongan
aslinya "Dosen Program Studi S1 Pendidikan Teknologi Informasi" -- separuh
kalimat hilang di tampilan (kemungkinan CSS truncation atau limit render
di sisi mereka). Contoh lain: kartu menampilkan "sales marketing manager,
sales executive," tapi judul asli "Sales Marketing Manager Sales
Executive Leader Masterpark".

Untungnya URL detail-nya SELALU memuat judul LENGKAP dalam bentuk slug:

    https://toploker.com/lowongan/{tanggal}!{judul-slug}-{id}!di!{perusahaan-slug}

Jadi judul dan (sebagian) nama perusahaan diambil dari SLUG URL, BUKAN dari
teks yang tampil di kartu. Field lain (tanggal, pendidikan, tipe kerja,
lokasi, gaji) aman diambil dari span masing-masing karena tidak terpotong.

CATATAN slug perusahaan: kadang punya ID internal nempel di akhir (mis.
"grand-master-223" untuk perusahaan "Grand Master"), kadang tidak (mis.
"universitas-sains-dan-teknologi-komputer" tanpa angka sama sekali).
Angka di akhir dibuang HANYA kalau memang ada -- lihat _urai_slug().

CATATAN dominasi satu perusahaan di offset awal: BukuWarung (PT Buku Usaha
Digital) memasang sangat banyak lowongan sejenis berulang -- offset 0-16
nyaris 100% perusahaan itu saja. Bukan bug, itu memang isi situsnya.
Keragaman baru terlihat mulai offset ~24 ke atas.

Struktur kartu (dipastikan lewat try_selector.py --html):

    div.card.shadoww.p-3                              <- satu kartu
      span.font-weight-bold (dgn fa-calendar-alt)       <- tanggal posting
      a[href^="https://toploker.com/lowongan/"]         <- link + slug judul
      span.text-uppercase.font-weight-bold              <- nama perusahaan
        (kadang ada span.tooltip-custom bersarang untuk
         badge "Perusahaan Terverifikasi" -- harus dibuang
         sebelum ambil teks, atau ikut terbaca sebagai
         bagian nama perusahaan)
      span (dgn fa-user-graduate)                       <- pendidikan
      span (dgn fa-user-clock)                          <- tipe kerja
      span.text-capitalize (dgn fa-map-marked-alt)      <- lokasi
      span (dgn fa-money-bill-wave)                     <- gaji, atau "-"
"""

import re
from urllib.parse import urljoin

from categorize import classify_job

BASE_URL = "https://toploker.com"
# BUKAN /loker/daftar -- path itu diblokir diam-diam. Lihat catatan modul.
LIST_URL = f"{BASE_URL}/rekomendasi/daftar"
PER_PAGE = 8  # ukuran halaman situs ini; offset harus kelipatan angka ini

ALL_KEYWORDS = {"all", "semua", "*", ""}

CARD_SELECTOR = "div.card.shadoww.p-3"


# Pola longgar: cuma pisahkan 3 bagian besar via literal "!"..."!di!"...
# Bagian judul dan job_id DIPISAH BELAKANGAN secara terpisah (lihat
# _urai_slug), karena format penyambungannya TERNYATA TIDAK KONSISTEN --
# ditemukan setelah adapter versi awal salah membuang 33 dari 200 lowongan
# nyata (16.5%). Tiga pola job_id yang sama-sama muncul di data asli:
#   "...-690!di!..."           id dipisah tanda hubung (pola awal yang
#                               sempat dikira satu-satunya)
#   "...collection1994!di!..." id NEMPEL LANGSUNG tanpa tanda hubung
#   "...jawa-tengah!di!..."    TIDAK ADA id numerik sama sekali di slug
_POLA_SLUG = re.compile(r"/lowongan/([\d-]+)!(.+)!di!(.+)$")


def _is_browse_all(query: str | None) -> bool:
    return (query or "").strip().lower() in ALL_KEYWORDS


def _urai_slug(url: str) -> dict | None:
    """Ambil judul LENGKAP, job_id, dan nama perusahaan dari slug URL.

    Dipakai karena teks yang tampil di kartu (span judul) selalu terpotong
    -- lihat catatan modul di atas.

    job_id TIDAK SELALU ada sebagai angka eksplisit di slug -- lihat tiga
    pola berbeda di komentar _POLA_SLUG. Kalau tidak ketemu angka sama
    sekali, dipakai hash dari URL lengkap sebagai pengganti: tetap stabil
    (URL yang sama selalu menghasilkan job_id yang sama) dan tetap unik
    antar lowongan berbeda, meski bukan angka asli dari sistem mereka.
    """
    m = _POLA_SLUG.search(url)
    if not m:
        return None
    _tanggal, bagian_judul, perusahaan_slug = m.groups()

    # Judul: buang angka di ujung bagian_judul kalau ada (boleh nempel
    # langsung ATAU didahului tanda hubung), murni untuk KERAPIAN TEKS
    # judul saja -- BUKAN untuk job_id (lihat di bawah).
    m_id = re.search(r"(\d+)$", bagian_judul)
    judul_slug = bagian_judul[:m_id.start()].rstrip("-") if m_id else bagian_judul
    judul = judul_slug.replace("-", " ").strip().title()

    # job_id SELALU dari hash URL LENGKAP -- BUKAN dari angka mentah di
    # slug. Sempat dipakai angka mentah itu langsung (mis. "690") dengan
    # asumsi ID tersebut unik per lowongan di sistem TopLoker -- TERBUKTI
    # SALAH: dari 9989 lowongan yang berhasil di-scrape, cuma 1070 yang
    # tersimpan ke database karena db.py men-dedup berdasarkan (site,
    # job_id) sebelum upsert. Rentang angka di slug itu ternyata sempit
    # (kemungkinan cuma beberapa ribu nilai), jadi banyak lowongan BEDA
    # TOTAL (perusahaan lain, judul lain, tanggal lain) kebetulan berakhir
    # dengan angka yang sama, saling menimpa lewat dedup.
    #
    # URL lengkap (tanggal+judul+perusahaan digabung) jauh lebih unik
    # secara praktis. Hash MD5 dari string yang sama akan selalu
    # menghasilkan output yang sama, jadi lowongan yang sama tetap
    # ter-update dengan benar kalau di-scrape ulang di masa depan --
    # bukan tersimpan dobel.
    import hashlib
    job_id = hashlib.md5(url.encode()).hexdigest()[:16]

    # Slug perusahaan kadang punya ID internal nempel di akhir (mis.
    # "grand-master-223"), kadang tanggal PENUH nempel (mis.
    # "pt-arull-onshop-2026-06-27" -- bukan sekadar satu angka ID biasa,
    # makanya tanggal dibuang dulu sebagai satu blok sebelum baru cek
    # angka tunggal biasa).
    perusahaan_slug = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", perusahaan_slug)
    perusahaan_slug = re.sub(r"-\d+$", "", perusahaan_slug)
    perusahaan = perusahaan_slug.replace("-", " ").strip().title()

    return {"judul": judul, "job_id": job_id, "perusahaan": perusahaan}


def _teks_bersih(node) -> str | None:
    if node is None:
        return None
    teks = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
    return teks or None


def _cari_span_ikon(card, kelas_ikon: str) -> str | None:
    """Cari span yang memuat <i class="{kelas_ikon} ..."> di dalamnya,
    kembalikan teks span itu (minus ikonnya sendiri)."""
    ikon = card.select_one(f"i.{kelas_ikon}")
    if ikon is None:
        return None
    span = ikon.find_parent("span")
    if span is None:
        return None
    # Ambil teks span TANPA ikut membaca teks di dalam <i> (ikon FontAwesome
    # tidak punya teks, tapi berjaga-jaga tetap dikecualikan eksplisit).
    return _teks_bersih(span)


def search_toploker(query: str, limit: int = 100) -> list[dict]:
    from sites.base import get_soup

    keyword = "" if _is_browse_all(query) else query.strip().lower()
    jobs: list[dict] = []
    seen: set[str] = set()
    offset = 0

    # Katalog ~11.000 lowongan (dipastikan lewat pencarian biner manual),
    # jadi batas pengaman dinaikkan jauh dari versi lama (yang cuma
    # mengasumsikan puluhan lowongan). 1500 halaman x 8 = 12.000 lowongan,
    # sedikit di atas total yang terukur.
    maks_halaman = 1500

    for _ in range(maks_halaman):
        if len(jobs) >= limit:
            break
        try:
            # URL ini pakai OFFSET di path (bukan query string ?page=),
            # dan offset HARUS kelipatan PER_PAGE -- lihat catatan modul
            # soal endpoint /rekomendasi/daftar.
            url = LIST_URL if offset == 0 else f"{LIST_URL}/{offset}"
            soup = get_soup(url)
        except Exception:  # noqa: BLE001
            break

        cards = soup.select(CARD_SELECTOR)
        if not cards:
            break

        sebelum = len(jobs)
        for card in cards:
            link = card.select_one('a[href*="/lowongan/"]')
            if not link or not link.get("href"):
                continue
            url_lowongan = urljoin(BASE_URL, link["href"])
            if url_lowongan in seen:
                continue

            info_slug = _urai_slug(url_lowongan)
            if not info_slug:
                continue

            judul = info_slug["judul"]

            # Nama perusahaan: span tampilan biasanya AMAN (tidak terpotong
            # seperti judul), tapi bisa memuat teks tooltip badge verifikasi
            # yang bersarang di dalamnya ("Perusahaan Terverifikasi..." dst).
            # Kalau ada tooltip, buang dulu sebelum ambil teks -- sisanya
            # baru dibandingkan dengan hasil slug sebagai cadangan.
            span_perusahaan = card.select_one("div.text-center.mt-3 span.text-uppercase")
            # Cek verifikasi DULU, SEBELUM membuang tooltip -- ikon
            # fa-badge-check ada DI DALAM tooltip itu sendiri. Kalau

            # tooltip di-extract lebih dulu, ikonnya ikut hilang dan
            # status verifikasi selalu terbaca False walau sebenarnya True.
            terverifikasi = (
                span_perusahaan.select_one("i.fa-badge-check") is not None
                if span_perusahaan else False
            )

            perusahaan = None
            if span_perusahaan:
                tooltip = span_perusahaan.select_one(".tooltip-custom")
                if tooltip:
                    tooltip.extract()
                perusahaan = _teks_bersih(span_perusahaan)
            # Title-case supaya konsisten baik yang berasal dari span
            # tampilan maupun dari fallback slug URL -- tanpa ini,
            # sebagian nama perusahaan tampil huruf kecil semua ("grand
            # master") sementara yang lain rapi ("Universitas Sains...").
            perusahaan = (perusahaan or info_slug["perusahaan"]).title()

            if keyword and keyword not in f"{judul} {perusahaan}".lower():
                continue

            tanggal = _teks_bersih(card.select_one("div.mb-2 span.font-weight-bold"))
            pendidikan = _cari_span_ikon(card, "fa-user-graduate")
            tipe_kerja = _cari_span_ikon(card, "fa-user-clock")
            lokasi = _cari_span_ikon(card, "fa-map-marked-alt")
            gaji_teks = _cari_span_ikon(card, "fa-money-bill-wave")
            gaji_teks = None if gaji_teks == "-" else gaji_teks

            seen.add(url_lowongan)
            jobs.append({
                "title": judul,
                "company": perusahaan,
                "url": url_lowongan,
                "job_id": info_slug["job_id"],
                "location": lokasi,
                "education": pendidikan,
                "job_type": tipe_kerja,
                "salary_text": gaji_teks,
                "date_text": tanggal,
                "verified": terverifikasi,
            })
            if len(jobs) >= limit:
                break

        # Halaman ini tidak menambah lowongan baru sama sekali -- kemungkinan
        # semua isinya duplikat dari halaman sebelumnya (situsnya menggeser
        # urutan saat lowongan baru masuk). Berhenti daripada berputar-putar
        # tanpa hasil.
        if len(jobs) == sebelum:
            break

        offset += PER_PAGE

    return jobs[:limit]


def toploker_to_records(
    jobs: list[dict],
    search_term: str,
    search_location: str | None,
    requested_by_chat_id: str,
) -> list[dict]:
    from categorize import classify_employment_type, classify_work_arrangement

    records = []
    for job in jobs:
        title = job.get("title")
        url = job.get("url")
        job_id = job.get("job_id")
        if not title or not url or not job_id:
            continue

        location = job.get("location") or "Indonesia"
        job_type = job.get("job_type")

        bits = []
        if job.get("verified"):
            bits.append("Perusahaan terverifikasi TopLoker")
        if job.get("date_text"):
            bits.append(f"Diposting: {job['date_text']}")
        description = " | ".join(bits) or None

        records.append({
            "job_id": str(job_id),
            "site": "toploker",
            "job_url": url,
            "job_url_direct": url,
            "title": title,
            "company": job.get("company") or "Tidak disebutkan",
            "location": location,
            "date_posted": None,
            "job_type": job_type,
            "salary_source": None,
            "interval": None,
            "min_amount": None,
            "max_amount": None,
            "currency": None,
            "is_remote": None,
            "job_level": job.get("education"),
            "job_function": None,
            "listing_type": "verified" if job.get("verified") else None,
            "emails": None,
            "description": description,
            "company_industry": None,
            "company_url": BASE_URL,
            "company_logo": None,
            "company_url_direct": None,
            "company_addresses": location,
            "company_num_employees": None,
            "company_revenue": None,
            "company_description": None,
            "skills": None,
            "experience_range": job.get("education"),
            "company_rating": None,
            "company_reviews_count": None,
            "vacancy_count": None,
            "work_from_home_type": None,
            "raw_salary": job.get("salary_text"),
            "category": classify_job(title, search_term),
            "work_arrangement": classify_work_arrangement(
                None, title, job_type, location),
            "employment_type": classify_employment_type(job_type, title),
            "search_term": search_term or "scrapeall",
            "search_location": search_location or location,
            "requested_by_chat_id": str(requested_by_chat_id),
        })
    return records
