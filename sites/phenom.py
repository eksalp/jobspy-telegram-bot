from __future__ import annotations

"""
Adapter generik untuk Phenom People (platform di balik banyak career site
korporat besar: pola URL-nya `/job/<kota>/<slug>/<siteId>/<jobId>`).

Phenom mengekspos endpoint pencarian yang dipakai frontend-nya sendiri:

    POST https://{host}/widgets
    body: {"lang":"en_us","deviceType":"desktop","country":"id",
           "pageName":"search-results","ddoKey":"refineSearch",
           "from":0,"size":10,"keywords":"","jobs":true,"counts":true, ...}

Cara mengenali: HTML halaman karirnya memuat string `ph_widget`, `phApp`,
atau `ddoKey`. `siteId` bisa dibaca dari URL detail lowongan mana pun.
"""

from .base import http_post_json, is_browse_all, strip_html
from .registry import SiteSpec, register

PAGE_SIZE = 10


def phenom_fetcher(host: str, country: str = "id", lang: str = "en_us",
                   selected_fields: dict | None = None):
    host = host.rstrip("/")
    api = f"{host}/widgets"

    def fetch(query: str, limit: int) -> list[dict]:
        keywords = "" if is_browse_all(query) else query.strip()
        jobs: list[dict] = []
        offset = 0

        while len(jobs) < limit and offset < 1000:
            payload = {
                "lang": lang,
                "deviceType": "desktop",
                "country": country,
                "pageName": "search-results",
                "ddoKey": "refineSearch",
                "sortBy": "Most recent",
                "subsearch": "",
                "from": offset,
                "jobs": True,
                "counts": True,
                "all_fields": ["country", "state", "city", "category", "type"],
                "size": PAGE_SIZE,
                "clearAll": False,
                "jdsource": "facets",
                "isSliderEnable": False,
                "pageId": "page11",
                "siteType": "external",
                "keywords": keywords,
                "global": True,
                "selected_fields": selected_fields or {},
                "locationData": {},
            }
            data = http_post_json(api, payload, headers={"Referer": f"{host}/search"})
            refine = (data.get("refineSearch") or {}).get("data") or {}
            listing = (refine.get("jobs") or [])
            if not listing:
                break

            for job in listing:
                location = ", ".join(
                    p for p in (job.get("city"), job.get("state"), job.get("country"))
                    if p and p != "null"
                ) or None
                jobs.append({
                    "title": job.get("title"),
                    "url": job.get("applyUrl") or job.get("jobSeoUrl")
                    or f"{host}/job/{job.get('jobId')}",
                    "job_id": str(job.get("jobId") or job.get("jobSeqNo") or ""),
                    "location": location,
                    "job_function": job.get("category") or job.get("department"),
                    "job_type": job.get("type"),
                    "date_posted": (job.get("postedDate") or "")[:10] or None,
                    "description": strip_html(job.get("descriptionTeaser")),
                })
                if len(jobs) >= limit:
                    break

            total = (refine.get("totalHits") or refine.get("totalCount") or 0)
            offset += len(listing)
            if total and offset >= total:
                break
            if len(listing) < PAGE_SIZE:
                break

        return jobs[:limit]

    return fetch


def register_phenom(
    name: str, label: str, company: str, host: str, country: str = "id",
    lang: str = "en_us", selected_fields: dict | None = None,
    industry: str | None = None, company_url_direct: str | None = None,
    verified: bool = False, tags: set[str] | None = None, notes: str = "",
) -> SiteSpec:
    return register(SiteSpec(
        name=name, label=label, company=company,
        fetch=phenom_fetcher(host, country, lang, selected_fields),
        industry=industry,
        company_url=host,
        company_url_direct=company_url_direct,
        verified=verified,
        enrich=False,
        tags=(tags or set()) | {"phenom"},
        notes=notes,
    ))
