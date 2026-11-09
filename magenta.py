from __future__ import annotations

"""
Scraper untuk magentaku.id — MAGENTA (Magang Generasi Bertalenta), program
magang resmi Kementerian BUMN.

Berbeda dari MagangHub yang penyelenggaranya umum, MAGENTA khusus BUMN dan
anak usahanya: Kimia Farma, Pegadaian, Pelindo, Telkom, BTN, dan seterusnya.
Katalognya jauh lebih kecil (puluhan, bukan puluhan ribu) tapi kualitasnya
tinggi.

Halaman listing dirender di server, paginasi lewat ?page=N.

CATATAN PENTING: kartu lowongan TIDAK menautkan ke halaman detail — satu-
satunya tautan di dalamnya menuju profil perusahaan (/c/{kode}), dan detail
lowongan dibuka lewat modal JavaScript. Jadi tidak ada URL unik per lowongan.

Konsekuensinya:
  * `job_url` memakai halaman perusahaan + fragmen judul, supaya tetap unik
    dan tetap mengarah ke tempat yang masuk akal bagi pengguna
  * `job_id` dibentuk dari hash judul + perusahaan; kalau judulnya diubah
    pihak MAGENTA, row lama tidak ter-update melainkan muncul sebagai
    lowongan baru

Struktur kartu (dipastikan lewat lihat_kartu.py):

    h2.title                     <- judul posisi
    p.content-detail (ke-1)      <- nama perusahaan
    p.content-detail (ke-2)      <- lokasi
    p.show-quota-list            <- "1 Posisi • 120 Pelamar"
    span.caption                 <- badge: "Magang", "6 bulan", "Onsite"
    a[href*="/c/"]               <- profil perusahaan
"""

import hashlib
import re
import unicodedata

from categorize import classify_job

BASE_URL = "https://magentaku.id"
LIST_URL = f"{BASE_URL}/lowongan"

ALL_KEYWORDS = {"all", "semua", "*", ""}

_KUOTA = re.compile(r"(\d+)\s*Posisi", re.I)
_PELAMAR = re.compile(r"(\d+)\s*Pelamar", re.I)
_DURASI = re.compile(r"^\d+\s*(bulan|minggu|tahun)$", re.I)

_ARRANGEMENT = {
    "onsite": "onsite",
    "on site": "onsite",
    "hybrid": "hybrid",
    "remote": "remote",
    "wfh": "remote",
}


def _is_browse_all(query: str | None) -> bool:
    return (query or "").strip().lower() in ALL_KEYWORDS


def _slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "lowongan"


def _bersih(node) -> str | None:
    if node is None:
        return None
    text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
    return text or None


