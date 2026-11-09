from __future__ import annotations

import logging

from supabase import Client, create_client

import config

logger = logging.getLogger(__name__)

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)
    return _client


def _dedupe_key(record: dict) -> tuple[str, str]:
    """Normalisasi (site, job_id) supaya perbandingan Python konsisten dengan
    perbandingan yang dilakukan Postgres di constraint `jobs_site_job_id_key`.

    Tanpa ini, dua record yang di mata Postgres SAMA (mis. job_id 12345 vs
    "12345", atau "12345 " dengan spasi nyasar) bisa dianggap kunci BERBEDA
    oleh dict Python, lolos dari dedup, lalu bertabrakan lagi saat upsert dan
    memicu "ON CONFLICT DO UPDATE command cannot affect row a second time".
    str() + strip() membuat perbandingan Python match dengan perbandingan
    text di kolom Postgres.
    """
    site = str(record.get("site") or "").strip()
    job_id = str(record.get("job_id") or "").strip()
    return site, job_id


def deduplicate(records: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """Buang record dengan (site, job_id) kembar, sisakan yang terakhir.

    Postgres menolak `ON CONFLICT DO UPDATE` kalau satu perintah memuat dua
    baris dengan kunci konflik yang sama:

        ON CONFLICT DO UPDATE command cannot affect row a second time

    Jadi dedup HARUS dilakukan sebelum dikirim, bukan diserahkan ke database.
    Yang terakhir dipertahankan karena biasanya berasal dari sumber yang
    diproses belakangan dan datanya lebih lengkap.

    Return (record_bersih, jumlah_kembar_per_situs).
    """
    unique: dict[tuple, dict] = {}
    dupes: dict[str, int] = {}

    for record in records:
        key = _dedupe_key(record)
        if key in unique:
            site = record.get("site") or "?"
            dupes[site] = dupes.get(site, 0) + 1
        unique[key] = record

    return list(unique.values()), dupes


def upsert_jobs(records: list[dict], batch_size: int = 200) -> int:
    """Upsert record job ke tabel `jobs`, dedup berdasarkan (site, job_id).

    Return jumlah row yang berhasil dikirim (setelah dedup).
    """
    if not records:
        return 0

    records, dupes = deduplicate(records)
    if dupes:
        logger.info(
            "Dedup sebelum upsert: %d record kembar dibuang (%s)",
            sum(dupes.values()),
            ", ".join(f"{site}: {n}" for site, n in sorted(dupes.items())),
        )

    client = get_client()
    total = 0
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        client.table("jobs").upsert(batch, on_conflict="site,job_id").execute()
        total += len(batch)
    return total