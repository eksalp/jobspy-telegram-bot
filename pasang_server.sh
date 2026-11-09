#!/usr/bin/env bash
# Instalasi sekali jalan di server Oracle (Ubuntu). Jalankan dari folder bot:
#
#     cd ~/jobspy-telegram-bot
#     bash pasang_server.sh
#
# Aman dijalankan ulang (misal setelah update kode): langkah yang sudah
# beres akan dilewati atau diperbarui saja.
set -euo pipefail

FOLDER="$(cd "$(dirname "$0")" && pwd)"
PENGGUNA="$(whoami)"
cd "$FOLDER"

echo "==> 1/6 Paket sistem"
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip rsync

echo "==> 2/6 Zona waktu Asia/Jakarta (supaya jadwal pagi = jam WIB)"
sudo timedatectl set-timezone Asia/Jakarta

echo "==> 3/6 Virtual environment + library Python"
[ -d venv ] || python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
if [ -f requirements-browser.txt ]; then
  venv/bin/pip install -r requirements-browser.txt
  echo "==> 3b/6 Chromium untuk Playwright (dipakai Astra)"
  sudo venv/bin/python -m playwright install-deps chromium
  venv/bin/python -m playwright install chromium
fi

echo "==> 4/6 Cek file .env"
if [ ! -f .env ]; then
  echo "!! .env TIDAK ADA. Salin dari laptop dulu (lihat DEPLOY_ORACLE.md langkah 5)."
  exit 1
fi
for kunci in TELEGRAM_BOT_TOKEN SUPABASE_URL SUPABASE_SERVICE_ROLE_KEY; do
  grep -q "^${kunci}=" .env || { echo "!! ${kunci} belum ada di .env"; exit 1; }
done

echo "==> 5/6 Service bot (jalan 24 jam, nyala lagi otomatis)"
sudo tee /etc/systemd/system/jobspy-bot.service >/dev/null <<EOF
[Unit]
Description=JobSpy Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${PENGGUNA}
WorkingDirectory=${FOLDER}
ExecStart=${FOLDER}/venv/bin/python ${FOLDER}/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

echo "==> 6/6 Scrape otomatis setiap pagi jam 06.00 WIB"
sudo tee /etc/systemd/system/jobspy-scrape.service >/dev/null <<EOF
[Unit]
Description=Scrape semua situs lowongan (terjadwal)
After=network-online.target

[Service]
Type=oneshot
User=${PENGGUNA}
WorkingDirectory=${FOLDER}
ExecStart=${FOLDER}/venv/bin/python ${FOLDER}/jadwal_harian.py
TimeoutStartSec=4h
EOF

sudo tee /etc/systemd/system/jobspy-scrape.timer >/dev/null <<EOF
[Unit]
Description=Jadwal scrape harian lowongan

[Timer]
OnCalendar=*-*-* 06:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now jobspy-bot.service
sudo systemctl restart jobspy-bot.service
sudo systemctl enable --now jobspy-scrape.timer

echo
echo "Selesai. Status bot:"
sudo systemctl --no-pager --lines=5 status jobspy-bot.service || true
echo
echo "Jadwal scrape berikutnya:"
systemctl list-timers jobspy-scrape.timer --no-pager || true
