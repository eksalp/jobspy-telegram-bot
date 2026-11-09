from __future__ import annotations

"""Pendaftaran Kalibrr (logika scraping ada di kalibrr.py)."""

from .registry import SiteSpec, register


def register_kalibrr() -> None:
    from kalibrr import kalibrr_to_records, search_kalibrr

    def fetch(query: str, limit: int) -> list[dict]:
        jobs = search_kalibrr(query=query, limit=limit)
        records = kalibrr_to_records(
            jobs, search_term=query, search_location=None,
            requested_by_chat_id="")
        # Semua kolom diteruskan; yang di luar KNOWN_KEYS masuk lewat
        # extra_fields di registry dan menimpa default make_record.
        keluar = []
        for r in records:
            item = {
                "title": r["title"], "url": r["job_url"], "job_id": r["job_id"],
                "location": r["location"], "company": r["company"],
                "job_type": r["job_type"], "job_level": r["job_level"],
                "job_function": r["job_function"],
                "date_posted": r["date_posted"],
                "is_remote": r["is_remote"], "description": r["description"],
            }
            for kolom in (
                "min_amount", "max_amount", "currency", "interval",
                "salary_source", "raw_salary", "work_arrangement",
                "employment_type", "experience_range", "work_from_home_type",
                "skills", "vacancy_count", "company_logo", "listing_type",
                "company_description", "company_addresses", "category",
            ):
                if r.get(kolom) is not None:
                    item[kolom] = r[kolom]
            keluar.append(item)
        return keluar

    register(SiteSpec(
        name="kalibrr", label="Kalibrr", company="Berbagai perusahaan",
        fetch=fetch,
        industry="Various (job aggregator)",
        company_url="https://kalibrr.id",
        # API-nya sudah mengembalikan deskripsi dan kualifikasi utuh.
        enrich=False,
        verified=True, tags={"aggregator", "id"},
        notes="API kjs/job_board/search, ~1180 loker. Deskripsi, kualifikasi, "
              "skill, dan gaji lengkap.",
    ))
