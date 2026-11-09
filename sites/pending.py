from __future__ import annotations

"""
Daftar situs yang platform ATS-nya belum diketahui.

File ini SENGAJA tidak mengimpor apapun — supaya detect_ats.py bisa membacanya
tanpa menarik bs4, playwright, jobspy, dan scraper lama. Menjalankan detektor
seharusnya cuma butuh `requests`.

Format: nama_situs -> (label, URL karir, nama perusahaan, industri)
Begitu satu situs berhasil dikonfigurasi di companies.py, hapus entry-nya dari
sini.
"""

PENDING: dict[str, tuple[str, str, str, str]] = {
    "pertamina":    ("Pertamina", "https://recruitment.pertamina.com",
                     "PT Pertamina (Persero)", "Energy / Oil & Gas"),
    "telkom":       ("Telkom Indonesia", "http://recruitment.telkom.co.id/login_page",
                     "PT Telkom Indonesia Tbk", "Telecommunications"),
    # Sinar Mas Land — DINONAKTIFKAN setelah 5 percobaan. Temuan lengkap:
    #
    #   Listing  : https://career.sinarmasland.com/vacancy-all  (4 lowongan)
    #   Blok     : div.col-md-6.box-job  -> HANYA berisi deskripsi
    #   Link     : vacancy-detail?kayttajatunnus=<kategori>&jid=<lowongan>
    #              `kayttajatunnus` = ID KATEGORI (sama untuk semua),
    #              `jid` = ID lowongan (pembeda sesungguhnya)
    #
    # Masalahnya: judul lowongan TIDAK ADA di dalam blok deskripsinya, dan
    # blok itu tidak punya saudara sebelumnya. Halaman detail juga tidak
    # menolong — satu halaman dipakai bersama untuk seluruh kategori, dan
    # judulnya berisi nama kelompok ("Sales & Marketing"), bukan posisi.
    #
    # Judul asli ada di daftar "Current Vacancy", tapi tidak ada atribut apa
    # pun yang menghubungkannya ke `jid`. Satu-satunya cara adalah memasangkan
    # berdasarkan urutan — dan itu bisa menukar judul antar lowongan tanpa
    # terdeteksi. Untuk 4 lowongan, risikonya tidak sepadan.
    #
    # Kalau mau dilanjutkan: pakai Playwright, klik tiap judul di daftar
    # "Current Vacancy" dan baca `jid` yang dimuat — itu memberi pemetaan
    # judul->jid yang benar, bukan tebakan urutan.
    "sinarmas":     ("Sinarmas Land", "https://career.sinarmasland.com/vacancy-all",
                     "Sinar Mas Land", "Property & Real Estate"),
    "bni":          ("BNI", "https://bni.co.id/en-us/",
                     "PT Bank Negara Indonesia Tbk", "Banking & Financial Services"),
    # Unilever, L'Oreal, Danone: SUDAH DICOBA dengan adapter Phenom People
    # (POST /widgets) — ketiganya menjawab 404, jadi platformnya BUKAN Phenom.
    # PMI dengan adapter yang sama berhasil, jadi adapternya sendiri benar.
    # Perlu deteksi ulang; kemungkinan Avature, SuccessFactors, atau custom.
    "unilever":     ("Unilever", "https://careers.unilever.com/en/indonesia",
                     "Unilever Indonesia", "FMCG / Consumer Goods"),
    "loreal":       ("L'Oreal", "https://careers.loreal.com/en_US/content/Indonesia",
                     "L'Oreal Indonesia", "Beauty & Personal Care"),
    "danone":       ("Danone", "https://careers.danone.com/id/id/home.html",
                     "Danone Indonesia", "Food & Beverage"),
    # Traveloka: selector tebakan mengembalikan 0. Situsnya Next.js;
    # kemungkinan ada XHR ke /api/jobs — cek tab Network seperti Indofood.
    "traveloka":    ("Traveloka", "https://careers.traveloka.com/jobs",
                     "Traveloka", "Travel & E-Commerce"),
    # Wings: SuccessFactors Career Site Builder yang merender daftar loker
    # lewat JavaScript. Selector SF generasi lama (a.jobTitle-link) tidak
    # menemukan apa pun; probe /rss, /go/All-Jobs/, dan paging juga nihil.
    "wings":        ("Wings Group", "https://www.wingscareer.com",
                     "Wings Group Indonesia", "FMCG / Consumer Goods"),
    "nestle":       ("Nestlé", "https://nestle.co.id/jobs",
                     "PT Nestlé Indonesia", "Food & Beverage"),
    "kawanlama":    ("Kawan Lama Group", "https://karir.kawanlamagroup.com",
                     "Kawan Lama Group", "Retail & Distribution"),
    "yamaha":       ("Yamaha", "http://yamaha-motor.co.id/corporate/career",
                     "PT Yamaha Indonesia Motor Manufacturing", "Automotive"),
    # BYD: situs dealer (PT Harmoni Target Indonesia), bukan BYD Indonesia
    # korporat. Halaman karirnya cuma memuat SATU lowongan bertaut, dengan URL
    # post WordPress bertanggal yang berubah tiap tahun. Posisi lain hanya ada
    # sebagai pilihan dropdown di formulir, tanpa link. Tidak layak di-scrape.
    # Mandiri: halaman karirnya memuat sidik jari Talentics, jadi lowongannya
    # kemungkinan diposting lewat jobs.talentics.id. Scraper talentics.py yang
    # sudah ada mungkin bisa dipakai kalau selectornya diperbaiki.
    "mandiri":      ("Bank Mandiri", "https://www.bankmandiri.co.id/mandiri-career",
                     "PT Bank Mandiri Tbk", "Banking & Financial Services"),
    "mayora":       ("Mayora", "http://mayoraindah.co.id/landing/karier-18",
                     "PT Mayora Indah Tbk", "Food & Beverage"),
    "sampoerna":    ("Sampoerna", "http://sampoerna.com/id/careers",
                     "PT HM Sampoerna Tbk", "Tobacco / FMCG"),
    # Indosat: mengembalikan 403 untuk requests, bahkan dengan header browser
    # lengkap (Accept, Sec-Fetch-*, Upgrade-Insecure-Requests). Proteksinya di
    # level jaringan/WAF, bukan sekadar pemeriksaan User-Agent — jadi tidak
    # bisa diakali dari sisi header. Perlu Playwright kalau mau dikerjakan.
    "indosat":      ("Indosat Ooredoo Hutchison",
                     "https://www.ooredoo.com/id/careers/opportunities/",
                     "PT Indosat Ooredoo Hutchison Tbk", "Telecommunications"),
    "sig":          ("Semen Indonesia Group", "https://sig.id/karir",
                     "PT Semen Indonesia (Persero) Tbk", "Building Materials"),
    "paragon":      ("Paragon Corp", "http://career.paragon-innovation.com",
                     "PT Paragon Technology and Innovation", "Beauty & Personal Care"),
    "alfamart":     ("Alfamart", "https://alfakarir.alfamart.co.id",
                     "PT Sumber Alfaria Trijaya Tbk", "Retail"),
    "djarum":       ("Djarum", "https://career.djarum.com/home",
                     "PT Djarum", "Tobacco / FMCG"),
    "map":          ("MAP", "http://map.co.id/id/careers/",
                     "PT Mitra Adiperkasa Tbk", "Retail & Lifestyle"),
    "kai":          ("KAI Wisata", "https://recruitment.kaiwisata.id",
                     "PT KA Pariwisata (KAI Wisata)", "Transportation & Tourism"),
    "citilink":     ("Citilink", "http://recruitment.citilink.co.id/career",
                     "PT Citilink Indonesia", "Aviation"),
}
