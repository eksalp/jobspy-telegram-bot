# Alat bantu development

Isi folder ini BUKAN bagian bot yang jalan di Telegram — semuanya alat untuk
menambah situs karir baru ke registry (`sites/companies.py`). `bot.py` tidak
mengimpor apa pun dari folder ini.

Jalankan semuanya **dari root project**, bukan dari dalam `tools/`:

```bash
python tools/detect_ats.py          # deteksi platform ATS untuk situs di sites/pending.py
python tools/try_selector.py "<url>" # uji CSS selector kartu loker di satu halaman
python tools/diag.py <situs>         # diagnosa kenapa situs tertentu 0 hasil
python tools/lihat_kartu.py <url> "<kata>"  # cari kartu lewat teksnya, bukan class
```

Detail tiap alat ada di docstring masing-masing file.
