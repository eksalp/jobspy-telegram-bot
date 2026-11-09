from __future__ import annotations

"""Pendaftaran Karirhub Kemnaker (logika scraping ada di karirhub.py)."""

from .registry import SiteSpec, register


def register_karirhub() -> None:
    from karirhub import karirhub_to_records, search_karirhub

    def fetch(query: str, limit: int) -> list[dict]:
        jobs = search_karirhub(query=query, limit=limit)
        records = karirhub_to_records(
            jobs, search_term=query, search_location=None,
            requested_by_chat_id="")

        keluar = []
        for r in records:
            item = {
                "title": r["title"], "url": r["job_url"], "job_id": r["job_id"],
                "location": r["location"], "company": r["company"],
                "description": r["description"],
            }
            for kolom in ("min_amount", "max_amount", "currency", "interval",
                          "salary_source", "raw_salary", "vacancy_count",
                          "work_arrangement", "employment_type"):
                if r.get(kolom) is not None:
                    item[kolom] = r[kolom]
            keluar.append(item)
        return keluar

    register(SiteSpec(
        name="karirhub", label="Karirhub Kemnaker",
        company="Berbagai perusahaan (agregator Kemnaker)",
        fetch=fetch,
        industry="Government (job aggregator)",
        company_url="https://karirhub.kemnaker.go.id",
        enrich=False,
        verified=True, tags={"aggregator", "id", "pemerintah"},
        notes="Mirror dari KitaLulus dan sumber lain — kartunya eksplisit "
              "menyebut 'Lowongan dari Kitalulus'. Bukan pemasang langsung.",
    ))
