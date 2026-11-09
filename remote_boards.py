from __future__ import annotations

"""
Lowongan remote internasional dari dua sumber yang MENYEDIAKAN FEED RESMI:

1. We Work Remotely  -- RSS publik
   https://weworkremotely.com/remote-jobs.rss  (+ feed per kategori)
   Syarat dari halaman https://weworkremotely.com/remote-job-rss-feed:
   "all we ask is that you attribute the links back to We Work Remotely."
   -> job_url selalu link WWR asli, site = "weworkremotely".

2. Remote OK  -- API JSON publik  https://remoteok.com/api
   Elemen PERTAMA array adalah pemberitahuan legal, sisanya lowongan.
   Syaratnya: tautkan kembali ke URL lowongan di Remote OK (link biasa,
   bukan nofollow) dan sebut "Remote OK" sebagai sumber; jangan pakai
   logonya tanpa izin. -> job_url selalu URL Remote OK, deskripsi diawali
   "Sumber: Remote OK", dan logo Remote OK sendiri tidak dipakai (logo
   PERUSAHAAN dari field company_logo boleh). Satu request mengembalikan
   ±100 lowongan terbaru; API mengabaikan paginasi.

Situs lain di daftar yang SENGAJA tidak diambil:
- Wellfound: memasang DataDome khusus untuk memblokir scraper lowongan.
- LinkedIn: robots.txt melarang akses otomatis; sudah tersedia lewat
  JobSpy (/update ... --sites linkedin --remote) tanpa deskripsi.
- Toptal: bukan papan lowongan, melainkan jaringan freelancer terseleksi
  (daftar & lolos seleksi dulu); tidak ada daftar lowongan publik.

Semua lowongan dari dua sumber ini remote, jadi region diisi "remote".
Negara diisi hanya kalau lokasinya jelas menyebut Indonesia; selebihnya
(Worldwide, USA Only, Europe, ...) dibiarkan kosong. Teks lokasi aslinya
tetap disimpan apa adanya supaya pencari kerja bisa melihat batasan negara
(mis. "USA Only" biasanya mensyaratkan izin kerja di AS).
"""

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

WWR_FEED = "https://weworkremotely.com/remote-jobs.rss"
WWR_KATEGORI = [
    "remote-customer-support-jobs", "remote-product-jobs",
    "remote-full-stack-programming-jobs", "remote-back-end-programming-jobs",
    "remote-front-end-programming-jobs", "remote-programming-jobs",
    "remote-sales-and-marketing-jobs", "remote-management-and-finance-jobs",
    "remote-design-jobs", "remote-devops-sysadmin-jobs", "all-other-remote-jobs",
]
REMOTEOK_API = "https://remoteok.com/api"

ALL_KEYWORDS = {"all", "semua", "*", ""}

_HEADERS = {
    # Generik: jangan pernah menaruh email/identitas pribadi di sini.
    "User-Agent": "JobFinderBot/1.0 (+aggregator lowongan untuk pencari kerja)",
    "Accept": "application/rss+xml, application/xml, application/json, */*",
}

_TIPE = {
    "full-time": "full-time", "full time": "full-time",
    "part-time": "part-time", "part time": "part-time",
    "contract": "kontrak", "contractor": "kontrak",
    "freelance": "freelance", "internship": "magang",
}


def _get(url: str, retries: int = 3, timeout: int = 30):
    """GET polos dengan header sendiri.

    SENGAJA tidak memakai sites.base.http_get: fungsi itu menggabungkan
    header navigasi browser (Sec-Fetch-Dest: document, dst) yang terbukti
    membuat API JSON menolak request (kasus web3.career dulu).
    """
    import requests

    terakhir = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001
            terakhir = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"Gagal GET {url}: {terakhir}")


def _is_browse_all(q: str | None) -> bool:
    return (q or "").strip().lower() in ALL_KEYWORDS


def _bersih(v) -> str | None:
    if v is None:
        return None
    v = re.sub(r"\s+", " ", str(v)).strip()
    return v or None


def _negara(lokasi: str | None) -> str | None:
    return "Indonesia" if lokasi and "indonesia" in lokasi.lower() else None


def _cocok(keyword: str, *teks) -> bool:
    gabung = " ".join(t or "" for t in teks).lower()
    return all(k in gabung for k in keyword.split())


# ----------------------------------------------------------------- WWR (RSS)

def _anak(item: ET.Element, nama: str) -> str | None:
    """Ambil teks elemen anak, abaikan namespace (media:, dc:, ...)."""
    for el in item:
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == nama:
            return el.text
    return None


def _anak_attr(item: ET.Element, nama: str, attr: str) -> str | None:
    for el in item:
        if el.tag.rsplit("}", 1)[-1] == nama and el.get(attr):
            return el.get(attr)
    return None


