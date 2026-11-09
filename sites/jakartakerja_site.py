from __future__ import annotations

"""Pendaftaran jakartakerja.com (logika scraping ada di jakartakerja.py)."""

from .registry import SiteSpec, register


def register_jakartakerja() -> None:
    from jakartakerja import jakartakerja_to_records, search_jakartakerja

    def fetch(query: str, limit: int) -> list[dict]:
        jobs = search_jakartakerja(query=query, limit=limit)
        records = jakartakerja_to_records(
            jobs, search_term=query, search_location=None,
            requested_by_chat_id="")
        keluar = []
        for r in records:
            item = {
                "title": r["title"], "url": r["job_url"], "job_id": r["job_id"],
                "location": r["location"], "company": r["company"],
                "job_type": r["job_type"], "is_remote": r["is_remote"],
                "date_posted": r["date_posted"], "description": r["description"],
            }
            for kolom in ("min_amount", "max_amount", "currency", "interval",
                          "salary_source", "raw_salary", "work_arrangement",
                          "employment_type", "company_logo", "company_url",
                          "company_addresses"):
                if r.get(kolom) is not None:
                    item[kolom] = r[kolom]
            keluar.append(item)
        return keluar

    register(SiteSpec(
        name="jakartakerja", label="JakartaKerja", company="Berbagai perusahaan",
        fetch=fetch,
        industry="Various (job aggregator)",
        company_url="https://www.jakartakerja.com",
        # Detail lengkap sudah diambil dari JSON-LD JobPosting.
        enrich=False,
        verified=True, tags={"aggregator", "id"},
        notes="Daftar dari /page/N/, detail dari JSON-LD JobPosting. "
              "Lowongan yang validThrough-nya lewat dibuang.",
    ))
