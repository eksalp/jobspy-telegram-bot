# Scrape otomatis setiap malam dengan GitHub Actions

Setiap hari **jam 01.00 WIB**, GitHub menjalankan dua tahap berurutan:
1. **Reset + semua situs**: mengosongkan tabel `jobs` (sama seperti `/reset`), lalu scrape semua situs (sama seperti `/updateall`). Ringkasan 🗓 dikirim ke Telegram.
2. **Indeed & LinkedIn**: 68 kata kunci (sama seperti `/carikerja` → Semua kelompok). Ringkasan 🔎 dikirim ke Telegram.

Tahap 2 tetap jalan walaupun tahap 1 gagal. Masing-masing punya batas 6 jam sendiri. Hasil tiap situs dan tiap kata kunci langsung tersimpan.

Gratis dan tanpa kartu kredit. Laptop boleh mati.

Yang **tidak** ditangani GitHub: perintah interaktif di Telegram (`/carikerja`, `/update`, `/reset`, …). Untuk itu bot tetap harus jalan di Mac (`python bot.py`) saat kamu butuh.

---

## 0. Syarat

- Fungsi `reset_jobs()` sudah dibuat di Supabase (`reset_jobs.sql`). Kalau `/reset` di Telegram sudah berhasil, berarti sudah.
- File dari zip sudah disalin ke folder bot, **termasuk yang tersembunyi**: `.gitignore` dan folder `.github/`. Finder menyembunyikan file berawalan titik, jadi salin lewat Terminal. Ganti lokasi zip kalau berbeda:

```bash
cd ~/Downloads && unzip -o scrape_github_actions.zip
cp -R ~/Downloads/scrape_github_actions/. /Users/eksalp/Downloads/Project/jobspy-telegram-bot/
```

## 1. Buat akun GitHub

Daftar di https://github.com/signup. Gratis, cukup email.

## 2. Unggah folder bot ke GitHub (pakai GitHub Desktop)

1. Unduh dan instal **GitHub Desktop**: https://desktop.github.com, lalu login dengan akun GitHub.
2. Menu **File → Add Local Repository…** → pilih folder `jobspy-telegram-bot`.
   Kalau muncul *"This directory does not appear to be a Git repository"*, klik **create a repository** → **Create Repository**.
3. **CEK DULU daftar file di kiri sebelum commit:**
   - `.env` **TIDAK BOLEH ADA** di daftar. Isinya token bot dan kunci Supabase. `.gitignore` sudah mengecualikannya, tapi pastikan dengan mata sendiri.
   - `glints_session.txt` juga tidak boleh ada.
   - Kalau salah satunya muncul, **berhenti** dan pastikan `.gitignore` sudah ada di folder bot.
4. Isi ringkasan di kiri bawah (misal `bot pertama kali`) → **Commit to main**.
5. Klik **Publish repository**.
   - **Hilangkan centang "Keep this code private"** (jadikan repo **publik**). Di repo publik, GitHub Actions gratis tanpa batas menit. Di repo privat jatahnya sekitar 2.000 menit per bulan, padahal scrape harian bisa 1,5–3 jam, jadi akan habis di pertengahan bulan.
   - Repo publik artinya **kode** bisa dibaca orang lain. Itu aman selama `.env` tidak ikut, karena semua rahasia disimpan terpisah di langkah 3.

## 3. Simpan rahasia di GitHub

Buka repo kamu di github.com → **Settings** → **Secrets and variables** → **Actions** → tab **Secrets** → **New repository secret**. Buat empat secret ini. Nilainya salin dari `.env` di Mac, **tanpa** tanda kutip:

| Name | Isi |
|---|---|
| `TELEGRAM_BOT_TOKEN` | token bot |
| `SUPABASE_URL` | URL project Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | service role key Supabase |
| `ALLOWED_CHAT_IDS` | chat ID kamu (tujuan ringkasan) |

Opsional, di tab **Variables**: `SCRAPE_ALL_RESULTS`, yaitu batas lowongan per situs. Default-nya 20000.

Secret yang disimpan di sini **tidak pernah terlihat** di log maupun oleh pengunjung repo.

## 4. Uji sekali sekarang

1. Di repo → tab **Actions**. Kalau diminta, klik **I understand my workflows, go ahead and enable them**.
2. Pilih **Scrape harian** di kiri → **Run workflow**.
   - Centang **reset** kalau mau tabel dikosongkan dulu, atau hilangkan centangnya untuk hanya meng-update.
   - Centang **carikerja** kalau Indeed & LinkedIn juga mau dijalankan.
3. Klik run yang muncul untuk melihat progres. Ada dua kotak: **Reset + semua situs** (log `(3/29) Kalibrr ...`) dan **Indeed & LinkedIn** (log `(12/68) data scientist ...`).
4. Kamu akan menerima **dua pesan** di Telegram: 🗓 setelah tahap 1 dan 🔎 setelah tahap 2. Kalau tidak ada pesan, cek secret `ALLOWED_CHAT_IDS`.

Setelah ini, workflow jalan sendiri setiap malam.

## 5. Hal yang perlu diketahui

- **Jamnya tidak selalu tepat 01.00.** Jadwal GitHub kadang terlambat 10–30 menit, terutama saat server mereka sibuk.
- **Selama scrape berjalan (±3–5 jam untuk kedua tahap), Jobly berisi sebagian data.** Tabel kosong jam 01.00 lalu terisi situs demi situs. Itu sebabnya dipilih tengah malam.
- **Jadwal dimatikan otomatis setelah 60 hari tanpa aktivitas di repo.** GitHub mengirim email peringatan dulu. Cukup buka tab Actions → **Enable workflow**, atau commit perubahan apa saja.
- **IP GitHub adalah IP datacenter.** Situs yang memblokir server cloud bisa menghasilkan 0 di sini walaupun di Mac jalan. Lihat ringkasan Telegram: situs dengan ⚪ 0 atau ❌ adalah kandidatnya.
- **Kalau kamu mengubah kode di Mac**, buka GitHub Desktop → commit → **Push origin**. Scrape berikutnya otomatis memakai kode terbaru.
- **Mengubah jam:** edit baris `cron` di `.github/workflows/scrape-harian.yml`. Waktunya dalam UTC (WIB dikurangi 7 jam). Contoh: `"0 22 * * *"` = 05.00 WIB.
