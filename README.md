# JobSpy Telegram Bot → Supabase

Bot Telegram yang, saat dikirim `/update <kata kunci>`, akan scraping loker pakai
[JobSpy](https://github.com/cullenwatson/JobSpy) (Indeed, LinkedIn, Glassdoor, Google,
ZipRecruiter, Bayt, Naukri) lalu menyimpan/update hasilnya ke tabel `jobs` di Supabase.

## 1. Siapkan Supabase

1. Buat project di [supabase.com](https://supabase.com) (kalau belum ada).
2. Buka **SQL Editor** → **New query**, paste isi file `schema.sql`, lalu **Run**.
   Ini akan membuat tabel `jobs` beserta index & trigger `updated_at`.
3. Buka **Project Settings → API**, catat:
   - `Project URL` → jadi `SUPABASE_URL`
   - `service_role` key (bukan `anon` key, karena bot perlu izin insert/update
     dari server) → jadi `SUPABASE_SERVICE_ROLE_KEY`

   ⚠️ **Jangan** taruh `service_role` key di kode frontend/publik. Key ini hanya
   dipakai di server tempat bot jalan.

## 2. Buat Bot Telegram

1. Chat [@BotFather](https://t.me/BotFather) di Telegram → `/newbot` → ikuti instruksinya.
2. Catat token yang diberikan → jadi `TELEGRAM_BOT_TOKEN`.

## 3. Setup di komputer/server kamu

Butuh Python 3.10+.

```bash
cd jobspy-telegram-bot
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Salin `.env.example` jadi `.env`, lalu isi nilainya:

```bash
cp .env.example .env
```

Edit `.env`:

```
TELEGRAM_BOT_TOKEN=isi_token_dari_botfather
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=isi_service_role_key
ALLOWED_CHAT_IDS=              # kosongkan dulu
DEFAULT_SITES=indeed,linkedin
DEFAULT_LOCATION=Indonesia
DEFAULT_COUNTRY_INDEED=Indonesia
DEFAULT_RESULTS_WANTED=30
DEFAULT_HOURS_OLD=72
```

## 4. Jalankan bot

```bash
python bot.py
```

Kalau muncul log `Bot mulai polling...`, bot sudah aktif. Buka chat dengan bot kamu di
Telegram, kirim `/start` untuk lihat cara pakai.

### (Opsional) Batasi siapa yang boleh pakai bot

Chat `/start` ke bot, lihat log terminal — akan tercetak `chat_id=...`. Salin angka itu
ke `ALLOWED_CHAT_IDS` di `.env` (boleh lebih dari satu, pisahkan koma), lalu restart bot.

## 5. Cara pakai

```
/update <kata kunci> [opsi...]
```

Opsi yang tersedia:

| Opsi | Keterangan | Contoh |
|---|---|---|
| `--location` | Lokasi pencarian | `--location "Jakarta Selatan"` |
| `--sites` | Situs sumber, pisah koma | `--sites indeed,linkedin` |
| `--country` | Negara untuk Indeed/Glassdoor | `--country indonesia` |
| `--results` | Maks hasil per situs | `--results 50` |
| `--hours` | Hanya posting N jam terakhir | `--hours 24` |
| `--remote` | Hanya loker remote | `--remote` |

Contoh:

```
/update data analyst
/update backend engineer --location Bandung --sites indeed,linkedin --results 50
/update ui ux designer --remote --hours 24
```

Bot akan membalas status pencarian, lalu meng-upsert hasilnya ke tabel `jobs` di
Supabase. Dedup dilakukan berdasarkan kombinasi `(site, job_id)` — kalau loker yang sama
muncul lagi di pencarian berikutnya, row lama akan di-update (`updated_at` berubah),
bukan dobel.

## 6. Menjalankan terus-menerus (opsional)

Supaya bot tetap jalan walau terminal ditutup, di Linux/macOS bisa pakai `systemd` atau
`tmux`/`screen` sederhana:

```bash
tmux new -s jobspy-bot
source venv/bin/activate
python bot.py
# tekan Ctrl+B lalu D untuk detach, bot tetap jalan di background
```

## Catatan

- JobSpy melakukan scraping langsung ke situs loker. Situs seperti LinkedIn/Indeed bisa
  membatasi request (rate limit) kalau dipakai terlalu sering/banyak — kurangi
  `--results` atau tambahkan jeda antar `/update` kalau sering gagal. JobSpy juga
  mendukung `proxies` (lihat kode `jobspy` asli) kalau perlu.
- Kolom `description` bisa panjang — kalau tidak perlu, kamu bisa hapus kolom itu dari
  `schema.sql` dan `scraper.py` untuk hemat storage.
