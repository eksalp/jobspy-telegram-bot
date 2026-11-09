from __future__ import annotations

"""
Scraper untuk karir.bca.co.id.

Strukturnya server-side rendered (Next.js) — data ada di HTML, bisa pakai
requests biasa tanpa Playwright. Tiap card loker ada di div.shadow-card dengan
struktur:
  - <p class="...opensans-bold..."> = judul
  - <p class="...blue-secondary-30..."> = lokasi
  - <a href="/candidate/id/career/[slug]"> = link detail
  - div#experience-level = level pengalaman
  - div#job-pipeline = fungsi pekerjaan
"""

import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from categorize import classify_employment_type, classify_job, classify_work_arrangement

BASE_URL = "https://karir.bca.co.id"
LIST_URL = f"{BASE_URL}/candidate/id/career"
ALL_KEYWORDS = {"all", "semua", "*"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
}


def _get_soup(url: str, params: dict | None = None, retries: int = 3) -> BeautifulSoup:
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=20)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2)
    raise RuntimeError("Gagal mengambil halaman")


def _parse_job_cards(soup: BeautifulSoup) -> list[dict]:
    """Ambil semua card loker dari soup halaman BCA.

    Tiap card = div yang punya class mengandung 'shadow-card'.
    Dari situ kita ambil judul, lokasi, experience level, fungsi, dan URL.
    """
    jobs = []
    seen_urls: set[str] = set()
    slug_pattern = re.compile(r"^/candidate/(?:id|en)/career/[^/]+/?$")

    cards = soup.find_all("div", class_=lambda c: c and "shadow-card" in c)
    for card in cards:
        # URL loker: ambil <a> pertama yang href-nya cocok pola /candidate/.../career/[slug]
        link_tag = card.find("a", href=slug_pattern)
        if not link_tag:
            continue
        href = link_tag.get("href", "")
        full_url = urljoin(BASE_URL, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        # Judul: <p> yang class-nya mengandung 'opensans-bold' (judul ditulis tebal)
        title_tag = card.find("p", class_=lambda c: c and "opensans-bold" in c)
        title = title_tag.get_text(strip=True) if title_tag else None
        if not title:
            continue

        # Lokasi: <p> yang class-nya mengandung 'blue-secondary'
        loc_tag = card.find("p", class_=lambda c: c and "blue-secondary" in c)
        location = loc_tag.get_text(strip=True) if loc_tag else "Indonesia"

        # Experience level: div dengan id="experience-level"
        exp_div = card.find(id="experience-level")
        experience = None
        if exp_div:
            exp_texts = [t.strip() for t in exp_div.stripped_strings if t.strip()]
            experience = exp_texts[0] if exp_texts else None

        # Job pipeline / fungsi: div dengan id="job-pipeline"
        pipeline_div = card.find(id="job-pipeline")
        job_function = None
        if pipeline_div:
            pipe_texts = [t.strip() for t in pipeline_div.stripped_strings if t.strip()]
            job_function = pipe_texts[0] if pipe_texts else None

        jobs.append({
            "title": title,
            "url": full_url,
            "location": location or "Indonesia",
            "experience_level": experience,
            "job_function": job_function,
        })

    return jobs


def search_bca(query: str, limit: int = 50) -> list[dict]:
    """Scrape loker BCA.

    - query = 'semua' / 'all' / '*'  → ambil semua loker
    - query = kata kunci bebas        → filter judul (client-side)

    BCA menampilkan loker di tab 'Highlight' (default) dan 'Terbaru'.
    Kita ambil keduanya lalu dedup.
    """
    browse_all = query.strip().lower() in ALL_KEYWORDS
    results: list[dict] = []
    seen_urls: set[str] = set()

    # Tab 'Terbaru' via parameter audience (Fresh Graduate & Experienced)
    # Tab default (Highlight) tidak butuh parameter
    param_sets: list[dict] = [{}]
    if browse_all:
        param_sets += [{"audience": "fresh_graduate"}, {"audience": "experienced"}]

    for params in param_sets:
        try:
            soup = _get_soup(LIST_URL, params=params or None)
        except Exception:
            continue

        for job in _parse_job_cards(soup):
            if job["url"] in seen_urls:
                continue
            if not browse_all:
                if query.strip().lower() not in job["title"].lower():
                    continue
            seen_urls.add(job["url"])
            results.append(job)
            if len(results) >= limit:
                return results

        time.sleep(0.5)

    return results[:limit]


def bca_to_records(
    jobs: list[dict],
    search_term: str,
    search_location: str,
    requested_by_chat_id: str,
) -> list[dict]:
    records = []
    for job in jobs:
        title = job.get("title", "")
        location = job.get("location", "Indonesia")
        job_function = job.get("job_function")
        experience = job.get("experience_level")
        url = job.get("url", "")

        record = {
            "job_id": url,
            "site": "bca",
            "job_url": url,
            "job_url_direct": url,
            "title": title,
            "company": "PT Bank Central Asia Tbk (BCA)",
            "location": location,
            "date_posted": None,
            "job_type": None,
            "salary_source": None,
            "interval": None,
            "min_amount": None,
            "max_amount": None,
            "currency": None,
            "is_remote": False,
            "job_level": experience,
            "job_function": job_function,
            "listing_type": None,
            "emails": None,
            "description": None,
            "company_industry": "Banking & Financial Services",
            "company_url": BASE_URL,
            "company_logo": None,
            "company_url_direct": "https://www.bca.co.id",
            "company_addresses": "Jakarta, Indonesia",
            "company_num_employees": None,
            "company_revenue": None,
            "company_description": None,
            "skills": None,
            "experience_range": experience,
            "company_rating": None,
            "company_reviews_count": None,
            "vacancy_count": None,
            "work_from_home_type": None,
            "raw_salary": None,
            "category": classify_job(title, job_function, search_term),
            "work_arrangement": classify_work_arrangement(False, title, location),
            "employment_type": classify_employment_type(None, title, experience),
            "search_term": search_term,
            "search_location": search_location or "Indonesia",
            "requested_by_chat_id": str(requested_by_chat_id),
        }
        records.append(record)
    return records
