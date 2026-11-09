from __future__ import annotations

"""
Scraper untuk kitalulus.com.

Memakai API GraphQL resmi yang dipakai frontend-nya sendiri:

    POST https://gql.kitalulus.com/graphql
    operationName: "Vacancies"

Tanpa auth. Field yang diminta (lewat query GraphQL) sudah sangat lengkap:
gaji, tipe kerja, lokasi (provinsi+kota), pendidikan minimum, pengalaman
minimum, dan jobRole. Total katalog ~10.000 lowongan (field `elements`).

CATATAN PENTING soal field `page` di respons: BUKAN nomor halaman yang sedang
dilihat, melainkan ceil(elements / limit) — total halaman yang tersedia untuk
ukuran limit itu. Contoh nyata: request limit=3 dengan elements=10000
mengembalikan page=3334 (=ceil(10000/3)). Jadi paginasi HARUS mengandalkan
`hasNextPage` dan penghitungan offset sendiri, BUKAN field `page` di respons.

CATATAN soal gaji: `salaryLowerBound`/`salaryUpperBound` bernilai 0,0 untuk
lowongan "Dapat Dinegosiasikan" — bukan gaji Rp0. Nilai 0 pada keduanya
diperlakukan sebagai "tidak ada data gaji", bukan gaji nol.

URL detail: https://www.kitalulus.com/lowongan/detail/{slug} — dikonfirmasi
dari HTML kartu asli (bukan tebakan).
"""

import re

from categorize import classify_job

BASE_URL = "https://www.kitalulus.com"
API_URL = "https://gql.kitalulus.com/graphql"
PAGE_SIZE = 30

ALL_KEYWORDS = {"all", "semua", "*", ""}

_HEADERS = {
    "Accept": "application/graphql-response+json,application/json;q=0.9",
    "Content-Type": "application/json",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/",
    "x-channel": "web",
}

_QUERY = """fragment VacancyCardFragment on Vacancy {
  id
  slug
  code
  positionName
  isHighlighted
  isClosed
  educationLevelStr
  salaryLowerBound
  salaryUpperBound
  updatedAtStr
  genderStr
  maxAge
  minExperience
  typeStr
  company {
    name
    code
    logoUrl
    __typename
  }
  province {
    name
    __typename
  }
  city {
    name
    __typename
  }
  jobRole {
    displayName
    __typename
  }
  __typename
}

query Vacancies($keyword: String, $tag: String, $pagination: CommonFilter, $filters: [SearchCategoryFilter!], $locations: [LocationAreaInput!], $haveMisiSeruLimit: Boolean, $userMaxEducation: String, $userJobSpecializationRoleIds: [ID!]) {
  vacanciesV4(
    keyword: $keyword
    tag: $tag
    pagination: $pagination
    filters: $filters
    locations: $locations
    haveMisiSeruLimit: $haveMisiSeruLimit
    userMaxEducation: $userMaxEducation
    userJobSpecializationRoleIds: $userJobSpecializationRoleIds
  ) {
    title
    hasNextPage
    hasPrevPage
    elements
    page
    tag {
      title
      __typename
    }
    metadata {
      title
      description
      __typename
    }
    list {
      ...VacancyCardFragment
      __typename
    }
    __typename
  }
}"""

# typeStr dari API -> istilah yang dikenali categorize.py
_EMPLOYMENT = {
    "kontrak": "Contract",
    "full-time": "Full-time", "full time": "Full-time",
    "part-time": "Part-time", "part time": "Part-time",
    "freelance": "Freelance",
    "magang": "Internship", "internship": "Internship",
}


def _is_browse_all(query: str | None) -> bool:
    return (query or "").strip().lower() in ALL_KEYWORDS


