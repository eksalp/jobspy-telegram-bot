from __future__ import annotations

"""
Scraper untuk jobindo.com.

Situs ini pakai Laravel + Inertia.js. Endpoint listing biasa cuma
menampilkan 10 lowongan pertama dan mengabaikan parameter ?page= (server
selalu redirect balik ke URL tanpa page). Data lengkap didapat lewat
endpoint partial Inertia:

    GET https://jobindo.com/lowongan-kerja-terbaru?page=N
    Header wajib:
        x-inertia: true
        x-inertia-partial-component: front/job/latest-page
        x-inertia-partial-data: jobs
        x-inertia-version: <versi berjalan, lihat _ambil_versi_inertia>
        x-requested-with: XMLHttpRequest

Tanpa cookie/login sama sekali -- sempat dicoba dan berhasil dengan status
200 murni dari request bersih. Total katalog saat ditulis: 197 lowongan,
20 halaman @ 10/halaman -- volume kecil, jadi diambil semua sekali jalan
tanpa perlu checkpoint.

CATATAN PENTING soal versi Inertia: kalau `x-inertia-version` yang dikirim
tidak cocok dengan versi build situs saat itu, server membalas HTTP 409
dengan header `x-inertia-location` -- ini BUKAN error/blokir, itu memang
begitu cara kerja Inertia. Kalau situsnya deploy ulang, versi berubah dan
scraper perlu tahu versi baru. `_ambil_versi_inertia()` membaca versi itu
otomatis dari halaman HTML biasa (yang selalu bisa diakses bebas), supaya
adapter tidak pernah hardcode versi yang bisa kedaluwarsa.

CATATAN soal field yang TIDAK bisa dipercaya: `application_deadline_timestamp`
di respons API SELALU SAMA dengan `date_available_timestamp` -- ini bug di
API mereka, bukan kesalahan pembacaan. Deadline yang benar dan konsisten
dengan expires_format ada di field `expires` (unix timestamp mentah).

PERUBAHAN API (Oktober 2026): endpoint daftar di atas sekarang hanya
mengembalikan ringkasan kartu (title, company berupa string, region_txt,
posted_at, salary_txt, job_url RELATIF, dst). Field lengkap -- `message`
(kualifikasi), `html` (deskripsi), `region_name`, `created_at`,
`apply_url`, `posting_address`, plus `company_profile` -- sekarang HANYA
ada di halaman detail tiap lowongan, di atribut data-page (props.job dan
props.company_profile). Gejalanya waktu itu: semua lowongan Jobindo masuk
database dengan lokasi "Indonesia", tanpa deskripsi/tanggal/level, tanpa
error apa pun. Makanya search_jobindo() sekarang membuka halaman detail
tiap lowongan (paralel) dan menggabungkannya ke data daftar.

CATATAN soal gaji: `salary_min`/`salary_max` TIDAK bisa dipercaya sebagai
angka (contoh nyata: salary_max=30 untuk "Rp3.000.000", salary_min=1 untuk
"Rp0"). Yang dipakai teks jadinya, `salary_min_name`/`salary_max_name`,
dan hanya kalau `has_salary` true (kalau false, situsnya menampilkan
"Rahasia").
"""

import re

from categorize import classify_job

BASE_URL = "https://jobindo.com"
LIST_URL = f"{BASE_URL}/lowongan-kerja-terbaru"
PARTIAL_COMPONENT = "front/job/latest-page"

ALL_KEYWORDS = {"all", "semua", "*", ""}

_HEADERS_DASAR = {
    "Accept": "text/html, application/xhtml+xml",
    "X-Requested-With": "XMLHttpRequest",
}


def _is_browse_all(query: str | None) -> bool:
    return (query or "").strip().lower() in ALL_KEYWORDS


def _ambil_versi_inertia() -> str:
    """Baca x-inertia-version yang sedang berlaku dari halaman HTML biasa.

    Versi ini berubah tiap situs deploy ulang. Membaca otomatis dari HTML
    (yang selalu bisa diakses bebas, terbukti dari fetch awal) supaya
    adapter tidak pernah hardcode angka yang bisa basi.

    Inertia menaruh data halaman awal di atribut `data-page="..."` pada
    <div id="app">, dengan tanda kutip di-escape HTML (&quot;), BUKAN
    sebagai JSON polos dengan tanda kutip biasa. Regex yang mencari
    '"version":"..."' literal tidak akan pernah cocok -- makanya diambil
    ISI ATRIBUTNYA dulu, di-unescape, baru di-parse sebagai JSON. Ini juga
    lebih tahan banting terhadap perubahan spasi/urutan key dibanding
    menebak lewat regex pada JSON mentah.
    """
    import html as html_lib
    import json

    from sites.base import http_get

    html = http_get(LIST_URL, retries=2, timeout=20).text

    m = re.search(r'data-page="([^"]*)"', html)
    if not m:
        raise RuntimeError(
            "Tidak menemukan atribut data-page di HTML jobindo.com. "
            "Kemungkinan situsnya mengubah cara render halamannya."
        )

    mentah = html_lib.unescape(m.group(1))
    try:
        data_awal = json.loads(mentah)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"data-page ditemukan tapi bukan JSON valid: {e}"
        ) from e

    versi = data_awal.get("version")
    if not versi:
        raise RuntimeError(
            "data-page tidak memuat field 'version'. Struktur Inertia "
            "situs ini mungkin sudah berubah."
        )
    return versi


