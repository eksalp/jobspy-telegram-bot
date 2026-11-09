from __future__ import annotations

"""
Scraper untuk career.indofood.com.

Situs ini ASP.NET WebForms. Daftar lowongan TIDAK ada di HTML — dimuat lewat
page method:

    POST https://career.indofood.com/default.aspx/OnGetAdvFilter
    body: {"advFilter": { ...filter... }}

Bentuk responsnya tidak biasa: field "d" berisi STRING, bukan objek. String itu
dipisah dengan literal "[space2]":

    bagian 0 -> {"MsgCode": 0, "MsgDesc": ...}      status
    bagian 1 -> {"ListAdvFilterJob": [...], ...}    datanya

Tiap item lowongan punya pasangan field dwibahasa: `JobPositionName` (Inggris)
dan `JobPositionName2` (Indonesia). Modul ini mengambil versi Indonesia dulu,
jatuh ke Inggris kalau kosong.

`TotalData` menempel di tiap item (bukan di root), dipakai untuk tahu kapan
paginasi berhenti.
"""

import json

from categorize import classify_employment_type, classify_job, classify_work_arrangement

BASE_URL = "https://career.indofood.com"
API_URL = f"{BASE_URL}/default.aspx/OnGetAdvFilter"
DETAIL_URL = f"{BASE_URL}/vacancy_detail.aspx?id="
SPLIT_TOKEN = "[space2]"
PAGE_SIZE = 50


ALL_KEYWORDS = {"all", "semua", "*", ""}


def _is_browse_all(query: str | None) -> bool:
    return (query or "").strip().lower() in ALL_KEYWORDS


def _lang(primary, fallback=None):
    """Ambil teks Indonesia, jatuh ke Inggris kalau kosong."""
    for value in (fallback, primary):
        if value and str(value).strip() and str(value).strip().lower() != "null":
            return str(value).strip()
    return None


def _build_filter(keyword: str, page: int) -> dict:
    return {
        "NeedJobList": "Y",
        "RefreshCE": "N",
        "SearchKeyword": keyword,
        "CheckedAdvFilterEduLevel": [],
        "CheckedAdvFilterFunction": [],
        "CheckedAdvFilterExpLevel": [],
        "CheckedAdvFilterCity": [],
        "pageNumber": page,
        "PageSize": PAGE_SIZE,
        "BindFuncANDJOB": False,
        "SortedBy": "lastposted",
        "Lang": "id",
    }


def _fetch_page(keyword: str, page: int) -> list[dict]:
    payload = {"advFilter": _build_filter(keyword, page)}
    # Impor ditunda ke dalam fungsi: mengimpor sites.base di level modul
    # memicu sites/__init__ -> companies -> indofood, yaitu circular import.
    from sites.base import http_post_json

    raw = http_post_json(API_URL, payload, headers={
        "Referer": f"{BASE_URL}/vacancy.aspx",
        "X-Requested-With": "XMLHttpRequest",
    })

    envelope = raw.get("d")
    if not envelope:
        return []

    parts = envelope.split(SPLIT_TOKEN)
    status = json.loads(parts[0]) if parts else {}
    if status.get("MsgCode") != 0:
        raise RuntimeError(
            f"Indofood menolak permintaan: {status.get('MsgDesc', 'tidak diketahui')}")

    if len(parts) < 2 or not parts[1].strip():
        return []

    return json.loads(parts[1]).get("ListAdvFilterJob") or []


def _location(job: dict) -> str:
    """Rakit lokasi meniru logika kotaAlias di vacancy.js."""
    city_list = (job.get("CityList") or "").strip()
    if city_list.lower() == "all":
        prov = _lang(job.get("PropinsiList"), job.get("PropinsiList2"))
        if prov:
            return ", ".join(
                f"Seluruh kota di {p.strip()}" for p in prov.split(",") if p.strip())
        return "Indonesia"

    city = _lang(job.get("CityList"), job.get("CityList2"))
    site = (job.get("JobLocation") or "").strip()
    if city and "," not in city and site:
        # Kalau nama lokasi kerja sama dengan nama kotanya, jangan digandakan
        # ("Bukittinggi - Bukittinggi" -> "Bukittinggi").
        if site.strip().lower() == city.strip().lower():
            return city
        return f"{site} - {city}"
    return city or site or "Indonesia"


def search_indofood(query: str, limit: int = 50) -> list[dict]:
    keyword = "" if _is_browse_all(query) else query.strip()
    jobs: list[dict] = []
    page = 1

    while len(jobs) < limit and page <= 20:
        batch = _fetch_page(keyword, page)
        if not batch:
            break

        jobs.extend(batch)

        total = batch[0].get("TotalData") or 0
        if total and len(jobs) >= total:
            break
        if len(batch) < PAGE_SIZE:
            break
        page += 1

    return jobs[:limit]


def indofood_to_records(
    jobs: list[dict],
    search_term: str,
    search_location: str | None,
    requested_by_chat_id: str,
) -> list[dict]:
    records = []
    for job in jobs:
        title = _lang(job.get("JobPositionName"), job.get("JobPositionName2"))
        if not title:
            continue

        job_id = str(job.get("JobID") or "")
        url = f"{DETAIL_URL}{job_id}"
        location = _location(job)
        function = _lang(job.get("JobFunctionName"), job.get("JobFunctionName2"))
        division = _lang(job.get("JobDivisionName"), job.get("JobDivisionName2"))
        level = _lang(job.get("ExpLevelName"), job.get("ExpLevelName2"))
        education = _lang(job.get("JobEduLevelName"), job.get("JobEduLevelName2"))
        status = _lang(job.get("JobStatusName"), job.get("JobStatusName2"))
        valid_until = _lang(job.get("JobValidUntilStr"), job.get("JobValidUntilStrID"))
        major = (job.get("JobMajorList") or "").strip()
        if major.lower() == "all":
            major = "Semua Jurusan"

        description = " | ".join(p for p in [
            f"Divisi: {division}" if division else None,
            f"Pendidikan: {education}" if education else None,
            f"Jurusan: {major}" if major else None,
            f"Level: {level}" if level else None,
            f"Status: {status}" if status else None,
            f"Berlaku sampai: {valid_until}" if valid_until else None,
        ] if p) or None

        records.append({
            "job_id": job_id or url,
            "site": "indofood",
            "job_url": url,
            "job_url_direct": url,
            "title": title,
            "company": "PT Indofood Sukses Makmur Tbk",
            "location": location,
            "date_posted": None,
            "job_type": status,
            "salary_source": None,
            "interval": None,
            "min_amount": None,
            "max_amount": None,
            "currency": None,
            "is_remote": False,
            "job_level": level,
            "job_function": function or division,
            "listing_type": None,
            "emails": None,
            "description": description,
            "company_industry": "Food & Beverage",
            "company_url": BASE_URL,
            "company_logo": None,
            "company_url_direct": "https://www.indofood.com",
            "company_addresses": "Jakarta, Indonesia",
            "company_num_employees": None,
            "company_revenue": None,
            "company_description": None,
            "skills": None,
            "experience_range": level,
            "company_rating": None,
            "company_reviews_count": None,
            "vacancy_count": None,
            "work_from_home_type": None,
            "raw_salary": None,
            "category": classify_job(title, function, search_term),
            "work_arrangement": classify_work_arrangement(
                False, title, None, location, description),
            "employment_type": classify_employment_type(status, title, description),
            "search_term": search_term or "scrapeall",
            "search_location": search_location or location,
            "requested_by_chat_id": str(requested_by_chat_id),
        })
    return records
