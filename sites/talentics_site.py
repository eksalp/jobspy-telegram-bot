from __future__ import annotations

"""Pendaftaran Talentics (logika scraping ada di talentics.py)."""

from .registry import SiteSpec, register


def register_talentics() -> None:
    from talentics import search_talentics, talentics_to_records

    def fetch(query: str, limit: int) -> list[dict]:
        jobs = search_talentics(query=query, limit=limit)
        records = talentics_to_records(
            jobs, search_term=query, search_location=None,
            requested_by_chat_id="")
        keluar = []
        for r in records:
            item = {
                "title": r["title"], "url": r["job_url"], "job_id": r["job_id"],
                "location": r["location"], "company": r["company"],
                "job_type": r["job_type"], "job_level": r["job_level"],
                "is_remote": r["is_remote"], "date_posted": r["date_posted"],
                "description": r["description"],
            }
            for kolom in ("work_arrangement", "employment_type",
                          "experience_range", "job_url_direct", "company_url"):
                if r.get(kolom) is not None:
                    item[kolom] = r[kolom]
            keluar.append(item)
        return keluar

    register(SiteSpec(
        name="talentics", label="Talentics", company="Berbagai perusahaan",
        fetch=fetch,
        industry="Various (ATS aggregator)",
        company_url="https://jobs.talentics.id",
        # Deskripsi sudah diambil sendiri dari halaman detail.
        enrich=False,
        verified=True, tags={"id", "aggregator"},
        notes="API /ajaxs/jobs dengan sesi Laravel (cookie + CSRF), tanpa "
              "Playwright. Deskripsi dari halaman detail.",
    ))
