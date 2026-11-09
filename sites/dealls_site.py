from __future__ import annotations

"""Pendaftaran Dealls (logika scraping ada di dealls.py)."""

from .registry import SiteSpec, register


def register_dealls() -> None:
    from dealls import dealls_to_records, search_dealls

    def fetch(query: str, limit: int) -> list[dict]:
        jobs = search_dealls(query=query, limit=limit)
        records = dealls_to_records(
            jobs, search_term=query, search_location=None,
            requested_by_chat_id="")
        return [{
            "title": r["title"], "url": r["job_url"], "job_id": r["job_id"],
            "location": r["location"], "company": r["company"],
            "job_type": r["job_type"], "job_function": r["job_function"],
            "date_posted": r["date_posted"], "is_remote": r["is_remote"],
            "description": r["description"],
        } for r in records]

    register(SiteSpec(
        name="dealls", label="Dealls", company="Berbagai perusahaan",
        fetch=fetch,
        industry="Various (job aggregator)",
        company_url="https://dealls.com",
        # API-nya sudah mengembalikan semua kolom penting; halaman detail
        # tidak menambah apa-apa yang sepadan dengan biaya request.
        enrich=False,
        verified=True, tags={"aggregator", "id"},
        notes="API sejutacita; ~1200 loker. Satu-satunya sumber dengan gaji "
              "sebagai angka.",
    ))
