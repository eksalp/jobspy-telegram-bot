from __future__ import annotations

"""
Adapter generik untuk Workday (myworkdayjobs.com).

Workday punya JSON API publik yang dipakai frontend-nya sendiri — tidak butuh
auth, tidak butuh Playwright:

    POST https://{tenant}.{pod}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
    body: {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}

Cara cari parameter untuk perusahaan baru: buka halaman karirnya, kalau
redirect ke `xxx.wd3.myworkdayjobs.com/en-US/YYY` maka tenant=xxx, pod=wd3,
site=YYY.

CATATAN: `limit` di-cap server-side di 20. Pagination lewat `offset`.
"""

from concurrent.futures import ThreadPoolExecutor

from .base import (
    http_get,
    http_post_json,
    in_indonesia,
    is_browse_all,
    strip_html,
)
from .registry import SiteSpec, register

PAGE_SIZE = 20


def _fetch_detail(host: str, tenant: str, site: str, job: dict) -> dict:
    """Ambil deskripsi lengkap satu lowongan dari API detail Workday.

    Endpoint listing hanya mengembalikan judul dan lokasi. Detailnya ada di
    `/wday/cxs/{tenant}/{site}{externalPath}` — JSON, tanpa auth, tanpa
    browser. Ini jauh lebih bersih daripada merender halaman HTML-nya.
    """
    path = job.pop("_path", None)
    if not path:
        return job
    try:
        data = http_get(f"{host}/wday/cxs/{tenant}/{site}{path}",
                        headers={"Accept": "application/json"},
                        retries=1, timeout=20).json()
    except Exception:  # noqa: BLE001
        return job

    info = data.get("jobPostingInfo") or {}
    job["description"] = strip_html(info.get("jobDescription")) or job.get("description")
    job["date_posted"] = (info.get("startDate") or "")[:10] or None
    job["job_type"] = info.get("timeType") or job.get("job_type")
    job["is_remote"] = info.get("remoteType") is not None or None
    if info.get("location"):
        job["location"] = info["location"]
    return job


def workday_fetcher(tenant: str, site: str, pod: str = "wd3",
                    locale: str = "en-US", only_indonesia: bool = False,
                    with_details: bool = True, detail_limit: int = 1000):
    """Bikin fungsi fetch untuk satu tenant Workday.

    `only_indonesia=True` untuk tenant global (mis. Samsung) — hasilnya
    disaring di sisi klien berdasarkan locationsText, karena facet lokasi
    Workday pakai ID internal yang beda-beda tiap tenant.
    """
    host = f"https://{tenant}.{pod}.myworkdayjobs.com"
    api = f"{host}/wday/cxs/{tenant}/{site}/jobs"

    def fetch(query: str, limit: int) -> list[dict]:
        search_text = "" if is_browse_all(query) else query.strip()
        jobs: list[dict] = []
        offset = 0

        while len(jobs) < limit:
            data = http_post_json(api, {
                "appliedFacets": {},
                "limit": PAGE_SIZE,
                "offset": offset,
                "searchText": search_text,
            }, headers={"Referer": f"{host}/{locale}/{site}"})

            postings = data.get("jobPostings") or []
            if not postings:
                break

            for post in postings:
                location = post.get("locationsText")
                if only_indonesia and not in_indonesia(location):
                    continue
                path = post.get("externalPath") or ""
                bullets = post.get("bulletFields") or []
                jobs.append({
                    "title": post.get("title"),
                    "url": f"{host}/{locale}/{site}{path}",
                    "job_id": bullets[0] if bullets else path,
                    "location": location,
                    "date_posted": None,   # listing cuma kasih "Posted 3 Days Ago"
                    "description": strip_html(post.get("shortDescription")),
                    "_path": path,
                })

            offset += len(postings)
            total = data.get("total") or 0
            if total and offset >= total:
                break
            if len(postings) < PAGE_SIZE:
                break
            # Kalau menyaring, jangan berhenti hanya karena halaman ini kosong
            # setelah difilter — tapi tetap batasi supaya tidak menyapu ribuan
            # loker global.
            if only_indonesia and offset >= 600:
                break

        jobs = jobs[:limit]

        if with_details and jobs:
            with ThreadPoolExecutor(max_workers=6) as pool:
                list(pool.map(
                    lambda j: _fetch_detail(host, tenant, site, j),
                    jobs[:detail_limit],
                ))
        for job in jobs:
            job.pop("_path", None)

        return jobs

    return fetch


def register_workday(
    name: str, label: str, company: str, tenant: str, site: str,
    pod: str = "wd3", locale: str = "en-US", industry: str | None = None,
    company_url_direct: str | None = None, verified: bool = False,
    tags: set[str] | None = None, notes: str = "", only_indonesia: bool = False,
    with_details: bool = True,
) -> SiteSpec:
    host = f"https://{tenant}.{pod}.myworkdayjobs.com"
    return register(SiteSpec(
        name=name, label=label, company=company,
        fetch=workday_fetcher(tenant, site, pod, locale, only_indonesia,
                              with_details),
        industry=industry,
        company_url=f"{host}/{locale}/{site}",
        company_url_direct=company_url_direct,
        verified=verified,
        # Halaman lowongan Workday dirender JavaScript, jadi pengayaan HTML
        # cuma menghasilkan profil perusahaan. Deskripsi sudah diambil lewat
        # API detail (with_details) yang jauh lebih akurat.
        enrich=False,
        tags=(tags or set()) | {"workday"},
        notes=notes,
    ))