def search_weworkremotely(query: str, limit: int = 2000) -> list[dict]:
    keyword = "" if _is_browse_all(query) else query.strip().lower()
    feeds = [WWR_FEED] + [
        f"https://weworkremotely.com/categories/{k}.rss" for k in WWR_KATEGORI]

    jobs: list[dict] = []
    seen: set[str] = set()
    for feed in feeds:
        try:
            xml = _get(feed, retries=2).content
            root = ET.fromstring(xml)
        except Exception:  # noqa: BLE001
            continue
        for item in root.iter("item"):
            link = _bersih(_anak(item, "link")) or _bersih(_anak(item, "guid"))
            if not link or link in seen:
                continue
            seen.add(link)
            judul_mentah = _bersih(_anak(item, "title")) or ""
            # Format judul WWR: "Nama Perusahaan: Posisi"
            if ": " in judul_mentah:
                company, title = judul_mentah.split(": ", 1)
            else:
                company, title = None, judul_mentah
            job = {
                "link": link,
                "title": title.strip(),
                "company": (company or "").strip() or None,
                "region": _bersih(_anak(item, "region")),
                "country": _bersih(_anak(item, "country")),
                "category": _bersih(_anak(item, "category")),
                "type": _bersih(_anak(item, "type")),
                "skills": _bersih(_anak(item, "skills")),
                "description": _anak(item, "description"),
                "pubDate": _bersih(_anak(item, "pubDate")),
                "logo": _anak_attr(item, "content", "url"),
            }
            if keyword and not _cocok(keyword, job["title"], job["company"],
                                      job["category"], job["skills"]):
                continue
            jobs.append(job)
    return jobs[:limit]


def _tanggal_rss(teks: str | None) -> str | None:
    if not teks:
        return None
    try:
        return parsedate_to_datetime(teks).date().isoformat()
    except (TypeError, ValueError):
        return None


def weworkremotely_to_records(jobs, search_term, search_location,
                              requested_by_chat_id) -> list[dict]:
    from categorize import classify_employment_type, classify_job
    from sites.base import strip_html

    records = []
    for j in jobs:
        lokasi = j.get("region") or j.get("country") or "Anywhere in the World"
        tipe_mentah = j.get("type")
        tipe = _TIPE.get((tipe_mentah or "").lower())
        desk = strip_html(re.sub(r"<br\s*/?>|</(p|li|h\d)>", "\n",
                                 j.get("description") or ""), max_len=8000)
        records.append({
            "job_id": j["link"].rstrip("/").rsplit("/", 1)[-1],
            "url": j["link"],
            "title": j["title"],
            "company": j.get("company") or "Tidak disebutkan",
            "location": lokasi,
            "country": _negara(lokasi),
            "region": "remote",
            "date_posted": _tanggal_rss(j.get("pubDate")),
            "job_type": tipe_mentah,
            "job_function": j.get("category"),
            "is_remote": True,
            "work_arrangement": "remote",
            "employment_type": tipe or classify_employment_type(tipe_mentah, j["title"]),
            "description": desk or None,
            "skills": j.get("skills"),
            "company_logo": j.get("logo"),
            "category": classify_job(j["title"], j.get("category"), search_term),
        })
    return records


# --------------------------------------------------------- Remote OK (API)

def search_remoteok(query: str, limit: int = 500) -> list[dict]:
    keyword = "" if _is_browse_all(query) else query.strip().lower()
    data = _get(REMOTEOK_API).json()
    if not isinstance(data, list):
        return []
    # Elemen pertama = pemberitahuan legal (punya "legal", bukan "position").
    jobs = [d for d in data if isinstance(d, dict) and d.get("position")]
    if keyword:
        jobs = [d for d in jobs if _cocok(keyword, d.get("position"),
                                          d.get("company"), " ".join(d.get("tags") or []))]
    return jobs[:limit]


def remoteok_to_records(jobs, search_term, search_location,
                        requested_by_chat_id) -> list[dict]:
    from categorize import classify_employment_type, classify_job
    from sites.base import strip_html

    records = []
    for j in jobs:
        url = j.get("url") or (f"https://remoteok.com/remote-jobs/{j['slug']}"
                               if j.get("slug") else None)
        title = _bersih(j.get("position"))
        if not url or not title:
            continue
        lokasi = _bersih(j.get("location")) or "Worldwide"
        lo = j.get("salary_min") or None   # 0 = tidak dicantumkan
        hi = j.get("salary_max") or None
        if lo and not hi:
            hi = lo
        if hi and not lo:
            lo = hi
        tanggal = (j.get("date") or "")[:10] or None
        if not tanggal and j.get("epoch"):
            tanggal = datetime.fromtimestamp(int(j["epoch"]), tz=timezone.utc).date().isoformat()
        tags = [t for t in (j.get("tags") or []) if t]
        desk = strip_html(re.sub(r"<br\s*/?>|</(p|li|h\d)>", "\n",
                                 j.get("description") or ""), max_len=7800)
        desk = "Sumber: Remote OK (remoteok.com)" + (f"\n{desk}" if desk else "")

        records.append({
            "job_id": str(j.get("id") or j.get("slug")),
            "url": url,
            "job_url_direct": url,   # syarat Remote OK: tautkan ke halaman mereka
            "title": title,
            "company": _bersih(j.get("company")) or "Tidak disebutkan",
            "location": lokasi,
            "country": _negara(lokasi),
            "region": "remote",
            "date_posted": tanggal,
            "job_type": None,
            "is_remote": True,
            "work_arrangement": "remote",
            "employment_type": classify_employment_type(None, title, " ".join(tags)),
            "description": desk,
            "skills": ", ".join(tags) or None,
            "company_logo": j.get("company_logo") or None,
            "min_amount": float(lo) if lo else None,
            "max_amount": float(hi) if hi else None,
            "currency": "USD" if lo else None,
            "interval": "yearly" if lo else None,
            "salary_source": "remoteok" if lo else None,
            "raw_salary": f"USD {lo:,.0f} - {hi:,.0f}/tahun" if lo else None,
            "category": classify_job(title, " ".join(tags), search_term),
        })
    return records
