from __future__ import annotations

"""
Scraper untuk dealls.com — agregator lowongan Indonesia.

Memakai API publik yang dipakai frontend-nya sendiri (backend Dealls bernama
"sejutacita"):

    GET https://api.sejutacita.id/v1/explore-job/job
        ?page=1&limit=50&published=true&status=active
        &sortParam=mostRelevant&sortBy=asc&boostTheBoostedJob=true

Tanpa auth. Header `x-client-app-name` dikirim meniru aplikasi webnya.

Versi sebelumnya mengurai HTML halaman depan dan hanya dapat 18 lowongan,
karena tombol "Lihat Lebih Banyak" memuat data lewat JavaScript dan parameter
?page= di halaman web diabaikan. Lewat API ini seluruh katalog terjangkau
(saat ditulis: 1209 lowongan, 68 halaman).

Ini satu-satunya sumber kita yang menyediakan RENTANG GAJI sebagai angka,
bukan teks — jadi min_amount/max_amount terisi tanpa perlu diurai.
"""

import re

from categorize import classify_job

BASE_URL = "https://dealls.com"
API_URL = "https://api.sejutacita.id/v1/explore-job/job"
PAGE_SIZE = 50

ALL_KEYWORDS = {"all", "semua", "*", ""}

_HEADERS = {
    "Accept": "*/*",
    "Content-Type": "application/json",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/",
    "x-client-app-name": "Deall-Talent-Web",
}

# employmentTypes[] -> istilah yang dikenali categorize.py
_EMPLOYMENT = {
    "fulltime": "Full-time",
    "parttime": "Part-time",
    "internship": "Internship",
    "contract": "Contract",
    "freelance": "Freelance",
    "temporary": "Temporary",
    "volunteer": "Volunteer",
}

# workplaceType -> kolom work_arrangement
_ARRANGEMENT = {
    "onsite": "onsite",
    "hybrid": "hybrid",
    "remote": "remote",
    "workfromanywhere": "remote",
}


def _is_browse_all(query: str | None) -> bool:
    return (query or "").strip().lower() in ALL_KEYWORDS


def _norm(value: str | None) -> str:
    return re.sub(r"[^a-z]", "", (value or "").lower())


def _employment(types: list | None) -> str | None:
    for item in types or []:
        mapped = _EMPLOYMENT.get(_norm(item))
        if mapped:
            return mapped
    return None


def _matches(job: dict, keyword: str) -> bool:
    """Filter sisi klien.

    API-nya tidak punya parameter pencarian yang terdokumentasi, jadi untuk
    kata kunci kita ambil beberapa halaman lalu saring sendiri. Konsekuensinya
    pencarian kata kunci hanya menjangkau halaman yang sempat diambil.
    """
    if not keyword:
        return True
    haystack = " ".join(str(p) for p in [
        job.get("role"),
        (job.get("company") or {}).get("name"),
        (job.get("company") or {}).get("sector"),
        job.get("jobRoleCategorySlug"),
        " ".join(s.get("name", "") for s in (job.get("skills") or [])),
    ] if p).lower()
    return keyword in haystack


def search_dealls(query: str, limit: int = 50) -> list[dict]:
    from sites.base import http_get

    keyword = "" if _is_browse_all(query) else query.strip().lower()
    jobs: list[dict] = []
    page = 1
    # Untuk pencarian kata kunci perlu menyisir lebih banyak halaman karena
    # penyaringan dilakukan di sisi kita.
    max_pages = 30 if keyword else 25

    while len(jobs) < limit and page <= max_pages:
        data = http_get(API_URL, params={
            "page": page,
            "limit": PAGE_SIZE,
            "published": "true",
            "status": "active",
            "sortParam": "mostRelevant",
            "sortBy": "asc",
            "boostTheBoostedJob": "true",
        }, headers=_HEADERS).json()

        payload = data.get("data") or {}
        docs = payload.get("docs") or []
        if not docs:
            break

        jobs.extend(job for job in docs if _matches(job, keyword))

        total_pages = payload.get("totalPages") or 0
        if total_pages and page >= total_pages:
            break
        page += 1

    return jobs[:limit]


