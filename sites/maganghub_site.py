from __future__ import annotations

"""Pendaftaran MagangHub Kemnaker (logika scraping ada di maganghub.py)."""

from .registry import SiteSpec, register


def register_maganghub() -> None:
    from maganghub import maganghub_to_records, search_maganghub

    def fetch(query: str, limit: int) -> list[dict]:
        # Jeda dilonggarkan saat penarikan besar.
        delay = 0.5 if limit > 2000 else 0.3
        # `lanjutkan=True`: tiap jalan meneruskan halaman terakhir yang
        # berhasil, jadi katalog 22.600 lowongan bisa dicicil dengan
        # /scrapeall rutin alih-alih satu proses 45 menit.
        jobs = search_maganghub(query=query, limit=limit, delay=delay,
                                lanjutkan=True)
        records = maganghub_to_records(
            jobs, search_term=query, search_location=None,
            requested_by_chat_id="")
        keluar = []
        for r in records:
            item = {
                "title": r["title"], "url": r["job_url"], "job_id": r["job_id"],
                "location": r["location"], "company": r["company"],
                "job_type": r["job_type"], "job_level": r["job_level"],
                "job_function": r["job_function"], "is_remote": False,
                "description": r["description"],
            }
            for kolom in ("employment_type", "work_arrangement",
                          "vacancy_count", "experience_range",
                          "work_from_home_type", "company_addresses"):
                if r.get(kolom) is not None:
                    item[kolom] = r[kolom]
            keluar.append(item)
        return keluar

    register(SiteSpec(
        name="maganghub", label="MagangHub Kemnaker",
        company="Berbagai penyelenggara",
        fetch=fetch,
        industry="Government (program magang)",
        company_url="https://maganghub.kemnaker.go.id",
        # Kartu listing sudah memuat semua yang kita butuhkan.
        enrich=False,
        verified=True, tags={"aggregator", "magang", "id", "pemerintah"},
        notes="Program magang nasional Kemnaker. Satu-satunya sumber dengan "
              "data kuota dan jumlah pelamar.",
    ))