def search_magenta(query: str, limit: int = 100) -> list[dict]:
    from sites.base import get_soup

    keyword = "" if _is_browse_all(query) else query.strip().lower()
    jobs: list[dict] = []
    terlihat: set[str] = set()
    # Berapa kali tiap kombinasi judul+perusahaan+lokasi sudah ditemui.
    # Menerus lintas halaman.
    kemunculan: dict[str, int] = {}
    page = 1

    while len(jobs) < limit and page <= 30:
        try:
            soup = get_soup(LIST_URL, params={"page": page} if page > 1 else None)
        except Exception:  # noqa: BLE001
            break

        # Kartu dikenali dari judulnya, lalu naik satu tingkat ke pembungkus.
        # Pembungkusnya sendiri tidak punya class, jadi tidak bisa diseleksi
        # langsung.
        headings = soup.select("h2.title")
        if not headings:
            break

        sebelum = len(jobs)
        for heading in headings:
            title = _bersih(heading)
            card = heading.parent
            if not title or card is None:
                continue

            detail = card.select("p.content-detail")
            quota_node = card.select_one("p.show-quota-list")

            # Halaman ini juga memuat MODAL detail lowongan, dan heading di
            # dalamnya ("Pendidikan", "Rincian Lowongan") memakai class
            # `title` yang sama — tanpa pemeriksaan ini, heading modal ikut
            # tersimpan sebagai lowongan palsu berperusahaan "BUMN".
            #
            # Kartu asli SELALU punya nama perusahaan, lokasi, dan keterangan
            # kuota; heading modal tidak punya satu pun.
            if len(detail) < 2 or quota_node is None:
                continue

            company = _bersih(detail[0])
            location = _bersih(detail[1])
            if not company:
                continue

            teks_kuota = _bersih(quota_node) or ""

            # Pelindo memasang beberapa lowongan dengan judul, perusahaan, DAN
            # lokasi identik (mis. "Internship Divisi Pelayanan SDM dan Umum"
            # 4x di Kota Surabaya). Itu posisi terpisah, bukan duplikat — kunci
            # judul+perusahaan+lokasi saja membuang 4 dari 37 lowongan.
            #
            # Situsnya tidak menyediakan ID per lowongan, jadi pembedanya
            # adalah NOMOR KEMUNCULAN: yang identik pertama dapat #1, kedua
            # #2, dan seterusnya.
            #
            # SENGAJA TIDAK memakai nomor urut halaman. Nomor urut berubah
            # setiap ada lowongan baru masuk di atasnya, sehingga job_id ikut
            # berubah dan lowongan lama tersimpan ulang sebagai record baru
            # alih-alih ter-update. Nomor kemunculan tetap stabil selama
            # jumlah lowongan kembarnya tidak berubah.
            dasar = f"{title}|{company}|{location}"
            kemunculan[dasar] = kemunculan.get(dasar, 0) + 1
            kunci = f"{dasar}#{kemunculan[dasar]}"
            if kunci in terlihat:
                continue

            if keyword and keyword not in f"{title} {company or ''}".lower():
                continue

            cocok = _KUOTA.search(teks_kuota)
            kuota = int(cocok.group(1)) if cocok else None
            cocok = _PELAMAR.search(teks_kuota)
            pelamar = int(cocok.group(1)) if cocok else None

            durasi = arrangement = None
            for badge in card.select("span.caption"):
                nilai = (_bersih(badge) or "").strip()
                if _DURASI.match(nilai):
                    durasi = nilai
                elif nilai.lower() in _ARRANGEMENT:
                    arrangement = _ARRANGEMENT[nilai.lower()]

            link = card.select_one('a[href*="/c/"]')
            company_url = link["href"] if link and link.get("href") else BASE_URL

            terlihat.add(kunci)
            jobs.append({
                "title": title,
                "company": company,
                "location": location,
                "dedup_key": kunci,
                "company_url": company_url,
                "quota": kuota,
                "applicants": pelamar,
                "duration": durasi,
                "arrangement": arrangement,
            })
            if len(jobs) >= limit:
                break

        if len(jobs) == sebelum:
            break
        page += 1

    return jobs[:limit]


def magenta_to_records(
    jobs: list[dict],
    search_term: str,
    search_location: str | None,
    requested_by_chat_id: str,
) -> list[dict]:
    from categorize import classify_work_arrangement

    records = []
    for job in jobs:
        title = job.get("title")
        if not title:
            continue

        company = job.get("company") or "BUMN"
        location = job.get("location") or "Indonesia"
        company_url = job.get("company_url") or BASE_URL

        # Tanpa URL detail, fragmen judul dipakai agar tiap baris tetap unik
        # dan tautannya tetap mengarah ke profil perusahaan yang relevan.
        url = f"{company_url}#{_slug(title)}"
        job_id = hashlib.md5(
            job.get("dedup_key", f"{title}|{company}|{location}").encode()
        ).hexdigest()[:16]

        bits = []
        if job.get("duration"):
            bits.append(f"Durasi: {job['duration']}")
        if job.get("quota") is not None:
            bits.append(f"{job['quota']} posisi")
        if job.get("applicants") is not None:
            bits.append(f"{job['applicants']} pelamar")
        if job.get("quota") and job.get("applicants") is not None:
            rasio = job["applicants"] / job["quota"]
            bits.append(f"Rasio {rasio:.0f} pelamar per posisi")
        description = " | ".join(bits) or None

        arrangement = job.get("arrangement") or "onsite"

        records.append({
            "job_id": job_id,
            "site": "magenta",
            "job_url": url,
            "job_url_direct": company_url,
            "title": title,
            "company": company,
            "location": location,
            "date_posted": None,
            "job_type": "Internship",
            "salary_source": None,
            "interval": None,
            "min_amount": None,
            "max_amount": None,
            "currency": None,
            "is_remote": arrangement == "remote",
            "job_level": None,
            "job_function": None,
            "listing_type": None,
            "emails": None,
            "description": description,
            "company_industry": None,
            "company_url": company_url,
            "company_logo": None,
            "company_url_direct": None,
            "company_addresses": location,
            "company_num_employees": None,
            "company_revenue": None,
            "company_description": None,
            "skills": None,
            "experience_range": None,
            "company_rating": None,
            "company_reviews_count": None,
            "vacancy_count": job.get("quota"),
            "work_from_home_type": arrangement,
            "raw_salary": None,
            "category": classify_job(title, search_term),
            "work_arrangement": arrangement or classify_work_arrangement(
                False, title, "Internship", location),
            "employment_type": "magang",
            "search_term": search_term or "scrapeall",
            "search_location": search_location or location,
            "requested_by_chat_id": str(requested_by_chat_id),
        })
    return records
