from __future__ import annotations

"""Pendaftaran JobStreet (logika scraping ada di jobstreet.py)."""

from .registry import SiteSpec, register


def register_jobstreet() -> None:
    from jobstreet import jobstreet_to_records, search_jobstreet

    def fetch(query: str, limit: int) -> list[dict]:
        jobs = search_jobstreet(query=query, limit=limit)
        records = jobstreet_to_records(
            jobs, search_term=query, search_location=None,
            requested_by_chat_id="")
        return [{
            "title": r["title"], "url": r["job_url"], "job_id": r["job_id"],
            "location": r["location"], "company": r["company"],
            "description": r["description"], "job_function": r["job_function"],
            "job_type": r["job_type"], "date_posted": r["date_posted"],
            # Field ini sudah dihitung dengan benar oleh jobstreet_to_records
            # (parsing salaryLabel, dan hint work_arrangement dari
            # workArrangements.data). Tanpa ini, registry.run() akan
            # menghitung ulang dari nol dengan is_remote=None dan salary
            # selalu kosong — informasi yang sudah didapat dari API akan
            # terbuang percuma.
            "salary_source": r["salary_source"],
            "interval": r["interval"],
            "min_amount": r["min_amount"],
            "max_amount": r["max_amount"],
            "currency": r["currency"],
            "raw_salary": r["raw_salary"],
            "work_arrangement": r["work_arrangement"],
            "employment_type": r["employment_type"],
            "category": r["category"],
        } for r in records]

    register(SiteSpec(
        name="jobstreet", label="JobStreet", company="Berbagai perusahaan",
        fetch=fetch,
        industry="Various (job aggregator)",
        company_url="https://id.jobstreet.com",
        # Halaman lowongannya diblokir bot detection, jadi pengayaan HTML
        # pasti gagal. Data dari API sudah cukup lengkap.
        enrich=False,
        tags={"aggregator", "id"},
        notes="API SEEK jobsearch v5 (dipindah dari chalice-search v4 yang "
              "dipensiunkan SEEK); skema hasil rekayasa balik.",
    ))