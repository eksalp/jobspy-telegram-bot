from __future__ import annotations

"""
Scraper untuk jakartakerja.com (lowongan Jakarta & Jabodetabek, WordPress).

robots.txt (Yoast): `User-agent: *` + `Disallow:` kosong -> semua boleh.

Sumber data:
1. Halaman daftar  https://www.jakartakerja.com/            (halaman 1)
                   https://www.jakartakerja.com/page/{N}/   (halaman N)
   -> dikumpulkan semua link /lowongan/{slug}/. Bagian "Rekomendasi" di
      tiap halaman berulang, jadi dedup pakai set URL, dan berhenti kalau
      satu halaman tidak menghasilkan link baru sama sekali.
2. Halaman detail  https://www.jakartakerja.com/lowongan/{slug}/
   -> JSON-LD schema.org JobPosting: title, description (HTML),
      identifier.value (ID numerik), datePosted, validThrough,
      employmentType, hiringOrganization{name, logo, sameAs},
      jobLocation.address{streetAddress, addressLocality, addressRegion},
      baseSalary.

API WordPress (/wp-json/wp/v2/...) TIDAK memuat lowongan -- hanya artikel
blog (tipe "post"); tipe lowongan tidak diekspos ke REST API.

CATATAN JSON-LD: string `description` berisi baris baru mentah DAN kadang
tanda kutip mentah (atribut HTML seperti data-pm-slice="0 0 []"), jadi
bloknya bukan JSON valid. Dicoba json.loads(strict=False) dulu; kalau gagal,
deskripsi dipotong keluar dengan regex (_baca_ld), sisanya di-parse, lalu
deskripsi ditempel kembali. Banyak nilai juga punya spasi berlebih di ujung
("Full Time    ") -> di-strip.
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

BASE_URL = "https://www.jakartakerja.com"
ALL_KEYWORDS = {"all", "semua", "*", ""}
MAKS_HALAMAN = 300
JEDA = 0.5            # detik antar halaman daftar
DETAIL_PARALEL = 4

_POLA_LINK = re.compile(r'href="(https://www\.jakartakerja\.com/lowongan/[a-z0-9-]+/?)"')
_POLA_LD = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)

_TIPE = {
    "full time": "full-time", "fulltime": "full-time", "penuh waktu": "full-time",
    "part time": "part-time", "paruh waktu": "part-time",
    "kontrak": "kontrak", "contract": "kontrak",
    "magang": "magang", "internship": "magang", "intern": "magang",
    "freelance": "freelance", "lepas": "freelance",
}


def _is_browse_all(query: str | None) -> bool:
    return (query or "").strip().lower() in ALL_KEYWORDS


def _bersih(v) -> str | None:
    if v is None:
        return None
    v = re.sub(r"\s+", " ", str(v)).strip()
    return v or None


def _kumpulkan_link(limit: int) -> list[str]:
    from sites.base import http_get

    links: list[str] = []
    seen: set[str] = set()
    for n in range(1, MAKS_HALAMAN + 1):
        url = BASE_URL + "/" if n == 1 else f"{BASE_URL}/page/{n}/"
        try:
            html = http_get(url, retries=2, timeout=20).text
        except Exception:  # noqa: BLE001
            break  # biasanya 404 setelah halaman terakhir
        baru = 0
        for href in _POLA_LINK.findall(html):
            href = href.rstrip("/") + "/"
            if href not in seen:
                seen.add(href)
                links.append(href)
                baru += 1
        if baru == 0 or len(links) >= limit:
            break
        time.sleep(JEDA)
    return links[:limit]


# Kunci sesudah "description" di JSON-LD situs ini. Dipakai untuk memotong
# deskripsi yang berisi tanda kutip TIDAK di-escape (contoh nyata:
# <p data-pm-slice="0 0 []">), yang membuat seluruh blok bukan JSON valid.
_POLA_DESKRIPSI = re.compile(
    r'"description"\s*:\s*"(.*?)"\s*,\s*(?="(?:identifier|datePosted|validThrough|'
    r'employmentType|hiringOrganization|jobLocation|baseSalary|@type)")', re.S)


def _baca_ld(blok: str):
    blok = blok.strip()
    try:
        return json.loads(blok, strict=False)
    except ValueError:
        pass
    m = _POLA_DESKRIPSI.search(blok)
    if not m:
        return None
    sisa = blok[:m.start()] + '"description": "",' + blok[m.end():]
    try:
        data = json.loads(sisa, strict=False)
    except ValueError:
        return None
    if isinstance(data, dict):
        data["description"] = m.group(1).replace('\\"', '"')
    return data


def _jobposting(html: str) -> dict | None:
    for blok in _POLA_LD.findall(html):
        data = _baca_ld(blok)
        if data is None:
            continue
        kandidat = data.get("@graph", [data]) if isinstance(data, dict) else data
        for item in kandidat if isinstance(kandidat, list) else [kandidat]:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return None


def _ambil_detail(url: str) -> dict | None:
    from sites.base import http_get

    try:
        html = http_get(url, retries=2, timeout=20).text
    except Exception:  # noqa: BLE001
        return None
    jp = _jobposting(html)
    if jp:
        jp["_url"] = url
    return jp


def search_jakartakerja(query: str, limit: int = 3000) -> list[dict]:
    keyword = "" if _is_browse_all(query) else query.strip().lower()
    links = _kumpulkan_link(limit if not keyword else 3000)
    if keyword:
        # Slug memuat judul & perusahaan ("admin-sales-di-kreons-19"),
        # jadi saring dulu dari slug supaya tidak membuka ribuan detail.
        kunci = keyword.replace(" ", "-")
        links = [u for u in links if kunci in u]

    with ThreadPoolExecutor(max_workers=DETAIL_PARALEL) as pool:
        hasil = [j for j in pool.map(_ambil_detail, links) if j]

    hari_ini = date.today().isoformat()
    aktif = [j for j in hasil
             if not (_bersih(j.get("validThrough")) or "9999")[:10] < hari_ini]
    return aktif[:limit]


def _gaji(jp: dict) -> tuple[float | None, float | None, str | None]:
    gaji = jp.get("baseSalary") or {}
    nilai = gaji.get("value") if isinstance(gaji, dict) else None
    if isinstance(nilai, dict):
        lo, hi = nilai.get("minValue"), nilai.get("maxValue") or nilai.get("value")
        unit = (nilai.get("unitText") or "").lower()
    else:
        lo = hi = nilai if isinstance(nilai, (int, float)) else None
        unit = ""
    try:
        lo = float(lo) if lo not in (None, "") else None
        hi = float(hi) if hi not in (None, "") else None
    except (TypeError, ValueError):
        lo = hi = None
    if lo and not hi:
        hi = lo
    if hi and not lo:
        lo = hi
    interval = {"month": "monthly", "year": "yearly", "day": "daily",
                "hour": "hourly"}.get(unit, "monthly") if lo else None
    return lo, hi, interval


def jakartakerja_to_records(
    jobs: list[dict],
    search_term: str,
    search_location: str | None,
    requested_by_chat_id: str,
) -> list[dict]:
    from categorize import classify_employment_type, classify_job, classify_work_arrangement
    from sites.base import strip_html

    records = []
    for jp in jobs:
        url = jp.get("_url")
        title = _bersih(jp.get("title"))
        if not url or not title:
            continue
        ident = jp.get("identifier") or {}
        job_id = _bersih(ident.get("value")) if isinstance(ident, dict) else None
        job_id = job_id or url.rstrip("/").rsplit("/", 1)[-1]

        org = jp.get("hiringOrganization") or {}
        company = _bersih(org.get("name")) or "Tidak disebutkan"

        lok = jp.get("jobLocation") or {}
        if isinstance(lok, list):
            lok = lok[0] if lok else {}
        alamat = lok.get("address") or {}
        kota = _bersih(alamat.get("addressLocality"))
        prov = _bersih(alamat.get("addressRegion"))
        location = ", ".join(x for x in (kota, prov) if x) or "Jakarta"

        tipe_mentah = _bersih(jp.get("employmentType"))
        if isinstance(jp.get("employmentType"), list):
            tipe_mentah = _bersih(" ".join(jp["employmentType"]))
        tipe = _TIPE.get((tipe_mentah or "").lower().replace("_", " "))

        desk = strip_html(
            re.sub(r"<br\s*/?>|</(p|li)>", "\n", jp.get("description") or ""),
            max_len=8000)
        batas = (_bersih(jp.get("validThrough")) or "")[:10]
        if batas:
            desk = f"Batas lamar: {batas}\n{desk}" if desk else f"Batas lamar: {batas}"

        lo, hi, interval = _gaji(jp)

        records.append({
            "job_id": str(job_id),
            "site": "jakartakerja",
            "job_url": url,
            "job_url_direct": url,
            "title": title,
            "company": company,
            "location": location,
            "date_posted": (_bersih(jp.get("datePosted")) or "")[:10] or None,
            "job_type": tipe_mentah,
            "min_amount": lo,
            "max_amount": hi,
            "currency": "IDR" if lo else None,
            "interval": interval,
            "salary_source": "jakartakerja" if lo else None,
            "raw_salary": f"Rp{lo:,.0f} - Rp{hi:,.0f}" if lo else None,
            "is_remote": None,
            "job_level": None,
            "job_function": None,
            "description": desk,
            "company_logo": _bersih(org.get("logo")),
            "company_url": _bersih(org.get("sameAs")) or BASE_URL,
            "company_addresses": _bersih(alamat.get("streetAddress")),
            "category": classify_job(title, search_term),
            "work_arrangement": classify_work_arrangement(None, title, location, desk),
            "employment_type": tipe or classify_employment_type(tipe_mentah, title),
            "search_term": search_term,
            "search_location": search_location or location,
            "requested_by_chat_id": str(requested_by_chat_id),
        })
    return records
