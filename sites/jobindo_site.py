from __future__ import annotations

"""Pendaftaran jobindo.com (logika scraping ada di jobindo.py)."""

from .registry import SiteSpec, register


def register_jobindo() -> None:
    from jobindo import jobindo_to_records, search_jobindo

    def fetch(query: str, limit: int) -> list[dict]:
        jobs = search_jobindo(query=query, limit=limit)
        records = jobindo_to_records(
            jobs, search_term=query, search_location=None,
            requested_by_chat_id="")

        keluar = []
        for r in records:
            item = {
                "title": r["title"], "url": r["job_url"], "job_id": r["job_id"],
                "location": r["location"], "company": r["company"],
                "job_type": r["job_type"], "job_level": r["job_level"],
                "job_function": r["job_function"], "is_remote": r["is_remote"],
                "date_posted": r["date_posted"], "description": r["description"],
            }
            for kolom in ("min_amount", "max_amount", "currency", "interval",
                          "salary_source", "raw_salary", "work_arrangement",
                          "employment_type", "experience_range",
                          "company_logo", "company_url_direct", "job_url_direct",
                          "company_url",
                          "company_addresses", "company_description"):
                if r.get(kolom) is not None:
                    item[kolom] = r[kolom]
            keluar.append(item)
        return keluar

    register(SiteSpec(
        name="jobindo", label="Jobindo", company="Berbagai perusahaan",
        fetch=fetch,
        industry="Various (job aggregator)",
        company_url="https://jobindo.com",
        # API sudah kasih deskripsi & kualifikasi lengkap.
        enrich=False,
        verified=True, tags={"aggregator", "id"},
        notes="API Inertia.js partial-reload, ~197 loker. Butuh "
              "x-inertia-version yang dibaca otomatis dari HTML tiap "
              "request pertama (lihat _ambil_versi_inertia di jobindo.py).",
    ))
