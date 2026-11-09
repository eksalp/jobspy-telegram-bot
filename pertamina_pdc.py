from __future__ import annotations

"""
Scraper untuk karir.pertamina-pdc.com (PT Patra Drilling Contractor).

Situs ASP.NET Razor Pages. Daftar lowongan tidak ada di HTML — diambil lewat
page handler:

    GET https://karir.pertamina-pdc.com/?handler=AllJobVacancies

Perhatikan bentuk URL-nya: `?handler=Nama`, bukan `/api/nama`. Ini konvensi
Razor Pages, dan itu sebabnya endpoint ini tidak muncul saat mencari pola
"api/" di DevTools. Situs yang sama juga punya /api/function untuk dropdown
filter, sehingga mudah menyangka `/api/` adalah satu-satunya pola yang dipakai.

Bentuk respons:

    {"success": true, "data": [
        {"id": "<guid>", "statusAktif": "Open", "subject": "",
         "posisi": "Mekanik Alat Berat", "typeText": "Projek",
         "name": "Outsourcing Operation"}, ...]}

Pemetaan ke kolom `jobs`:
    posisi     -> title
    name       -> job_function  (fungsi kerja, mis. "Outsourcing Operation")
    typeText   -> job_type      (Head Office / Projek / Talent Pool)
    id         -> job_id        (GUID, stabil walau judul diubah)

Lokasi tidak disediakan API-nya. Banyak judul memuat lokasi di belakang tanda
hubung ("HSE / Safety Personnel - Taiwan"), jadi lokasi ditarik dari sana bila
polanya cocok; kalau tidak, dibiarkan "Indonesia".
"""

import re

from categorize import classify_employment_type, classify_job, classify_work_arrangement

BASE_URL = "https://karir.pertamina-pdc.com"
API_URL = f"{BASE_URL}/?handler=AllJobVacancies"

ALL_KEYWORDS = {"all", "semua", "*", ""}

# Lokasi yang lazim muncul di ekor judul lowongan PDC
_KNOWN_PLACES = re.compile(
    r"\b(Taiwan|Jakarta|Prabumulih|Sumatra|Sumatera|Kalimantan|Sulawesi|Papua|"
    r"Riau|Bekasi|Balikpapan|Surabaya|Cirebon|Cepu|Bojonegoro|Offshore|"
    r"Onshore|Sorong|Duri|Dumai|Rantau|Jambi|Palembang|Bandung|Semarang)\b",
    re.I,
)


def _is_browse_all(query: str | None) -> bool:
    return (query or "").strip().lower() in ALL_KEYWORDS


def _location_from_title(title: str) -> str:
    """Tarik lokasi dari ekor judul, mis. 'Crane Operator - Taiwan'."""
    m = _KNOWN_PLACES.search(title)
    if not m:
        return "Indonesia"
    place = m.group(1)
    if place.lower() in {"offshore", "onshore"}:
        return f"Indonesia ({place.title()})"
    if place.lower() == "taiwan":
        return "Taiwan"
    return f"{place.title()}, Indonesia"


def search_pertamina_pdc(query: str, limit: int = 100) -> list[dict]:
    from sites.base import http_get

    data = http_get(API_URL, headers={
        "Referer": f"{BASE_URL}/",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "*/*",
    }).json()

    if not data.get("success"):
        raise RuntimeError("PDC menolak permintaan (success=false)")

    jobs = data.get("data") or []
    keyword = "" if _is_browse_all(query) else query.strip().lower()

    result = []
    for job in jobs:
        title = (job.get("posisi") or "").strip()
        if not title:
            continue
        # "Talent Pool" bukan lowongan sungguhan, cuma penampung pelamar
        if title.lower() == "talent pool":
            continue
        if (job.get("statusAktif") or "").lower() not in {"open", ""}:
            continue
        if keyword and keyword not in f"{title} {job.get('name', '')}".lower():
            continue
        result.append(job)
        if len(result) >= limit:
            break

    return result


def pertamina_pdc_to_records(
    jobs: list[dict],
    search_term: str,
    search_location: str | None,
    requested_by_chat_id: str,
) -> list[dict]:
    records = []
    for job in jobs:
        title = (job.get("posisi") or "").strip()
        job_id = job.get("id") or title
        # Halaman detail dibuka lewat modal di beranda, jadi tidak ada URL
        # sendiri per lowongan. Fragmen id dipakai agar tiap baris tetap unik.
        url = f"{BASE_URL}/#job-{job_id}"
        function = (job.get("name") or "").strip() or None
        job_type = (job.get("typeText") or "").strip() or None
        location = _location_from_title(title)

        description = " | ".join(p for p in [
            f"Fungsi: {function}" if function else None,
            f"Tipe: {job_type}" if job_type else None,
            f"Status: {job.get('statusAktif')}" if job.get("statusAktif") else None,
        ] if p) or None

        records.append({
            "job_id": job_id,
            "site": "pertamina_pdc",
            "job_url": url,
            "job_url_direct": url,
            "title": title,
            "company": "PT Patra Drilling Contractor",
            "location": location,
            "date_posted": None,
            "job_type": job_type,
            "salary_source": None,
            "interval": None,
            "min_amount": None,
            "max_amount": None,
            "currency": None,
            "is_remote": False,
            "job_level": None,
            "job_function": function,
            "listing_type": None,
            "emails": None,
            "description": description,
            "company_industry": "Energy / Oil & Gas",
            "company_url": BASE_URL,
            "company_logo": None,
            "company_url_direct": "https://www.pertamina-pdc.com",
            "company_addresses": "PDC Tower, Jl. Matraman Raya No.87, Jakarta Timur",
            "company_num_employees": None,
            "company_revenue": None,
            "company_description": None,
            "skills": None,
            "experience_range": None,
            "company_rating": None,
            "company_reviews_count": None,
            "vacancy_count": None,
            "work_from_home_type": None,
            "raw_salary": None,
            "category": classify_job(title, function, search_term),
            "work_arrangement": classify_work_arrangement(
                False, title, job_type, location, description),
            "employment_type": classify_employment_type(job_type, title, description),
            "search_term": search_term or "scrapeall",
            "search_location": search_location or location,
            "requested_by_chat_id": str(requested_by_chat_id),
        })
    return records
