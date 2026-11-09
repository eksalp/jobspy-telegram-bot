# Menambah situs karir baru

## Yang berubah

Sebelumnya tiap situs butuh: satu file scraper penuh (~200 baris, 40 baris di antaranya dict record yang sama persis), dua baris import di `bot.py`, satu `use_xxx = ...`, satu blok `if use_xxx:` di `update_cmd`, dan satu baris lagi di `scrapeall_cmd`. Enam tempat per situs. Untuk 35 situs itu sekitar 700 baris tambahan di `bot.py` saja.

Sekarang satu situs = satu blok konfigurasi di `sites/companies.py`. `bot.py` tidak perlu disentuh lagi.

```
sites/
  base.py         helper bersama + make_record() (dict 40 kolom, ditulis sekali)
  registry.py     daftar situs + resolve() + run()
  workday.py      adapter Workday
  phenom.py       adapter Phenom People
  ats_json.py     adapter Greenhouse / Lever / SmartRecruiters / Ashby
  html_sites.py   adapter SuccessFactors / HTML statis / Playwright
  companies.py    <- konfigurasi 35 perusahaan (satu-satunya file yang kamu edit)
  legacy.py       pembungkus scraper lama (bca, shopee, dst — kodenya tidak diubah)
detect_ats.py     deteksi platform tiap situs, hasilkan konfigurasi siap-copy
```

## Alur untuk 27 situs yang belum terdeteksi

Aku tidak bisa menebak konfigurasi 27 situs sisanya tanpa melihat responsnya sungguhan — kalau ditebak, hasilnya 27 scraper yang gagal diam-diam. `detect_ats.py` menyelesaikan ini secara otomatis. Jalankan dari mesinmu:

```bash
pip install -r requirements.txt
python detect_ats.py
```

Outputnya seperti ini:

```
OK gojek          greenhouse       48 loker
OK indofood       successfactors   -
?? telkom         tidak terdeteksi halaman depan tampak butuh login
...
======================================================================
RINGKASAN PLATFORM
  greenhouse          4 situs: gojek, paragon, ...
  successfactors      3 situs: indofood, kalbe, ...
  tidak terdeteksi   11 situs: telkom, byd, ...
```

Lalu file `generated_sites.py` berisi baris `register_*(...)` yang tinggal di-review dan dipindah ke `sites/companies.py`. Untuk yang sudah terverifikasi (`OK`), biasanya bisa langsung copy tanpa diubah.

## Menambah manual

**Kalau platformnya punya API** (paling gampang):

```python
register_ats("greenhouse", name="gojek", label="Gojek", company="Gojek (GoTo Group)",
             token="gojek", industry="Technology", verified=True, tags={"tech", "id"})
```

**Kalau HTML statis**, deskripsikan strukturnya sebagai CSS selector — tanpa menulis kode scraping:

```python
register_html("static", name="nutrifood", label="Nutrifood",
              company="PT Nutrifood Indonesia",
              list_url="https://nutrifood.co.id/vacancy/",
              card="div.vacancy-item",      # tiap kartu loker
              title="h3.vacancy-title",
              location="span.vacancy-loc",
              page_param="page",
              industry="Food & Beverage")
```

**Kalau SPA** (HTML-nya kosong, konten diisi JavaScript), sama persis tapi `"playwright"`. Situs ini otomatis ditandai `needs_browser=True` sehingga bisa dilewati dengan alias `fast`.

## Perintah baru di Telegram

- `/sites` — daftar semua situs terdaftar. ✅ sudah dites, ⚠️ belum dites, 🐢 lambat karena butuh browser.
- `--sites verified` — hanya situs yang sudah dikonfirmasi jalan
- `--sites all` — semua situs perusahaan
- `--sites fast` — semua kecuali yang butuh Playwright
- `--sites tag:bank` — per kategori (`bank`, `bumn`, `fmcg`, `tech`, `id`)

## Catatan jujur soal status

Dari 35 situs di daftarmu:

- **1 terverifikasi**: tiket.com. Halaman karirnya mengarahkan lamaran ke Workday tenant `tiketdotcom`, dan Workday punya JSON API publik — ini yang paling bersih dari semuanya.
- **5 dikonfigurasi tapi belum dites**: Unilever, PMI, L'Oréal, Danone (dugaan Phenom People), Traveloka (selector tebakan). Jalankan dan lihat hasilnya; kalau 0 loker, `detect_ats.py` akan memberi tahu platform yang benar.
- **27 belum terdeteksi**: ada di `PENDING` dalam `sites/companies.py`, menunggu `detect_ats.py`.
- **2 kemungkinan besar tidak bisa di-scrape**: Telkom (`recruitment.telkom.co.id/login_page` — listing di balik login) dan BNI (URL yang kamu kasih adalah homepage korporat, bukan halaman karir). Untuk keduanya, lebih realistis mengandalkan JobSpy/LinkedIn atau `lokerbumn` yang sudah ada.

Scraper lama (`bca.py`, `shopee.py`, `lokerbumn.py`, `pertamina_ptc.py`, `astracareer.py`, `talentics.py`) tidak diubah sebarispun — hanya dibungkus di `sites/legacy.py`. Kalau ada yang aneh, perilakunya masih bisa dibandingkan langsung dengan versi sebelumnya.

## Dua bug yang sekalian diperbaiki

- `bot.py` mengimpor `shopee` dan `pertamina_ptc` dua kali, dan `use_shopee`/`use_pertamina_ptc` di-assign dua kali.
- Handler `/scrapeall` didaftarkan dua kali ke `Application`, jadi tiap perintah `/scrapeall` menjalankan scraping dobel.
