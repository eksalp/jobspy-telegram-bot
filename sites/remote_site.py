from __future__ import annotations

"""Pendaftaran We Work Remotely & Remote OK (logika di remote_boards.py)."""

from .registry import SiteSpec, register

_KOLOM_TAMBAHAN = (
    "country", "region", "work_arrangement", "employment_type", "skills",
    "company_logo", "min_amount", "max_amount", "currency", "interval",
    "salary_source", "raw_salary", "job_url_direct",
)


def _bungkus(search, to_records):
    def fetch(query: str, limit: int) -> list[dict]:
        hasil = []
        for r in to_records(search(query=query, limit=limit), query, None, ""):
            item = {k: r.get(k) for k in (
                "title", "url", "job_id", "location", "company", "job_type",
                "job_function", "is_remote", "date_posted", "description")}
            for k in _KOLOM_TAMBAHAN:
                if r.get(k) is not None:
                    item[k] = r[k]
            hasil.append(item)
        return hasil
    return fetch


def register_remote_boards() -> None:
    from remote_boards import (remoteok_to_records, search_remoteok,
                               search_weworkremotely, weworkremotely_to_records)

    register(SiteSpec(
        name="weworkremotely", label="We Work Remotely", company="Berbagai perusahaan",
        fetch=_bungkus(search_weworkremotely, weworkremotely_to_records),
        industry="Various (remote job board)",
        company_url="https://weworkremotely.com",
        enrich=False, verified=True, tags={"remote", "global", "aggregator"},
        notes="RSS resmi; syarat: tautkan kembali ke WWR.",
    ))
    register(SiteSpec(
        name="remoteok", label="Remote OK", company="Berbagai perusahaan",
        fetch=_bungkus(search_remoteok, remoteok_to_records),
        industry="Various (remote job board)",
        company_url="https://remoteok.com",
        enrich=False, verified=True, tags={"remote", "global", "aggregator"},
        notes="API resmi (±100 terbaru); syarat: tautkan ke Remote OK & "
              "sebut sebagai sumber.",
    ))
