from __future__ import annotations

"""
Bungkus scraper lama (bca.py, shopee.py, dst) supaya ikut registry baru.

Kode scraper lamanya TIDAK diubah sama sekali — file ini cuma adaptor tipis.
Jadi kalau ada masalah, perilakunya masih persis seperti sebelumnya dan bisa
dibandingkan langsung.

Catatan: scraper lama sudah punya `*_to_records()` sendiri yang menghasilkan
record lengkap. Registry butuh bentuk dict mentah, jadi di sini record hasil
scraper lama dipetakan balik ke bentuk mentah. Sedikit boros, tapi menjaga
supaya kamu tidak perlu menulis ulang lima scraper yang sudah jalan.
"""

import logging

from .enrich import EnrichConfig
from .registry import SiteSpec, register

logger = logging.getLogger(__name__)


def _wrap(search_fn, records_fn, site_key: str):
    def fetch(query: str, limit: int) -> list[dict]:
        jobs = search_fn(query=query, limit=limit)
        records = records_fn(
            jobs, search_term=query, search_location=None, requested_by_chat_id=""
        )
        return [{
            "title": r.get("title"),
            "url": r.get("job_url"),
            "job_id": r.get("job_id"),
            "location": r.get("location"),
            "description": r.get("description"),
            "job_function": r.get("job_function"),
            "job_level": r.get("job_level"),
            "job_type": r.get("job_type"),
            "date_posted": r.get("date_posted"),
            "is_remote": r.get("is_remote"),
            "company": r.get("company"),
        } for r in records]

    return fetch


def register_legacy_sites() -> None:
    from bca import bca_to_records, search_bca
    from shopee import search_shopee, shopee_to_records
    from lokerbumn import lokerbumn_to_records, search_lokerbumn

    register(SiteSpec(
        name="bca", label="BCA", company="PT Bank Central Asia Tbk (BCA)",
        fetch=_wrap(search_bca, bca_to_records, "bca"),
        industry="Banking & Financial Services",
        company_url_direct="https://www.bca.co.id",
        verified=True, tags={"bank", "id"},
    ))

    register(SiteSpec(
        name="shopee", label="Shopee", company="Shopee",
        fetch=_wrap(search_shopee, shopee_to_records, "shopee"),
        industry="E-Commerce & Technology",
        company_url_direct="https://shopee.co.id",
        verified=True, tags={"tech", "id"},
    ))

    register(SiteSpec(
        name="lokerbumn", label="Loker BUMN", company="BUMN Indonesia",
        fetch=_wrap(search_lokerbumn, lokerbumn_to_records, "lokerbumn"),
        industry="Various (BUMN)",
        verified=True, tags={"bumn", "id", "aggregator"},
    ))

    # astracareer mengimpor playwright di level modul. Playwright
    # opsional (lihat requirements-browser.txt), jadi kalau belum terpasang
    # situs ini dilewati saja — bot tetap jalan penuh untuk situs lain.
    try:
        from astracareer import astra_career_to_records, search_astra_career
    except ImportError as e:
        logger.info(
            "Situs berbasis browser dilewati (%s). "
            "Pasang dengan: pip install -r requirements-browser.txt "
            "&& playwright install chromium", e,
        )
        return

    # Ternyata jalan: 136 loker dengan judul posisi sungguhan. Komentar lama
    # di astracareer.py yang bilang selectornya belum divalidasi sudah usang.
    # Lokasi masih kosong (situsnya tidak menampilkannya di kartu listing).
    register(SiteSpec(
        name="astracareer", label="Astra Career", company="PT Astra International Tbk",
        fetch=_wrap(search_astra_career, astra_career_to_records, "astracareer"),
        industry="Automotive / Conglomerate",
        needs_browser=True, verified=True, tags={"automotive", "id"},
        # Listing Astra cuma judul + link, jadi halaman detail dikunjungi untuk
        # mengisi deskripsi, penempatan, dan batas lamar.
        enrich=EnrichConfig(max_jobs=40),
        notes="Butuh Playwright; detail diambil dari halaman lowongan.",
    ))

    # Talentics pindah ke sites/talentics_site.py (API JSON, tanpa Playwright).


def register_web3career() -> None:
    """Daftarkan web3.career ke registry.

    Sebelumnya situs ini ditangani lewat blok khusus di bot.py, jadi ia tidak
    ikut alias `verified`/`all`/`fast` dan hanya jalan kalau namanya disebut
    eksplisit. Setelah didaftarkan di sini, blok khusus itu jadi kode mati:
    resolve() sudah menangkap "web3career" sebagai spec, sehingga
    use_web3career selalu False dan tidak ada scraping ganda.

    Bedanya dengan situs lain: web3.career tidak menerima kata kunci bebas,
    hanya tag tertentu. Kata kunci dicocokkan dulu ke tag terdekat; kalau tidak
    ada yang cocok (termasuk saat query "semua"), dipakai tag "blockchain".
    """
    from web3career import (
        find_matching_tag,
        search_web3career,
        web3career_to_records,
    )

    def fetch(query: str, limit: int) -> list[dict]:
        # config diimpor di dalam fetch, bukan saat registrasi: config.py
        # membaca variabel environment wajib, dan pendaftaran situs tidak
        # seharusnya gagal hanya karena .env belum termuat.
        import config

        if not config.WEB3CAREER_API_TOKEN:
            raise RuntimeError(
                "WEB3CAREER_API_TOKEN belum diisi di .env "
                "(daftar gratis di https://web3.career/web3-jobs-api)")

        tag = None
        if query and query.strip().lower() not in {"all", "semua", "*", ""}:
            tag = find_matching_tag(query)
        tag = tag or "blockchain"

        jobs = search_web3career(tag=tag, limit=limit)
        records = web3career_to_records(
            jobs, search_term=query, search_location=None,
            requested_by_chat_id="", search_remote=False,
        )
        return [{
            "title": r.get("title"), "url": r.get("job_url"),
            "job_id": r.get("job_id"), "location": r.get("location"),
            "description": r.get("description"),
            "job_function": r.get("job_function"),
            "job_type": r.get("job_type"),
            "date_posted": r.get("date_posted"),
            "is_remote": r.get("is_remote"),
            "company": r.get("company"),
        } for r in records]

    register(SiteSpec(
        name="web3career", label="web3.career", company="Various (Web3)",
        fetch=fetch,
        industry="Blockchain & Crypto",
        company_url_direct="https://web3.career",
        # API-nya sudah mengembalikan deskripsi lengkap (show_description=true),
        # jadi mengunjungi halaman detail tiap lowongan cuma buang request.
        enrich=False,
        verified=True,
        tags={"web3", "crypto", "aggregator", "global"},
        notes="Butuh WEB3CAREER_API_TOKEN. Lowongan GLOBAL (mayoritas AS), "
              "bukan Indonesia — pertimbangkan kalau target kamu lokal.",
    ))
