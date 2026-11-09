from __future__ import annotations

"""Pendaftaran KitaLulus (logika scraping ada di kitalulus.py)."""

from .registry import SiteSpec, register


def register_kitalulus() -> None:
    from kitalulus import kitalulus_to_records, search_kitalulus

    def fetch(query: str, limit: int) -> list[dict]:
        jobs = search_kitalulus(query=query, limit=limit)
        records = kitalulus_to_records(
            jobs, search_term=query, search_location=None,
            requested_by_chat_id="")

        keluar = []
        for r in records:
            item = {
                "title": r["title"], "url": r["job_url"], "job_id": r["job_id"],
                "location": r["location"], "company": r["company"],
                "job_type": r["job_type"], "job_level": r["job_level"],
                "job_function": r["job_function"], "is_remote": r["is_remote"],
                "description": r["description"],
            }
            for kolom in ("min_amount", "max_amount", "currency", "interval",
                          "salary_source", "raw_salary", "work_arrangement",
                          "employment_type", "experience_range",
                          "company_logo", "listing_type"):
                if r.get(kolom) is not None:
                    item[kolom] = r[kolom]
            keluar.append(item)
        return keluar

    register(SiteSpec(
        name="kitalulus", label="KitaLulus", company="Berbagai perusahaan",
        fetch=fetch,
        industry="Various (job aggregator)",
        company_url="https://www.kitalulus.com",
        enrich=False,
        verified=True, tags={"aggregator", "id"},
        notes="API GraphQL vacanciesV4, ~10.000 loker. Perhatian: field "
              "`page` di respons BUKAN halaman aktif, melainkan total "
              "halaman (ceil(elements/limit)) — paginasi pakai hasNextPage.",
    ))
