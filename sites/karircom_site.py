from __future__ import annotations

"""Pendaftaran karir.com (logika scraping ada di karircom.py)."""

from .registry import SiteSpec, register


def register_karircom() -> None:
    from karircom import karircom_to_records, search_karircom

    def fetch(query: str, limit: int) -> list[dict]:
        jobs = search_karircom(query=query, limit=limit)
        records = karircom_to_records(
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
                          "employment_type", "work_from_home_type",
                          "company_logo", "listing_type", "company_description"):
                if r.get(kolom) is not None:
                    item[kolom] = r[kolom]
            keluar.append(item)
        return keluar

    register(SiteSpec(
        name="karircom", label="Karir.com", company="Berbagai perusahaan",
        fetch=fetch,
        industry="Various (job aggregator)",
        company_url="https://karir.com",
        enrich=False,
        verified=True, tags={"aggregator", "id"},
        notes="API v2/search/opportunities. URL lowongan (/lowongan/{id}) "
              "belum diverifikasi buka langsung — cek kalau ada laporan 404.",
    ))
