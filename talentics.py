from __future__ import annotations

"""
Scraper untuk jobs.talentics.id (ATS dipakai BFI Finance, Bank Syariah
Nasional, AHP Law Firm, dst). robots.txt mengizinkan semua akses.

VERSI LAMA memakai Playwright dengan selector tebakan yang tidak pernah
dicocokkan dengan situs aslinya. Kartu lowongannya bukan link, jadi semua
lowongan mendapat URL halaman daftar yang sama -> job_id kembar -> dibuang
saat dedup sampai tersisa SATU lowongan saja (padahal katalognya ±1.500).

VERSI INI memakai API JSON yang dipanggil halaman itu sendiri:

    GET https://jobs.talentics.id/ajaxs/jobs?page=N
    -> paginator Laravel: current_page, last_page, per_page (10), total,
       data: [{job_id, title, slug, organization{slug,...},
               organization_name, level, workplace, type, job_locations,
               location, due_date, published_at, redirect_url, ...}]

API ini menolak (401) panggilan tanpa sesi. Polanya Laravel standar: buka
halaman /jobs sekali dengan requests.Session untuk mendapat cookie
`talentics_session` + `XSRF-TOKEN`, lalu kirim token CSRF di header
(X-CSRF-TOKEN dari <meta name="csrf-token"> dan/atau X-XSRF-TOKEN dari
cookie). Tidak butuh Playwright.

Link lowongan: https://jobs.talentics.id/{organization.slug}/{slug}
Deskripsi: tidak ada di API daftar; diambil dari halaman detail di bawah
judul "Job Description" (lihat _ambil_deskripsi). Kalau halaman detail
ternyata dirender JavaScript dan teksnya tidak ada di HTML, deskripsi
dibiarkan kosong -- tidak mengarang.
"""

import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://jobs.talentics.id"
LIST_URL = f"{BASE_URL}/jobs"
API_URL = f"{BASE_URL}/ajaxs/jobs"

ALL_KEYWORDS = {"all", "semua", "*", ""}
MAKS_HALAMAN = 400        # pengaman; saat ditulis 150 halaman @ 10
JEDA = 0.3                # detik antar halaman API
AMBIL_DESKRIPSI = True
DETAIL_PARALEL = 4

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# `type` di API. Hanya yang sudah dipastikan dari data nyata yang dipetakan
# (kartu dengan type=3 tampil sebagai "Karyawan Kontrak"); sisanya dibiarkan
# ke klasifikasi otomatis dari judul.
_TIPE = {3: "kontrak"}

_WORKPLACE = {
    "wfo": "onsite", "work from office": "onsite", "onsite": "onsite",
    "wfh": "remote", "work from home": "remote", "remote": "remote",
    "hybrid": "hybrid",
}


def _sesi() -> tuple[requests.Session, dict]:
    """Buka /jobs sekali untuk mendapat cookie sesi + token CSRF."""
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "id-ID,id;q=0.9,en;q=0.8"})
    r = s.get(LIST_URL, timeout=30)
    r.raise_for_status()

    headers = {
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": LIST_URL,
    }
    m = re.search(r'<meta[^>]+name="csrf-token"[^>]+content="([^"]+)"', r.text) \
        or re.search(r'<meta[^>]+content="([^"]+)"[^>]+name="csrf-token"', r.text)
    if m:
        headers["X-CSRF-TOKEN"] = m.group(1)
    xsrf = s.cookies.get("XSRF-TOKEN")
    if xsrf:
        headers["X-XSRF-TOKEN"] = unquote(xsrf)
    return s, headers


def _is_browse_all(query: str | None) -> bool:
    return (query or "").strip().lower() in ALL_KEYWORDS


def search_talentics(query: str, limit: int = 2000) -> list[dict]:
    keyword = "" if _is_browse_all(query) else query.strip().lower()
    sesi, headers = _sesi()

    jobs: list[dict] = []
    seen: set = set()
    halaman, terakhir = 1, None
    while halaman <= MAKS_HALAMAN and len(jobs) < limit:
        r = sesi.get(API_URL, params={"page": halaman}, headers=headers, timeout=30)
        if r.status_code in (401, 419) and halaman == 1:
            raise RuntimeError(
                f"API Talentics menolak sesi (HTTP {r.status_code}). Cara "
                "situsnya membagikan token mungkin berubah.")
        r.raise_for_status()
        data = r.json()
        batch = data.get("data") or []
        if not batch:
            break
        for job in batch:
            jid = job.get("job_id") or job.get("id")
            if jid in seen:
                continue
            seen.add(jid)
            if keyword and keyword not in (job.get("title") or "").lower() \
                    and keyword not in (job.get("organization_name") or "").lower():
                continue
            jobs.append(job)
        terakhir = data.get("last_page") or terakhir
        if terakhir and halaman >= terakhir:
            break
        halaman += 1
        time.sleep(JEDA)

    jobs = jobs[:limit]
    if AMBIL_DESKRIPSI and jobs:
        with ThreadPoolExecutor(max_workers=DETAIL_PARALEL) as pool:
            for job, desk in zip(jobs, pool.map(lambda j: _ambil_deskripsi(sesi, j), jobs)):
                job["_deskripsi"] = desk
    return jobs


