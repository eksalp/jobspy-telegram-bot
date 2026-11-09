from __future__ import annotations

"""Pendaftaran Indofood ke registry (logika scraping ada di indofood.py)."""

from .registry import SiteSpec, register


def register_indofood() -> None:
    from indofood import indofood_to_records, search_indofood

    def fetch(query: str, limit: int) -> list[dict]:
        jobs = search_indofood(query=query, limit=limit)
        records = indofood_to_records(jobs, search_term=query,
                                      search_location=None, requested_by_chat_id="")
        return [{
            "title": r["title"], "url": r["job_url"], "job_id": r["job_id"],
            "location": r["location"], "description": r["description"],
            "job_function": r["job_function"], "job_level": r["job_level"],
            "job_type": r["job_type"], "is_remote": False,
        } for r in records]

    register(SiteSpec(
        name="indofood", label="Indofood",
        company="PT Indofood Sukses Makmur Tbk",
        fetch=fetch,
        industry="Food & Beverage",
        company_url="https://career.indofood.com/vacancy.aspx",
        company_url_direct="https://www.indofood.com",
        verified=True, tags={"fmcg", "id"},
        notes="Page method ASP.NET OnGetAdvFilter, ~110 loker.",
    ))
