# Deploy ke Render (gratis, cocok untuk pemakaian jarang / ~1x sehari)

Bot mode ini (`app.py`) pakai **webhook**, bukan polling: Telegram yang akan
"membangunkan" server begitu kamu kirim `/update`. Render boleh tidur kalau nganggur —
itu wajar dan gratis. Konsekuensinya: balasan pertama setelah lama nganggur bisa lambat
~30-60 detik (cold start), setelah itu normal.

Tidak perlu install `git` di komputer — semua bisa lewat browser.

---

## 1. Upload kode ke GitHub (lewat web, tanpa command line)

1. Buat akun di https://github.com kalau belum punya (gratis).
2. Klik ikon **+** di kanan atas → **New repository**.
   - Nama bebas, misal `jobspy-telegram-bot`
   - Pilih **Private** (biar kode & struktur env kamu tidak publik)
   - Klik **Create repository**
3. Di halaman repo kosong itu, klik **uploading an existing file**.
4. Dari file explorer, drag-and-drop **semua isi folder** `jobspy-telegram-bot`
   (bukan folder zip-nya, tapi isi di dalamnya: `app.py`, `bot.py`, `requirements.txt`,
   dst) ke area upload.

   ⚠️ **Jangan upload file `.env`** kalau kamu sudah pernah mengisinya dengan token asli
   — itu rahasia, biar diisi langsung di Render nanti (bukan di GitHub). Kalau belum
   diisi (masih `.env.example`), upload boleh saja, tapi lebih aman skip file `.env`.
5. Scroll ke bawah, klik **Commit changes**.

## 2. Bikin akun Render & hubungkan ke repo

1. Buka https://render.com → **Get Started** → daftar (bisa pakai akun GitHub kamu
   langsung, lebih cepat, tidak perlu kartu kredit).
2. Di dashboard Render → **New +** → **Web Service**.
3. Pilih **Build and deploy from a Git repository** → hubungkan akun GitHub kamu →
   pilih repo `jobspy-telegram-bot` yang tadi dibuat.
4. Isi konfigurasi:
   - **Name**: bebas, misal `jobspy-telegram-bot`
   - **Region**: pilih yang terdekat (misal Singapore)
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app --timeout 120`
   - **Instance Type**: **Free**
5. Di bagian **Environment Variables**, klik **Add Environment Variable** satu-satu:

   | Key | Value |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | token dari @BotFather |
   | `TELEGRAM_WEBHOOK_SECRET` | bikin string acak sendiri, misal `jbspy8x9k2m` (bebas, buat verifikasi keamanan) |
   | `SUPABASE_URL` | dari Supabase Project Settings → API |
   | `SUPABASE_SERVICE_ROLE_KEY` | dari Supabase Project Settings → API |
   | `DEFAULT_SITES` | `indeed,linkedin` |
   | `DEFAULT_LOCATION` | `Indonesia` |
   | `DEFAULT_COUNTRY_INDEED` | `Indonesia` |
   | `DEFAULT_RESULTS_WANTED` | `30` |
   | `DEFAULT_HOURS_OLD` | `72` |

6. Klik **Create Web Service**. Render akan build & deploy otomatis (~2-5 menit).
7. Setelah selesai, catat URL yang diberikan Render, bentuknya seperti:
   `https://jobspy-telegram-bot-xxxx.onrender.com`

## 3. Daftarkan URL webhook ke Telegram

Ini langkah terakhir — cukup buka satu URL di browser (ganti bagian `<...>` sesuai
punyamu):

```
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://<RENDER_URL>/webhook/<TELEGRAM_WEBHOOK_SECRET>&secret_token=<TELEGRAM_WEBHOOK_SECRET>
```

Contoh kalau token bot = `123:ABC` dan webhook secret = `jbspy8x9k2m`, dan Render URL =
`https://jobspy-telegram-bot-xxxx.onrender.com`:

```
https://api.telegram.org/bot123:ABC/setWebhook?url=https://jobspy-telegram-bot-xxxx.onrender.com/webhook/jbspy8x9k2m&secret_token=jbspy8x9k2m
```

Paste ke address bar browser, Enter. Kalau berhasil, muncul respons JSON:
`{"ok":true,"result":true,"description":"Webhook was set"}`

## 4. Tes

Chat `/start` ke bot kamu di Telegram. Karena baru pertama kali (server lagi tidur),
tunggu ~30-60 detik untuk balasan pertama. Setelah itu coba:

```
/update data analyst --location Bandung --results 20
```

Kalau bot tidak balas sama sekali, cek log di Render dashboard → tab **Logs** pada
service kamu, untuk lihat errornya.

## 5. Update kode di kemudian hari

Edit file langsung di GitHub (klik file → ikon pensil → edit → Commit), atau upload
ulang file yang berubah lewat cara di Langkah 1. Render otomatis re-deploy setiap ada
commit baru ke branch `main`.

## Catatan penting

- **Jangan bagikan** `TELEGRAM_WEBHOOK_SECRET` atau `SUPABASE_SERVICE_ROLE_KEY` ke
  siapa pun — keduanya cuma boleh ada di Environment Variables Render, jangan pernah
  ditulis di kode atau di-commit ke GitHub.
- Kalau nanti mau ganti `TELEGRAM_WEBHOOK_SECRET`, update juga di Render env var lalu
  jalankan lagi URL `setWebhook` di Langkah 3 dengan secret yang baru.
- Free tier Render dapat 750 jam instance gratis/bulan per workspace — untuk
  pemakaian ~1x/hari yang sebagian besar waktu bot tidur, ini jauh lebih dari cukup.
