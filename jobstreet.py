from __future__ import annotations

"""
Scraper untuk id.jobstreet.com (JobStreet Indonesia, grup SEEK).

Halaman webnya memblokir skrip lewat bot detection, tapi API pencarian yang
dipakai frontend-nya terbuka tanpa auth:

    GET https://id.jobstreet.com/api/jobsearch/v5/search
        ?siteKey=ID-Main&sourcesystem=houston
        &keywords=...&page=1&pageSize=30

CATATAN: endpoint lama /api/chalice-search/v4/search sudah dipensiunkan oleh
SEEK dan sekarang mengembalikan 404. Ini sudah dipindah ke v5 di atas. Bentuk
respons juga sedikit berbeda: lokasi ada di `locations[0].label` (bukan field
`location` datar), dan teks gaji ada di `salaryLabel` (bukan `salary`).

PENTING: skema respons ini hasil rekayasa balik, bukan API resmi yang
didokumentasikan. Nama field bisa berubah sewaktu-waktu tanpa pemberitahuan.
Karena itu semua pembacaan field di sini memakai fallback berlapis, dan ada
mode pemeriksaan untuk melihat bentuk aslinya:

    python jobstreet.py

Perintah itu mencetak kunci-kunci JSON dari satu lowongan pertama, sehingga
kalau strukturnya berubah, pemetaannya gampang dibetulkan.
"""

import re

from categorize import classify_employment_type, classify_job, classify_work_arrangement

BASE_URL = "https://id.jobstreet.com"
API_URL = f"{BASE_URL}/api/jobsearch/v5/search"
PAGE_SIZE = 30

ALL_KEYWORDS = {"all", "semua", "*", ""}

# "Rp 8.000.000 – Rp 10.000.000 per month" / "Rp8,000,000 - Rp10,000,000"
_SALARY = re.compile(
    r"Rp\s*([\d.,]+)\s*[–—-]\s*(?:Rp\s*)?([\d.,]+)", re.I)
_PER_UNIT = re.compile(r"per\s+(month|year|hour|day|bulan|tahun|jam|hari)", re.I)

_INTERVAL = {
    "month": "monthly", "bulan": "monthly",
    "year": "yearly", "tahun": "yearly",
    "hour": "hourly", "jam": "hourly",
    "day": "daily", "hari": "daily",
}



def _get_json(url: str, params: dict, headers: dict, timeout: int = 20) -> dict:
    """GET yang meniru sidik jari TLS browser.

    JobStreet tidak menolak dengan 403 — koneksinya justru DIDIAMKAN sampai
    timeout. Itu ciri proteksi berbasis sidik jari TLS (JA3): server mengenali
    `requests` dari cara ia melakukan handshake, terlepas dari header apa pun
    yang dikirim.

    `tls-client` meniru handshake Chrome sungguhan dan sudah terpasang sebagai
    dependensi python-jobspy. Kalau tidak ada, kita jatuh ke requests biasa —
    yang kemungkinan besar gagal, tapi setidaknya pesannya jelas.
    """
    from urllib.parse import urlencode

    full_url = f"{url}?{urlencode(params)}"

    try:
        import tls_client
    except ModuleNotFoundError:
        from sites.base import http_get
        return http_get(url, params=params, headers=headers,
                        retries=1, timeout=timeout).json()

    session = tls_client.Session(
        client_identifier="chrome_120",
        random_tls_extension_order=True,
    )
    resp = session.get(full_url, headers=headers, timeout_seconds=timeout)

    if resp.status_code != 200:
        raise RuntimeError(
            f"JobStreet menjawab {resp.status_code}. "
            "Kemungkinan endpoint atau parameternya berubah.")

    try:
        return resp.json()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Respons JobStreet bukan JSON: {e}") from e


def _is_browse_all(query: str | None) -> bool:
    return (query or "").strip().lower() in ALL_KEYWORDS


