from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import pandas as pd
from jobspy import scrape_jobs

import config
from categorize import classify_job, classify_work_arrangement, classify_employment_type


def _clean_value(value: Any) -> Any:
    """Bikin value siap dikirim sebagai JSON ke Supabase (NaN -> None, dll)."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (pd.Timestamp,)):
        if pd.isna(value):
            return None
        return value.date().isoformat()
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value) if value else None
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def run_search(
    search_term: str,
    location: str | None = None,
    sites: list[str] | None = None,
    country_indeed: str | None = None,
    results_wanted: int | None = None,
    hours_old: int | None = None,
    is_remote: bool = False,
) -> pd.DataFrame:
    """Jalankan jobspy.scrape_jobs dengan default dari config kalau tidak dikasih."""
    return scrape_jobs(
        site_name=sites or config.DEFAULT_SITES,
        search_term=search_term,
        google_search_term=search_term,
        location=location or config.DEFAULT_LOCATION,
        country_indeed=country_indeed or config.DEFAULT_COUNTRY_INDEED,
        results_wanted=results_wanted or config.DEFAULT_RESULTS_WANTED,
        hours_old=hours_old or config.DEFAULT_HOURS_OLD,
        is_remote=is_remote,
    )


def df_to_records(
    df: pd.DataFrame,
    search_term: str,
    search_location: str,
    requested_by_chat_id: str,
    is_remote_filter: bool = False,
) -> list[dict]:
    """Ubah DataFrame hasil jobspy jadi list of dict yang siap di-upsert ke tabel `jobs`.
    `is_remote_filter` = True kalau user eksplisit pakai --remote saat search - kalau
    begitu, semua hasil dianggap PASTI remote (situsnya udah filter), jadi klasifikasi
    work arrangement nggak nebak-nebak dari field per-job yang kadang kosong/null.
    """
    if df is None or df.empty:
        return []

    records: list[dict] = []
    for row in df.to_dict(orient="records"):
        cleaned = {k: _clean_value(v) for k, v in row.items()}

        job_id = cleaned.get("id")
        job_url = cleaned.get("job_url")
        if not job_id:
            # fallback: pakai job_url sebagai job_id kalau situsnya tidak kasih id unik
            job_id = job_url

        record = {
            "job_id": job_id,
            "site": cleaned.get("site"),
            "job_url": job_url,
            "job_url_direct": cleaned.get("job_url_direct"),
            "title": cleaned.get("title"),
            "company": cleaned.get("company"),
            "location": cleaned.get("location"),
            "date_posted": cleaned.get("date_posted"),
            "job_type": cleaned.get("job_type"),
            "salary_source": cleaned.get("salary_source"),
            "interval": cleaned.get("interval"),
            "min_amount": cleaned.get("min_amount"),
            "max_amount": cleaned.get("max_amount"),
            "currency": cleaned.get("currency"),
            "is_remote": cleaned.get("is_remote"),
            "job_level": cleaned.get("job_level"),
            "job_function": cleaned.get("job_function"),
            "listing_type": cleaned.get("listing_type"),
            "emails": cleaned.get("emails"),
            "description": cleaned.get("description"),
            "company_industry": cleaned.get("company_industry"),
            "company_url": cleaned.get("company_url"),
            "company_logo": cleaned.get("company_logo"),
            "company_url_direct": cleaned.get("company_url_direct"),
            "company_addresses": cleaned.get("company_addresses"),
            "company_num_employees": cleaned.get("company_num_employees"),
            "company_revenue": cleaned.get("company_revenue"),
            "company_description": cleaned.get("company_description"),
            "skills": cleaned.get("skills"),
            "experience_range": cleaned.get("experience_range"),
            "company_rating": cleaned.get("company_rating"),
            "company_reviews_count": cleaned.get("company_reviews_count"),
            "vacancy_count": cleaned.get("vacancy_count"),
            "work_from_home_type": cleaned.get("work_from_home_type"),
            "raw_salary": None,
            "category": classify_job(
                cleaned.get("title"), cleaned.get("skills"), search_term
            ),
            "work_arrangement": classify_work_arrangement(
                True if is_remote_filter else cleaned.get("is_remote"),
                cleaned.get("title"), cleaned.get("job_type"),
                cleaned.get("location"), cleaned.get("description"),
            ),
            "employment_type": classify_employment_type(
                cleaned.get("job_type"), cleaned.get("title"), cleaned.get("description"),
            ),
            "search_term": search_term,
            "search_location": search_location,
            "requested_by_chat_id": str(requested_by_chat_id),
        }
        records.append(record)

    return records
