"""Cek jakartakerja.com: robots.txt, API WordPress, dan satu halaman detail.

    python cek_jakartakerja.py

Hanya membaca, tidak mengubah database. Tempel SELURUH output-nya ke chat.
"""
import json
import re

import requests

BASE = "https://www.jakartakerja.com"
H = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")}


def pendek(v, n=200):
    t = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    return t if len(t) <= n else t[:n] + "...(dipotong)"


def get(url, **kw):
    try:
        return requests.get(url, headers=H, timeout=20, **kw)
    except Exception as e:  # noqa: BLE001
        print(f"  GAGAL {url}: {e}")
        return None


print("=== robots.txt ===")
r = get(f"{BASE}/robots.txt")
if r is not None:
    print("status", r.status_code)
    print(r.text[:1500])

print("\n=== API WordPress: daftar tipe konten ===")
r = get(f"{BASE}/wp-json/wp/v2/types")
if r is not None:
    print("status", r.status_code)
    try:
        for nama, info in r.json().items():
            print(f"  {nama:<20} rest_base={info.get('rest_base')}")
    except Exception:  # noqa: BLE001
        print(r.text[:300])

for jalur in ("lowongan", "job_listing", "jobs", "posts"):
    r = get(f"{BASE}/wp-json/wp/v2/{jalur}", params={"per_page": 2})
    if r is None:
        continue
    print(f"\n=== /wp-json/wp/v2/{jalur} -> status {r.status_code} ===")
    if r.status_code != 200:
        continue
    print("  total:", r.headers.get("X-WP-Total"), "| halaman:", r.headers.get("X-WP-TotalPages"))
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        continue
    if data:
        for k in sorted(data[0]):
            print(f"  {k:<20} = {pendek(data[0][k])}")
    break

print("\n=== halaman detail ===")
r = get(f"{BASE}/")
link = None
if r is not None:
    m = re.search(r'href="(https://www\.jakartakerja\.com/lowongan/[^"]+)"', r.text)
    link = m.group(1) if m else None
print("url:", link)
if link:
    d = get(link)
    if d is not None:
        print("status", d.status_code)
        lds = re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', d.text, re.S)
        print("jumlah JSON-LD:", len(lds))
        for ld in lds:
            if "JobPosting" in ld:
                print("JSON-LD JobPosting:", pendek(ld, 2000))
                break
        else:
            teks = re.sub(r"<[^>]+>", " ", d.text)
            print("teks (1000 karakter):", re.sub(r"\s+", " ", teks)[:1000])