def _ambil_halaman(halaman: int, versi: str) -> dict:
    from sites.base import http_get

    headers = {
        **_HEADERS_DASAR,
        "X-Inertia": "true",
        "X-Inertia-Partial-Component": PARTIAL_COMPONENT,
        "X-Inertia-Partial-Data": "jobs",
        "X-Inertia-Version": versi,
    }
    resp = http_get(LIST_URL, params={"page": halaman}, headers=headers,
                    retries=2, timeout=20)
    return resp.json()


def _parse_data_page(teks_html: str) -> dict | None:
    import html as html_lib
    import json

    m = re.search(r'data-page="([^"]*)"', teks_html)
    if not m:
        return None
    try:
        return json.loads(html_lib.unescape(m.group(1)))
    except json.JSONDecodeError:
        return None


def _ambil_detail(job_url: str) -> dict | None:
    """Buka halaman detail satu lowongan, kembalikan props.job yang lengkap.

    props.company_profile ikut disisipkan sebagai `_company_profile`.
    Kembalikan None kalau gagal -- pemanggil tetap memakai data daftar.
    """
    from urllib.parse import urljoin

    from sites.base import http_get

    url = urljoin(BASE_URL, job_url or "")
    if not url.startswith(BASE_URL):
        return None
    try:
        resp = http_get(url, retries=2, timeout=20)
    except Exception:  # noqa: BLE001
        return None
    data = _parse_data_page(resp.text) or {}
    props = data.get("props") or {}
    job = props.get("job")
    if not isinstance(job, dict):
        return None
    job = dict(job)
    job["_company_profile"] = props.get("company_profile") or {}
    return job


def _lengkapi_dengan_detail(jobs: list[dict], max_workers: int = 6) -> list[dict]:
    """Gabungkan data halaman detail ke tiap lowongan (paralel)."""
    from concurrent.futures import ThreadPoolExecutor

    def satu(job: dict) -> dict:
        detail = _ambil_detail(job.get("job_url") or job.get("url") or "")
        return {**job, **detail} if detail else job

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(satu, jobs))


def search_jobindo(query: str, limit: int = 200) -> list[dict]:
    keyword = "" if _is_browse_all(query) else query.strip().lower()

    versi = _ambil_versi_inertia()
    jobs: list[dict] = []
    halaman = 1
    total_halaman = None

    while len(jobs) < limit:
        try:
            data = _ambil_halaman(halaman, versi)
        except Exception as e:  # noqa: BLE001
            # Kalau versi berubah di tengah proses (situsnya deploy ulang
            # persis saat kita scraping), ambil versi baru sekali dan
            # lanjutkan dari halaman yang sama -- bukan mengulang dari awal.
            if "409" in str(e) or "Expecting value" in str(e):
                versi = _ambil_versi_inertia()
                data = _ambil_halaman(halaman, versi)
            else:
                raise

        info = data.get("props", {}).get("jobs", {})
        batch = info.get("data") or []
        if not batch:
            break

        if keyword:
            batch = [
                j for j in batch
                if keyword in (j.get("title") or "").lower()
                or keyword in _nama_perusahaan(j).lower()
            ]

        jobs.extend(batch)

        if total_halaman is None:
            total_halaman = info.get("last_page") or 1
        halaman += 1
        if halaman > total_halaman:
            break

    return _lengkapi_dengan_detail(jobs[:limit])


def _nama_perusahaan(job: dict) -> str:
    # Format lama: employer_detail.company. Format baru: company (string).
    employer = job.get("employer_detail") or {}
    company = job.get("company")
    if isinstance(company, dict):
        company = company.get("name") or company.get("company")
    return (employer.get("company") or company or "").strip()


def _rupiah(teks: str | None) -> int | None:
    angka = re.sub(r"[^0-9]", "", teks or "")
    return int(angka) if angka and int(angka) > 0 else None


_WORK_ARRANGEMENT = {"on-site": "onsite", "onsite": "onsite",
                     "remote": "remote", "hybrid": "hybrid"}


