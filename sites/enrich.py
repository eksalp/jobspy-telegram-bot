from __future__ import annotations

"""
Pengayaan dari halaman detail.

Masalah yang diselesaikan: hampir semua halaman listing hanya memuat judul dan
link. Akibatnya kolom `description`, `job_level`, `date_posted`, dan sering
juga `location` kosong di database — persis seperti baris Astra yang isinya
mayoritas null.

Solusinya: setelah daftar lowongan didapat, kunjungi halaman detail masing-
masing dan ambil isinya. Dibuat generik supaya tidak perlu menulis selector
per situs:

  1. Buang nav/header/footer/script, sisanya dianggap konten
  2. Ambil elemen dengan teks terbanyak sebagai badan deskripsi
  3. Tarik label umum Indonesia/Inggris ("Batas Lamar", "Penempatan",
     "Lokasi", "Level", "Job Type") lewat regex

Biayanya satu request per lowongan, jadi dijalankan paralel dan dibatasi
`max_jobs`. Untuk Astra dengan 136 loker, ambil 40 pertama saja sudah jauh
lebih baik daripada semuanya kosong.

Kegagalan tidak pernah fatal: kalau halaman detail tidak bisa diambil atau
tidak terbaca, lowongannya tetap tersimpan dengan kolom seadanya.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Bagian halaman yang bukan konten lowongan
_CHROME_TAGS = ["nav", "header", "footer", "aside", "script", "style", "noscript"]

# Label yang lazim di situs karir Indonesia.
#
# Teks halaman digabung jadi satu baris panjang, jadi nilai satu label harus
# dihentikan secara eksplisit sebelum label berikutnya — tanpa itu "Penempatan:
# Jakarta Utara" ikut menelan "Job Level: Associate Job Type: ..." di belakangnya.
_STOP = (
    r"(?=\s*(?:[Dd]eskripsi|[Pp]ersyaratan|[Kk]ualifikasi|[Pp]enempatan|"
    r"[Ll]okasi|[Jj]ob\s*[Ll]evel|[Jj]ob\s*[Tt]ype|[Jj]ob\s*[Ff]unction|"
    r"[Jj]ob\s*[Ll]ocation|[Bb]atas\s*[Ll]amar|[Cc]losing|[Dd]ivisi|"
    r"[Ss]tatus|[Tt]ipe|[Jj]enjang|[Ee]xperience|[Ff]ungsi|[Rr]esponsibilit|"
    r"[Rr]equirement|[Qq]ualification|[Aa]bout|$))"
)

_LABELS: dict[str, list[str]] = {
    "date_closing": [
        r"[Bb]atas\s*[Ll]amar\s*[:\-]?\s*(.{4,40}?)" + _STOP,
        r"[Cc]losing\s*[Dd]ate\s*[:\-]?\s*(.{4,40}?)" + _STOP,
        r"[Bb]erlaku\s*sampai\s*[:\-]?\s*(.{4,40}?)" + _STOP,
    ],
    "location": [
        r"[Pp]enempatan\s*[:\-]?\s*(.{3,60}?)" + _STOP,
        r"[Ll]okasi(?:\s*[Kk]erja)?\s*[:\-]?\s*(.{3,60}?)" + _STOP,
        r"[Jj]ob\s*[Ll]ocation\s*[:\-]?\s*(.{3,60}?)" + _STOP,
        r"[Ww]illing to be (?:placed|located) in ([^.]{3,80})",
    ],
    "job_level": [
        r"[Jj]enjang\s*[Kk]arir\s*[:\-]?\s*(.{3,40}?)" + _STOP,
        r"[Jj]ob\s*[Ll]evel\s*[:\-]?\s*(.{3,40}?)" + _STOP,
        r"[Ee]xperience\s*[Ll]evel\s*[:\-]?\s*(.{3,40}?)" + _STOP,
    ],
    "job_type": [
        r"[Tt]ipe\s*[Pp]ekerjaan\s*[:\-]?\s*(.{3,40}?)" + _STOP,
        r"[Jj]ob\s*[Tt]ype\s*[:\-]?\s*(.{3,40}?)" + _STOP,
        r"[Ss]tatus\s*[Kk]aryawan\s*[:\-]?\s*(.{3,40}?)" + _STOP,
    ],
    "job_function": [
        r"[Ff]ungsi\s*[Kk]erja\s*[:\-]?\s*(.{3,40}?)" + _STOP,
        r"[Jj]ob\s*[Ff]unction\s*[:\-]?\s*(.{3,40}?)" + _STOP,
        r"[Dd]ivisi\s*[:\-]?\s*(.{3,40}?)" + _STOP,
    ],
}


@dataclass
class EnrichConfig:
    """Pengaturan pengayaan untuk satu situs."""

    enabled: bool = True
    content_selector: str | None = None   # kalau None, dideteksi otomatis
    max_jobs: int = 40                    # batas agar tidak terlalu lama
    max_workers: int = 6
    timeout: int = 20
    min_text: int = 120                   # konten lebih pendek dianggap gagal
    # Kolom yang dicoba diisi. Kalau SEMUA sudah terisi, halaman detail tidak
    # dikunjungi sama sekali. Sengaja tidak memasukkan job_function karena
    # jarang tersedia dan akan memaksa fetch yang sia-sia.
    fields: set[str] = field(
        default_factory=lambda: {"description", "location", "job_level",
                                 "job_type"}
    )


def _extract_main(soup, selector: str | None, min_text: int) -> str | None:
    """Ambil badan konten halaman detail."""
    for chrome in soup.find_all(_CHROME_TAGS):
        chrome.decompose()

    if selector:
        node = soup.select_one(selector)
        if node:
            text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
            return text if len(text) >= min_text else None

    # Otomatis: <main>/<article> kalau ada, kalau tidak elemen dengan teks
    # terbanyak tapi belum sebesar seluruh <body>.
    for tag in ("main", "article"):
        node = soup.find(tag)
        if node:
            text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
            if len(text) >= min_text:
                return text

    best, best_len = None, 0
    body = soup.find("body") or soup
    for node in body.find_all(["div", "section"], recursive=True):
        text = node.get_text(" ", strip=True)
        length = len(text)
        # elemen yang terlalu besar biasanya wrapper seluruh halaman
        if min_text <= length > best_len and length < 20000:
            best, best_len = node, length

    if best is None:
        text = re.sub(r"\s+", " ", body.get_text(" ", strip=True))
        return text if len(text) >= min_text else None

    return re.sub(r"\s+", " ", best.get_text(" ", strip=True))


def _extract_labels(text: str, wanted: set[str]) -> dict:
    found = {}
    for key, patterns in _LABELS.items():
        if key not in wanted and key != "date_closing":
            continue
        for pattern in patterns:
            m = re.search(pattern, text)
            if m:
                value = m.group(1).strip(" :-–—").strip()
                if value and len(value) > 2:
                    found[key] = value
                    break
    return found


def _enrich_one(job: dict, cfg: EnrichConfig) -> dict:
    from .base import get_soup

    url = job.get("url")
    if not url:
        return job

    try:
        soup = get_soup(url, retries=1, timeout=cfg.timeout)
    except Exception as e:  # noqa: BLE001
        logger.debug("Pengayaan gagal untuk %s: %s", url, e)
        return job

    body = _extract_main(soup, cfg.content_selector, cfg.min_text)
    if not body:
        return job

    if "description" in cfg.fields and not job.get("description"):
        job["description"] = body[:8000]

    labels = _extract_labels(body, cfg.fields)

    # Batas lamar bukan tanggal posting, jadi disimpan di deskripsi saja
    # supaya tidak salah mengisi kolom date_posted.
    closing = labels.pop("date_closing", None)
    if closing and job.get("description"):
        job["description"] = f"Batas lamar: {closing} | {job['description']}"[:8000]

    for key, value in labels.items():
        if key in cfg.fields and not job.get(key):
            job[key] = value

    return job


def enrich_jobs(jobs: list[dict], cfg: EnrichConfig) -> list[dict]:
    """Isi kolom kosong dengan mengunjungi halaman detail tiap lowongan.

    Dijalankan paralel. Lowongan di luar `max_jobs` dibiarkan apa adanya.
    """
    if not cfg.enabled or not jobs:
        return jobs

    # Hanya kunjungi halaman detail untuk lowongan yang memang kurang data.
    # Situs berbasis API (Workday, Lever, Indofood) sudah mengembalikan
    # deskripsi lengkap dari listing-nya, jadi tanpa saringan ini kita akan
    # menembak ribuan request yang tidak menghasilkan apa-apa.
    def _needs_enrich(job: dict) -> bool:
        if not job.get("url"):
            return False
        return any(not job.get(f) for f in cfg.fields)

    targets = [j for j in jobs if _needs_enrich(j)][: cfg.max_jobs]
    if not targets:
        logger.debug("Pengayaan dilewati: semua lowongan sudah lengkap")
        return jobs

    before = {id(j): j.get("description") for j in targets}

    with ThreadPoolExecutor(max_workers=cfg.max_workers) as pool:
        futures = [pool.submit(_enrich_one, job, cfg) for job in targets]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:  # noqa: BLE001
                logger.debug("Pengayaan bermasalah: %s", e)

    added = [j for j in targets
             if j.get("description") and not before.get(id(j))]

    # Kalau deskripsi yang baru diambil SAMA PERSIS antar banyak lowongan,
    # itu bukan deskripsi pekerjaan melainkan profil perusahaan atau kerangka
    # halaman JS yang belum terisi. Lebih baik dikosongkan daripada mengisi
    # database dengan teks yang menyesatkan.
    dropped = 0
    if len(added) >= 2:
        counts: dict[str, int] = {}
        for job in added:
            key = (job.get("description") or "")[:400]
            counts[key] = counts.get(key, 0) + 1
        for job in added:
            key = (job.get("description") or "")[:400]
            if counts[key] >= max(2, len(added) // 2):
                job["description"] = None
                dropped += 1

    kept = len(added) - dropped
    if dropped:
        logger.info(
            "Pengayaan: %d/%d dapat isi halaman detail, %d dibuang karena "
            "isinya sama di banyak lowongan (profil perusahaan, bukan deskripsi)",
            kept, len(targets), dropped)
    else:
        logger.info("Pengayaan: %d/%d lowongan dapat isi halaman detail",
                    kept, len(targets))
    return jobs


# Dipakai untuk situs yang tidak menyetel `enrich` sendiri. Konservatif:
# lowongan yang sudah lengkap dilewati, jadi situs berbasis API praktis tidak
# terkena biaya tambahan.
DEFAULT_ENRICH = EnrichConfig(max_jobs=30, max_workers=6)
