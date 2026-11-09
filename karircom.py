from __future__ import annotations

"""
Scraper untuk karir.com.

Memakai API publik yang dipakai frontend-nya sendiri:

    POST https://gateway2-beta.karir.com/v2/search/opportunities
    body: {"keyword": "...", "location_ids": [], ..., "limit": 50, "offset": 0}

Tanpa auth. Mengembalikan {"data": {"total_opportunities": N, "opportunities": [...]}}.

CATATAN PENTING soal field `description`: berisi lokasi, jenis kerja, dan mode
kerja DIGABUNG jadi satu string dipisah "•", mis.:

    "Prov. DKI-Jakarta • Kontrak • On-Site"
    "Jakarta Pusat • Purna Waktu • On-Site"
    "Prov. DKI-Jakarta"                        (kadang cuma lokasi saja)

Bukan deskripsi pekerjaan — nama field ini menyesatkan, jadi diurai jadi
location/job_type/workplace di sini, dan TIDAK dipakai sebagai kolom
description (yang dibiarkan None karena tidak tersedia di endpoint listing;
ada endpoint detail terpisah kalau nanti diperlukan).

CATATAN soal gaji: `salary_info` menentukan apakah `salary_lower`/`salary_upper`
valid. Nilainya:
    LABEL_FULL_SALARY         -> gaji ditampilkan, pakai lower/upper
    LABEL_COMPETITIVE_SALARY  -> gaji disembunyikan perusahaan, lower/upper null

CATATAN soal URL: halaman lowongan yang benar adalah
`https://karir.com/opportunities/{id}` (dipastikan Oktober 2026: status
200 dan memuat data lowongan). Pola lama `/lowongan/{id}` ternyata 404.

DESKRIPSI: diambil dari endpoint detail
    POST https://gateway2-beta.karir.com/v1/opportunity/detail
    body: {"opportunity_id": <id>}
yang mengembalikan data.responsibilities, data.requirements (HTML), dan
data.company.description. Dipanggil berurutan dengan jeda 1 detik karena
robots.txt karir.com meminta Crawl-delay: 1.
"""

import re

from categorize import classify_job

BASE_URL = "https://karir.com"
API_URL = "https://gateway2-beta.karir.com/v2/search/opportunities"
DETAIL_URL = "https://gateway2-beta.karir.com/v1/opportunity/detail"
PAGE_SIZE = 50

ALL_KEYWORDS = {"all", "semua", "*", ""}

_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/",
}

_WORKPLACE = {
    "on-site": "onsite", "onsite": "onsite",
    "hybrid": "hybrid",
    "remote": "remote", "wfh": "remote",
}

# Token jenis kerja yang muncul di description, Indonesia & Inggris
_JOB_TYPE = {
    "purna waktu": "Full-time", "full time": "Full-time", "penuh waktu": "Full-time",
    "kontrak": "Contract", "contract": "Contract",
    "paruh waktu": "Part-time", "part time": "Part-time",
    "magang": "Internship", "internship": "Internship",
    "freelance": "Freelance", "lepas": "Freelance",
    "harian": "Temporary", "temporary": "Temporary",
}


def _is_browse_all(query: str | None) -> bool:
    return (query or "").strip().lower() in ALL_KEYWORDS


def _parse_description(text: str | None) -> dict:
    """Urai 'Prov. DKI-Jakarta • Kontrak • On-Site' jadi field terpisah.

    Bagian pertama SELALU lokasi. Bagian sesudahnya diidentifikasi dari kata
    kuncinya (bukan dari posisi), karena urutannya tidak selalu konsisten.
    """
    if not text:
        return {}

    bagian = [p.strip() for p in text.split("•") if p.strip()]
    if not bagian:
        return {}

    out = {"location": bagian[0]}

    for token in bagian[1:]:
        lower = token.lower()
        if lower in _WORKPLACE:
            out["workplace"] = _WORKPLACE[lower]
        elif lower in _JOB_TYPE:
            out["job_type"] = _JOB_TYPE[lower]

    return out