def jobindo_to_records(
    jobs: list[dict],
    search_term: str,
    search_location: str | None,
    requested_by_chat_id: str,
) -> list[dict]:
    from categorize import classify_employment_type, classify_work_arrangement
    from sites.base import strip_html

    records = []
    for job in jobs:
        title = (job.get("title") or "").strip()
        job_id = job.get("id")
        if not title or not job_id:
            continue

        from urllib.parse import urljoin

        url = job.get("url") or urljoin(
            BASE_URL, job.get("job_url") or f"/lowongan-pekerjaan/{job_id}")
        location = (job.get("region_name") or job.get("region_txt")
                    or "Indonesia")

        employer = dict(job.get("employer_detail") or {})
        profil = job.get("_company_profile") or {}
        company = _nama_perusahaan(job) or profil.get("company") or "Tidak disebutkan"
        logo = job.get("logo_url") or profil.get("logo_url") or employer.get("logo_url")

        job_type = job.get("job_type_name") or job.get("job_type_txt")
        education = job.get("education_level_name") or job.get("education_level_txt")
        pengalaman = job.get("experience_txt")
        function = job.get("job_category_name") or job.get("job_category_txt")
        if function and function.strip().lower() == "lainnya":
            function = None
        wa = _WORK_ARRANGEMENT.get(
            (job.get("work_arrangement_txt") or "").strip().lower())

        has_salary = bool(job.get("has_salary"))
        min_amount = _rupiah(job.get("salary_min_name")) if has_salary else None
        max_amount = _rupiah(job.get("salary_max_name")) if has_salary else None
        if min_amount and not max_amount:
            max_amount = min_amount
        if max_amount and not min_amount:
            min_amount = max_amount
        has_salary = bool(min_amount or max_amount)
        raw_salary = (
            f"Rp{min_amount:,.0f} - Rp{max_amount:,.0f}" if has_salary else None
        )

        deskripsi = strip_html(job.get("html"), max_len=4000)
        kualifikasi = strip_html(job.get("message"), max_len=2000)
        if kualifikasi:
            deskripsi = (
                f"{deskripsi} | Kualifikasi: {kualifikasi}"
                if deskripsi else f"Kualifikasi: {kualifikasi}"
            )[:6000]

        date_posted = (job.get("created_at") or "")[:10] or None
        if not date_posted and job.get("posted_at"):
            from datetime import datetime, timezone
            try:
                date_posted = datetime.fromtimestamp(
                    int(job["posted_at"]), tz=timezone.utc).date().isoformat()
            except (TypeError, ValueError, OSError):
                date_posted = None

        # expires (unix timestamp), BUKAN application_deadline_timestamp --
        # field itu ada bug di API mereka (selalu sama dengan
        # date_available_timestamp). Lihat catatan di atas modul.
        deadline_teks = job.get("expires_format")

        # Link melamar: sebagian lowongan (terutama dari perusahaan besar
        # yang pasang lewat sistem ATS sendiri) punya link eksternal di
        # premi_link berupa TEKS PENGANTAR + URL, bukan URL polos -- ambil
        # URL-nya saja kalau ada, jatuh ke halaman detail Jobindo kalau tidak.
        link_eksternal = job.get("apply_url") or None
        premi = job.get("premi_link") or ""
        m = re.search(r"https?://\S+", premi)
        if m and not link_eksternal:
            link_eksternal = m.group(0).rstrip(".,)")

        records.append({
            "job_id": str(job_id),
            "site": "jobindo",
            "job_url": url,
            "job_url_direct": link_eksternal or url,
            "title": title,
            "company": company,
            "location": location,
            "date_posted": date_posted,
            "job_type": job_type,
            "salary_source": "jobindo" if has_salary else None,
            "interval": "monthly" if has_salary else None,
            "min_amount": min_amount,
            "max_amount": max_amount,
            "currency": "IDR" if has_salary else None,
            "is_remote": None,
            "job_level": education,
            "job_function": function,
            "listing_type": None,
            "emails": None,
            "description": deskripsi,
            "company_industry": None,
            "company_url": (urljoin(BASE_URL, profil["url"]) if profil.get("url")
                            else employer.get("url") or BASE_URL),
            "company_logo": logo,
            "company_url_direct": profil.get("website") or employer.get("website"),
            "company_addresses": profil.get("address") or employer.get("address"),
            "company_num_employees": None,
            "company_revenue": None,
            "company_description": strip_html(
                profil.get("description") or employer.get("company_description"),
                max_len=1000),
            "skills": None,
            "experience_range": pengalaman or education,
            "company_rating": None,
            "company_reviews_count": None,
            "vacancy_count": None,
            "work_from_home_type": None,
            "raw_salary": raw_salary,
            "category": classify_job(title, function, search_term),
            "work_arrangement": wa or classify_work_arrangement(
                None, title, job_type, location, deskripsi),
            "employment_type": classify_employment_type(job_type, title, deskripsi),
            "search_term": search_term or "scrapeall",
            "search_location": search_location or location,
            "requested_by_chat_id": str(requested_by_chat_id),
            # Deadline eksplisit sebagai teks -- kolom skema tidak punya
            # tempat khusus untuk ini, disertakan lewat extra_fields kalau
            # registry mendukungnya (lihat sites/registry.py KNOWN_KEYS).
            "_deadline_text": deadline_teks,
        })
    return records
