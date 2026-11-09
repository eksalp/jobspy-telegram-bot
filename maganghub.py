from __future__ import annotations

"""
Scraper untuk maganghub.kemnaker.go.id — program magang nasional Kemnaker.

Isinya berbeda dari semua sumber lain di registry: program magang resmi
pemerintah, bukan lowongan komersial. Jadi hampir tidak tumpang tindih dengan
Dealls, Kalibrr, atau situs karir perusahaan.

Halamannya Next.js dengan render sisi server, jadi datanya ada di HTML biasa.

Struktur kartu (dipastikan lewat try_selector.py --html):

    a.group.block.h-full                      <- kartu SEKALIGUS tautannya
      h3                                       <- judul posisi
      p.text-sm.font-medium.text-foreground    <- nama penyelenggara
      p.text-sm.text-muted-foreground.truncate <- bidang (mis. "Radiologi")
      (teks kartu)                             <- lokasi, pendidikan, kuota

Perhatikan kartunya adalah elemen `<a>` itu sendiri, bukan pembungkus yang
memuat `<a>` di dalamnya.

Data yang tidak ada di sumber lain: KUOTA, JUMLAH PELAMAR, dan persentase
peluang diterima. Ketiganya berguna sekali untuk pencari magang, jadi ikut
disimpan di description.
"""

import json
import logging
import re
from pathlib import Path
from urllib.parse import urljoin

from categorize import classify_job

logger = logging.getLogger(__name__)

BASE_URL = "https://maganghub.kemnaker.go.id"
LIST_URL = f"{BASE_URL}/magang-nasional/lowongan"

ALL_KEYWORDS = {"all", "semua", "*", ""}

CARD_SELECTOR = "a.group.block.h-full"

# Jumlah kartu per halaman listing; dipakai untuk menghitung batas halaman.
PER_PAGE = 18

_KUOTA = re.compile(r"Kuota:\s*(\d+)", re.I)
_PELAMAR = re.compile(r"Pelamar:\s*(\d+)", re.I)
# Frasa peluangnya diambil, TAPI persentasenya TIDAK.
#
# Di HTML, teks "Peluang Sangat Besar" dan angka "( 100 %)" berada di elemen
# berbeda, dan regex yang menjangkau keduanya sempat memasangkan angka dari
# kartu/elemen lain — akibatnya lowongan dengan kuota 5 dan pelamar 1 tetap
# tertulis 100%. Karena kuota dan pelamar sudah kita punya, persentasenya
# dihitung sendiri (lihat _peluang) supaya selalu konsisten dengan datanya.
_PELUANG_FRASA = re.compile(r"(Peluang\s+[A-Za-z ]{3,20}?)\s*\(", re.I)
_HARI = re.compile(r"(\d+)\s*hari\s*/\s*minggu", re.I)
_LIBUR = re.compile(r"Hari Libur\s+([A-Za-z]+)", re.I)
_PENDIDIKAN = re.compile(
    r"\b(SMA|SMK|MA|Diploma|D1|D2|D3|D4|S1|S2|S3|Sarjana|Semua Jenjang)\b", re.I)



def _peluang(quota: int | None, applicants: int | None,
             label: str | None) -> str | None:
    """Rakit keterangan peluang dari kuota dan jumlah pelamar.

    Dihitung sendiri, bukan diambil dari HTML, karena angka persennya berada
    di elemen terpisah dari frasanya dan mudah tertukar antar kartu.

    Sisa kuota dipakai sebagai ukuran: kuota 5 dengan 1 pelamar berarti 4 slot
    masih kosong (80%).
    """
    if quota is None or applicants is None or quota <= 0:
        return label
    sisa = max(quota - applicants, 0)
    persen = round(sisa / quota * 100)
    teks = f"Sisa kuota {sisa} dari {quota} ({persen}%)"
    return f"{label} — {teks}" if label else teks



# Berkas penanda posisi. Menarik 22.600 lowongan sekaligus butuh ~1.256
# request dan puluhan menit; dengan penanda ini penarikan bisa dicicil —
# tiap kali dijalankan, ia melanjutkan dari halaman terakhir yang berhasil.
CHECKPOINT_FILE = Path(__file__).with_name(".maganghub_progress.json")


def _baca_checkpoint() -> int:
    """Halaman berikutnya yang harus diambil. Default 1."""
    try:
        data = json.loads(CHECKPOINT_FILE.read_text())
        page = int(data.get("next_page", 1))
        return max(1, page)
    except Exception:  # noqa: BLE001
        return 1


def _tulis_checkpoint(next_page: int, selesai: bool = False) -> None:
    """Simpan posisi. `selesai=True` mengulang dari awal di jalan berikutnya.

    Kalau katalog sudah habis disusuri, kita kembali ke halaman 1 — lowongan
    baru selalu muncul di halaman awal, jadi putaran berikutnya justru yang
    paling berguna untuk pembaruan.
    """
    try:
        CHECKPOINT_FILE.write_text(json.dumps({
            "next_page": 1 if selesai else next_page,
            "terakhir_selesai": selesai,
        }))
    except Exception as e:  # noqa: BLE001
        logger.warning("Gagal menyimpan posisi MagangHub: %s", e)