def search_karircom(query: str, limit: int = 50) -> list[dict]:
    from sites.base import http_post_json

    keyword = "" if _is_browse_all(query) else query.strip()
    jobs: list[dict] = []
    offset = 0

    while len(jobs) < limit:
        payload = {
            "keyword": keyword,
            "location_ids": [], "company_ids": [], "industry_ids": [],
            "job_function_ids": [], "degree_ids": [],
            "locale": "id",
            "limit": min(PAGE_SIZE, limit - len(jobs)),
            "offset": offset,
            "level": "",
            "min_employee": 0, "max_employee": 0,
            "is_opportunity": True,
            "sort_order": "",
            "is_recomendation": False, "is_preference": False,
            "is_choice_opportunity": False, "is_subscribe": False,
            "workplace": None,
        }

        data = http_post_json(API_URL, payload, headers=_HEADERS)
        payload_data = data.get("data") or {}
        batch = payload_data.get("opportunities") or []
        if not batch:
            break

        jobs.extend(batch)

        total = payload_data.get("total_opportunities") or 0
        offset += len(batch)
        if offset >= total:
            break

    jobs = jobs[:limit]
    _lengkapi_detail(jobs)
    return jobs


def _lengkapi_detail(jobs: list[dict], jeda: float = 1.0) -> None:
    """Tempelkan `_detail` (respons endpoint detail) ke tiap lowongan."""
    import time

    from sites.base import http_post_json

    for i, job in enumerate(jobs):
        if job.get("id") is None:
            continue
        if i:
            time.sleep(jeda)  # robots.txt karir.com: Crawl-delay 1
        try:
            data = http_post_json(DETAIL_URL, {"opportunity_id": job["id"]},
                                  headers=_HEADERS)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data.get("data"), dict):
            job["_detail"] = data["data"]


def karircom_to_records(
    jobs: list[dict],
    search_term: str,
    search_location: str | None,
    requested_by_chat_id: str,
) -> list[dict]:
    from categorize import classify_employment_type, classify_work_arrangement

    records = []
    for job in jobs:
        title = (job.get("job_position") or "").strip()
        job_id = job.get("id")
        if not title or job_id is None:
            continue

        url = f"{BASE_URL}/opportunities/{job_id}"
        detail = job.get("_detail") or {}
        perusahaan_detail = detail.get("company") or {}

        meta = _parse_description(job.get("description"))
        location = meta.get("location") or "Indonesia"
        job_type = meta.get("job_type")
        workplace = meta.get("workplace")

        has_salary = (
            job.get("salary_info") == "LABEL_FULL_SALARY"
            and isinstance(job.get("salary_lower"), (int, float))
            and isinstance(job.get("salary_upper"), (int, float))
        )
        min_amount = job.get("salary_lower") if has_salary else None
        max_amount = job.get("salary_upper") if has_salary else None
        raw_salary = (
            f"Rp{min_amount:,.0f} - Rp{max_amount:,.0f}" if has_salary else None
        )

        from sites.base import strip_html

        extra = []
        if job.get("is_urgent"):
            extra.append("Segera dibutuhkan")
        tugas = strip_html(detail.get("responsibilities"), max_len=4000)
        syarat = strip_html(detail.get("requirements"), max_len=4000)
        if tugas:
            extra.append(f"Tanggung jawab: {tugas}")
        if syarat:
            extra.append(f"Persyaratan: {syarat}")
        description = " | ".join(extra)[:8000] or None

        records.append({
            "job_id": str(job_id),
            "site": "karircom",
            "job_url": url,
            "job_url_direct": url,
            "title": title,
            "company": job.get("company_name") or "Tidak disebutkan",
            "location": location,
            "date_posted": (job.get("posted_at") or "")[:10] or None,
            "job_type": job_type,
            "salary_source": "karircom" if has_salary else None,
            "interval": "monthly" if has_salary else None,
            "min_amount": min_amount,
            "max_amount": max_amount,
            "currency": "IDR" if has_salary else None,
            "is_remote": workplace == "remote" if workplace else None,
            "job_level": None,
            "job_function": None,
            "listing_type": "urgent" if job.get("is_urgent") else None,
            "emails": None,
            "description": description,
            "company_industry": None,
            "company_url": BASE_URL,
            "company_logo": job.get("company_logo_url"),
            "company_url_direct": None,
            "company_addresses": location,
            "company_num_employees": None,
            "company_revenue": None,
            "company_description": strip_html(
                perusahaan_detail.get("description"), max_len=1000),
            "skills": None,
            "experience_range": None,
            "company_rating": None,
            "company_reviews_count": None,
            "vacancy_count": None,
            "work_from_home_type": workplace,
            "raw_salary": raw_salary,
            "category": classify_job(title, search_term),
            "work_arrangement": workplace or classify_work_arrangement(
                None, title, job_type, location),
            "employment_type": classify_employment_type(job_type, title),
            "search_term": search_term or "scrapeall",
            "search_location": search_location or location,
            "requested_by_chat_id": str(requested_by_chat_id),
        })
    return records
