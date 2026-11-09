from __future__ import annotations

"""Pendaftaran toploker.com (logika scraping ada di toploker.py)."""

from .registry import SiteSpec, register


def register_toploker() -> None:
    from toploker import toploker_to_records, search_toploker

    def fetch(query: str, limit: int) -> list[dict]:
        jobs = search_toploker(query=query, limit=limit)
        records = toploker_to_records(
            jobs, search_term=query, search_location=None,
            requested_by_chat_id="")

        keluar = []
        for r in records:
            item = {
                "title": r["title"], "url": r["job_url"], "job_id": r["job_id"],
                "location": r["location"], "company": r["company"],
                "job_type": r["job_type"], "job_level": r["job_level"],
                "description": r["description"],
            }
            for kolom in ("employment_type", "work_arrangement",
                          "experience_range", "raw_salary", "listing_type"):
                if r.get(kolom) is not None:
                    item[kolom] = r[kolom]
            keluar.append(item)
        return keluar

    register(SiteSpec(
        name="toploker", label="TopLoker", company="Berbagai perusahaan",
        fetch=fetch,
        industry="Various (job aggregator)",
        company_url="https://toploker.com",
        enrich=False,
        verified=True, tags={"aggregator", "id"},
        notes="Pakai endpoint /rekomendasi/daftar (offset kelipatan 8), "
              "BUKAN /loker/daftar yang diblokir diam-diam. ~11.000 loker "
              "total, tapi offset 0-16 didominasi satu perusahaan "
              "(BukuWarung) -- keragaman baru muncul mulai offset ~24. "
              "Judul kartu SELALU terpotong tampilannya -- judul lengkap "
              "diambil dari slug URL, bukan span tampilan.",
    ))
