"""Lihat isi lengkap API Talentics + halaman detail satu lowongan.

    python cek_talentics2.py

Hanya membaca, tidak mengubah database. Tempel SELURUH output-nya ke chat.
"""
import json
import re

import requests

BASE = "https://jobs.talentics.id"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
H = {"User-Agent": UA, "Accept": "application/json",
     "X-Requested-With": "XMLHttpRequest", "Referer": f"{BASE}/jobs"}


def pendek(v, n=200):
    t = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    return t if len(t) <= n else t[:n] + "...(dipotong)"


r = requests.get(f"{BASE}/ajaxs/jobs", params={"page": 1}, headers=H, timeout=20)
print("API status:", r.status_code, "|", r.headers.get("content-type"))
data = r.json()

print("\n=== kunci paginasi ===")
for k, v in data.items():
    if k != "data":
        print(f"  {k:<16} = {pendek(v, 120)}")

items = data.get("data") or []
print("\njumlah lowongan di halaman 1:", len(items))
if not items:
    raise SystemExit

print("\n=== lowongan pertama, semua field ===")
for k in sorted(items[0]):
    print(f"  {k:<24} = {pendek(items[0][k])}")

# Cari bagian URL perusahaan dari link yang terlihat di halaman
job = items[0]
kandidat = [v for k, v in job.items()
            if isinstance(v, str) and re.fullmatch(r"[a-z0-9-]+", v) and "-" in v]
print("\nnilai mirip slug:", kandidat)

print("\n=== halaman detail ===")
org = next((job.get(k) for k in ("organization_slug", "org_slug", "company_slug")
            if job.get(k)), None)
if org:
    url = f"{BASE}/{org}/{job.get('slug')}"
    d = requests.get(url, headers={"User-Agent": UA}, timeout=20)
    print("url:", url, "| status", d.status_code)
    teks = d.text
    print("ada JSON-LD JobPosting:", '"JobPosting"' in teks)
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', teks, re.S)
    if m:
        print("JSON-LD:", pendek(m.group(1), 1500))
    else:
        bersih = re.sub(r"<[^>]+>", " ", teks)
        bersih = re.sub(r"\s+", " ", bersih)
        print("teks halaman (1000 karakter):", bersih[:1000])
else:
    print("field slug perusahaan tidak ketemu otomatis; lihat daftar field di atas.")
