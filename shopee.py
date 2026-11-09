from __future__ import annotations

"""
Scraper untuk careers.shopee.co.id.

Shopee pakai platform ATS dari workatsea.com dengan API publik yang bisa
diakses langsung tanpa login/auth — jauh lebih ringan dari Playwright.

Flow:
1. Fetch /meta/slice/ → dapat lookup table: lokasi, departemen, employment type
2. Fetch /job/list/?limit=N&offset=M → dapat semua loker dengan pagination
3. Decode ID ke teks pakai lookup table dari step 1
"""

import time
from html import unescape

import requests
from bs4 import BeautifulSoup

from categorize import classify_employment_type, classify_job, classify_work_arrangement

BASE_CAREER_URL = "https://careers.shopee.co.id"
ATS_BASE = "https://ats.workatsea.com/ats/api/v1/user"
META_URL = f"{ATS_BASE}/meta/slice/?flags=2147851120&from_career=true"
JOB_LIST_URL = f"{ATS_BASE}/job/list/"
ALL_KEYWORDS = {"all", "semua", "*"}

# API ATS ini memuat lowongan Shopee SELURUH DUNIA (Brazil, China, Vietnam,
# dst -- total ~2.600), bukan cuma Indonesia; hanya sekitar 190 yang
# berlokasi di Indonesia. Sengaja diambil SEMUA (keputusan pemilik bot:
# ada pengguna yang mau melamar ke luar negeri). Lowongan luar negeri tetap
# dapat country yang benar dari location_normalizer, jadi filter negara di
# Jobly yang memisahkannya. Ubah ke True untuk Indonesia saja.
HANYA_INDONESIA = False
BATAS_AMBIL_MENTAH = 5000  # pengaman pagination saat memfilter per negara

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": f"{BASE_CAREER_URL}/",
    "Origin": BASE_CAREER_URL,
}


def _strip_html(html: str | None) -> str | None:
    if not html:
        return None
    return BeautifulSoup(unescape(html), "html.parser").get_text(separator=" ", strip=True)


def _build_lookup(items: list[dict], key: str = "biz_id") -> dict:
    """Bangun dict {id: default_text} dari list meta.
    Coba key utama dulu, fallback ke key alternatif yang umum.
    """
    result = {}
    for item in items:
        # cari key ID yang valid di item ini
        id_val = item.get(key)
        if id_val is None:
            # fallback ke key lain yang umum di API Shopee
            for alt in ("employment_level_id", "dept_id", "department_id", "id"):
                id_val = item.get(alt)
                if id_val is not None:
                    break
        if id_val is not None:
            text = item.get("default_text") or item.get("employment_type_name") or ""
            result[str(id_val)] = text
    return result


