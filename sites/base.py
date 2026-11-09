from __future__ import annotations

"""
Helper bersama untuk semua adapter situs karir.

Tujuan file ini: menghapus copy-paste. Sebelumnya tiap scraper (bca.py,
shopee.py, dst) mengulang HEADERS, retry logic, dan ~40 baris dict record yang
sama persis. Sekarang semua itu ada di sini sekali saja.
"""

import logging
import re
import time
from html import unescape
from typing import Any

import requests
from bs4 import BeautifulSoup

from categorize import classify_employment_type, classify_job, classify_work_arrangement
from location_normalizer import normalize_location

logger = logging.getLogger(__name__)

ALL_KEYWORDS = {"all", "semua", "*", ""}

# Beberapa situs (mis. ooredoo.com) mengembalikan 403 kalau header-nya terlalu
# minim — mereka memeriksa Accept, Sec-Fetch-*, dan Upgrade-Insecure-Requests
# untuk membedakan browser dari skrip. Header di bawah meniru permintaan
# navigasi Chrome yang wajar.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    # SENGAJA tidak menawarkan "br" (Brotli) di sini. `requests`/`urllib3`
    # cuma bisa mendekompresnya kalau paket brotli/brotlicffi terpasang —
    # kalau tidak, dan server (mis. Workday) tetap merespons dengan Brotli
    # karena kita bilang "boleh", body yang diterima jadi kosong/rusak.
    # Ini persis penyebab error "Expecting value: line 1 column 1 (char 0)"
    # saat resp.json() dipanggil di http_post_json. gzip/deflate saja sudah
    # didukung semua situs dan tidak butuh paket tambahan.
    "Accept-Encoding": "gzip, deflate",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "Connection": "keep-alive",
}


# Dipakai untuk menyaring hasil dari tenant ATS global (mis. Samsung Workday
# mengembalikan 664 loker sedunia; kita cuma mau yang di Indonesia).
INDONESIA_HINTS = [
    "indonesia", "jakarta", "bandung", "surabaya", "medan", "semarang",
    "yogyakarta", "bekasi", "tangerang", "depok", "bogor", "makassar",
    "palembang", "batam", "denpasar", "bali", "malang", "cikarang",
    "karawang", "balikpapan", "pekanbaru", "cibitung", "purwakarta",
]


def in_indonesia(text: str | None, hints: list[str] | None = None) -> bool:
    if not text:
        return False
    haystack = text.lower()
    return any(h in haystack for h in (hints or INDONESIA_HINTS))


def is_browse_all(query: str | None) -> bool:
    return (query or "").strip().lower() in ALL_KEYWORDS


def matches(query: str, *fields: str | None) -> bool:
    """Filter client-side sederhana: query muncul di salah satu field."""
    if is_browse_all(query):
        return True
    haystack = " ".join(f for f in fields if f).lower()
    return query.strip().lower() in haystack


def _tls_session():
    """Session tls_client yang meniru handshake Chrome, atau None kalau tak ada."""
    try:
        import tls_client
    except ModuleNotFoundError:
        return None
    return tls_client.Session(
        client_identifier="chrome_120",
        random_tls_extension_order=True,
    )



def _with_deadline(func, timeout: int, *args, **kwargs):
    """Jalankan pemanggilan jaringan dengan batas waktu yang benar-benar mengikat.

    tls_client kadang mengabaikan timeout_seconds-nya sendiri dan menggantung
    tanpa batas di situs yang sengaja mendiamkan koneksi.

    Sengaja memakai thread daemon, BUKAN ThreadPoolExecutor: executor menunggu
    thread-nya selesai saat blok `with` berakhir, jadi batas waktunya percuma
    — pemanggil tetap tertahan sampai permintaannya selesai sendiri. Thread
    daemon bisa ditinggalkan dan tidak menghalangi proses berhenti.
    """
    import threading

    box: dict = {}

    def runner():
        try:
            box["value"] = func(*args, **kwargs)
        except BaseException as e:  # noqa: BLE001
            box["error"] = e

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout + 5)

    if thread.is_alive():
        raise RuntimeError(
            f"Tidak ada respons dalam {timeout + 5} detik "
            "(situs kemungkinan mendiamkan koneksi dari skrip)"
        )
    if "error" in box:
        raise box["error"]
    return box["value"]


def http_get(
    # Timeout sengaja tidak besar: sebagian situs berproteksi tidak menolak
    # dengan 403 melainkan MENDIAMKAN koneksi, jadi timeout panjang membuat
    # satu situs bermasalah menahan seluruh scrape.
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    retries: int = 3,
    timeout: int = 15,
) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(
                url, headers={**HEADERS, **(headers or {})},
                params=params, timeout=timeout,
            )
            resp.raise_for_status()
            return resp
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Gagal GET {url}: {last_exc}")


def tls_get(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = 20,
):
    """Versi GET dari pendekatan yang sudah dipakai http_post_json.

    Sebagian situs (web3.career, JobStreet) tidak menolak `requests` dengan
    403 — koneksinya justru DIDIAMKAN sampai timeout. Itu ciri proteksi
    berbasis sidik jari TLS (JA3): server mengenali klien dari cara ia
    melakukan handshake, bukan dari header yang dikirim, jadi menambah header
    apa pun tidak menolong.

    Return objek dengan `status_code`, `text`, dan `.json()` — sama seperti
    response requests, jadi bisa dipakai menggantikan http_get.
    """
    from urllib.parse import urlencode

    merged = {**HEADERS, **(headers or {})}
    session = _tls_session()

    if session is None:
        return http_get(url, params=params, headers=headers,
                        retries=1, timeout=timeout)

    full_url = f"{url}?{urlencode(params)}" if params else url

    # tls_client tidak selalu menegakkan timeout_seconds-nya sendiri, jadi
    # batas waktunya ditegakkan dari sisi kita (lihat _with_deadline).
    return _with_deadline(
        session.get, timeout, full_url, headers=merged, timeout_seconds=timeout)


