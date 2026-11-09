from __future__ import annotations

"""Pendaftaran MAGENTA (logika scraping ada di magenta.py)."""

from .registry import SiteSpec, register


def register_magenta() -> None:
    from magenta import magenta_to_records, search_magenta

    def fetch(query: str, limit: int) -> list[dict]:
        jobs = search_magenta(query=query, limit=limit)
        records = magenta_to_records(
            jobs, search_term=query, search_location=None,
            requested_by_chat_id="")
        keluar = []
        for r in records:
            item = {
                "title": r["title"], "url": r["job_url"], "job_id": r["job_id"],
                "location": r["location"], "company": r["company"],
                "job_type": r["job_type"], "is_remote": r["is_remote"],
                "description": r["description"],
            }
            for kolom in ("employment_type", "work_arrangement",
                          "vacancy_count", "work_from_home_type",
                          "company_addresses", "job_url_direct"):
                if r.get(kolom) is not None:
                    item[kolom] = r[kolom]
            keluar.append(item)
        return keluar

    register(SiteSpec(
        name="magenta", label="MAGENTA (Magang BUMN)",
        company="BUMN dan anak usaha",
        fetch=fetch,
        industry="Government (program magang BUMN)",
        company_url="https://magentaku.id",
        # Kartu listing sudah lengkap; tidak ada halaman detail per lowongan.
        enrich=False,
        verified=True, tags={"aggregator", "magang", "bumn", "id", "pemerintah"},
        notes="Magang BUMN. Kartu tidak punya URL detail, jadi job_id dari "
              "hash judul+perusahaan.",
    ))