def search_kitalulus(query: str, limit: int = 50) -> list[dict]:
    from sites.base import http_post_json

    keyword = "" if _is_browse_all(query) else query.strip()
    jobs: list[dict] = []
    page_request = 1  # nomor halaman yang KITA minta, bukan field `page` di respons

    while len(jobs) < limit:
        payload = {
            "operationName": "Vacancies",
            "variables": {
                "keyword": keyword,
                "tag": "",
                "locations": [],
                "haveMisiSeruLimit": True,
                "userMaxEducation": "",
                "userJobSpecializationRoleIds": [],
                "pagination": {"page": page_request,
                              "limit": min(PAGE_SIZE, limit - len(jobs))},
                "filters": [
                    {"key": "sortBy", "value": ["isHighlighted"]},
                    {"key": "jobSpecializations", "value": []},
                    {"key": "companyIndustries", "value": []},
                    {"key": "educationLevels", "value": []},
                    {"key": "gender", "value": []},
                    {"key": "salary", "value": []},
                    {"key": "types", "value": []},
                    {"key": "jobLevels", "value": []},
                    {"key": "locationSites", "value": []},
                    {"key": "workExperience", "value": []},
                ],
            },
            "extensions": {"clientLibrary": {"name": "@apollo/client", "version": "4.1.6"}},
            "query": _QUERY,
        }

        data = http_post_json(API_URL, payload, headers=_HEADERS)
        result = (data.get("data") or {}).get("vacanciesV4") or {}
        batch = result.get("list") or []
        if not batch:
            break

        jobs.extend(v for v in batch if not v.get("isClosed"))

        if not result.get("hasNextPage"):
            break
        page_request += 1
        if page_request > 500:  # pengaman, ~15.000 lowongan pada limit 30
            break

    return jobs[:limit]


def kitalulus_to_records(
    jobs: list[dict],
    search_term: str,
    search_location: str | None,
    requested_by_chat_id: str,
) -> list[dict]:
    from categorize import classify_employment_type, classify_work_arrangement

    records = []
    for job in jobs:
        title = (job.get("positionName") or "").strip()
        job_id = job.get("id")
        slug = job.get("slug")
        if not title or not job_id or not slug:
            continue

        url = f"{BASE_URL}/lowongan/detail/{slug}"

        company_info = job.get("company") or {}
        company = company_info.get("name") or "Tidak disebutkan"

        province = (job.get("province") or {}).get("name")
        city = (job.get("city") or {}).get("name")
        location = ", ".join(p for p in (city, province) if p) or "Indonesia"

        # 0,0 berarti "Dapat Dinegosiasikan", bukan gaji Rp0.
        low, high = job.get("salaryLowerBound"), job.get("salaryUpperBound")
        has_salary = bool(low) and bool(high)
        raw_salary = f"Rp{low:,.0f} - Rp{high:,.0f}" if has_salary else None

        job_type = _EMPLOYMENT.get((job.get("typeStr") or "").strip().lower())
        function = (job.get("jobRole") or {}).get("displayName")
        education = job.get("educationLevelStr")

        bits = []
        if education:
            bits.append(education)
        min_exp = job.get("minExperience")
        if min_exp:
            bits.append(f"Min. {min_exp} tahun pengalaman")
        gender = job.get("genderStr")
        if gender and "semua" not in gender.lower():
            bits.append(gender)
        description = " | ".join(bits) or None

        records.append({
            "job_id": str(job_id),
            "site": "kitalulus",
            "job_url": url,
            "job_url_direct": url,
            "title": title,
            "company": company,
            "location": location,
            "date_posted": None,  # updatedAtStr teks relatif ("hari ini"), bukan tanggal
            "job_type": job_type,
            "salary_source": "kitalulus" if has_salary else None,
            "interval": "monthly" if has_salary else None,
            "min_amount": low if has_salary else None,
            "max_amount": high if has_salary else None,
            "currency": "IDR" if has_salary else None,
            "is_remote": None,
            "job_level": education,
            "job_function": function,
            "listing_type": "highlighted" if job.get("isHighlighted") else None,
            "emails": None,
            "description": description,
            "company_industry": None,
            "company_url": BASE_URL,
            "company_logo": company_info.get("logoUrl") or None,
            "company_url_direct": None,
            "company_addresses": location,
            "company_num_employees": None,
            "company_revenue": None,
            "company_description": None,
            "skills": None,
            "experience_range": (
                f"Min. {min_exp} tahun" if min_exp else None),
            "company_rating": None,
            "company_reviews_count": None,
            "vacancy_count": None,
            "work_from_home_type": None,
            "raw_salary": raw_salary,
            "category": classify_job(title, function, search_term),
            "work_arrangement": classify_work_arrangement(None, title, job_type, location),
            "employment_type": classify_employment_type(job_type, title),
            "search_term": search_term or "scrapeall",
            "search_location": search_location or location,
            "requested_by_chat_id": str(requested_by_chat_id),
        })
    return records
