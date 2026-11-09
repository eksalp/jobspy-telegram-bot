from __future__ import annotations

import re
from datetime import datetime
from html import unescape
from typing import Any

import requests
from bs4 import BeautifulSoup

import config
from categorize import classify_job, classify_work_arrangement, classify_employment_type

API_BASE = "https://web3.career/api/v1"

# Daftar tag resmi yang didukung web3.career (per dokumentasi API-nya).
# Search term bebas dari user akan dicocokkan ke salah satu tag ini.
VALID_TAGS = [
    "ai", "analyst", "backend", "bitcoin", "blockchain", "community-manager",
    "crypto", "cryptography", "cto", "customer-support", "dao", "data-science",
    "defi", "design", "developer-relations", "devops", "discord", "economy-designer",
    "entry-level", "erc", "erc-20", "evm", "front-end", "full-stack", "gaming",
    "ganache", "golang", "hardhat", "intern", "java", "javascript", "layer-2",
    "marketing", "mobile", "moderator", "nft", "node", "non-tech", "open-source",
    "openzeppelin", "pay-in-crypto", "product-manager", "project-manager",
    "react", "refi", "research", "ruby", "rust", "sales", "smart-contract",
    "solana", "solidity", "truffle", "web3-py", "web3js", "zero-knowledge",
]


def find_matching_tag(search_term: str) -> str | None:
    """Cocokkan search term bebas dari user ke salah satu tag resmi web3.career.
    Contoh: "smart contract developer" -> "smart-contract"
            "backend engineer" -> "backend"
            "front end dev" -> "front-end"
    """
    normalized = re.sub(r"\s+", "-", search_term.strip().lower())
    if normalized in VALID_TAGS:
        return normalized

    words = [w for w in re.split(r"[\s,;]+", search_term.strip().lower()) if w]

    # cek kombinasi kata berurutan (2 kata dulu, biar tag gabungan kayak
    # "smart-contract"/"front-end" ketangkep sebelum kecocokan kata tunggal)
    for window in (2, 1):
        for i in range(len(words) - window + 1):
            candidate = "-".join(words[i : i + window])
            if candidate in VALID_TAGS:
                return candidate

    return None


