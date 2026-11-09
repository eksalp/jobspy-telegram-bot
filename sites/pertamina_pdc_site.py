from __future__ import annotations

"""Pendaftaran Pertamina PDC (logika scraping ada di pertamina_pdc.py)."""

from .registry import SiteSpec, register


def register_pertamina_pdc() -> None:
    from pertamina_pdc import pertamina_pdc_to_records, search_pertamina_pdc

    def fetch(query: str, limit: int) -> list[dict]:
        jobs = search_pertamina_pdc(query=query, limit=limit)
        records = pertamina_pdc_to_records(
            jobs, search_term=query, search_location=None,
            requested_by_chat_id="")
        return [{
            "title": r["title"], "url": r["job_url"], "job_id": r["job_id"],
            "location": r["location"], "description": r["description"],
            "job_function": r["job_function"], "job_type": r["job_type"],
            "is_remote": False,
        } for r in records]

    register(SiteSpec(
        name="pertamina_pdc", label="Pertamina PDC",
        company="PT Patra Drilling Contractor",
        fetch=fetch,
        industry="Energy / Oil & Gas",
        company_url="https://karir.pertamina-pdc.com",
        company_url_direct="https://www.pertamina-pdc.com",
        # Tidak ada halaman detail per lowongan (dibuka lewat modal), jadi
        # tidak ada yang bisa diperkaya.
        enrich=False,
        verified=True, tags={"bumn", "energy", "id"},
    ))
