from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from categorize import classify_job, classify_work_arrangement, classify_employment_type

BASE_URL = "https://lokerbumn.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; JobSpyTelegramBot/1.0; personal use)"
}

# pola URL post di lokerbumn.com: https://lokerbumn.com/<slug>/<dd>/<yyyy>/
POST_URL_PATTERN = re.compile(r"^https://lokerbumn\.com/[^/]+/\d{1,2}/\d{4}/?$")


def _parse_date_from_url(url: str) -> str | None:
    """URL-nya berakhir /DD/YYYY/ - bukan tanggal post yang presisi (kadang angka
    itu representasi internal WordPress, bukan hari beneran), jadi cuma dipakai
    sebagai fallback kasar kalau tanggal asli nggak ketemu di halaman post.
    """
    m = re.search(r"/(\d{1,2})/(\d{4})/?$", url)
    if not m:
        return None
    day, year = m.groups()
    try:
        return datetime(int(year), 1, min(int(day), 28)).date().isoformat()
    except ValueError:
        return None


ALL_KEYWORDS = {"all", "semua", "*"}


def search_lokerbumn(query: str, limit: int = 20, max_pages: int = 5) -> list[dict]:
    """Cari post di lokerbumn.com. Kalau `query` adalah "all"/"semua"/"*", ambil
    dari halaman listing utama (semua post terbaru) alih-alih fitur search.
    Return list of dict: {title, url}
    """
    browse_all = query.strip().lower() in ALL_KEYWORDS
    results: list[dict] = []
    seen_urls: set[str] = set()

    for page in range(1, max_pages + 1):
        if browse_all:
            url = f"{BASE_URL}/lowongan-kerja/" if page == 1 else f"{BASE_URL}/lowongan-kerja/page/{page}/"
        elif page == 1:
            url = f"{BASE_URL}/?s={quote(query)}"
        else:
            url = f"{BASE_URL}/page/{page}/?s={quote(query)}"

        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        links = soup.find_all("a", href=POST_URL_PATTERN)

        page_had_new = False
        for link in links:
            href = link.get("href", "").strip()
            title = link.get_text(strip=True)
            if not href or not title or href in seen_urls:
                continue
            seen_urls.add(href)
            page_had_new = True
            results.append({"title": title, "url": href})
            if len(results) >= limit:
                return results

        if not page_had_new:
            break  # halaman nggak ada hasil baru, berarti udah abis / nggak ada next page

    return results


def fetch_post_detail(url: str) -> dict:
    """Ambil detail satu post (deskripsi singkat + tanggal kalau ketemu)."""
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    date_posted = None
    time_tag = soup.find("time")
    if time_tag and time_tag.get("datetime"):
        try:
            date_posted = datetime.fromisoformat(
                time_tag["datetime"].replace("Z", "+00:00")
            ).date().isoformat()
        except ValueError:
            date_posted = None

    article = soup.find("article") or soup.find("main") or soup
    paragraphs = article.find_all("p") if article else []
    description = " ".join(p.get_text(strip=True) for p in paragraphs[:6]).strip()

    return {"date_posted": date_posted, "description": description}


def lokerbumn_to_records(
    posts: list[dict],
    search_term: str,
    search_location: str,
    requested_by_chat_id: str,
    fetch_details: bool = True,
) -> list[dict]:
    """Ubah hasil search lokerbumn.com jadi list of dict siap upsert ke tabel `jobs`.
    NOTE: lokerbumn.com berisi pengumuman rekrutmen (bisa mencakup banyak posisi
    sekaligus dalam satu post), bukan listing per-posisi terstruktur kayak Indeed/
    LinkedIn. Kolom `title` di sini = judul pengumuman, `company` tidak selalu
    terisi otomatis.
    """
    records = []
    for post in posts:
        url = post["url"]
        title = post["title"]

        date_posted = _parse_date_from_url(url)
        description = None

        if fetch_details:
            try:
                detail = fetch_post_detail(url)
                if detail.get("date_posted"):
                    date_posted = detail["date_posted"]
                description = detail.get("description")
            except Exception:
                pass

        record = {
            "job_id": url,
            "site": "lokerbumn",
            "job_url": url,
            "job_url_direct": url,
            "title": title,
            "company": None,
            "location": "Indonesia",
            "date_posted": date_posted,
            "job_type": None,
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
            "company_industry": None,
            "company_url": None,
            "company_logo": None,
            "company_url_direct": None,
            "company_addresses": None,
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
            "category": classify_job(title, description, search_term),
            "work_arrangement": classify_work_arrangement(False, title, description),
            "employment_type": classify_employment_type(None, title, description),
            "search_term": search_term,
            "search_location": search_location,
            "requested_by_chat_id": str(requested_by_chat_id),
        }
        records.append(record)

    return records