def reset_checkpoint() -> None:
    """Mulai lagi dari halaman 1 pada penarikan berikutnya."""
    CHECKPOINT_FILE.unlink(missing_ok=True)


def _is_browse_all(query: str | None) -> bool:
    return (query or "").strip().lower() in ALL_KEYWORDS


def _text(node, selector: str) -> str | None:
    found = node.select_one(selector)
    if not found:
        return None
    text = re.sub(r"\s+", " ", found.get_text(" ", strip=True))
    return text or None


def search_maganghub(query: str, limit: int = 100,
                     delay: float = 0.3, lanjutkan: bool = False) -> list[dict]:
    """Ambil lowongan magang, menyusuri halaman listing satu per satu.

    `delay` — jeda antar halaman (detik). Katalog MagangHub ~1.256 halaman;
    jeda kecil membuat penarikan jauh lebih sopan ke server Kemnaker.

    `lanjutkan` — kalau True, mulai dari halaman terakhir yang berhasil pada
    jalan sebelumnya, bukan dari halaman 1. Ini membuat katalog besar bisa
    dicicil: 300 lowongan per jalan, dan tiap jalan meneruskan yang kemarin.
    Setelah katalog habis, posisinya kembali ke halaman 1 sehingga jalan
    berikutnya menangkap lowongan baru.

    Pencarian dengan kata kunci selalu mulai dari halaman 1, karena posisi
    yang tersimpan tidak ada kaitannya dengan kata kunci itu.
    """
    import time

    from sites.base import get_soup

    keyword = "" if _is_browse_all(query) else query.strip().lower()
    jobs: list[dict] = []
    seen: set[str] = set()

    pakai_checkpoint = lanjutkan and not keyword
    page = _baca_checkpoint() if pakai_checkpoint else 1
    halaman_awal = page
    if pakai_checkpoint and page > 1:
        logger.info("MagangHub melanjutkan dari halaman %s", page)

    # Batas halaman diturunkan dari `limit`, bukan angka tetap. Versi
    # sebelumnya memakai `page <= 30` yang berarti maksimal ~540 lowongan —
    # padahal katalog MagangHub jauh lebih besar (puluhan ribu). Tambahan 5
    # halaman untuk menutupi duplikat dan hasil yang tersaring kata kunci.
    #
    # Ceiling 3000 halaman (~54.000 lowongan) tetap dipasang supaya kesalahan
    # ketik pada --results tidak berubah jadi ribuan request tanpa henti.
    max_pages = min(3000, limit // PER_PAGE + 5)
    halaman_akhir = halaman_awal + max_pages
    tanpa_tambahan = 0

    while len(jobs) < limit and page < halaman_akhir:
        try:
            soup = get_soup(LIST_URL, params={"page": page} if page > 1 else None)
        except Exception as e:  # noqa: BLE001
            # Penarikan penuh butuh ribuan request; satu halaman gagal tidak
            # boleh membatalkan semua yang sudah terkumpul.
            logger.warning(
                "MagangHub halaman %s gagal (%s). Berhenti dengan %s lowongan; "
                "posisi tersimpan, jalan berikutnya lanjut dari sini.",
                page, e, len(jobs))
            if pakai_checkpoint:
                _tulis_checkpoint(page)
            break

        cards = soup.select(CARD_SELECTOR)
        if not cards:
            # Halaman kosong = katalog habis. Kembalikan posisi ke awal.
            if pakai_checkpoint:
                _tulis_checkpoint(1, selesai=True)
                logger.info("MagangHub: katalog habis di halaman %s, "
                            "jalan berikutnya mulai dari halaman 1", page)
            break

        before = len(jobs)
        for card in cards:
            href = card.get("href")
            if not href:
                continue
            url = urljoin(BASE_URL, href)
            if url in seen:
                continue

            title = _text(card, "h3")
            if not title:
                continue

            company = _text(card, "p.text-sm.font-medium.text-foreground")
            field = _text(card, "p.text-sm.text-muted-foreground.truncate")

            card_text = re.sub(r"\s+", " ", card.get_text(" ", strip=True))

            # Lokasi ada di span pertama setelah judul/bidang; diambil dari
            # daftar span agar tidak tertukar dengan pendidikan atau hari kerja.
            location = None
            for span in card.select("span.flex.items-center"):
                value = re.sub(r"\s+", " ", span.get_text(" ", strip=True))
                if not value or _PENDIDIKAN.fullmatch(value) or _HARI.search(value):
                    continue
                if (_PELUANG_FRASA.search(value) or "Peluang" in value
                        or "Kuota" in value or "Pelamar" in value):
                    continue
                location = value
                break

            if keyword and keyword not in f"{title} {company or ''} {field or ''}".lower():
                continue

            m = _PENDIDIKAN.search(card_text)
            education = m.group(1) if m else None

            kuota = _KUOTA.search(card_text)
            pelamar = _PELAMAR.search(card_text)
            peluang = _PELUANG_FRASA.search(card_text)
            hari = _HARI.search(card_text)
            libur = _LIBUR.search(card_text)

            seen.add(url)
            jobs.append({
                "title": title,
                "company": company,
                "url": url,
                "location": location,
                "field": field,
                "education": education,
                "quota": int(kuota.group(1)) if kuota else None,
                "applicants": int(pelamar.group(1)) if pelamar else None,
                "chance_label": peluang.group(1).strip() if peluang else None,
                "days_per_week": hari.group(1) if hari else None,
                "day_off": libur.group(1) if libur else None,
            })
            if len(jobs) >= limit:
                break

        # Halaman berikutnya tidak menambah apa pun -> paginasi lewat ?page=
        # tidak didukung, berhenti daripada mengulang isi yang sama.
        if len(jobs) == before:
            # Satu halaman tanpa tambahan belum tentu berarti katalog habis:
            # bisa jadi seluruh isinya kebetulan sudah pernah terlihat (urutan
            # listing bergeser saat lowongan baru masuk), atau semuanya
            # tersaring kata kunci. Berhenti seketika di sini pernah membuat
            # penarikan mandek jauh sebelum halaman terakhir.
            tanpa_tambahan += 1
            if tanpa_tambahan >= 3:
                if pakai_checkpoint:
                    _tulis_checkpoint(1, selesai=True)
                logger.info("MagangHub: 3 halaman berturut-turut tanpa "
                            "lowongan baru, berhenti di halaman %s", page)
                break
        else:
            tanpa_tambahan = 0

        # Laporkan kemajuan berkala — penarikan penuh makan puluhan menit dan
        # tanpa ini prosesnya terlihat menggantung.
        if page % 25 == 0:
            logger.info("MagangHub: %s halaman, %s lowongan terkumpul",
                        page, len(jobs))

        page += 1
        if pakai_checkpoint:
            _tulis_checkpoint(page)
        if delay:
            time.sleep(delay)

    logger.info("MagangHub: %s lowongan dari halaman %s-%s",
                len(jobs), halaman_awal, page - 1)
    return jobs[:limit]


def maganghub_to_records(
    jobs: list[dict],
    search_term: str,
    search_location: str | None,
    requested_by_chat_id: str,
) -> list[dict]:
    from categorize import classify_work_arrangement

    records = []
    for job in jobs:
        title = job.get("title")
        url = job.get("url")
        if not title or not url:
            continue

        # URL berakhiran UUID: /lowongan/radiografer-c-arm-01a0525f-a841-...
        m = re.search(
            r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
            url, re.I)
        job_id = m.group(1) if m else url

        location = job.get("location") or "Indonesia"

        bits = []
        if job.get("education"):
            bits.append(f"Pendidikan minimal: {job['education']}")
        if job.get("days_per_week"):
            bits.append(f"{job['days_per_week']} hari/minggu")
        if job.get("day_off"):
            bits.append(f"Libur {job['day_off']}")
        if job.get("quota") is not None:
            bits.append(f"Kuota: {job['quota']}")
        if job.get("applicants") is not None:
            bits.append(f"Pelamar: {job['applicants']}")
        peluang = _peluang(job.get("quota"), job.get("applicants"),
                           job.get("chance_label"))
        if peluang:
            bits.append(peluang)
        description = " | ".join(bits) or None

        records.append({
            "job_id": str(job_id),
            "site": "maganghub",
            "job_url": url,
            "job_url_direct": url,
            "title": title,
            "company": job.get("company") or "Penyelenggara magang",
            "location": location,
            "date_posted": None,
            "job_type": "Internship",
            "salary_source": None,
            "interval": None,
            "min_amount": None,
            "max_amount": None,
            "currency": None,
            "is_remote": False,
            "job_level": job.get("education"),
            "job_function": job.get("field"),
            "listing_type": None,
            "emails": None,
            "description": description,
            "company_industry": None,
            "company_url": BASE_URL,
            "company_logo": None,
            "company_url_direct": None,
            "company_addresses": location,
            "company_num_employees": None,
            "company_revenue": None,
            "company_description": None,
            "skills": None,
            "experience_range": job.get("education"),
            "company_rating": None,
            "company_reviews_count": None,
            # Kuota = jumlah peserta yang diterima, sepadan dengan vacancy_count
            "vacancy_count": job.get("quota"),
            "work_from_home_type": "onsite",
            "raw_salary": None,
            "category": classify_job(title, job.get("field"), search_term),
            "work_arrangement": classify_work_arrangement(
                False, title, "Internship", location),
            "employment_type": "magang",
            "search_term": search_term or "scrapeall",
            "search_location": search_location or location,
            "requested_by_chat_id": str(requested_by_chat_id),
        })
    return records
