# Deploy ke Oracle Cloud "Always Free"

Setelah selesai, bot jalan 24 jam di server Oracle:
- kamu cukup kirim perintah di Telegram, laptop boleh dimatikan;
- bot otomatis nyala lagi kalau crash atau server restart;
- semua situs di-scrape otomatis **setiap pagi jam 06.00 WIB**, dan ringkasannya dikirim ke Telegram kamu.

Bot memakai mode *polling*, jadi tidak perlu membuka port apa pun selain SSH.

> Diperbarui November 2026. Jatah gratis ARM Oracle sekarang **2 OCPU + 12 GB RAM** total. Panduan lama menyebut 4 OCPU/24 GB, dan angka itu sudah tidak berlaku.

---

## 1. Daftar akun Oracle Cloud

1. Buka https://www.oracle.com/cloud/free/ lalu klik **Start for free**.
2. Isi data dan verifikasi. Nomor HP dan kartu kredit/debit diminta untuk verifikasi identitas. Akan ada *hold* sementara, bukan tagihan.
3. **Home Region: pilih Singapore.** Ini tidak bisa diganti setelah akun jadi, dan server gratis hanya boleh dibuat di home region.

## 2. Buat server (VM)

1. Di Console, buka menu ☰ → **Compute → Instances → Create instance**.
2. **Image:** klik *Change image* → **Canonical Ubuntu 24.04**.
3. **Shape:** klik *Change shape* → **Ampere** → **VM.Standard.A1.Flex**, lalu atur **2 OCPU** dan **12 GB memory**. Pastikan ada label **Always Free eligible**.
   - Kalau muncul **"Out of capacity"**: coba lagi beberapa jam kemudian, atau ganti *Availability domain* di bagian Placement. Ini sangat umum untuk shape ARM.
   - Jangan pakai `VM.Standard.E2.1.Micro` (AMD, RAM 1 GB). RAM-nya terlalu kecil untuk Chromium, sehingga scraper Astra akan gagal.
4. **SSH keys:** pilih **Generate a key pair for me**, lalu klik **Download private key**. Simpan baik-baik, karena file ini satu-satunya cara masuk ke server.
5. Klik **Create**, lalu tunggu status menjadi **Running**.
6. Catat **Public IP address** di halaman detail instance.

## 3. Siapkan kunci SSH di Mac

Di Terminal Mac (ganti nama file kunci sesuai yang kamu unduh):

```bash
mkdir -p ~/.ssh
mv ~/Downloads/ssh-key-*.key ~/.ssh/oracle.key
chmod 600 ~/.ssh/oracle.key
```

Coba masuk ke server. Ganti `IP_SERVER` dengan Public IP tadi:

```bash
ssh -i ~/.ssh/oracle.key ubuntu@IP_SERVER
```

Kalau muncul `ubuntu@...:~$`, berarti berhasil. Ketik `exit` untuk keluar.

## 4. Matikan bot di Mac

**Penting.** Telegram hanya mengizinkan **satu** bot yang menerima pesan dengan token yang sama. Kalau bot di Mac masih jalan, bot di server akan terus mendapat error `Conflict: terminated by other getUpdates request`.

Di Terminal tempat `python bot.py` berjalan di Mac, tekan **Ctrl+C**.

## 5. Salin folder bot dari Mac ke server

Di Terminal **Mac**, bukan di dalam SSH. Perintah ini satu baris panjang:

```bash
rsync -av --exclude '.venv' --exclude 'venv' --exclude '__pycache__' -e "ssh -i ~/.ssh/oracle.key" /Users/eksalp/Downloads/Project/jobspy-telegram-bot/ ubuntu@IP_SERVER:~/jobspy-telegram-bot/
```

Perintah ini ikut menyalin file tersembunyi yang penting: `.env` (token dan kunci Supabase), `.maganghub_progress.json` (checkpoint MagangHub), dan `glints_session.txt` kalau ada. Folder `.venv` dari Mac sengaja tidak disalin karena tidak bisa dipakai di server Linux.

## 6. Instal semuanya dengan satu perintah

Masuk ke server, lalu jalankan skrip instalasi:

```bash
ssh -i ~/.ssh/oracle.key ubuntu@IP_SERVER
cd ~/jobspy-telegram-bot
bash pasang_server.sh
```

Prosesnya 5–10 menit. Yang dilakukan skrip:
1. instal Python dan paket sistem;
2. set zona waktu ke WIB;
3. buat `venv` dan instal semua library, termasuk Chromium untuk Astra;
4. cek `.env` lengkap;
5. pasang bot sebagai service (`jobspy-bot`) yang jalan 24 jam;
6. pasang jadwal scrape harian jam 06.00 WIB (`jobspy-scrape.timer`).

Kalau di akhir muncul `active (running)` berwarna hijau, bot sudah jalan. Kirim `/start` ke bot di Telegram untuk mencoba. Setelah itu terminal SSH boleh ditutup dan laptop boleh dimatikan.

## 7. Perintah yang berguna di server

```bash
# Lihat log bot secara langsung (Ctrl+C untuk keluar; bot tetap jalan)
journalctl -u jobspy-bot -f

# Restart bot (misal setelah update kode)
sudo systemctl restart jobspy-bot

# Kapan scrape terjadwal berikutnya
systemctl list-timers jobspy-scrape.timer

# Jalankan scrape terjadwal sekarang juga (tanpa menunggu jam 06.00)
sudo systemctl start jobspy-scrape.service

# Log scrape terjadwal terakhir
journalctl -u jobspy-scrape -n 100
```

Ganti jam scrape harian: edit `OnCalendar=` di `/etc/systemd/system/jobspy-scrape.timer` (misal `*-*-* 05:30:00`), lalu jalankan `sudo systemctl daemon-reload`.

## 8. Update kode di kemudian hari

Ulangi **langkah 5** (rsync dari Mac). Hanya file yang berubah yang dikirim. Lalu di server:

```bash
cd ~/jobspy-telegram-bot && bash pasang_server.sh
```

Kalau hanya mengubah file `.py` tanpa menambah library, cukup `sudo systemctl restart jobspy-bot`.

## 9. Supaya aman dari tagihan dan tidak "diambil kembali"

- **Budget alert:** Console → **Billing & Cost Management → Budgets → Create budget**, isi nominal kecil (misal USD 1). Kamu akan dapat email kalau ada resource berbayar yang terpakai. Selama hanya memakai resource berlabel *Always Free eligible*, seharusnya tidak pernah terjadi.
- **Server menganggur bisa diambil kembali.** Oracle menganggap VM Always Free menganggur kalau dalam 7 hari CPU (persentil ke-95), jaringan, dan memorinya semuanya di bawah 20%. Scrape harian jam 06.00 membantu mencegah ini. Kalaupun server sampai diambil, **datamu aman**: semua lowongan ada di Supabase, dan kodenya ada di Mac kamu. Cukup buat VM baru lalu ulangi langkah 2–6.
- **IP server cloud lebih sering diblokir** daripada IP rumah. Kalau ada situs yang di Mac jalan tapi di server hasilnya 0 (Indeed, LinkedIn, atau TopLoker paling mungkin), itu penyebabnya, bukan bug di kode.
