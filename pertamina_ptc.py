from __future__ import annotations

"""
Scraper untuk recruitment.pertamina-ptc.com (Pertamina Training & Consulting).

Situs ini HTML statis murni — data loker langsung ada di HTML tanpa JS rendering.
Data yang diambil: judul, jenis pekerjaan, kualifikasi (sebagai deskripsi), lokasi.
"""

import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from categorize import classify_employment_type, classify_job, classify_work_arrangement

BASE_URL = "https://recruitment.pertamina-ptc.com"
LIST_URL = f"{BASE_URL}/guest/joblist"
ALL_KEYWORDS = {"all", "semua", "*"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
    "Referer": BASE_URL,
}


def _get_soup(url: str, retries: int = 3) -> BeautifulSoup:
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2)
    raise RuntimeError("Gagal mengambil halaman")


def _parse_jobs(soup: BeautifulSoup) -> list[dict]:
    """Parse semua loker dari halaman job list PTC.

    Struktur HTML per loker:
      <strong>JUDUL</strong>
      <strong>Jenis Pekerjaan</strong> CONTRACT/FULL-TIME/dll
      <strong>Kualifikasi</strong> ...teks...
      <strong>Lokasi</strong> ...teks...

    Masing-masing loker dipisah oleh <hr> tag.
    """
    jobs = []

    # Ambil semua blok yang berisi info loker
    # Tiap loker dimulai dari <strong> judul dan diakhiri <hr>
    content_div = soup.find("div", class_=lambda c: c and "container" in c)
    if not content_div:
        content_div = soup

    # Cari semua teks bold yang kemungkinan judul (bukan menu)
    # Strategi: loker ditandai dengan adanya "Jenis Pekerjaan" di sekitarnya
    all_text = content_div.get_text(separator="\n")
    blocks = re.split(r"\n---+\n|\n\s*\n\s*\n", all_text)

    for block in blocks:
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        if not lines:
            continue

        # Cek apakah block ini berisi info loker
        block_lower = block.lower()
        if "jenis pekerjaan" not in block_lower and "lokasi" not in block_lower:
            continue

        title = lines[0] if lines else None
        if not title or len(title) < 3:
            continue

        # Skip menu items
        if title.lower() in ("home", "job list", "how to", "faq", "login", "register",
                             "quick menu", "social icons", "hubungi kami"):
            continue

        # Ekstrak Jenis Pekerjaan
        job_type = None
        m = re.search(r"Jenis Pekerjaan\s*[:\-]?\s*(.+?)(?:\n|Kualifikasi|Lokasi)", block, re.IGNORECASE)
        if m:
            job_type = m.group(1).strip()

        # Ekstrak Lokasi
        location = "Indonesia"
        m = re.search(r"Lokasi\s*[:\-]?\s*(.+?)(?:\n|$)", block, re.IGNORECASE)
        if m:
            location = m.group(1).strip() or "Indonesia"

        # Ekstrak Kualifikasi sebagai deskripsi
        description = None
        m = re.search(r"Kualifikasi\s*[:\-]?\s*(.*?)(?:Lokasi|$)", block, re.IGNORECASE | re.DOTALL)
        if m:
            description = m.group(1).strip()[:1000]  # batasi panjang

        jobs.append({
            "title": title,
            "job_type": job_type,
            "location": location,
            "description": description,
            "url": LIST_URL,
        })

    return jobs


def search_pertamina_ptc(query: str, limit: int = 50) -> list[dict]:
    """Scrape loker Pertamina PTC.
    - query = 'semua'/'all'/'*' → ambil semua
    - query = kata kunci → filter dari judul
    """
    browse_all = query.strip().lower() in ALL_KEYWORDS

    soup = _get_soup(LIST_URL)
    all_jobs = _parse_jobs(soup)

    results = []
    for job in all_jobs:
        if not browse_all:
            if query.strip().lower() not in job["title"].lower():
                continue
        results.append(job)
        if len(results) >= limit:
            break

    return results


def pertamina_ptc_to_records(
    jobs: list[dict],
    search_term: str,
    search_location: str,
    requested_by_chat_id: str,
) -> list[dict]:
    records = []
    for job in jobs:
        title = job.get("title", "")
        location = job.get("location", "Indonesia")
        job_type = job.get("job_type")
        description = job.get("description")
        url = job.get("url", LIST_URL)

        record = {
            "job_id": f"ptc-{re.sub(r'[^a-z0-9]', '-', title.lower())[:60]}",
            "site": "pertamina_ptc",
            "job_url": url,
            "job_url_direct": url,
            "title": title,
            "company": "PT Pertamina Training & Consulting (PTC)",
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
            "job_function": None,
            "listing_type": None,
            "emails": None,
            "description": description,
            "company_industry": "Oil & Gas / Training & Consulting",
            "company_url": BASE_URL,
            "company_logo": None,
            "company_url_direct": "https://www.pertamina-ptc.com",
            "company_addresses": "Jakarta, Indonesia",
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
            "category": classify_job(title, search_term),
            "work_arrangement": classify_work_arrangement(False, title, location, description),
            "employment_type": classify_employment_type(job_type, title, description),
            "search_term": search_term,
            "search_location": search_location or "Indonesia",
            "requested_by_chat_id": str(requested_by_chat_id),
        }
        records.append(record)
    return records
