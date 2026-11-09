from __future__ import annotations

"""
Scraper untuk kalibrr.id (Kalibrr Indonesia).

Memakai API publik yang dipakai frontend-nya sendiri:

    GET https://kalibrr.id/kjs/job_board/search?limit=100&offset=0

Tanpa auth, tanpa tls_client. Mengembalikan {"count": N, "jobs": [...]}.

Versi sebelumnya mengurai HTML dan cuma dapat ~17 lowongan, karena tombol
"Load more jobs" memuat lewat JavaScript dan paginasi berbasis path tidak
bekerja. Lewat API ini seluruh katalog terjangkau (saat ditulis: 1180).

Datanya jauh lebih lengkap daripada yang tampil di kartu HTML — termasuk
deskripsi dan kualifikasi utuh, daftar skill, jumlah lowongan dibuka, dan
tanggal tayang.

CATATAN PENTING soal gaji: field `salary_shown` menentukan apakah nominalnya
boleh ditampilkan. Ada lowongan yang punya `maximum_salary` terisi tapi
`salary_shown: false` — perusahaan sengaja menyembunyikannya. Nilai seperti
itu TIDAK dipakai, supaya kita tidak menampilkan angka yang memang tidak
ingin dipublikasikan.
"""

import re

from categorize import classify_job

BASE_URL = "https://kalibrr.id"
API_URL = f"{BASE_URL}/kjs/job_board/search"
PAGE_SIZE = 100

ALL_KEYWORDS = {"all", "semua", "*", ""}

_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": f"{BASE_URL}/id-ID/home/all-jobs",
}

# Kode work_experience -> label. Dipastikan dari URL filter situsnya sendiri
# (mis. /home/w/300-associate-or-supervisor).
_EXPERIENCE = {
    100: "Internship / OJT",
    200: "Entry Level / Junior",
    300: "Associate / Supervisor",
    400: "Mid-Senior Level / Manager",
    500: "Director / Executive",
}

# `tenure` datang sebagai teks siap pakai
_TENURE = {
    "full time": "Full-time",
    "part time": "Part-time",
    "contractual": "Contract",
    "internship": "Internship",
    "freelance": "Freelance",
    "temporary": "Temporary",
}

_INTERVAL = {"month": "monthly", "year": "yearly",
             "hour": "hourly", "day": "daily", "week": "weekly"}


def _is_browse_all(query: str | None) -> bool:
    return (query or "").strip().lower() in ALL_KEYWORDS


def _strip_html(html: str | None, limit: int = 4000) -> str | None:
    if not html:
        return None
    from sites.base import strip_html
    return strip_html(html, max_len=limit)


def _location(job: dict) -> str:
    parts = ((job.get("google_location") or {})
             .get("address_components") or {})
    bits = [parts.get("city"), parts.get("region"), parts.get("country")]
    return ", ".join(p for p in bits if p) or "Indonesia"


def search_kalibrr(query: str, limit: int = 100) -> list[dict]:
    from sites.base import http_get

    keyword = "" if _is_browse_all(query) else query.strip()
    jobs: list[dict] = []
    offset = 0

    while len(jobs) < limit and offset < 5000:
        params = {"limit": PAGE_SIZE, "offset": offset}
        if keyword:
            # Endpoint ini menerima pencarian teks; kalau parameternya
            # diabaikan, penyaringan sisi klien di bawah tetap menjaga
            # relevansi hasil.
            params["text"] = keyword

        data = http_get(API_URL, params=params, headers=_HEADERS).json()
        batch = data.get("jobs") or []
        if not batch:
            break

        if keyword:
            needle = keyword.lower()
            batch = [
                j for j in batch
                if needle in (j.get("name") or "").lower()
                or needle in (j.get("company_name") or "").lower()
                or needle in (j.get("function") or "").lower()
            ]

        jobs.extend(batch)

        offset += PAGE_SIZE
        total = data.get("count") or 0
        if total and offset >= total:
            break

    return jobs[:limit]