def _first(mapping: dict, *keys, default=None):
    """Ambil nilai pertama yang ada dan tidak kosong dari beberapa nama field.

    Dipakai karena skema API ini tidak resmi — nama field bisa berbeda antar
    versi (mis. company bisa ada di advertiser.description atau companyName).
    """
    for key in keys:
        value = mapping
        for part in key.split("."):
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(part)
        if value not in (None, "", [], {}):
            return value
    return default


def _to_number(text: str) -> int | None:
    """'8.000.000' atau '8,000,000' -> 8000000."""
    digits = re.sub(r"[^\d]", "", text)
    if not digits:
        return None
    value = int(digits)
    return value if value >= 100_000 else None


def _parse_salary(text: str | None) -> dict:
    if not text:
        return {}
    m = _SALARY.search(text)
    if not m:
        return {}
    low, high = _to_number(m.group(1)), _to_number(m.group(2))
    if not (low and high):
        return {}

    out = {
        "min_amount": min(low, high),
        "max_amount": max(low, high),
        "currency": "IDR",
        "interval": "monthly",
        "raw_salary": text[:200],
    }
    unit = _PER_UNIT.search(text)
    if unit:
        out["interval"] = _INTERVAL.get(unit.group(1).lower(), "monthly")
    return out


def search_jobstreet(query: str, limit: int = 50,
                     location: str | None = None) -> list[dict]:
    keywords = "" if _is_browse_all(query) else query.strip()
    is_all = _is_browse_all(query)
    # Mode "semua"/"all" berarti user mau SEMUA lowongan, bukan dibatasi
    # `limit`. Loop tetap berhenti kalau JobStreet sendiri bilang sudah
    # habis (lihat pengecekan `total`/`len(batch) < PAGE_SIZE` di bawah).
    # `max_pages` dinaikkan jauh lebih tinggi untuk mode ini karena batas
    # asli sekarang adalah data itu sendiri, bukan `limit` — bukan berarti
    # tanpa batas sama sekali, supaya tidak menyapu tak berkesudahan kalau
    # ada bug di sisi JobStreet (mis. `total`/`hasMore` yang tidak akurat).
    max_pages = 100 if is_all else 20
    jobs: list[dict] = []
    page = 1

    while (is_all or len(jobs) < limit) and page <= max_pages:
        params = {
            "siteKey": "ID-Main",
            "sourcesystem": "houston",
            "page": page,
            "pageSize": PAGE_SIZE,
        }
        if keywords:
            params["keywords"] = keywords
        if location:
            params["where"] = location

        data = _get_json(API_URL, params, headers={
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
            "Referer": f"{BASE_URL}/",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        })

        batch = _first(data, "data", "jobs", "results", default=[])
        if not isinstance(batch, list) or not batch:
            break

        jobs.extend(batch)

        total = _first(data, "totalCount", "total", default=0)
        if total and len(jobs) >= total:
            break
        if len(batch) < PAGE_SIZE:
            break
        page += 1

    return jobs if is_all else jobs[:limit]


