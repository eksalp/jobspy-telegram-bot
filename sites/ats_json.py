from __future__ import annotations

"""
Adapter untuk ATS yang punya REST API JSON publik dan stabil.

Semuanya read-only, tanpa API key, tanpa Playwright:
  Greenhouse      https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
  Lever           https://api.lever.co/v0/postings/{token}?mode=json
  SmartRecruiters https://api.smartrecruiters.com/v1/companies/{id}/postings
  Ashby           https://api.ashbyhq.com/posting-api/job-board/{token}

Cara cari token perusahaan: buka halaman lowongannya, lihat tab Network di
DevTools, atau lihat URL tombol "Apply" — biasanya kelihatan
(mis. boards.greenhouse.io/gojek → token = "gojek").
"""

from datetime import datetime, timezone

from .base import http_get, matches, strip_html
from .registry import SiteSpec, register


def _iso_from_ms(ms) -> str | None:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).date().isoformat()
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# Greenhouse
# --------------------------------------------------------------------------- #
def greenhouse_fetcher(token: str):
    api = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"

    def fetch(query: str, limit: int) -> list[dict]:
        data = http_get(api, params={"content": "true"}).json()
        jobs = []
        for job in data.get("jobs") or []:
            title = job.get("title") or ""
            dept = ", ".join(
                d.get("name", "") for d in (job.get("departments") or [])
            ) or None
            description = strip_html(job.get("content"))
            if not matches(query, title, dept, description):
                continue
            jobs.append({
                "title": title,
                "url": job.get("absolute_url"),
                "job_id": str(job.get("id")),
                "location": (job.get("location") or {}).get("name"),
                "job_function": dept,
                "description": description,
                "date_posted": (job.get("updated_at") or "")[:10] or None,
            })
            if len(jobs) >= limit:
                break
        return jobs

    return fetch


# --------------------------------------------------------------------------- #
# Lever
# --------------------------------------------------------------------------- #
def lever_fetcher(token: str):
    api = f"https://api.lever.co/v0/postings/{token}"

    def fetch(query: str, limit: int) -> list[dict]:
        data = http_get(api, params={"mode": "json"}).json()
        jobs = []
        for job in data:
            cats = job.get("categories") or {}
            title = job.get("text") or ""
            description = strip_html(
                (job.get("descriptionPlain") or job.get("description") or "")
            )
            if not matches(query, title, cats.get("team"), description):
                continue
            jobs.append({
                "title": title,
                "url": job.get("hostedUrl") or job.get("applyUrl"),
                "job_id": job.get("id"),
                "location": cats.get("location"),
                "job_function": cats.get("team") or cats.get("department"),
                "job_type": cats.get("commitment"),
                "description": description,
                "date_posted": _iso_from_ms(job.get("createdAt")),
                "is_remote": (cats.get("location") or "").lower().startswith("remote")
                or None,
            })
            if len(jobs) >= limit:
                break
        return jobs

    return fetch


# --------------------------------------------------------------------------- #
# SmartRecruiters
# --------------------------------------------------------------------------- #
def smartrecruiters_fetcher(company_id: str, country: str | None = None):
    api = f"https://api.smartrecruiters.com/v1/companies/{company_id}/postings"

    def fetch(query: str, limit: int) -> list[dict]:
        jobs, offset, page = [], 0, 100
        while len(jobs) < limit:
            params: dict = {"limit": page, "offset": offset}
            if query and not matches(query):  # query spesifik → serahkan ke server
                params["q"] = query.strip()
            if country:
                params["country"] = country
            data = http_get(api, params=params).json()
            content = data.get("content") or []
            if not content:
                break
            for job in content:
                loc = job.get("location") or {}
                location = ", ".join(
                    p for p in (loc.get("city"), loc.get("region"), loc.get("country"))
                    if p
                ) or None
                jobs.append({
                    "title": job.get("name"),
                    "url": f"https://jobs.smartrecruiters.com/{company_id}/{job.get('id')}",
                    "job_id": job.get("id"),
                    "location": location,
                    "job_function": (job.get("department") or {}).get("label"),
                    "job_type": (job.get("typeOfEmployment") or {}).get("label"),
                    "date_posted": (job.get("releasedDate") or "")[:10] or None,
                    "is_remote": loc.get("remote"),
                })
                if len(jobs) >= limit:
                    break
            offset += len(content)
            if offset >= (data.get("totalFound") or 0):
                break
        return jobs[:limit]

    return fetch


# --------------------------------------------------------------------------- #
# Ashby
# --------------------------------------------------------------------------- #
def ashby_fetcher(token: str):
    api = f"https://api.ashbyhq.com/posting-api/job-board/{token}"

    def fetch(query: str, limit: int) -> list[dict]:
        data = http_get(api, params={"includeCompensation": "true"}).json()
        jobs = []
        for job in data.get("jobs") or []:
            title = job.get("title") or ""
            if not matches(query, title, job.get("department"), job.get("team")):
                continue
            jobs.append({
                "title": title,
                "url": job.get("jobUrl") or job.get("applyUrl"),
                "job_id": job.get("id"),
                "location": job.get("location"),
                "job_function": job.get("department") or job.get("team"),
                "job_type": job.get("employmentType"),
                "description": strip_html(job.get("descriptionHtml")),
                "date_posted": (job.get("publishedAt") or "")[:10] or None,
                "is_remote": job.get("isRemote"),
            })
            if len(jobs) >= limit:
                break
        return jobs

    return fetch


# --------------------------------------------------------------------------- #
# Helper registrasi
# --------------------------------------------------------------------------- #
_FETCHERS = {
    "greenhouse": greenhouse_fetcher,
    "lever": lever_fetcher,
    "smartrecruiters": smartrecruiters_fetcher,
    "ashby": ashby_fetcher,
}


def register_ats(
    platform: str, name: str, label: str, company: str, token: str,
    industry: str | None = None, company_url_direct: str | None = None,
    verified: bool = False, tags: set[str] | None = None, notes: str = "",
    **kwargs,
) -> SiteSpec:
    factory = _FETCHERS[platform]
    return register(SiteSpec(
        name=name, label=label, company=company,
        fetch=factory(token, **kwargs),
        industry=industry,
        company_url_direct=company_url_direct,
        verified=verified,
        # ATS ini sudah mengembalikan deskripsi lengkap lewat API-nya, dan
        # halaman webnya dirender JavaScript. Pengayaan HTML tidak membantu.
        enrich=False,
        tags=(tags or set()) | {platform},
        notes=notes,
    ))
