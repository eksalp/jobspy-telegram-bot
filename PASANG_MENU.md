# Memasang menu perintah per situs

## Dua baris di bot.py

Di dalam `def main()`, setelah semua `app.add_handler(...)` yang sudah ada dan
SEBELUM `app.run_polling(...)`, tambahkan:

```python
    import site_commands
    site_commands.register_site_commands(app, is_allowed, escape_md)
```

Itu saja. `site_commands.py` mengurus sisanya.

## Yang didapat

Satu perintah untuk tiap situs terdaftar, dibangkitkan otomatis dari registry:

    /magenta         scrape MAGENTA saja
    /pertamina_pdc   scrape Pertamina PDC saja
    /pertaminapdc    alias tanpa garis bawah, sama saja
    /dealls          scrape Dealls saja
    ...

Plus `/updateall` untuk menjalankan semua situs sekaligus.

Semuanya juga didaftarkan ke Telegram lewat `set_my_commands()`, jadi muncul di
menu hamburger dan autocomplete saat mengetik "/". Situs terverifikasi
diurutkan lebih dulu.

## Menambah situs baru

Tidak perlu menyentuh apa pun. Daftar perintah dibangkitkan dari
`sites.REGISTRY`, jadi begitu sebuah situs didaftarkan di `companies.py`, ia
otomatis dapat perintahnya sendiri pada restart berikutnya.

## Catatan

Menu Telegram di-cache di sisi klien. Kalau perintah baru belum muncul setelah
restart, tutup dan buka lagi chat-nya, atau tunggu beberapa menit.

Tiap perintah situs memakai `SCRAPE_ALL_RESULTS` dari .env sebagai batas.
Dengan MagangHub (~22.600 loker), Dealls (~1200), dan Kalibrr (~1180) sudah
masuk registry, nilai 300 jauh lebih masuk akal daripada 10000.

Batas Telegram 100 perintah. Saat ini terpakai 25, jadi masih longgar.
