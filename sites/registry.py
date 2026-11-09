from __future__ import annotations

"""
Registry situs karir.

Satu-satunya tempat daftar situs didefinisikan. bot.py tidak lagi perlu blok
`if use_xxx:` per situs — cukup `for spec in resolve(sites)`.

Menambah perusahaan baru = tambah satu entry di companies.py, tanpa menyentuh
bot.py sama sekali.
"""

import logging
from dataclasses import dataclass, field
from typing import Protocol

from .enrich import DEFAULT_ENRICH, EnrichConfig, enrich_jobs

logger = logging.getLogger(__name__)


class Fetcher(Protocol):
    """Adapter mengembalikan list dict mentah yang sudah dinormalisasi ringan.

    Key yang dikenali: title (wajib), url (wajib), job_id, location,
    description, job_function, job_level, job_type, date_posted, is_remote.
    """

    def __call__(self, query: str, limit: int) -> list[dict]: ...


@dataclass
class SiteSpec:
    name: str                      # id unik, dipakai di --sites dan SCRAPE_ALL_SITES
    label: str                     # nama enak dibaca untuk pesan Telegram
    company: str                   # nama perusahaan yang disimpan di kolom `company`
    fetch: Fetcher
    industry: str | None = None
    company_url: str | None = None
    company_url_direct: str | None = None
    needs_browser: bool = False    # True kalau butuh Playwright (lambat)
    verified: bool = False         # True kalau endpoint sudah dites beneran
    notes: str = ""
    tags: set[str] = field(default_factory=set)
    # Pengayaan dari halaman detail:
    #   None            -> pakai DEFAULT_ENRICH (berlaku untuk semua situs)
    #   EnrichConfig    -> pengaturan khusus situs ini
    #   False           -> matikan
    # Lowongan yang datanya sudah lengkap tetap dilewati, jadi situs berbasis
    # API tidak terkena request tambahan.
    enrich: EnrichConfig | bool | None = None


REGISTRY: dict[str, SiteSpec] = {}


def register(spec: SiteSpec) -> SiteSpec:
    if spec.name in REGISTRY:
        raise ValueError(f"Situs '{spec.name}' sudah terdaftar")
    REGISTRY[spec.name] = spec
    return spec


def get(name: str) -> SiteSpec | None:
    return REGISTRY.get(name.strip().lower())


def names() -> list[str]:
    return sorted(REGISTRY)


def resolve(requested: list[str]) -> tuple[list[SiteSpec], list[str]]:
    """Pisahkan nama situs jadi (spec custom yang dikenal, sisanya untuk JobSpy).

    Mendukung alias grup:
      `all` / `semua`     → semua situs custom
      `verified`          → hanya yang endpoint-nya sudah dikonfirmasi
      `fast`              → semua kecuali yang butuh Playwright
      `tag:bumn`          → semua situs bertag 'bumn'
    """
    specs: list[SiteSpec] = []
    leftover: list[str] = []
    seen: set[str] = set()

    def add(spec: SiteSpec) -> None:
        if spec.name not in seen:
            seen.add(spec.name)
            specs.append(spec)

    for raw in requested:
        key = raw.strip().lower()
        if not key:
            continue
        if key in {"all", "semua"}:
            for spec in REGISTRY.values():
                add(spec)
        elif key == "verified":
            for spec in REGISTRY.values():
                if spec.verified:
                    add(spec)
        elif key == "fast":
            for spec in REGISTRY.values():
                if not spec.needs_browser:
                    add(spec)
        elif key.startswith("tag:"):
            tag = key[4:]
            for spec in REGISTRY.values():
                if tag in spec.tags:
                    add(spec)
        elif key in REGISTRY:
            add(REGISTRY[key])
        else:
            leftover.append(raw)

    return specs, leftover


def run(spec: SiteSpec, query: str, limit: int, chat_id: str,
        search_location: str | None = None) -> list[dict]:
    """Jalankan satu situs dan kembalikan record siap-upsert."""
    from .base import make_record

    raw_jobs = spec.fetch(query=query, limit=limit)

    cfg = DEFAULT_ENRICH if spec.enrich is None else spec.enrich
    if cfg:
        raw_jobs = enrich_jobs(raw_jobs, cfg)

    KNOWN_KEYS = {
        "title", "url", "job_id", "location", "description", "job_function",
        "job_level", "job_type", "date_posted", "is_remote", "company",
        # Sisanya bukan berasal dari job dict, tapi tetap dijaga di sini
        # supaya extra_fields tidak pernah bertabrakan (TypeError: multiple
        # values) dengan kwarg eksplisit di panggilan make_record di bawah.
        "site", "company_industry", "company_url", "company_url_direct",
        "search_term", "search_location", "requested_by_chat_id",
    }

    records = []
    skipped = 0
    for job in raw_jobs:
        title = (job.get("title") or "").strip()
        url = job.get("url") or ""
        if not title or not url:
            # Dulu dibuang tanpa suara, dan itu membuat bug web3career sangat
            # sulit dilacak: fetch() mengembalikan data, tapi run() menghasilkan
            # nol tanpa error sama sekali — ternyata job_url-nya selalu None
            # karena API-nya memakai nama field "apply_url", bukan "url".
            skipped += 1
            continue
        # Adapter tertentu (mis. JobStreet) sudah menghitung field yang lebih
        # kaya (min_amount, work_arrangement, dst) sendiri. Field di luar
        # KNOWN_KEYS diteruskan apa adanya ke make_record, yang akan
        # meng-override nilai default (biasanya None) miliknya. Adapter lama
        # yang tidak mengirim field tambahan tidak terpengaruh sama sekali.
        extra_fields = {k: v for k, v in job.items() if k not in KNOWN_KEYS}
        records.append(make_record(
            site=spec.name,
            company=job.get("company") or spec.company,
            title=title,
            url=url,
            job_id=job.get("job_id"),
            location=job.get("location"),
            description=job.get("description"),
            job_function=job.get("job_function"),
            job_level=job.get("job_level"),
            job_type=job.get("job_type"),
            date_posted=job.get("date_posted"),
            is_remote=job.get("is_remote"),
            company_industry=spec.industry,
            company_url=spec.company_url,
            company_url_direct=spec.company_url_direct,
            search_term=query if query else "scrapeall",
            search_location=search_location,
            requested_by_chat_id=chat_id,
            **extra_fields,
        ))

    if skipped:
        logger.warning(
            "%s: %d dari %d lowongan dibuang karena judul atau URL-nya kosong. "
            "Biasanya berarti pemetaan field di adapternya salah.",
            spec.name, skipped, len(raw_jobs),
        )

    return records
