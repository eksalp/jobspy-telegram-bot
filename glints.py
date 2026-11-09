from __future__ import annotations

"""
Scraper untuk glints.com (Glints Indonesia).

ARSITEKTUR (hasil investigasi lengkap):
- Endpoint : POST https://glints.com/api/v2-alc/graphql?op=searchJobsV3
- Auth     : Cookie `session=Fe26.2**...` dari browser setelah login
             Tanpa cookie ini, page 2+ ditolak (403 "please login").
- Variables: {"data": {"CountryCode": "ID", "includeExternalJobs": true,
                       "page": N, "pageSize": 30, "SearchTerm": "..."}}
  - "CountryCode" (kapital C dan K) — bukan "countryCode"
  - "includeExternalJobs": true — wajib untuk hasil lengkap
  - Filter negara JUGA via header: x-glints-country-code: ID
- Session cookie disimpan di file GLINTS_SESSION_FILE (default:
  glints_session.txt) — isi dengan value cookie `session` dari browser.

Cara ambil cookie session:
  1. Login di https://glints.com di browser
  2. F12 → Network → filter "searchJobsV3" → scroll halaman explore
  3. Klik request → Headers → cari cookie "session=Fe26.2**..."
  4. Copy value-nya (panjang), simpan ke file glints_session.txt
"""

import json
import os
import re
import time
import unicodedata
from pathlib import Path

import requests

BASE_URL = "https://glints.com"
GRAPHQL_URL = f"{BASE_URL}/api/v2-alc/graphql"
EXPLORE_URL = f"{BASE_URL}/id/en/opportunities/jobs/explore"
PAGE_SIZE = 30

ALL_KEYWORDS = {"all", "semua", "*", ""}

# File tempat menyimpan nilai cookie session Glints
GLINTS_SESSION_FILE = os.environ.get(
    "GLINTS_SESSION_FILE",
    str(Path(__file__).parent / "glints_session.txt"),
)

# Fallback keyword rotation saat tidak ada session (guest mode, max 30/keyword)
BROWSE_ALL_TERMS = [
    "sales", "marketing", "digital marketing", "account executive",
    "telesales", "software engineer", "frontend", "backend", "fullstack",
    "data analyst", "data engineer", "product manager", "ui ux",
    "mobile developer", "devops", "qa engineer", "admin", "operator",
    "staff", "supervisor", "customer service", "accounting", "finance",
    "tax", "audit", "hr", "human resources", "recruiter",
    "logistik", "driver", "kurir", "warehouse", "procurement",
    "guru", "content creator", "graphic design", "copywriter",
    "social media", "engineer", "teknisi", "quality control",
    "chef", "barista", "kasir",
]

HEADERS_HTML = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.5 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en",
}

GQL_QUERY = """
query searchJobsV3($data: JobSearchConditionInput!) {
  searchJobsV3(data: $data) {
    jobsInPage {
      id
      title
      type
      workArrangementOption
      shouldShowSalary
      educationLevel
      minYearsOfExperience
      maxYearsOfExperience
      createdAt
      __DESC__
      isHot
      isApplied
      source
      company {
        id
        name
        brandName
        logo
        industry { id name }
        isVIP
      }
      location {
        id
        formattedName
        level
      }
      hierarchicalJobCategory {
        id
        name
        level
      }
      salaries {
        id
        salaryType
        salaryMode
        minAmount
        maxAmount
        CurrencyCode
      }
      skills {
        skill { id name }
        mustHave
      }
    }
    hasMore
  }
}
"""

# descriptionJsonString (format Draft.js) terbukti ada di tipe Job Glints --
# halaman detail lowongan memuatnya di __NEXT_DATA__ dengan nama yang sama.
# Diminta langsung di searchJobsV3 supaya tidak perlu membuka ±1.200 halaman
# detail satu per satu. Kalau server menolak field ini, _fetch_page otomatis
# jatuh ke query tanpa deskripsi (lihat _DESKRIPSI_DIDUKUNG).
_DESKRIPSI_DIDUKUNG = {"nilai": True}


def _query(dengan_deskripsi: bool) -> str:
    return GQL_QUERY.replace("__DESC__", "descriptionJsonString" if dengan_deskripsi else "")