def _clean(value: Any) -> str | None:
    """Rapikan teks polos dari API: decode entity HTML dan rapikan spasi.

    API web3.career mengembalikan judul dengan entity mentah ("Analytics &amp;
    Strategic") dan lokasi berspasi di depan (" NY New York US"). Kalau tidak
    dibersihkan, keduanya tersimpan apa adanya di database dan terlihat aneh
    saat dikirim ke Telegram.

    Deskripsi tidak lewat sini karena _strip_html sudah menangani entity
    sekaligus membuang tag-nya.
    """
    if value is None:
        return None
    text = unescape(str(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)


def _parse_posted_at(value: Any) -> str | None:
    if not value or not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d %b %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None  # format tidak dikenali, biarkan kosong daripada salah parse


def search_web3career(
    tag: str,
    remote: bool = False,
    country: str | None = None,
    limit: int = 30,
    token: str | None = None,
) -> list[dict]:
    """Panggil API web3.career, return list of dict job mentah dari API."""
    token = token or config.WEB3CAREER_API_TOKEN
    if not token:
        raise ValueError(
            "WEB3CAREER_API_TOKEN belum diisi di .env. Daftar & ambil token gratis di "
            "https://web3.career/web3-jobs-api"
        )

    params = {
        "token": token,
        "tag": tag,
        "limit": min(max(limit, 1), 100),
        "show_description": "true",
    }
    if remote:
        params["remote"] = "true"
    if country:
        params["country"] = re.sub(r"\s+", "-", country.strip().lower())

    # SENGAJA pakai requests polos tanpa HEADERS global kita.
    #
    # Pernah diubah ke sites.base.tls_get dan itu MERUSAKNYA: tls_get
    # menggabungkan HEADERS bersama, yang isinya header untuk NAVIGASI HALAMAN
    # WEB (Sec-Fetch-Dest: document, Accept: text/html, Upgrade-Insecure-
    # Requests). Untuk panggilan API murni kombinasi itu janggal, dan
    # web3.career mendiamkan permintaannya sampai timeout.
    #
    # Gejalanya menyesatkan: menggantung di TLS handshake, persis seperti
    # proteksi sidik jari TLS — padahal penyebabnya cuma header yang salah.
    # Jadi jangan "perbaiki" ini dengan menambahkan header atau tls_client.
    resp = requests.get(API_BASE, params=params, timeout=25)
    resp.raise_for_status()
    data = resp.json()

    if not isinstance(data, list):
        raise ValueError("Format respons API web3.career tidak dikenali.")

    # respons berbentuk [string, string, [job, job, ...]] — cari elemen array-nya
    jobs = next((item for item in data if isinstance(item, list)), None)
    if jobs is None and len(data) > 0 and isinstance(data[0], dict):
        jobs = data
    return jobs or []


def _add_blockchain_category(existing: str | None) -> str:
    """Semua loker dari web3career pasti terkait blockchain/web3 secara definisi,
    jadi kategori ini selalu ditambahkan eksplisit (nggak cuma nebak dari teks).
    """
    cats = [c.strip() for c in existing.split(",")] if existing else []
    if "blockchain-web3" not in cats:
        cats.insert(0, "blockchain-web3")
    return ", ".join(cats)


def web3career_to_records(
    jobs: list[dict],
    search_term: str,
    search_location: str,
    requested_by_chat_id: str,
    search_remote: bool = False,
) -> list[dict]:
    """Ubah hasil API web3.career jadi list of dict siap di-upsert ke tabel `jobs`.
    `search_remote` = True kalau user eksplisit pakai --remote saat search - kalau
    begitu, semua hasil PASTI remote (API udah filter), jadi klasifikasi work
    arrangement nggak perlu nebak-nebak lagi dari field per-job yang kadang kosong.
    """
    records = []
    for job in jobs:
        job_id = job.get("id") or job.get("apply_url") or job.get("url")
        if not job_id:
            continue

        tags = job.get("tags")
        skills = ", ".join(tags) if isinstance(tags, list) and tags else None

        is_remote_val = True if search_remote else (
            bool(job.get("remote")) if job.get("remote") is not None else None
        )

        record = {
            "job_id": str(job_id),
            "site": "web3career",
            # API web3.career TIDAK punya field "url" — yang tersedia
            # "apply_url". Sebelum ini job_url selalu None, dan registry
            # membuang setiap lowongan karena mensyaratkan judul DAN url.
            # Gejalanya menyesatkan: fetch() kelihatan mengembalikan data,
            # tapi sites.run() menghasilkan nol tanpa error apa pun.
            "job_url": job.get("url") or job.get("apply_url"),
            "job_url_direct": job.get("apply_url") or job.get("url"),
            "title": _clean(job.get("title")),
            "company": _clean(job.get("company")),
            "location": _clean(job.get("location")),
            "date_posted": _parse_posted_at(job.get("postedAt")),
            "job_type": None,
            "salary_source": None,
            "interval": None,
            "min_amount": None,
            "max_amount": None,
            "currency": None,
            "is_remote": is_remote_val,
            "job_level": None,
            "job_function": None,
            "listing_type": None,
            "emails": None,
            "description": _strip_html(job.get("description") or ""),
            "company_industry": None,
            "company_url": None,
            "company_logo": None,
            "company_url_direct": None,
            "company_addresses": None,
            "company_num_employees": None,
            "company_revenue": None,
            "company_description": None,
            "skills": skills,
            "experience_range": None,
            "company_rating": None,
            "company_reviews_count": None,
            "vacancy_count": None,
            "work_from_home_type": None,
            "raw_salary": job.get("salary"),
            "category": _add_blockchain_category(
                classify_job(_clean(job.get("title")), skills, search_term)
            ),
            "work_arrangement": classify_work_arrangement(
                is_remote_val, _clean(job.get("title")),
                _clean(job.get("location")), skills
            ),
            "employment_type": classify_employment_type(
                None, _clean(job.get("title")), skills
            ),
            "search_term": search_term,
            "search_location": search_location or _clean(job.get("location")) or "Worldwide",
            "requested_by_chat_id": str(requested_by_chat_id),
        }
        records.append(record)

    return records
