from __future__ import annotations

"""
Daftar semua perusahaan yang di-scrape. INI SATU-SATUNYA FILE YANG PERLU DIEDIT
kalau mau menambah / memperbaiki situs.

Status tiap entry ditandai `verified`:
  verified=True   endpoint sudah dikonfirmasi benar
  verified=False  konfigurasi berdasarkan pola umum platform-nya, BELUM dites
                  terhadap situs aslinya — kemungkinan besar perlu penyesuaian

Untuk entry yang masih di PENDING (bawah file), platform-nya belum diketahui.
Jalankan `python detect_ats.py` dari mesinmu (yang internetnya bebas) — script
itu akan mendeteksi platform tiap situs dan mencetak baris registrasi yang
tinggal di-copy ke file ini.
"""
# sites/companies.py
from .legacy import register_legacy_sites
from .glints_site import register_glints        # ← tambah ini

from .ats_json import register_ats
from .enrich import EnrichConfig
from .html_sites import register_html
from .phenom import register_phenom
from .registry import SiteSpec, register
from .workday import register_workday

# --------------------------------------------------------------------------- #
# Scraper lama — dibungkus ulang supaya ikut registry, kodenya tidak diubah
# --------------------------------------------------------------------------- #
from .legacy import register_legacy_sites, register_web3career

register_legacy_sites()
register_web3career()

# Indofood: ASP.NET page method, ditemukan lewat vacancy.js.
# Bukan HTML scraping — endpoint JSON, jadi tidak rusak kalau temanya diganti.
from .indofood_site import register_indofood  # noqa: E402

register_indofood()

# Pertamina PDC: ASP.NET Razor Pages. Endpoint-nya ?handler=AllJobVacancies,
# bukan /api/... — konvensi Razor Pages yang mudah terlewat kalau hanya
# mencari pola "api/" di DevTools. 66 lowongan aktif.
from .pertamina_pdc_site import register_pertamina_pdc  # noqa: E402

register_pertamina_pdc()

# Dealls: agregator lowongan Indonesia. Memakai API publik backend-nya
# (api.sejutacita.id) — bukan scraping HTML. Halaman webnya cuma menampilkan
# 18 lowongan karena tombol "Lihat Lebih Banyak" memuat lewat JavaScript;
# lewat API, seluruh katalog terjangkau (~1200 loker). Satu-satunya sumber
# yang memberi RENTANG GAJI sebagai angka.
from .dealls_site import register_dealls  # noqa: E402

register_dealls()

# Kalibrr: agregator Indonesia/Filipina. Memakai API publik
# kjs/job_board/search — bukan scraping HTML. Halaman webnya cuma menampilkan
# ~17 loker karena tombol "Load more jobs" memuat lewat JavaScript; lewat API,
# seluruh katalog terjangkau (~1180 loker) berikut deskripsi dan kualifikasi.
from .kalibrr_site import register_kalibrr  # noqa: E402

register_kalibrr()

# MagangHub Kemnaker: program magang nasional. Isinya berbeda dari semua
# sumber lain — program pemerintah, bukan lowongan komersial — jadi hampir
# tidak tumpang tindih dengan agregator mana pun.
from .maganghub_site import register_maganghub  # noqa: E402

register_maganghub()

# MAGENTA (Magang Generasi Bertalenta): program magang Kementerian BUMN.
# Katalognya kecil (puluhan) tapi isinya BUMN besar — Kimia Farma, Pegadaian,
# Pelindo, Telkom. Melengkapi MagangHub yang penyelenggaranya umum.
from .magenta_site import register_magenta  # noqa: E402

register_magenta()

# JobStreet Indonesia (grup SEEK). Halaman webnya memblokir skrip lewat bot
# detection, tapi API pencarian frontend-nya terbuka tanpa auth. Skemanya
# hasil rekayasa balik — jalankan `python jobstreet.py` untuk memeriksa bentuk
# respons aslinya kalau pemetaan kolomnya meleset.
from .jobstreet_site import register_jobstreet  # noqa: E402

register_jobstreet()


# --------------------------------------------------------------------------- #
# SUDAH DIKONFIRMASI
# --------------------------------------------------------------------------- #

# tiket.com mengarahkan semua lamaran ke Workday tenant `tiketdotcom`
# (dikonfirmasi dari tombol Apply di careers.tiket.com).
register_workday(
    name="tiket", label="tiket.com", company="PT Global Tiket Network (tiket.com)",
    tenant="tiketdotcom", site="Tiket_Careers", pod="wd3",
    industry="Travel & E-Commerce",
    company_url_direct="https://careers.tiket.com",
    verified=True, tags={"tech", "id"},
)


register_workday(
    name="kalbe", label="Kalbe Farma", company="PT Kalbe Farma Tbk",
    tenant="kalbe", site="External", pod="wd102",
    industry="Pharmaceutical & Healthcare",
    company_url_direct="https://www.kalbe.co.id",
    verified=True, tags={"pharma", "id"},
)

# Token Lever-nya `GoToGroup`, jadi hasilnya mencakup seluruh GoTo
# (Gojek + Tokopedia + GoTo Financial), bukan Gojek saja.
register_ats(
    "lever", name="gojek", label="Gojek / GoTo", company="GoTo Group (Gojek)",
    token="GoToGroup",
    industry="Technology",
    company_url_direct="https://www.gotocompany.com",
    verified=True, tags={"tech", "id"},
)

