from __future__ import annotations

"""Pendaftaran Glints (logika scraping ada di glints.py)."""

from .registry import SiteSpec, register


def register_glints() -> None:
    from glints import glints_to_records, search_glints

    def fetch(query: str, limit: int) -> list[dict]:
        jobs = search_glints(query=query, limit=limit)
        records = glints_to_records(
            jobs, search_term=query, search_location=None,
            requested_by_chat_id="")
        return [{
            "title": r["title"], "url": r["job_url"], "job_id": r["job_id"],
            "location": r["location"], "company": r["company"],
            "description": r["description"], "job_function": r["job_function"],
            "job_type": r["job_type"], "date_posted": r["date_posted"],
            "is_remote": r["is_remote"],
            # Field ini sudah dihitung dengan benar oleh glints_to_records
            # (workArrangementOption eksplisit dari Glints, bukan tebakan;
            # salary dari JobSalary bertipe BASIC). Diteruskan supaya
            # registry.run() tidak menghitung ulang dari nol dengan info
            # yang lebih sedikit — lihat catatan yang sama di jobstreet_site.py.
            "salary_source": r["salary_source"],
            "interval": r["interval"],
            "min_amount": r["min_amount"],
            "max_amount": r["max_amount"],
            "currency": r["currency"],
            "raw_salary": r["raw_salary"],
            "work_arrangement": r["work_arrangement"],
            "employment_type": r["employment_type"],
            "category": r["category"],
            "skills": r["skills"],
            "job_level": r["job_level"],
            "experience_range": r["experience_range"],
            "company_logo": r["company_logo"],
        } for r in records]

    register(SiteSpec(
        name="glints", label="Glints", company="Berbagai perusahaan",
        fetch=fetch,
        industry="Various (job aggregator)",
        company_url="https://glints.com/id",
        # Deskripsi lowongan tidak ada di data listing (SSR explore page),
        # cuma di halaman detail per-job — tapi halaman itu kemungkinan
        # butuh request tambahan per lowongan (mahal). Dibiarkan mati dulu;
        # bisa dinyalakan lagi kalau butuh deskripsi lengkap dan willing
        # menanggung request tambahan.
        enrich=False,
        verified=True,
        tags={"aggregator", "id"},
        notes=(
            "Data diambil dari __NEXT_DATA__ (Apollo GraphQL cache) yang "
            "di-render server di halaman explore, BUKAN dari endpoint API "
            "terpisah. Filter kata kunci sudah dites & terkonfirmasi jalan "
            "di server (dipetakan ke variabel GraphQL 'SearchTerm'). Butuh "
            "tls_client terpasang — Glints mendiamkan koneksi 'requests' "
            "polos, sama seperti JobStreet."
        ),
    ))