def draft_ke_teks(raw: str | None) -> str | None:
    """Ubah descriptionJsonString (Draft.js) jadi teks berbaris."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    baris = []
    for blok in data.get("blocks") or []:
        teks = (blok.get("text") or "").strip()
        if not teks:
            continue
        if blok.get("type") in ("unordered-list-item", "ordered-list-item"):
            teks = f"• {teks}"
        baris.append(teks)
    hasil = "\n".join(baris).strip()
    return hasil[:8000] or None


_TIMEOUT = 45


def _is_browse_all(query: str | None) -> bool:
    return (query or "").strip().lower() in ALL_KEYWORDS


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "job"


def _load_session_cookie() -> dict | None:
    """Baca cookie dari file. Return dict {name: value} atau None.

    File bisa berisi:
    - Seluruh string Cookie header dari browser (direkomendasikan):
        device_id=xxx; session=Fe26.2**...; glints_tracking_id=yyy; ...
    - Atau hanya nilai `session` saja (fallback lama).
    """
    try:
        raw = Path(GLINTS_SESSION_FILE).read_text().strip()
        if not raw:
            return None
        # Jika mengandung "=" dan ";" → string cookie header lengkap
        if "=" in raw and ";" in raw:
            cookies = {}
            for part in raw.split(";"):
                part = part.strip()
                if "=" in part:
                    k, _, v = part.partition("=")
                    cookies[k.strip()] = v.strip()
            return cookies if cookies else None
        # Fallback: anggap sebagai nilai session saja
        return {"session": raw}
    except FileNotFoundError:
        return None


def _gql_headers(country: str, page: int = 1) -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/18.5 Mobile/15E148 Safari/604.1"
        ),
        "Accept": "*/*",
        "Accept-Language": "en",
        "Content-Type": "application/json",
        "Origin": BASE_URL,
        "Referer": (
            f"{EXPLORE_URL}?country={country}"
            f"&locationName=All+Cities%2FProvinces&page={page}"
        ),
        "x-glints-country-code": country,
        "sec-ch-ua": '"Chromium";v="152", "Not?A_Brand";v="24", "Google Chrome";v="152"',
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": '"iOS"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "priority": "u=1, i",
    }


def _make_session(country: str, cookies: dict | None) -> requests.Session:
    """Buat requests.Session, inject semua cookie dari file jika ada."""
    sess = requests.Session()

    # Warm-up untuk dapat device_id dan cookie dasar dari server
    try:
        sess.get(
            f"{EXPLORE_URL}?country={country}&locationName=All+Cities%2FProvinces",
            headers=HEADERS_HTML,
            timeout=15,
        )
        time.sleep(0.5)
    except Exception:
        pass

    # Inject semua cookie dari file — override cookie yang sudah ada dari warm-up
    if cookies:
        for name, value in cookies.items():
            sess.cookies.set(name, value, domain="glints.com")
        has_session = "session" in cookies
        print(
            f"[glints] Menggunakan {len(cookies)} cookie dari file "
            f"({'termasuk session ✅' if has_session else 'tanpa session cookie ⚠️'})"
        )
    else:
        print(
            "[glints] ⚠️  Tidak ada cookie — mode guest. "
            f"Simpan Cookie header dari browser ke {GLINTS_SESSION_FILE}"
        )

    return sess


def _fetch_page(
    sess: requests.Session,
    country: str,
    keyword: str,
    page: int,
    seen_ids: set,
) -> tuple[list[dict], bool]:
    """Fetch satu halaman. Return (new_jobs, has_more)."""
    headers = _gql_headers(country, page)
    variables_data: dict = {
        "CountryCode": country,
        "includeExternalJobs": True,
        "page": page,
        "pageSize": PAGE_SIZE,
    }
    if keyword:
        variables_data["SearchTerm"] = keyword

    payload = {
        "operationName": "searchJobsV3",
        "query": _query(_DESKRIPSI_DIDUKUNG["nilai"]),
        "variables": {"data": variables_data},
    }

    for attempt in range(3):
        try:
            resp = sess.post(
                f"{GRAPHQL_URL}?op=searchJobsV3",
                headers=headers,
                json=payload,
                timeout=_TIMEOUT,
            )
            break
        except Exception as e:
            if attempt < 2:
                print(f"[glints] RETRY {attempt+1}/2 page={page} keyword={keyword!r}: {e}")
                time.sleep(3)
            else:
                print(f"[glints] ERROR page={page} keyword={keyword!r}: {e}")
                return [], False

    if resp.status_code == 403:
        msg = resp.json().get("errors", [{}])[0].get("message", "")
        print(f"[glints] 403 page={page} — {msg} (session cookie expired?)")
        return [], False

    if resp.status_code != 200:
        print(f"[glints] HTTP {resp.status_code} page={page}: {resp.text[:120]}")
        return [], False

    data = resp.json()
    if data.get("errors"):
        pesan = data["errors"][0].get("message", "")
        if _DESKRIPSI_DIDUKUNG["nilai"] and "descriptionJsonString" in pesan:
            print("[glints] field descriptionJsonString ditolak server, "
                  "lanjut tanpa deskripsi")
            _DESKRIPSI_DIDUKUNG["nilai"] = False
            return _fetch_page(sess, country, keyword, page, seen_ids)
        print(f"[glints] GQL error: {pesan}")
        return [], False

    sr = (data.get("data") or {}).get("searchJobsV3") or {}
    jobs_raw = sr.get("jobsInPage") or []
    has_more = sr.get("hasMore", False)

    new_jobs = []
    for j in jobs_raw:
        jid = j.get("id")
        if jid and jid not in seen_ids:
            seen_ids.add(jid)
            new_jobs.append(j)

    print(
        f"[glints] keyword={keyword!r:<22} page={page} "
        f"raw={len(jobs_raw)} new={len(new_jobs)} hasMore={has_more}"
    )
    return new_jobs, has_more


def search_glints(
    query: str,
    limit: int = 50,
    location: str | None = None,
    country: str = "ID",
    client_side_filter: bool = True,
) -> list[dict]:
    """Ambil lowongan dari Glints.

    - Dengan session cookie: pagination penuh (page 2, 3, ... sampai hasMore=False)
    - Tanpa session cookie: rotasi keyword (30 hasil per keyword, guest mode)
    """
    keyword = "" if _is_browse_all(query) else query.strip()
    is_all = _is_browse_all(query)

    cookies = _load_session_cookie()
    sess = _make_session(country, cookies)
    seen_ids: set = set()
    jobs: list[dict] = []

    has_session = bool(cookies and "session" in cookies)

    if has_session:
        # Mode login: pagination normal
        terms = [""] if is_all else [keyword]
        for term in terms:
            page = 1
            max_pages = 200 if is_all else 20
            while (not limit or len(jobs) < limit) and page <= max_pages:
                new, has_more = _fetch_page(sess, country, term, page, seen_ids)
                jobs.extend(new)
                if not has_more or (limit and len(jobs) >= limit):
                    break
                page += 1
                time.sleep(0.8)
    else:
        # Mode guest: rotasi keyword
        if is_all:
            terms = BROWSE_ALL_TERMS
        else:
            terms = [keyword]

        for term in terms:
            if limit and len(jobs) >= limit:
                break
            new, _ = _fetch_page(sess, country, term, 1, seen_ids)
            jobs.extend(new)
            time.sleep(1.5)

    # Client-side filter untuk keyword spesifik sebagai jaring pengaman
    if keyword and client_side_filter and jobs:
        needle = keyword.lower()
        filtered = [
            j for j in jobs
            if needle in (j.get("title") or "").lower()
            or needle in (
                (j.get("hierarchicalJobCategory") or {}).get("name") or ""
            ).lower()
            or any(
                needle in (sk.get("skill") or {}).get("name", "").lower()
                for sk in (j.get("skills") or [])
            )
        ]
        if filtered:
            jobs = filtered

    return jobs if (is_all and not limit) else jobs[:limit] if limit else jobs


def glints_to_records(
    jobs: list[dict],
    search_term: str,
    search_location: str | None,
    requested_by_chat_id: str,
) -> list[dict]:
    records = []
    for job in jobs:
        title = job.get("title")
        job_id = job.get("id")
        if not title or not job_id:
            continue

        url = f"{BASE_URL}/id/opportunities/jobs/{_slugify(title)}/{job_id}"

        company = job.get("company") or {}
        company_name = (
            company.get("brandName") or company.get("name") or "Tidak disebutkan"
        )

        loc = job.get("location") or {}
        location_str = loc.get("formattedName") or "Indonesia"

        category = job.get("hierarchicalJobCategory") or {}
        category_name = category.get("name")

        skill_names = [
            (sk.get("skill") or {}).get("name", "")
            for sk in (job.get("skills") or [])
            if (sk.get("skill") or {}).get("name")
        ]

        basic_salaries = [
            s for s in (job.get("salaries") or [])
            if s.get("salaryType") == "BASIC"
        ]
        min_amount = max_amount = currency = interval = raw_salary = None
        if basic_salaries and job.get("shouldShowSalary"):
            s = basic_salaries[0]
            min_amount = s.get("minAmount")
            max_amount = s.get("maxAmount")
            currency = s.get("CurrencyCode")
            interval = {
                "MONTH": "monthly", "YEAR": "yearly",
                "DAY": "daily", "HOUR": "hourly",
            }.get(s.get("salaryMode"), "monthly")
            if min_amount is not None and max_amount is not None:
                raw_salary = f"{currency} {min_amount:,.0f} - {max_amount:,.0f}"

        work_arrangement_raw = job.get("workArrangementOption")
        work_arrangement = {
            "ONSITE": "onsite", "HYBRID": "hybrid", "REMOTE": "remote",
        }.get(work_arrangement_raw)

        # Nilai harus sama dengan standar kolom employment_type yang dibaca
        # filter Jobly: full-time | kontrak | freelance | magang | part-time.
        employment_type = {
            "FULL_TIME": "full-time", "PART_TIME": "part-time",
            "CONTRACT": "kontrak", "INTERNSHIP": "magang",
            "PROJECT_BASED": "freelance", "FREELANCE": "freelance",
            "DAILY": "kontrak",
        }.get(job.get("type"), "full-time")

        date_posted = (job.get("createdAt") or "")[:10] or None

        records.append({
            "job_id": str(job_id),
            "site": "glints",
            "job_url": url,
            "job_url_direct": url,
            "title": str(title),
            "company": str(company_name),
            "location": location_str,
            "date_posted": date_posted,
            "job_type": job.get("type"),
            "salary_source": "glints" if min_amount is not None else None,
            "interval": interval,
            "min_amount": min_amount,
            "max_amount": max_amount,
            "currency": currency,
            "is_remote": work_arrangement_raw == "REMOTE" if work_arrangement_raw else None,
            "job_level": job.get("educationLevel"),
            "job_function": category_name,
            "listing_type": None,
            "emails": None,
            "description": draft_ke_teks(job.get("descriptionJsonString")),
            "company_industry": (company.get("industry") or {}).get("name"),
            "company_url": BASE_URL,
            "company_logo": company.get("logo"),
            "company_url_direct": None,
            "company_addresses": None,
            "company_num_employees": None,
            "company_revenue": None,
            "company_description": None,
            "skills": ", ".join(skill_names) or None,
            "experience_range": (
                f"{job.get('minYearsOfExperience')}-{job.get('maxYearsOfExperience')} tahun"
                if job.get("minYearsOfExperience") is not None else None
            ),
            "company_rating": None,
            "company_reviews_count": None,
            "vacancy_count": None,
            "work_from_home_type": None,
            "raw_salary": raw_salary,
            "category": category_name,
            "work_arrangement": work_arrangement,
            "employment_type": employment_type,
            "search_term": search_term or "scrapeall",
            "search_location": search_location or location_str,
            "requested_by_chat_id": str(requested_by_chat_id),
        })
    return records


if __name__ == "__main__":
    import sys

    raw = search_glints("semua", limit=90)
    if not raw:
        sys.exit("Tidak ada data.")

    print(f"\n✅ Total: {len(raw)} lowongan unik\n")
    print("Hasil pemetaan (10 pertama):")
    for rec in list(glints_to_records(raw, "semua", None, "test"))[:10]:
        print(
            f"  {rec['title'][:38]:<40} | {rec['company'][:22]:<24} | "
            f"{rec['location'][:18]:<20} | {rec['work_arrangement'] or '-':<8} | "
            f"{rec['min_amount'] or '-'}"
        )