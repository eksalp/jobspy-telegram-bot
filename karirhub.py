from __future__ import annotations

"""
Scraper untuk karirhub.kemnaker.go.id — agregator lowongan Kemnaker.

BUKAN sumber lowongan sendiri: kartu-kartunya secara eksplisit menyebut
"Lowongan dari Kitalulus" (dan kemungkinan sumber lain), jadi Karirhub adalah
mirror/agregator, bukan pemasang lowongan langsung.

Halaman dirender di server (Next.js SSR), jadi datanya ada di HTML biasa.

Struktur kartu (dipastikan lewat try_selector.py --html):

    div.text-card-foreground.w-full.h-full   <- satu kartu, TIDAK sekaligus <a>
      span.text-[10px]                        <- "sekitar 1 jam yang lalu"
      h4 > a[href^="/lowongan-dalam-negeri/"]  <- judul + link detail
      p.font-normal.text-base.truncate        <- nama perusahaan
      p.text-xs...text-gray-500 (opsional)     <- lokasi, SERING KOSONG
      div berisi "Kisaran Gaji"                <- label, nilainya di sibling
      teks "Rp 2 jt-Rp 5,5 jt"                 <- rentang gaji, satuan "jt"
      teks "Lamar sebelum 21 Okt 2026"         <- batas lamar
      teks "Tersisa N lowongan"                <- sisa slot

Gaji dalam notasi ringkas Indonesia ("2 jt", "5,5 jt", kadang "1,2 M" untuk
miliar) — bukan angka biasa, jadi diurai dengan pengali satuan.

job_id diambil dari UUID di URL (segmen terakhir setelah slug judul), jadi
stabil walau judulnya diedit.
"""

import re
from urllib.parse import urljoin

from categorize import classify_job

BASE_URL = "https://karirhub.kemnaker.go.id"
LIST_URL = f"{BASE_URL}/lowongan-dalam-negeri/lowongan"

ALL_KEYWORDS = {"all", "semua", "*", ""}

CARD_SELECTOR = "div.text-card-foreground.w-full.h-full"

# "Rp 2 jt-Rp 5,5 jt", "Rp 1,2 M-Rp 1,5 M", "Rp 5.500.000"
_PENGALI = {"jt": 1_000_000, "juta": 1_000_000, "m": 1_000_000_000, "miliar": 1_000_000_000}
_SALARY_RANGE = re.compile(
    r"Rp\s*([\d.,]+)\s*(jt|juta|m|miliar)?\s*-\s*Rp\s*([\d.,]+)\s*(jt|juta|m|miliar)?",
    re.I)
_SALARY_SINGLE = re.compile(r"Rp\s*([\d.,]+)\s*(jt|juta|m|miliar)?", re.I)

_SISA = re.compile(r"Tersisa\s*(\d+)", re.I)
# Dibatasi sampai sebelum "Tersisa" atau akhir teks — tanpa batas ini,
# "21 Okt 2026 Tersisa 1 lowongan" ikut tersimpan sebagai deadline.
_BATAS = re.compile(
    r"Lamar sebelum\s*(.+?)(?=\s*Tersisa|\s*$)", re.I)


def _is_browse_all(query: str | None) -> bool:
    return (query or "").strip().lower() in ALL_KEYWORDS


def _angka(text: str, satuan: str | None) -> float | None:
    """'2' + 'jt' -> 2_000_000.0. Koma Indonesia dipakai sebagai desimal di sini
    (mis. '5,5 jt' = 5.5 juta), beda dari titik-ribuan pada 'Rp 5.500.000'."""
    bersih = text.strip()
    if satuan:
        bersih = bersih.replace(",", ".")
        try:
            nilai = float(bersih)
        except ValueError:
            return None
        return nilai * _PENGALI.get(satuan.lower(), 1)

    # tanpa satuan -> asumsikan format ribuan biasa "5.500.000"
    digit = bersih.replace(".", "").replace(",", "")
    return float(digit) if digit.isdigit() else None


def _parse_salary(text: str) -> dict:
    m = _SALARY_RANGE.search(text)
    if m:
        low = _angka(m.group(1), m.group(2))
        high = _angka(m.group(3), m.group(4) or m.group(2))
        if low and high:
            return {"min_amount": min(low, high), "max_amount": max(low, high),
                    "currency": "IDR", "interval": "monthly"}
    m = _SALARY_SINGLE.search(text)
    if m:
        nilai = _angka(m.group(1), m.group(2))
        if nilai:
            return {"min_amount": nilai, "max_amount": nilai,
                    "currency": "IDR", "interval": "monthly"}
    return {}