def dealls_to_records(
    jobs: list[dict],
    search_term: str,
    search_location: str | None,
    requested_by_chat_id: str,
) -> list[dict]:
    from categorize import classify_employment_type, classify_work_arrangement

    records = []
    for job in jobs:
        title = (job.get("role") or "").strip()
        if not title:
            continue

        job_id = job.get("id") or job.get("slug")
        slug = job.get("slug")
        url = f"{BASE_URL}/loker/{slug}" if slug else BASE_URL

        company_info = job.get("company") or {}
        company = (company_info.get("name") or "").strip() or "Tidak disebutkan"

        city = (job.get("city") or {}).get("name")
        country = (job.get("country") or {}).get("name")
        location = ", ".join(p for p in (city, country) if p) or "Indonesia"

        arrangement = _ARRANGEMENT.get(_norm(job.get("workplaceType")))
        job_type = _employment(job.get("employmentTypes"))

        salary = job.get("salaryRange") or {}
        start, end = salary.get("start"), salary.get("end")
        has_salary = isinstance(start, (int, float)) and isinstance(end, (int, float))

        skills = ", ".join(
            s.get("name", "") for s in (job.get("skills") or []) if s.get("name")
        ) or None

        # jobRoleCategorySlug: "it-and-software-engineering" -> "It And Software Engineering"
        function = job.get("jobRoleCategorySlug")
        if function:
            function = function.replace("-", " ").title()

        bits = []
        if job.get("urgentlyNeeded"):
            bits.append("Segera dibutuhkan")
        if skills:
            bits.append(f"Skill: {skills}")
        applicants = (job.get("stats") or {}).get("applicantCount")
        if applicants is not None:
            bits.append(f"{applicants} pelamar")
        description = " | ".join(bits) or None

        records.append({
            "job_id": str(job_id),
            "site": "dealls",
            "job_url": url,
            "job_url_direct": job.get("externalPlatformApplyUrl") or url,
            "title": title,
            "company": company,
            "location": location,
            "date_posted": (job.get("publishedAt") or "")[:10] or None,
            "job_type": job_type,
            "salary_source": "dealls" if has_salary else None,
            "interval": "monthly" if has_salary else None,
            "min_amount": min(start, end) if has_salary else None,
            "max_amount": max(start, end) if has_salary else None,
            "currency": "IDR" if has_salary else None,
            "is_remote": arrangement == "remote" if arrangement else None,
            "job_level": None,
            "job_function": function,
            "listing_type": "boosted" if job.get("boosted") else None,
            "emails": None,
            "description": description,
            "company_industry": company_info.get("sector"),
            "company_url": (
                f"{BASE_URL}/companies/{company_info.get('slug')}"
                if company_info.get("slug") else BASE_URL
            ),
            "company_logo": company_info.get("logoUrl"),
            "company_url_direct": None,
            "company_addresses": location,
            "company_num_employees": None,
            "company_revenue": None,
            "company_description": None,
            "skills": skills,
            "experience_range": None,
            "company_rating": None,
            "company_reviews_count": None,
            "vacancy_count": None,
            "work_from_home_type": job.get("workplaceType"),
            "raw_salary": (
                f"Rp{min(start, end):,} - Rp{max(start, end):,}"
                if has_salary else None
            ),
            "category": classify_job(title, function, skills, search_term),
            # Dealls menyebut pengaturan kerjanya eksplisit, jadi dipakai
            # langsung; classify_work_arrangement hanya cadangan.
            "work_arrangement": arrangement or classify_work_arrangement(
                None, title, job_type, location),
            "employment_type": classify_employment_type(job_type, title),
            "search_term": search_term or "scrapeall",
            "search_location": search_location or location,
            "requested_by_chat_id": str(requested_by_chat_id),
        })
    return records