def _url(job: dict) -> str | None:
    org = (job.get("organization") or {}).get("slug")
    slug = job.get("slug")
    if org and slug:
        return f"{BASE_URL}/{org}/{slug}"
    return None


_PENANDA_AKHIR = re.compile(
    r"\n\s*(Similar Jobs|Other Jobs|Lowongan Lain|Share|Bagikan|"
    r"Apply Now|Lamar Sekarang|Back to Job List|Kebijakan Privasi|"
    r"Privacy Policy)\s*(\n|$)", re.I)


def _ambil_deskripsi(sesi: requests.Session, job: dict) -> str | None:
    url = _url(job)
    if not url:
        return None
    try:
        r = sesi.get(url, timeout=30)
        if r.status_code != 200:
            return None
    except Exception:  # noqa: BLE001
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    for buang in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        buang.decompose()
    teks = soup.get_text("\n")
    teks = re.sub(r"[ \t]+", " ", teks)
    teks = re.sub(r"\n\s*\n+", "\n", teks)
    i = teks.find("Job Description")
    if i < 0:
        return None
    isi = teks[i + len("Job Description"):]
    m = _PENANDA_AKHIR.search(isi)
    if m:
        isi = isi[:m.start()]
    isi = isi.strip()
    return isi[:8000] if len(isi) >= 40 else None


def _lokasi(job: dict) -> str:
    daftar = [l.get("location") for l in (job.get("job_locations") or [])
              if l.get("location")]
    utama = daftar[0] if daftar else (job.get("location") or "")
    utama = re.sub(r"\s*\(Indonesia\)", "", utama).strip(" ,")
    if len(daftar) > 1:
        utama = f"{utama} (+{len(daftar) - 1} lokasi lain)"
    return utama or "Indonesia"


def talentics_to_records(
    jobs: list[dict],
    search_term: str,
    search_location: str | None,
    requested_by_chat_id: str,
) -> list[dict]:
    from categorize import classify_employment_type, classify_job, classify_work_arrangement

    records = []
    for job in jobs:
        url = _url(job)
        title = (job.get("title") or "").strip()
        jid = job.get("job_id") or job.get("id")
        if not url or not title or jid is None:
            continue

        lokasi = _lokasi(job)
        level = job.get("level") or None
        wp_teks = (job.get("workplace") or "").lower()
        work_arrangement = next(
            (v for k, v in _WORKPLACE.items() if k in wp_teks), None)
        tipe = _TIPE.get(job.get("type"))

        desk = job.get("_deskripsi")
        batas = (job.get("due_date") or "")[:10]
        if batas:
            desk = f"Batas lamar: {batas}\n{desk}" if desk else f"Batas lamar: {batas}"

        records.append({
            "job_id": str(jid),
            "site": "talentics",
            "job_url": url,
            "job_url_direct": job.get("redirect_url") or url,
            "title": title,
            "company": job.get("organization_name") or "Tidak disebutkan",
            "location": lokasi,
            "date_posted": (job.get("published_at") or job.get("created_at") or "")[:10] or None,
            "job_type": tipe,
            "is_remote": work_arrangement == "remote" if work_arrangement else None,
            "job_level": level,
            "job_function": None,
            "description": desk,
            "experience_range": level,
            "category": classify_job(title, search_term),
            "work_arrangement": work_arrangement or classify_work_arrangement(
                None, title, lokasi),
            "employment_type": tipe or classify_employment_type(None, title, level),
            "company_url": f"{BASE_URL}/{(job.get('organization') or {}).get('slug', '')}".rstrip("/"),
            "search_term": search_term,
            "search_location": search_location or lokasi,
            "requested_by_chat_id": str(requested_by_chat_id),
        })
    return records