def search_karirhub(query: str, limit: int = 50) -> list[dict]:
    from sites.base import get_soup

    keyword = "" if _is_browse_all(query) else query.strip().lower()
    jobs: list[dict] = []
    seen: set[str] = set()
    page = 1

    while len(jobs) < limit and page <= 40:
        try:
            soup = get_soup(LIST_URL, params={"page": page} if page > 1 else None)
        except Exception:  # noqa: BLE001
            break

        cards = soup.select(CARD_SELECTOR)
        if not cards:
            break

        sebelum = len(jobs)
        for card in cards:
            link = card.select_one('a[href^="/lowongan-dalam-negeri/lowongan/"]')
            if not link or not link.get("href"):
                continue
            url = urljoin(BASE_URL, link["href"])
            if url in seen:
                continue

            title = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            if not title:
                continue

            company = None
            p_company = card.select_one("p.font-normal.text-base.truncate")
            if p_company:
                company = re.sub(
                    r"\s+", " ", p_company.get_text(" ", strip=True)) or None

            location = None
            p_loc = card.select_one("p.text-xs.text-gray-500.truncate")
            if p_loc:
                teks = re.sub(r"\s+", " ", p_loc.get_text(" ", strip=True))
                location = teks or None

            if keyword and keyword not in f"{title} {company or ''}".lower():
                continue

            full_text = card.get_text(" ", strip=True)
            gaji = _parse_salary(full_text)

            sisa = _SISA.search(full_text)
            batas = _BATAS.search(full_text)

            seen.add(url)
            jobs.append({
                "title": title,
                "company": company,
                "location": location,
                "url": url,
                "remaining_slots": int(sisa.group(1)) if sisa else None,
                "deadline": batas.group(1).strip() if batas else None,
                **gaji,
            })
            if len(jobs) >= limit:
                break

        if len(jobs) == sebelum:
            break
        page += 1

    return jobs[:limit]


def karirhub_to_records(
    jobs: list[dict],
    search_term: str,
    search_location: str | None,
    requested_by_chat_id: str,
) -> list[dict]:
    from categorize import classify_employment_type, classify_work_arrangement

    records = []
    for job in jobs:
        title = job.get("title")
        url = job.get("url")
        if not title or not url:
            continue

        m = re.search(
            r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
            url, re.I)
        job_id = m.group(1) if m else url

        location = job.get("location") or "Indonesia"
        has_salary = job.get("min_amount") is not None
        raw_salary = (
            f"Rp{job['min_amount']:,.0f} - Rp{job['max_amount']:,.0f}"
            if has_salary else None
        )

        bits = []
        if job.get("deadline"):
            bits.append(f"Lamar sebelum {job['deadline']}")
        if job.get("remaining_slots") is not None:
            bits.append(f"Tersisa {job['remaining_slots']} lowongan")
        description = " | ".join(bits) or None

        records.append({
            "job_id": str(job_id),
            "site": "karirhub",
            "job_url": url,
            "job_url_direct": url,
            "title": title,
            "company": job.get("company") or "Tidak disebutkan",
            "location": location,
            "date_posted": None,
            "job_type": None,
            "salary_source": "karirhub" if has_salary else None,
            "interval": job.get("interval"),
            "min_amount": job.get("min_amount"),
            "max_amount": job.get("max_amount"),
            "currency": job.get("currency"),
            "is_remote": None,
            "job_level": None,
            "job_function": None,
            "listing_type": None,
            "emails": None,
            "description": description,
            "company_industry": None,
            "company_url": BASE_URL,
            "company_logo": None,
            "company_url_direct": None,
            "company_addresses": location,
            "company_num_employees": None,
            "company_revenue": None,
            "company_description": None,
            "skills": None,
            "experience_range": None,
            "company_rating": None,
            "company_reviews_count": None,
            "vacancy_count": job.get("remaining_slots"),
            "work_from_home_type": None,
            "raw_salary": raw_salary,
            "category": classify_job(title, search_term),
            "work_arrangement": classify_work_arrangement(None, title, None, location),
            "employment_type": classify_employment_type(None, title),
            "search_term": search_term or "scrapeall",
            "search_location": search_location or location,
            "requested_by_chat_id": str(requested_by_chat_id),
        })
    return records