def _fetch_meta() -> dict:
    """Ambil metadata untuk decode ID → teks (lokasi, departemen, employment type)."""
    resp = requests.get(META_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json().get("data") or {}

    # flat_locations: {(region_id, city_id) -> "CityName, RegionName"}
    location_map: dict[tuple, str] = {}
    region_names: dict = {}
    for loc in data.get("flat_locations") or []:
        region_names[loc.get("region_id")] = loc.get("region_name", "")
        key = (loc.get("region_id"), loc.get("city_id"))
        city = loc.get("city_name", "")
        region = loc.get("region_name", "")
        location_map[key] = f"{city}, {region}" if city and region else city or region

    # employment level: key bisa "employment_level_id" atau "biz_id"
    emp_map = _build_lookup(data.get("employment_level_list") or [])

    # departemen: key bisa "dept_id", "biz_id", atau lainnya
    dept_map = _build_lookup(data.get("dept_list") or [])

    # job types
    job_type_map = _build_lookup(data.get("job_types") or [])

    return {
        "location_map": location_map,
        "region_names": region_names,
        "dept_map": dept_map,
        "emp_map": emp_map,
        "job_type_map": job_type_map,
    }


def _fetch_jobs(limit: int = 100) -> list[dict]:
    """Ambil job dari API dengan pagination sampai limit terpenuhi."""
    all_jobs: list[dict] = []
    offset = 0
    page_size = 30

    while len(all_jobs) < limit:
        params = {"limit": page_size, "offset": offset}
        try:
            resp = requests.get(JOB_LIST_URL, headers=HEADERS, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json().get("data", {})
        except Exception:
            break

        jobs = data.get("job_list") or []
        if not jobs:
            break

        all_jobs.extend(jobs)
        offset += len(jobs)

        # API Shopee pakai "total_count" bukan "total"
        total = data.get("total_count") or data.get("total") or 0
        if total and offset >= total:
            break

        # kalau total tidak ada tapi dapat kurang dari page_size, berarti sudah habis
        if len(jobs) < page_size:
            break

        time.sleep(0.3)

    return all_jobs[:limit]


def search_shopee(query: str, limit: int = 50) -> list[dict]:
    """Scrape loker Shopee.

    - query = 'semua' / 'all' / '*'  → ambil semua loker
    - query = kata kunci bebas        → filter client-side dari job_name
    """
    browse_all = query.strip().lower() in ALL_KEYWORDS

    try:
        meta = _fetch_meta()
    except Exception as e:
        raise RuntimeError(f"Gagal ambil metadata Shopee: {e}") from e

    # Kalau difilter per negara, `limit` berlaku SETELAH filter -- jadi
    # ambil seluruh katalog mentah dulu. Kalau tidak, 50 lowongan pertama
    # bisa saja semuanya dari Brazil dan hasil Indonesia jadi nol.
    if HANYA_INDONESIA:
        jumlah_mentah = BATAS_AMBIL_MENTAH
    else:
        jumlah_mentah = limit if browse_all else limit * 3
    try:
        raw_jobs = _fetch_jobs(limit=jumlah_mentah)
    except Exception as e:
        raise RuntimeError(f"Gagal ambil daftar loker Shopee: {e}") from e

    location_map = meta["location_map"]
    region_names = meta["region_names"]
    dept_map = meta["dept_map"]
    emp_map = meta["emp_map"]
    job_type_map = meta["job_type_map"]

    results: list[dict] = []
    for job in raw_jobs:
        title = job.get("job_name", "")
        if not browse_all:
            if query.strip().lower() not in title.lower():
                continue

        # decode lokasi
        region_id = job.get("region_id")
        city_id = job.get("city_id")
        if HANYA_INDONESIA and region_names.get(region_id) != "Indonesia":
            continue
        location = location_map.get((region_id, city_id), "")
        if not location:
            location = "Indonesia"

        # decode departemen & employment type
        dept_id = str(job.get("department_id", ""))
        emp_id = str(job.get("employment_id", ""))
        job_type_id = str(job.get("job_type_id", ""))
        department = dept_map.get(dept_id, "")
        # employment_id menunjuk ke employment_level_list, isinya LEVEL
        # ("Entry Level", "Experienced (Individual Contributor)",
        # "Internship"), bukan tipe kerja. Dulu dimasukkan ke job_type,
        # sehingga job_level selalu kosong.
        level = emp_map.get(emp_id, "")
        employment_raw = job_type_map.get(job_type_id, "") or level

        # URL detail loker
        job_id_str = job.get("job_id", str(job.get("id", "")))
        job_url = f"{BASE_CAREER_URL}/jobs/{job_id_str}"

        # deskripsi
        # sub_team_description sering menyebut pola kerja ("hybrid",
        # "100% on-site"), jadi ikut dimasukkan supaya work_arrangement
        # terdeteksi dengan benar.
        desc_html = " ".join(
            job.get(k) or ""
            for k in ("job_description", "requirements", "sub_team_description")
        )
        description = _strip_html(desc_html.strip()) if desc_html.strip() else None

        results.append({
            "job_id": job_id_str,
            "title": title,
            "url": job_url,
            "location": location,
            "department": department,
            "level": level,
            "employment_raw": employment_raw,
            "description": description,
        })

        if len(results) >= limit:
            break

    return results


def shopee_to_records(
    jobs: list[dict],
    search_term: str,
    search_location: str,
    requested_by_chat_id: str,
) -> list[dict]:
    records = []
    for job in jobs:
        title = job.get("title", "")
        location = job.get("location", "Indonesia")
        department = job.get("department")
        employment_raw = job.get("employment_raw", "")
        level = job.get("level") or None
        url = job.get("url", "")
        description = job.get("description")

        record = {
            "job_id": job.get("job_id", url),
            "site": "shopee",
            "job_url": url,
            "job_url_direct": url,
            "title": title,
            "company": "Shopee",
            "location": location,
            "date_posted": None,
            "job_type": employment_raw or None,
            "salary_source": None,
            "interval": None,
            "min_amount": None,
            "max_amount": None,
            "currency": None,
            "is_remote": False,
            "job_level": level,
            "job_function": department or None,
            "listing_type": None,
            "emails": None,
            "description": description,
            "company_industry": "E-Commerce & Technology",
            "company_url": BASE_CAREER_URL,
            "company_logo": None,
            "company_url_direct": "https://shopee.co.id",
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
            "category": classify_job(title, department, search_term),
            "work_arrangement": classify_work_arrangement(
                None, title, location, description
            ),
            "employment_type": classify_employment_type(
                employment_raw, title, level
            ),
            "search_term": search_term,
            "search_location": search_location or location,
            "requested_by_chat_id": str(requested_by_chat_id),
        }
        records.append(record)
    return records