def kalibrr_to_records(
    jobs: list[dict],
    search_term: str,
    search_location: str | None,
    requested_by_chat_id: str,
) -> list[dict]:
    from categorize import classify_employment_type, classify_work_arrangement

    records = []
    for job in jobs:
        title = (job.get("name") or "").strip()
        job_id = job.get("id")
        if not title or not job_id:
            continue

        company_info = job.get("company") or job.get("company_info") or {}
        code = company_info.get("code")
        slug = job.get("slug")
        url = (
            f"{BASE_URL}/c/{code}/jobs/{job_id}/{slug}"
            if code and slug else f"{BASE_URL}/c/jobs/{job_id}"
        )

        location = _location(job)

        # Hormati salary_shown: ada lowongan dengan nominal terisi tapi
        # sengaja disembunyikan perusahaannya.
        min_amount = max_amount = currency = interval = raw_salary = None
        if job.get("salary_shown"):
            low, high = job.get("base_salary"), job.get("maximum_salary")
            values = [v for v in (low, high) if isinstance(v, (int, float))]
            if values:
                min_amount, max_amount = min(values), max(values)
                currency = job.get("salary_currency") or "IDR"
                interval = _INTERVAL.get(
                    (job.get("salary_interval") or "month").lower(), "monthly")
                raw_salary = f"{currency} {min_amount:,.0f} - {max_amount:,.0f}"

        if job.get("is_work_from_home"):
            arrangement, is_remote = "remote", True
        elif job.get("is_hybrid"):
            arrangement, is_remote = "hybrid", False
        else:
            arrangement, is_remote = "onsite", False

        job_type = _TENURE.get((job.get("tenure") or "").strip().lower())
        level = _EXPERIENCE.get(job.get("work_experience"))

        skills = ", ".join(
            s.get("sds_skill", {}).get("name", "")
            for s in (job.get("job_sds_skills") or [])
            if s.get("sds_skill", {}).get("name")
        ) or None

        description = _strip_html(job.get("description"))
        qualifications = _strip_html(job.get("qualifications"), limit=3000)
        if qualifications:
            description = (
                f"{description} | Kualifikasi: {qualifications}"
                if description else f"Kualifikasi: {qualifications}"
            )[:8000]

        extra = []
        if job.get("is_open_to_fresh_grads"):
            extra.append("Terbuka untuk fresh graduate")
        deadline = (job.get("application_end_date") or "")[:10]
        if deadline:
            extra.append(f"Batas lamar: {deadline}")
        if extra and description:
            description = f"{' | '.join(extra)} | {description}"[:8000]
        elif extra:
            description = " | ".join(extra)

        records.append({
            "job_id": str(job_id),
            "site": "kalibrr",
            "job_url": url,
            "job_url_direct": job.get("apply_redirect_url") or url,
            "title": title,
            "company": job.get("company_name") or company_info.get("name")
            or "Tidak disebutkan",
            "location": location,
            "date_posted": (job.get("activation_date") or "")[:10] or None,
            "job_type": job_type,
            "salary_source": "kalibrr" if min_amount is not None else None,
            "interval": interval,
            "min_amount": min_amount,
            "max_amount": max_amount,
            "currency": currency,
            "is_remote": is_remote,
            "job_level": level,
            "job_function": job.get("function"),
            "listing_type": "featured" if job.get("is_featured") else None,
            "emails": None,
            "description": description,
            "company_industry": company_info.get("industry"),
            "company_url": f"{BASE_URL}/c/{code}" if code else BASE_URL,
            "company_logo": company_info.get("logo_small"),
            "company_url_direct": (job.get("company_info") or {}).get("url"),
            "company_addresses": location,
            "company_num_employees": None,
            "company_revenue": None,
            "company_description": _strip_html(
                company_info.get("description"), limit=1000),
            "skills": skills,
            "experience_range": level,
            "company_rating": None,
            "company_reviews_count": None,
            "vacancy_count": job.get("number_of_openings"),
            "work_from_home_type": arrangement,
            "raw_salary": raw_salary,
            "category": classify_job(title, job.get("function"), skills, search_term),
            "work_arrangement": arrangement or classify_work_arrangement(
                is_remote, title, job_type, location),
            "employment_type": classify_employment_type(job_type, title),
            "search_term": search_term or "scrapeall",
            "search_location": search_location or location,
            "requested_by_chat_id": str(requested_by_chat_id),
        })
    return records
