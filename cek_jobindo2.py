"""Diagnosa lanjutan Jobindo: lihat ISI field baru + halaman detail.

    python cek_jobindo2.py

Tidak mengubah database. Tempel SELURUH output-nya ke chat (sebagai teks).
"""
import json

from jobindo import (_HEADERS_DASAR, _ambil_versi_inertia, search_jobindo)
from sites.base import http_get


def pendek(v, n=300):
    t = json.dumps(v, ensure_ascii=False, default=str)
    return t if len(t) <= n else t[:n] + "...(dipotong)"


jobs = search_jobindo("semua", limit=2)
print("=== ISI LOWONGAN DARI DAFTAR ===")
for i, j in enumerate(jobs, 1):
    print(f"--- lowongan {i} ---")
    for k in sorted(j):
        print(f"  {k:<22} = {pendek(j[k])}")

if not jobs:
    raise SystemExit("Daftar kosong.")

from urllib.parse import urljoin
url = urljoin("https://jobindo.com", jobs[0].get("job_url") or "")
print("\n=== HALAMAN DETAIL ===")
print("url:", url)
import html as _html
import re as _re


def tampilkan(data):
    print("component:", data.get("component"))
    props = data.get("props") or {}
    print("kunci props:", sorted(props))
    for nama, isi in props.items():
        if isinstance(isi, dict) and len(isi) > 5:
            print(f"\n--- props['{nama}'] ---")
            for k in sorted(isi):
                print(f"  {k:<26} = {pendek(isi[k], 200)}")


# Cara 1: halaman HTML biasa, ambil JSON di atribut data-page
r1 = http_get(url, retries=1, timeout=20)
m = _re.search(r'data-page="([^"]+)"', r1.text)
print("cara 1 (HTML): status", r1.status_code, "| ada data-page:", bool(m))
if m:
    tampilkan(json.loads(_html.unescape(m.group(1))))
    raise SystemExit

# Cara 2: request Inertia (JSON langsung)
versi = _ambil_versi_inertia()
try:
    r2 = http_get(url, headers={**_HEADERS_DASAR, "X-Inertia": "true",
                                "X-Inertia-Version": versi},
                  retries=1, timeout=20)
    print("cara 2 (Inertia): status", r2.status_code)
    tampilkan(r2.json())
except Exception as e:  # noqa: BLE001
    print("cara 2 gagal:", e)
    print("500 karakter pertama HTML cara 1:")
    print(r1.text[:500])