def jobstreet_to_records(
    jobs: list[dict],
    search_term: str,
    search_location: str | None,
    requested_by_chat_id: str,
) -> list[dict]:
    records = []
    for job in jobs:
        title = _first(job, "title", "jobTitle")
        if not title:
            continue

        job_id = str(_first(job, "id", "jobId", "solMetadata.jobId", default="") or "")
        url = f"{BASE_URL}/job/{job_id}" if job_id else BASE_URL

        company = _first(
            job, "advertiser.description", "companyName", "company.name",
            "advertiser.name", default="Tidak disebutkan")

        locations_list = _first(job, "locations", default=[])
        v5_location = None
        if isinstance(locations_list, list) and locations_list:
            first_loc = locations_list[0]
            if isinstance(first_loc, dict):
                v5_location = first_loc.get("label")

        location_parts = [
            v5_location or _first(job, "location", "locationName", "jobLocation"),
            _first(job, "area", "areaName"),
        ]
        loc = ", ".join(str(p) for p in location_parts if p) or "Indonesia"

        classifications_list = _first(job, "classifications", default=[])
        v5_function = None
        if isinstance(classifications_list, list) and classifications_list:
            first_class = classifications_list[0]
            if isinstance(first_class, dict):
                sub = first_class.get("subclassification") or {}
                top = first_class.get("classification") or {}
                v5_function = (
                    (sub.get("description") if isinstance(sub, dict) else None)
                    or (top.get("description") if isinstance(top, dict) else None)
                )

        work_type = _first(job, "workTypes", "workType", "employmentType", "jobType")
        if isinstance(work_type, list):
            work_type = ", ".join(str(w) for w in work_type) if work_type else None

        function = v5_function or _first(
            job, "classification.description", "classification",
            "category", "subClassification.description")
        if isinstance(function, dict):
            function = function.get("description")

        teaser = _first(job, "teaser", "jobSummary", "shortDescription")
        bullets = _first(job, "bulletPoints", default=[])
        if isinstance(bullets, list) and bullets:
            teaser = " | ".join(
                [str(teaser)] if teaser else []) + " | " + " | ".join(
                str(b) for b in bullets)
        description = re.sub(r"\s+", " ", str(teaser)).strip()[:4000] if teaser else None

        posted = _first(job, "listingDate", "postedDate", "datePosted")
        date_posted = str(posted)[:10] if posted else None

        arrangement_hint = None
        arrangements_data = _first(job, "workArrangements.data", default=[])
        if isinstance(arrangements_data, list) and arrangements_data:
            first_arr = arrangements_data[0]
            if isinstance(first_arr, dict):
                label = first_arr.get("label") or {}
                arrangement_hint = label.get("text") if isinstance(label, dict) else None

        salary = _parse_salary(
            _first(job, "salaryLabel", "salary", "salaryText", "displaySalary"))

        records.append({
            "job_id": job_id or url,
            "site": "jobstreet",
            "job_url": url,
            "job_url_direct": url,
            "title": str(title),
            "company": str(company),
            "location": loc,
            "date_posted": date_posted,
            "job_type": str(work_type) if work_type else None,
            "salary_source": "jobstreet" if salary else None,
            "interval": salary.get("interval"),
            "min_amount": salary.get("min_amount"),
            "max_amount": salary.get("max_amount"),
            "currency": salary.get("currency"),
            "is_remote": None,
            "job_level": None,
            "job_function": str(function) if function else None,
            "listing_type": None,
            "emails": None,
            "description": description,
            "company_industry": None,
            "company_url": BASE_URL,
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
            "raw_salary": salary.get("raw_salary"),
            "category": classify_job(str(title), function, search_term),
            "work_arrangement": classify_work_arrangement(
                arrangement_hint, str(title), str(work_type or ""), loc, description),
            "employment_type": classify_employment_type(
                str(work_type or ""), str(title), description),
            "search_term": search_term or "scrapeall",
            "search_location": search_location or loc,
            "requested_by_chat_id": str(requested_by_chat_id),
        })
    return records


if __name__ == "__main__":
    # Mode pemeriksaan: lihat bentuk asli respons API supaya pemetaan field
    # bisa dibetulkan kalau JobStreet mengubah skemanya.
    import json
    import sys

    sys.path.insert(0, ".")
    raw = search_jobstreet("semua", limit=2)
    if not raw:
        sys.exit("API tidak mengembalikan apa-apa. Kemungkinan endpoint atau "
                 "parameternya berubah, atau permintaan diblokir.")

    print(f"{len(raw)} lowongan mentah. Kunci pada item pertama:\n")
    for key, value in raw[0].items():
        preview = json.dumps(value, ensure_ascii=False)[:90]
        print(f"  {key:<24} {preview}")

    print("\nHasil pemetaan:")
    for rec in jobstreet_to_records(raw, "semua", None, "test"):
        print(f"  {rec['title'][:40]:<42} | {rec['company'][:24]:<26} | "
              f"{rec['location'][:20]:<22} | {rec['min_amount'] or '-'}")