def http_post_json(
    url: str,
    payload: dict,
    headers: dict | None = None,
    retries: int = 3,
    timeout: int = 25,
) -> dict:
    """POST JSON, coba tiru sidik jari TLS Chrome dulu sebelum fallback requests.

    Beberapa endpoint (mis. Workday /wday/cxs/.../jobs) duduk di belakang
    Cloudflare dan diam-diam membalas body KOSONG (status tetap 2xx, tidak
    ada error HTTP) kalau permintaannya datang dari `requests` Python biasa —
    fingerprint TLS-nya beda dari browser sungguhan. Ini persis pola yang
    sudah ditemukan di JobStreet dan web3.career, jadi pendekatannya
    disamakan: pakai tls_client (meniru Chrome) kalau terpasang, baru jatuh
    ke requests polos kalau tidak ada.
    """
    import json as _json

    merged_headers = {
        **HEADERS, "Content-Type": "application/json",
        "Accept": "application/json", **(headers or {}),
    }

    session = _tls_session()

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            if session is not None:
                resp = _with_deadline(
                    session.post, timeout,
                    url, json=payload, headers=merged_headers,
                    timeout_seconds=timeout,
                )
                if resp.status_code >= 400:
                    raise RuntimeError(f"HTTP {resp.status_code}")
                text = resp.text
                if not text:
                    # Body kosong dengan status 2xx biasanya berarti dua hal:
                    # respons Brotli yang tidak bisa didekompres (lihat catatan
                    # Accept-Encoding di HEADERS), atau proteksi bot yang
                    # membalas hampa. Header respons dicatat supaya bisa
                    # dibedakan tanpa menebak.
                    logger.warning(
                        "POST %s -> status=%s tapi body kosong. Header: %s",
                        url, resp.status_code, dict(resp.headers),
                    )
                    raise RuntimeError(
                        f"Body respons kosong (status={resp.status_code})"
                    )
                return _json.loads(text)

            resp = requests.post(
                url, json=payload, headers=merged_headers, timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Gagal POST {url}: {last_exc}")


def get_soup(url: str, params: dict | None = None, **kw) -> BeautifulSoup:
    return BeautifulSoup(http_get(url, params=params, **kw).text, "html.parser")


def strip_html(html: str | None, max_len: int = 8000) -> str | None:
    if not html:
        return None
    text = BeautifulSoup(unescape(html), "html.parser").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    return text[:max_len]


def make_record(
    *,
    site: str,
    company: str,
    title: str,
    url: str,
    job_id: str | None = None,
    location: str | None = None,
    description: str | None = None,
    job_function: str | None = None,
    job_level: str | None = None,
    job_type: str | None = None,
    date_posted: str | None = None,
    is_remote: bool | None = None,
    company_industry: str | None = None,
    company_url: str | None = None,
    company_url_direct: str | None = None,
    search_term: str = "",
    search_location: str | None = None,
    requested_by_chat_id: str = "",
    **extra: Any,
) -> dict:
    """Bangun satu row `jobs` yang bentuknya identik dengan output scraper lama.

    Semua kolom di schema.sql diisi eksplisit supaya upsert tidak pernah
    menabrak kolom yang belum ada nilainya di record lain.
    """
    record = {
        "job_id": job_id or url,
        "site": site,
        "job_url": url,
        "job_url_direct": url,
        "title": title,
        "company": company,
        "location": location or "Indonesia",
        "date_posted": date_posted,
        "job_type": job_type,
        "salary_source": None,
        "interval": None,
        "min_amount": None,
        "max_amount": None,
        "currency": None,
        "is_remote": is_remote,
        "job_level": job_level,
        "job_function": job_function,
        "listing_type": None,
        "emails": None,
        "description": description,
        "company_industry": company_industry,
        "company_url": company_url,
        "company_logo": None,
        "company_url_direct": company_url_direct,
        "company_addresses": None,
        "company_num_employees": None,
        "company_revenue": None,
        "company_description": None,
        "skills": None,
        "experience_range": job_level,
        "company_rating": None,
        "company_reviews_count": None,
        "vacancy_count": None,
        "work_from_home_type": None,
        "raw_salary": None,
        "category": classify_job(title, job_function, search_term),
        "work_arrangement": classify_work_arrangement(
            is_remote, title, job_type, location, description
        ),
        "employment_type": classify_employment_type(job_type, title, description),
        "search_term": search_term or "scrapeall",
        "search_location": search_location or location or "Indonesia",
        "requested_by_chat_id": str(requested_by_chat_id),
    }
    record.update(extra)

    # country/region dihitung dari lokasi AKHIR (setelah extra, karena
    # sebagian adapter mengirim lokasi yang lebih rapi lewat extra). Kalau
    # adapter sudah mengisi country/region sendiri, nilainya dihormati.
    if not record.get("country") and not record.get("region"):
        country, region = normalize_location(record.get("location"))
        record["country"] = country
        record["region"] = region
    return record