# PMI terbukti memakai Phenom People — endpoint /widgets mengembalikan
# lowongan Jakarta. Unilever, L'Oreal, dan Danone SUDAH DICOBA dengan adapter
# yang sama dan ketiganya menjawab 404 di /widgets, jadi platformnya bukan
# Phenom. Ketiganya dikembalikan ke pending.py.
register_phenom(
    name="pmi", label="Philip Morris International", company="Philip Morris International",
    host="https://join.pmicareers.com", country="id",
    selected_fields={"country": ["Indonesia"]},
    industry="Tobacco / FMCG",
    company_url_direct="https://www.pmi.com",
    verified=True, tags={"fmcg", "id"},
)

# Indomaret: HTML statis biasa. Diverifikasi lewat try_selector.py — 5 kartu,
# judul & URL asli. Isinya jalur karir (MDP, IT Specialist, Professional,
# Staff), bukan lowongan per posisi; memang begitu situsnya menyusun listing.
# Judul diambil dari teks anchor karena tidak ada elemen judul terpisah.
register_html(
    "static", name="indomaret", label="Indomaret", company="Indomaret Group",
    list_url="https://career.indomaretgroup.com/jobs",
    card="div.col-lg-6",
    # Pengayaan dimatikan: halaman tujuannya adalah halaman kategori karir,
    # dan isinya cuma banner peringatan penipuan — bukan deskripsi lowongan.
    enrich=False,
    industry="Retail",
    company_url_direct="https://www.indomaret.co.id",
    verified=True, tags={"retail", "id"},
)


# Nutrifood: WordPress biasa. Semua lowongan ada di SATU halaman sebagai
# heading + daftar kualifikasi, tanpa halaman detail per posisi — jadi tidak
# ada URL unik per lowongan dan job_id dibentuk dari judul.
# Filter kurung siku dipakai karena Nutrifood menandai posisi dengan
# "[Fulltime] ..." / "[Internship] ...", sehingga heading biasa terabaikan.
register_html(
    "heading_list", name="nutrifood", label="Nutrifood",
    company="PT Nutrifood Indonesia",
    list_url="https://nutrifood.co.id/vacancy/",
    heading="h4.wp-block-heading",
    title_filter=r"^\s*\[",
    industry="Food & Beverage",
    company_url_direct="https://www.nutrifood.co.id",
    verified=True, tags={"fmcg", "id"},
)


# Pertamina PTC: scraper lama (pertamina_ptc.py) mengembalikan 0 padahal
# halamannya jelas memuat lowongan — selectornya sudah usang. Diganti adapter
# labeled_block: tiap lowongan adalah blok "Label: nilai" tanpa link detail,
# dikenali dari label "Jenis Pekerjaan" yang pasti ada di setiap blok.
# job_id memakai kode resmi PTC dari judul (mis. PTC0126D01765), jadi stabil
# walau judulnya diedit.
register_html(
    "labeled_block", name="pertamina_ptc",
    label="Pertamina Training & Consulting",
    company="PT Pertamina Training & Consulting",
    list_url="https://recruitment.pertamina-ptc.com/guest/joblist",
    marker="Jenis Pekerjaan",
    labels={"job_type": "Jenis Pekerjaan", "description": "Kualifikasi",
            "location": "Lokasi"},
    id_regex=r"\[\s*([A-Z0-9]+)\s*\]",
    enrich=False,          # semua data sudah ada di listing
    industry="Energy / Oil & Gas",
    company_url_direct="https://www.pertamina-ptc.com",
    verified=True, tags={"bumn", "energy", "id"},
)


# --------------------------------------------------------------------------- #
# BELUM TERDETEKSI
# --------------------------------------------------------------------------- #
# Daftarnya ada di sites/pending.py (file terpisah tanpa import apapun, supaya
# detect_ats.py bisa membacanya tanpa butuh bs4/playwright/jobspy).
from .pending import PENDING  # noqa: E402


__all__ = ["PENDING", "SiteSpec", "register"]




register_glints()

# Karir.com: API v2/search/opportunities. URL lowongan hasil scrape
# (/lowongan/{id}) belum diverifikasi buka langsung di browser.
from .karircom_site import register_karircom  # noqa: E402

register_karircom()

# Jobindo.com: API Inertia.js partial-reload, ~197 loker.
from .jobindo_site import register_jobindo  # noqa: E402

register_jobindo()

# TopLoker: HTML statis, judul kartu terpotong tampilannya -- diambil dari
# slug URL, bukan span tampilan.
from .toploker_site import register_toploker  # noqa: E402

register_toploker()



# KitaLulus: API GraphQL resmi, ~10.000 loker. Sumber asli di balik mirror
# Karirhub Kemnaker.
from .kitalulus_site import register_kitalulus  # noqa: E402

register_kitalulus()

# Talentics: API JSON /ajaxs/jobs + sesi Laravel (cookie + token CSRF).
from .talentics_site import register_talentics  # noqa: E402

register_talentics()

# JakartaKerja: daftar dari /page/N/, detail dari JSON-LD JobPosting.
from .jakartakerja_site import register_jakartakerja  # noqa: E402

register_jakartakerja()

# Lowongan remote internasional dari feed resmi (RSS WWR, API Remote OK).
from .remote_site import register_remote_boards  # noqa: E402

register_remote_boards()

                               # ← dan ini